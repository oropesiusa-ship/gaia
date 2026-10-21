"""Visible external evidence dimensions, dependence groups and contextual conclusions."""
from datetime import datetime
import re
from urllib.parse import urlsplit

from ..provenance import digest
from .policy import classify
from .schema import artifact, reference


def assess_sources(request, sources, extractions, analysis_at):
    groups = dependence_groups(sources, extractions)
    ex = {e["payload"]["source_ref"]["id"]: e for e in extractions}
    values = []
    for source in sources:
        p = source["payload"]
        e = ex[source["artifact_id"]]
        same_group = sum(groups[s["artifact_id"]] == groups[source["artifact_id"]] for s in sources)
        primary = p["source_class"].startswith("PRIMARY_")
        quality = {"authority": "HIGH" if primary else "MEDIUM" if p["source_class"] == "SECONDARY_TECHNICAL" else "LOW" if p["source_class"] == "COMMUNITY" else "UNKNOWN",
                   "directness": "MEDIUM" if e["payload"]["fragments"] else "LOW", "freshness": "UNKNOWN",
                   "reproducibility": "HIGH", "specificity": "HIGH" if e["payload"]["version"] else "LOW",
                   "independence": "LOW" if same_group > 1 else "UNKNOWN", "provenance_completeness": "HIGH"}
        values.append(artifact("ASSESSMENT", {"assessment_kind": "SOURCE", "source_ref": reference(source),
                                "extraction_ref": reference(e), "source_class": p["source_class"], "source_quality": quality,
                                "independence_group": groups[source["artifact_id"]], "origin": p["origin"],
                                "publication_date_verified": False, "locally_verified": False}, created_at=analysis_at,
                                limitations=["Source authority class does not make every statement true; publication freshness and independent authorship remain uncertain."]))
    return values


def dependence_groups(sources, extractions):
    parents = {s["artifact_id"]: s["artifact_id"] for s in sources}
    ex = {e["payload"]["source_ref"]["id"]: e["payload"] for e in extractions}
    def root(key):
        while parents[key] != key:
            key = parents[key]
        return key
    def origins(source):
        data = ex[source["artifact_id"]]
        refs = set()
        if data["canonical_url"]:
            refs.add(data["canonical_url"])
        for url in data["references"]:
            parts = urlsplit(url)
            if classify(parts.hostname, parts.path)[0].startswith("PRIMARY_"):
                refs.add(url)
        return refs
    for index, a in enumerate(sources):
        for b in sources[index + 1:]:
            same = (a["payload"]["publisher_group"] == b["payload"]["publisher_group"]
                    or a["payload"]["content_hash"] == b["payload"]["content_hash"]
                    or origins(a) & origins(b)
                    or a["payload"]["url"] in origins(b) or b["payload"]["url"] in origins(a))
            if same:
                x, y = root(a["artifact_id"]), root(b["artifact_id"])
                parents[max(x, y)] = min(x, y)
    return {s["artifact_id"]: "ig" + digest(sorted(k for k in parents if root(k) == root(s["artifact_id"])))[:24] for s in sources}


def applicability(claim, context):
    p = claim["payload"]
    version = p["context"]["version"]
    if p["topic"] == "LOCAL_INFERENCE_ECOSYSTEM":
        return "RELATED", ["ECOSYSTEM_METADATA_NOT_A_HOST_COMPATIBILITY_PROOF"]
    if p["topic"].startswith("PYTHON_"):
        if context.get("python_implementation") and context["python_implementation"] != "CPython":
            return "NOT_APPLICABLE", ["SOURCE_IS_CPYTHON_SPECIFIC"]
        if version and context.get("python_version") and not context["python_version"].startswith(version + ".") and context["python_version"] != version:
            return "RELATED", ["DOCUMENTATION_PATCH_VERSION_DIFFERS" if context["python_version"].split(".")[:2] == version.split(".")[:2] else "DIFFERENT_DOCUMENTED_PYTHON_VERSION"]
        if context.get("python_implementation") == "CPython" and context.get("python_version") and version:
            return "POTENTIALLY_APPLICABLE", ["VERSION_MATCHES_BUT_LOCAL_GIL_BUILD_CONFIGURATION_NOT_OBSERVED"]
        return "UNKNOWN", ["EXPLICIT_PYTHON_CONTEXT_OR_VERSION_MISSING"]
    local = context.get("cuda_compute_capability")
    if local:
        if tuple(map(int, local.split("."))) < tuple(map(int, p["reported_value"].split("."))):
            return "NOT_APPLICABLE", ["HOST_COMPUTE_CAPABILITY_BELOW_REPORTED_MINIMUM"]
        return "POTENTIALLY_APPLICABLE", ["HARDWARE_MINIMUM_MET_SOFTWARE_VERSION_COMPATIBILITY_UNVERIFIED"]
    return "UNKNOWN", ["HOST_COMPUTE_CAPABILITY_NOT_PROVIDED"]


