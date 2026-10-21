"""Explicit questions, bounded destinations and minimal optional local context."""
import re
from urllib.parse import urlsplit

from ..provenance import digest
from .network import normalize_url
from .policy import SOURCE_CLASSES, identity, settings
from .schema import artifact, reference, validate

TOPICS = {"PYTHON_GIL_CPU_THREADING", "PYTHON_FREE_THREADED_BUILD", "CUDA_MIN_COMPUTE_CAPABILITY"}
FRESHNESS = {"NONE", "LOW", "MEDIUM", "HIGH"}
CONTEXT = {"python_version", "python_implementation", "cuda_compute_capability", "workload"}


def valid_context(value):
    if set(value) - CONTEXT:
        raise ValueError("Unknown research context fields")
    for key, val in value.items():
        choices = {"python_implementation": {"CPython", "PyPy"}, "workload": {"numpy_mlp", "language_model", "UNKNOWN"}}
        if key in choices:
            if val not in choices[key]:
                raise ValueError("Invalid context enum")
        elif not isinstance(val, str) or not re.fullmatch(r"[0-9]{1,2}\.[0-9]{1,2}(?:\.[0-9]{1,2})?", val):
            raise ValueError("Invalid context version")


def create(question, urls, *, topics, context=None, refs=(), allowed_domains=(), allowed_classes=None,
           network_authorized=False, allow_http=False, budget=None, freshness="MEDIUM", evidence_requirements=None, configuration=None, created_at=None):
    cfg = settings(configuration)
    if not isinstance(question, str) or not 8 <= len(question) <= 500 or any(ord(c) < 32 for c in question):
        raise ValueError("Explicit bounded research question required")
    if type(network_authorized) is not bool or type(allow_http) is not bool or freshness not in FRESHNESS:
        raise ValueError("Invalid research authorization/freshness")
    if not topics or set(topics) - TOPICS:
        raise ValueError("Use explicit supported evidence topics")
    allowed_domains = sorted(set(allowed_domains))
    for domain in allowed_domains:
        normalized = normalize_url("https://" + domain + "/")
        if urlsplit(normalized).hostname != domain:
            raise ValueError("Domain allowlist must be normalized")
    normalized = sorted({normalize_url(u, allow_http=allow_http and not cfg["https_only"], domains=allowed_domains) for u in urls})
    requested = {k: cfg[k] for k in ("max_sources", "max_requests", "max_total_bytes", "max_duration_seconds", "max_redirects")}
    if budget:
        if set(budget) - requested.keys():
            raise ValueError("Unknown request budget")
        requested.update(budget)
    for k, value in requested.items():
        if type(value) not in (int, float) or not (0 if k == "max_redirects" else .1 if k == "max_duration_seconds" else 1) <= value <= cfg[k] or k != "max_duration_seconds" and type(value) is not int:
            raise ValueError("Request may only restrict global budgets")
    if not normalized or len(normalized) > requested["max_sources"]:
        raise ValueError("Explicit URL set exceeds source budget")
    requirements = {"minimum_sources": 1, "require_primary": True, "require_version": False}
    if evidence_requirements:
        if set(evidence_requirements) - requirements.keys():
            raise ValueError("Unknown evidence requirement")
        requirements.update(evidence_requirements)
    if (type(requirements["minimum_sources"]) is not int or not 1 <= requirements["minimum_sources"] <= len(normalized)
            or type(requirements["require_primary"]) is not bool or type(requirements["require_version"]) is not bool):
        raise ValueError("Invalid evidence requirements")
    classes = sorted(allowed_classes or SOURCE_CLASSES)
    if set(classes) - SOURCE_CLASSES:
        raise ValueError("Unknown source class")
    valid_context(context or {})
    safe_refs = []
    for ref in refs:
        if set(ref) != {"kind", "id", "hash"} or ref["kind"] not in ("TARGET", "DIAGNOSIS", "STRATEGY", "OBSERVATION") or not re.fullmatch(r"[a-z]{1,3}[0-9a-f]{4,64}", ref["id"]) or not re.fullmatch(r"[a-f0-9]{64}", ref["hash"]):
            raise ValueError("Invalid research lineage reference")
        safe_refs.append(dict(ref))
    terms = {"PYTHON_GIL_CPU_THREADING": ["Python", "threading", "GIL"], "PYTHON_FREE_THREADED_BUILD": ["Python", "free-threaded", "build"],
             "CUDA_MIN_COMPUTE_CAPABILITY": ["CUDA", "compute capability", "requirements"]}
    payload = {"question": question, "urls": normalized, "topics": sorted(set(topics)), "context": context or {}, "refs": safe_refs,
               "allowed_source_classes": classes, "allowed_domains": allowed_domains, "budget": requested, "freshness": freshness,
               "network_authorized": network_authorized, "allow_http": allow_http, "policy": identity(cfg), "evidence_requirements": requirements,
               "search_plan": {"provider": "EXPLICIT_URLS_OR_LOCAL_REPLAY", "terms": sorted({t for topic in topics for t in terms[topic]}),
                               "evidence_needed": ["EXACT_QUOTE", "SOURCE_IDENTITY", "VERSION_OR_SCOPE_WHEN_KNOWN"],
                               "stop_conditions": ["EVIDENCE_REQUIREMENTS_SATISFIED", "BUDGET_EXHAUSTED", "CONTRADICTION_REQUIRES_RESOLUTION", "NO_USEFUL_SOURCES"]}}
    return artifact("REQUEST", payload, created_at=created_at,
                    limitations=["Question/context are local inputs; fetch sends only explicit URLs and fixed headers, never the question or observation."])


def validate_request(value):
    validate(value)
    if value["kind"] != "REQUEST":
        raise ValueError("Research request required")
    p = value["payload"]
    reproduced = create(p["question"], p["urls"], topics=p["topics"], context=p["context"], refs=p["refs"],
                        allowed_domains=p["allowed_domains"], allowed_classes=p["allowed_source_classes"],
                        network_authorized=p["network_authorized"], allow_http=p["allow_http"], budget=p["budget"], freshness=p["freshness"],
                        evidence_requirements=p["evidence_requirements"],
                        configuration={"external_research": p["policy"]["settings"]}, created_at=value["created_at"])
    if reproduced != value:
        raise ValueError("Research request identity/policy mismatch")
    return value


def observation_context(observation):
    from ..diagnosis.evidence import validate_input
    validate_input(observation)
    facts = observation["sections"]["facts"]
    result = {}
    python = facts.get("runtime", {}).get("python", {})
    if python.get("version"):
        result["python_version"] = python["version"]
    if python.get("implementation") in ("CPython", "PyPy"):
        result["python_implementation"] = python["implementation"]
    capabilities = sorted({d["compute_capability"] for d in facts.get("gpu", {}).get("devices", []) if d.get("compute_capability")})
    if len(capabilities) == 1:
        result["cuda_compute_capability"] = capabilities[0]
    valid_context(result)
    return result, {"kind": "OBSERVATION", "id": observation["observation_id"], "hash": observation["observation_hash"]}
