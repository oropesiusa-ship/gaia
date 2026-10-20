"""Canonical priority graph and policy consistency validation."""
from datetime import datetime
import json
import re

from ..provenance import canonical_json, digest
from .policy import COST, CONFIDENCE, IMPACT, RULES, VERSION, decide, ordering, settings
from .targets import TARGET_CLASSES

PRIORITY_SCHEMA = "gaia_target_prioritization_v1"
FIELDS = {"prioritization_id", "schema", "timestamp", "source_diagnoses", "source_observations", "candidate_targets",
          "ordering", "exclusions", "blockers", "rationale", "limitations", "policy", "cost", "prioritization_hash"}


def seal(document):
    value = json.loads(canonical_json(document))
    value["prioritization_hash"] = digest({k: v for k, v in value.items() if k != "prioritization_hash"})
    validate(value)
    return value


def validate(value):
    if set(value) != FIELDS or value["schema"] != PRIORITY_SCHEMA or not re.fullmatch(r"p[0-9]{6,}", value["prioritization_id"]):
        raise ValueError("Invalid prioritization schema")
    if datetime.fromisoformat(value["timestamp"]).tzinfo is None:
        raise ValueError("Missing timezone")
    cfg = settings({"prioritization": value["policy"]["settings"]})
    if (value["policy"]["version"] != VERSION or value["policy"]["rules_evaluated"] != list(RULES)
            or value["policy"]["hash"] != digest({"version": VERSION, "settings": cfg, "rules": RULES})):
        raise ValueError("Invalid policy identity")
    ids = {t["target_id"] for t in value["candidate_targets"]}
    if len(ids) != len(value["candidate_targets"]):
        raise ValueError("Duplicate target ids")
    sources = {d["diagnosis_hash"]: d for d in value["source_diagnoses"]}
    if not sources or len(sources) != len(value["source_diagnoses"]):
        raise ValueError("Missing or duplicate diagnosis references")
    for ref in sources.values():
        if not re.fullmatch(r"d[0-9]{6,}", ref["diagnosis_id"]) or not re.fullmatch(r"[a-f0-9]{64}", ref["diagnosis_hash"]):
            raise ValueError("Invalid source reference")
    for t in value["candidate_targets"]:
        if not re.fullmatch(r"t[0-9]{4,}", t["target_id"]):
            raise ValueError("Invalid target id")
        d = t["dimensions"]
        if (t["target_class"] not in TARGET_CLASSES or d["impact"] not in IMPACT or d["diagnostic_confidence"] not in CONFIDENCE
                or d["investigation_cost"] not in COST or d["risk"] not in ("LOW", "MEDIUM", "HIGH")
                or d["reversibility"] not in ("EASY", "MODERATE", "DIFFICULT", "UNKNOWN")
                or d["information_value"] not in ("LOW", "MEDIUM", "HIGH") or d["blocking_power"] not in ("NONE", "LOW", "MEDIUM", "HIGH")
                or d["evidence_completeness"] not in ("PARTIAL", "SUFFICIENT")):
            raise ValueError("Invalid target dimensions")
        if not t["source_refs"] or not set(t["dependencies"]) <= ids or t["target_id"] in t["dependencies"]:
            raise ValueError("Invalid target trace/dependency")
        for ref in t["source_refs"]:
            source = sources.get(ref["diagnosis_hash"])
            if not source or source["diagnosis_id"] != ref["diagnosis_id"] or source["outcome"] != "ISSUES_DETECTED":
                raise ValueError("Target from invalid/no-issue diagnosis")
        if t["component_id"] in ("gpu", "appliance") and "FROZEN_COMPONENT" not in t["blocked_by"]:
            raise ValueError("Frozen component without blocker")
        if t["dependencies"] and "DEPENDENT_TARGET" not in t["blocked_by"]:
            raise ValueError("Dependency blocker missing")
        if (t["priority"], t["rule_ids"], t["reasons"]) != decide(d, t["blocked_by"], cfg):
            raise ValueError("Priority inconsistent with dimensions/blockers")
        if not set(t["rule_ids"]) <= set(RULES):
            raise ValueError("Unknown priority rule")
        if t["intent"] not in ("ACQUIRE_EVIDENCE", "INVESTIGATE_ISSUE") or (d["diagnostic_confidence"] in ("LOW", "VERY_LOW") and t["intent"] != "ACQUIRE_EVIDENCE"):
            raise ValueError("Unsupported confirmed-issue intent")
    graph = {t["target_id"]: t["dependencies"] for t in value["candidate_targets"]}
    def visit(node, ancestors):
        if node in ancestors:
            raise ValueError("Dependency cycle")
        for dep in graph[node]:
            visit(dep, ancestors | {node})
    for node in graph:
        visit(node, set())
    if value["ordering"] != [t["target_id"] for t in ordering(value["candidate_targets"])]:
        raise ValueError("Inconsistent ordering")
    if value["blockers"] != {t["target_id"]: t["blocked_by"] for t in value["candidate_targets"] if t["blocked_by"]}:
        raise ValueError("Inconsistent blocker index")
    if value["prioritization_hash"] != digest({k: v for k, v in value.items() if k != "prioritization_hash"}):
        raise ValueError("Prioritization hash mismatch")
    canonical_json(value)
    return value
