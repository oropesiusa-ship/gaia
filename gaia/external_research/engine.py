"""FETCH is separate from deterministic EXTRACT / ASSESS / CONCLUDE and offline replay."""
import time

from ..provenance import digest
from .assessment import assess, assess_sources
from .claims import extract_claims
from .extraction import extract
from .fetch import Fetcher, validate_source
from .network import FetchError, normalize_url
from .policy import identity, settings
from .request import validate_request
from .schema import artifact, reference, timestamp
from .search import DirectURLs


def validate_sources(request, sources):
    validate_request(request)
    p = request["payload"]
    cfg = p["policy"]["settings"]
    if len(sources) > p["budget"]["max_sources"] or len({s["artifact_id"] for s in sources}) != len(sources):
        raise ValueError("Source budget/duplicates invalid")
    if sum(s["payload"]["wire_bytes"] for s in sources) > p["budget"]["max_total_bytes"] or sum(s["payload"]["decoded_bytes"] for s in sources) > p["budget"]["max_total_bytes"]:
        raise ValueError("Captured sources exceed request bytes")
    for source in sources:
        validate_source(source)
        sp = source["payload"]
        if sp["requested_url"] not in p["urls"] or sp["source_class"] not in p["allowed_source_classes"] or sp["decoded_bytes"] > cfg["max_decompressed_bytes"] or sp["wire_bytes"] > cfg["max_response_bytes"]:
            raise ValueError("Source outside research scope")
        if len(sp["retrieval_chain"]) > p["budget"]["max_redirects"] + 1:
            raise ValueError("Source redirect budget mismatch")
        for url in [sp["url"], sp["requested_url"]] + [s["url"] for s in sp["retrieval_chain"]] + [s["url"] for r in sp["robots"] for s in r["retrieval_chain"]]:
            normalize_url(url, allow_http=p["allow_http"] and not cfg["https_only"], domains=p["allowed_domains"])
    return sources


def analyze(request, sources, *, analysis_at=None):
    start = time.perf_counter()
    validate_sources(request, sources)
    sources = sorted(sources, key=lambda s: s["artifact_id"])
    analysis_at = analysis_at or timestamp()
    extractions, usable_sources, failures = [], [], []
    for source in sources:
        try:
            extractions.append(extract(source))
            usable_sources.append(source)
        except (ValueError, RecursionError):
            failures.append({"phase": "EXTRACT", "source_ref": reference(source), "reason": "UNSUPPORTED_PASSIVE_CONTENT", "nonfatal": True})
    claims = [c for source, extraction in zip(usable_sources, extractions) for c in extract_claims(request, source, extraction, analysis_at)]
    assessments, contradictions = assess(request, usable_sources, extractions, claims, analysis_at)
    source_assessments = assess_sources(request, usable_sources, extractions, analysis_at)
    supported, unsupported, unresolved = [], [], []
    for a in assessments:
        p = a["payload"]
        if p["status"] == "UNRESOLVED":
            unresolved.append(p["claim_ref"])
        elif p["status"] in ("SUPPORTED", "CORROBORATED") and p["applicability"] not in ("NOT_APPLICABLE", "UNKNOWN"):
            supported.append(p["claim_ref"])
        else:
            unsupported.append({"claim_ref": p["claim_ref"], "reason": "NOT_LOCALLY_APPLICABLE" if p["applicability"] == "NOT_APPLICABLE" else "LIMITED_EXTERNAL_SUPPORT_OR_CONTEXT"})
    found_topics = {c["payload"]["topic"] for c in claims}
    unknowns = ["LOCAL_BUILD_OR_EXPERIMENTAL_VALIDATION_NOT_ESTABLISHED", "PUBLISHER_INDEPENDENCE_NOT_PROVEN_BY_DISTINCT_URLS"]
    unknowns += ["NO_CATALOG_SUPPORT:" + t for t in request["payload"]["topics"] if t not in found_topics]
    if any(e["payload"]["publication_date"] is None for e in extractions):
        unknowns.append("VERIFIED_PUBLICATION_DATE_UNAVAILABLE")
    if failures:
        unknowns.append("PASSIVE_EXTRACTION_FAILED_FOR_SOME_CAPTURED_SOURCES")
    conclusion = artifact("CONCLUSION", {"request_ref": reference(request), "question": request["payload"]["question"],
                         "mode": "EVIDENCE_ONLY_MODE", "supported_claims": supported, "unsupported_claims": unsupported,
                         "unresolved_claims": unresolved, "contradictions": contradictions, "unknowns": unknowns,
                         "sources": [reference(s) for s in sources], "claims": [reference(c) for c in claims],
                         "assessments": [reference(a) for a in assessments],
                         "source_assessments": [reference(a) for a in source_assessments],
                         "confidence": "LOW" if contradictions else "MEDIUM" if any(a["payload"]["confidence"] in ("MEDIUM", "HIGH") and a["payload"]["claim_ref"] in supported for a in assessments) else "LOW" if supported else "VERY_LOW",
                         "applicability": [{"claim_ref": a["payload"]["claim_ref"], "status": a["payload"]["applicability"], "reasons": a["payload"]["applicability_reasons"]} for a in assessments],
                         "recommendation_status": "NOT_AUTHORIZED", "locally_verified_knowledge_created": False,
                         "stop_condition": "CONTRADICTION_REQUIRES_RESOLUTION" if contradictions else "EVIDENCE_REQUIREMENTS_SATISFIED" if found_topics == set(request["payload"]["topics"]) else "NO_USEFUL_SOURCES"},
                         created_at=analysis_at, limitations=["External report/corroboration never bypasses local hypothesis, experiment, replication and protected evaluation.",
                                                              "Unsupported for this context does not mean the external proposition is false.",
                                                              "No solution applied, experiment executed or configuration/evaluator modified.",
                                                              "Claim catalog is narrow and extractive; absence of a match is not absence of evidence on the Internet."])
    value = {"schema": "gaia_external_research_run_v1", "request_ref": reference(request), "analysis_at": analysis_at,
             "mode": "EVIDENCE_ONLY_MODE", "source_refs": [reference(s) for s in sources],
             "extractions": extractions, "claims": claims, "assessments": assessments, "source_assessments": source_assessments,
             "analysis_failures": failures, "conclusion": conclusion,
             "cost": {"duration_s": time.perf_counter() - start, "sources_processed": len(sources), "claims_generated": len(claims)}}
    value["run_hash"] = digest(value)
    return value


