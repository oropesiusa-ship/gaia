"""Canonical diagnosis graph. Diagnosis is an interpretation, never a causal proof."""
from datetime import datetime
import json
import re

from ..provenance import canonical_json, digest
from .confidence import assess

DIAGNOSIS_SCHEMA = "gaia_system_diagnosis_v1"
TAXONOMY = {"COMPUTE_PRESSURE", "MEMORY_PRESSURE", "GPU_MEMORY_PRESSURE", "STORAGE_PRESSURE",
            "RUNTIME_REGRESSION", "RESOURCE_CONTENTION", "MEASUREMENT_NOISE", "QUALITY_REGRESSION",
            "CAPABILITY_GAP", "ENVIRONMENT_CHANGE", "UNKNOWN_CAUSE"}
OUTCOMES = {"ISSUES_DETECTED", "NO_SIGNIFICANT_ISSUE", "INSUFFICIENT_EVIDENCE"}
REQUIRED = {"diagnosis_id", "schema", "timestamp", "source_observations", "identity", "outcome", "issues", "hypotheses",
            "alternatives", "evidence", "contradictions", "missing_evidence", "confidence", "limitations",
            "rules", "comparison", "cost", "diagnosis_hash"}


def seal(document):
    result = json.loads(canonical_json(document))
    result["diagnosis_hash"] = digest({k: v for k, v in result.items() if k != "diagnosis_hash"})
    validate(result)
    return result


def validate(value):
    if set(value) != REQUIRED or value["schema"] != DIAGNOSIS_SCHEMA:
        raise ValueError("Invalid diagnosis schema")
    if not re.fullmatch(r"d[0-9]{6,}", value["diagnosis_id"]):
        raise ValueError("Invalid diagnosis id")
    if datetime.fromisoformat(value["timestamp"]).tzinfo is None or value["outcome"] not in OUTCOMES:
        raise ValueError("Invalid timestamp/outcome")
    if not value["source_observations"] or not value["limitations"]:
        raise ValueError("Missing source/limitations")
    evidence = {e["evidence_id"]: e for e in value["evidence"]}
    hypotheses = {h["hypothesis_id"]: h for h in value["hypotheses"]}
    issues = {i["issue_id"]: i for i in value["issues"]}
    if len(evidence) != len(value["evidence"]) or len(hypotheses) != len(value["hypotheses"]) or len(issues) != len(value["issues"]):
        raise ValueError("Duplicate diagnosis graph ids")
    for e in evidence.values():
        if e["type"] not in {"DIRECT", "CORRELATIONAL", "NEGATIVE", "CONTROL", "CONTEXTUAL"} or e["strength"] not in {"WEAK", "MODERATE", "STRONG"}:
            raise ValueError("Invalid evidence type/strength")
        if e["observation_ref"] not in value["source_observations"] or not e["field"].startswith("/"):
            raise ValueError("Invalid evidence source")
        if not set(e["supports"] + e["contradicts"]) <= hypotheses.keys():
            raise ValueError("Dangling hypothesis evidence link")
    for h in hypotheses.values():
        if h["kind"] not in TAXONOMY or h["issue_id"] not in issues or h["causality"] != "NOT_ESTABLISHED":
            raise ValueError("Invalid hypothesis")
        if not set(h["rule_ids"]) <= set(value["rules"]["evaluated"]):
            raise ValueError("Unknown rule reference")
        if not set(h["supports"] + h["contradictions"]) <= evidence.keys():
            raise ValueError("Dangling evidence reference")
        if not set(h["alternative_ids"]) <= hypotheses.keys() or h["hypothesis_id"] in h["alternative_ids"]:
            raise ValueError("Invalid alternatives")
        for field, reverse in (("supports", "supports"), ("contradictions", "contradicts")):
            for eid in h[field]:
                if h["hypothesis_id"] not in evidence[eid][reverse]:
                    raise ValueError("Evidence link mismatch")
        basis = h["confidence_basis"]
        computed = assess([evidence[e] for e in h["supports"]], [evidence[e] for e in h["contradictions"]],
                          stable=basis["stable_measurement"], searched=bool(h["contradiction_search"]),
                          alternative_weakened=basis["alternative_weakened"], missing_critical=basis["missing_critical"],
                          minimum_independent=basis["minimum_independent"], unknown=h["kind"] == "UNKNOWN_CAUSE")
        if computed != basis or h["confidence"] != computed["level"]:
            raise ValueError("Inconsistent hypothesis confidence")
    for issue in issues.values():
        if not set(issue["hypothesis_ids"]) <= hypotheses.keys() or not set(issue["evidence_refs"]) <= evidence.keys():
            raise ValueError("Invalid issue links")
        if issue["primary_hypothesis"] not in issue["hypothesis_ids"]:
            raise ValueError("Invalid primary hypothesis")
    if value["outcome"] == "NO_SIGNIFICANT_ISSUE" and (issues or hypotheses):
        raise ValueError("No-issue outcome contains invented hypotheses")
    if value["outcome"] == "ISSUES_DETECTED" and not issues:
        raise ValueError("Issues outcome without issues")
    if value["contradictions"] != {h: v["contradictions"] for h, v in hypotheses.items()}:
        raise ValueError("Contradictions index mismatch")
    if value["alternatives"] != {i: [h for h in v["hypothesis_ids"] if h != v["primary_hypothesis"]] for i, v in issues.items()}:
        raise ValueError("Alternatives index mismatch")
    if value["confidence"] != {h: v["confidence"] for h, v in hypotheses.items()}:
        raise ValueError("Confidence index mismatch")
    if value["diagnosis_hash"] != digest({k: v for k, v in value.items() if k != "diagnosis_hash"}):
        raise ValueError("Diagnosis hash mismatch")
    canonical_json(value)
    return value