def assess(request, sources, extractions, claims, analysis_at):
    source_map = {s["artifact_id"]: s for s in sources}
    ex = {e["payload"]["source_ref"]["id"]: e for e in extractions}
    groups = dependence_groups(sources, extractions)
    conflicts = []
    for i, a in enumerate(claims):
        for b in claims[i + 1:]:
            ap, bp = a["payload"], b["payload"]
            if ap["topic"] == bp["topic"] and ap["condition"] == bp["condition"] and ap["reported_value"] != bp["reported_value"]:
                av, bv = ap["context"]["version"], bp["context"]["version"]
                conflicts.append({"a": reference(a), "b": reference(b), "status": "UNRESOLVED",
                                  "relationship": "VERSION_DEPENDENT" if av and bv and av != bv else "CONTRADICTORY_OR_SCOPE_UNRESOLVED",
                                  "explanation": "DIFFERENT_VERSIONS_MAY_EXPLAIN_DISAGREEMENT" if av != bv else "NO_SILENT_SOURCE_SELECTION"})
    assessments = []
    for claim in claims:
        p = claim["payload"]
        source = source_map[p["source_ref"]["id"]]
        s = source["payload"]
        e = ex[source["artifact_id"]]["payload"]
        same = [c for c in claims if c["payload"]["topic"] == p["topic"] and c["payload"]["reported_value"] == p["reported_value"]
                and c["payload"]["condition"] == p["condition"] and c["payload"]["context"]["version"] == p["context"]["version"]]
        primary = [c for c in same if c["payload"]["source_class"].startswith("PRIMARY_")]
        independent = {groups[c["payload"]["source_ref"]["id"]] for c in primary}
        related_conflicts = [c for c in conflicts if claim["artifact_id"] in (c["a"]["id"], c["b"]["id"])]
        app, reasons = applicability(claim, request["payload"]["context"])
        age = (datetime.fromisoformat(analysis_at) - datetime.fromisoformat(source["created_at"])).total_seconds()
        freshness = "UNKNOWN_PUBLICATION_DATE"
        if e["update_date"]:
            date_age = (datetime.fromisoformat(analysis_at) - datetime.fromisoformat(e["update_date"])).total_seconds()
            freshness = "RECENT_SOURCE_REPORTED_UPDATE" if 0 <= date_age < 365 * 86400 else "HISTORICAL_OR_UNCERTAIN_UPDATE"
        status = "UNRESOLVED" if related_conflicts else "CORROBORATED" if len(independent) >= 2 else "SUPPORTED" if s["source_class"].startswith("PRIMARY_") else "REPORTED"
        confidence = "MEDIUM" if status == "SUPPORTED" else "LOW" if status == "REPORTED" else "VERY_LOW" if status == "UNRESOLVED" else "HIGH"
        if app in ("NOT_APPLICABLE", "UNKNOWN", "RELATED") and confidence in ("MEDIUM", "HIGH"):
            confidence = "LOW"
        # Version/build-dependent evidence is not a precise proof about this local runtime.
        if (not p["context"]["version"] or request["payload"]["freshness"] == "HIGH" and freshness != "RECENT_SOURCE_REPORTED_UPDATE") and confidence == "HIGH":
            confidence = "MEDIUM"
        if urlsplit(s["url"]).scheme != "https":
            confidence = "LOW"
        quality = {"authority": "HIGH" if s["source_class"].startswith("PRIMARY_") else "MEDIUM" if s["source_class"] == "SECONDARY_TECHNICAL" else "LOW" if s["source_class"] == "COMMUNITY" else "UNKNOWN",
                   "directness": "HIGH", "freshness": "MEDIUM" if freshness == "RECENT_SOURCE_REPORTED_UPDATE" else "UNKNOWN",
                   "reproducibility": "HIGH", "specificity": "HIGH" if e["version"] else "LOW",
                   "independence": "MEDIUM" if len(independent) >= 2 else "UNKNOWN", "provenance_completeness": "HIGH"}
        assessments.append(artifact("ASSESSMENT", {"claim_ref": reference(claim), "source_ref": reference(source),
                           "source_quality": quality, "status": status, "confidence": confidence, "freshness": freshness,
                           "retrieval_age_seconds": max(0, age), "publication_date_verified": False,
                           "applicability": app, "applicability_reasons": reasons, "independence_group": groups[source["artifact_id"]],
                           "independent_primary_groups": len(independent), "corroborating_claim_refs": [reference(c) for c in same if c is not claim],
                           "contradictions": related_conflicts, "locally_verified": False}, created_at=analysis_at,
                           limitations=["External support is distinct from locally verified operational knowledge.",
                                        "Publisher/canonical/reference/content dependence checks are conservative heuristics, not proof of independent authorship.",
                                        "Recent retrieval is not proof of recent publication; build/version applicability remains bounded."]))
    return assessments, conflicts