def replay(request, sources, original_run):
    if original_run["run_hash"] != digest({k: v for k, v in original_run.items() if k != "run_hash"}):
        raise ValueError("Research run hash mismatch")
    value = analyze(request, sources, analysis_at=original_run["analysis_at"])
    excluded = {"run_hash", "cost"}
    if {k: v for k, v in value.items() if k not in excluded} != {k: v for k, v in original_run.items() if k not in excluded}:
        raise ValueError("Offline interpretation differs from captured run")
    return value


def acquire(request, store, configuration=None, *, provider=None, offline=False):
    validate_request(request)
    cfg = settings(configuration)
    fetcher = Fetcher(request, configuration)
    sources, events = [], []
    urls = (provider or DirectURLs()).search(request)
    if len(urls) > request["payload"]["budget"]["max_sources"] or any(u not in request["payload"]["urls"] for u in urls):
        raise ValueError("Provider exceeded explicit research scope")
    for url in dict.fromkeys(urls):
        cached = store.cached(url, request["payload"]["freshness"], configuration, timestamp())
        if cached:
            try:
                validate_sources(request, sources + [cached])
            except ValueError:
                cached = None
        if cached:
            sources.append(cached)
            events.append({"url": url, "phase": "FETCH", "status": "CACHE", "source_ref": reference(cached), "retrieved_at": cached["created_at"]})
            continue
        if offline:
            events.append({"url": url, "phase": "FETCH", "status": "UNAVAILABLE", "reason": "OFFLINE_CACHE_MISS"})
            continue
        try:
            value = fetcher.fetch(url)
            validate_sources(request, sources + [value])
            store.cache_source(value)
            sources.append(value)
            events.append({"url": url, "phase": "FETCH", "status": "FETCHED", "source_ref": reference(value)})
        except FetchError as exc:
            events.append({"url": url, "phase": "FETCH", "status": "UNAVAILABLE", "reason": exc.code})
            if "BUDGET" in exc.code or exc.code == "NETWORK_NOT_AUTHORIZED":
                break
        except (ValueError, OSError):
            events.append({"url": url, "phase": "FETCH", "status": "ERROR", "reason": "SOURCE_VALIDATION_FAILED"})
    return sources, {"mode": "OFFLINE_CACHE_ONLY" if offline else "EXPLICIT_FETCH", "events": events,
                     "requests": fetcher.requests, "wire_bytes": fetcher.wire_bytes, "decoded_bytes": fetcher.decoded_bytes,
                     "duration_s": time.monotonic() - fetcher.started,
                     "stop_condition": "BUDGET_OR_AUTHORIZATION_LIMIT" if any("BUDGET" in e.get("reason", "") or e.get("reason") == "NETWORK_NOT_AUTHORIZED" for e in events) else "SOURCE_SET_EXHAUSTED"}
