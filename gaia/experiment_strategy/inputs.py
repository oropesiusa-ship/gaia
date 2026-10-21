"""Validate saved input identities and project only fixed-vocabulary references."""
import re

from ..diagnosis.schema import validate as validate_diagnosis
from ..learning.engine import settings as learning_settings
from ..learning.applicability import assess
from ..learning.schema import HASH, HIERARCHY, finite, validate as validate_learning, valid_context
from ..prioritization.schema import validate as validate_priority
from ..prioritization.targets import CLASSES as TARGETS
from ..provenance import digest


def ingest(priority, learning_runs, context, diagnoses, analysis_mode):
    validate_priority(priority)
    if analysis_mode not in ("CURRENT_TARGET", "HISTORICAL_ANALYSIS"):
        raise ValueError("Unknown analysis mode")
    if context is not None:
        valid_context(context)
    if analysis_mode == "HISTORICAL_ANALYSIS" and context is None:
        raise ValueError("Historical analysis requires explicit declared scope")
    mapped = {v[0]: v[1] for v in TARGETS.values()}
    for t in priority["candidate_targets"]:
        if set(t["blocked_by"]) - {"FROZEN_COMPONENT", "DEPENDENT_TARGET", "CAPABILITY_UNAVAILABLE"}:
            raise ValueError("Unknown target blocker")
        if t["component_id"] != mapped[t["target_class"]]:
            raise ValueError("Target class/component mismatch")
        for ref in t["source_refs"]:
            if (not re.fullmatch(r"i[0-9]{4,}", ref["issue_id"]) or not re.fullmatch(r"h[0-9]{4,}", ref["hypothesis_id"])
                    or any(not re.fullmatch(r"e[0-9]{4,}", e) for e in ref["evidence_refs"])):
                raise ValueError("Invalid target evidence reference")
    for ref in priority["source_observations"]:
        if ref["role"] not in ("current", "baseline") or not re.fullmatch(r"o[0-9]{6,}", ref["observation_id"]) or any(not HASH.fullmatch(ref[k]) for k in ("observation_hash", "environment_hash", "source_hash")):
            raise ValueError("Invalid priority observation identity")
    diagnostic = {validate_diagnosis(d)["diagnosis_hash"]: d for d in diagnoses}
    for ref in priority["source_diagnoses"]:
        if ref["outcome"] not in ("ISSUES_DETECTED", "NO_SIGNIFICANT_ISSUE", "INSUFFICIENT_EVIDENCE"):
            raise ValueError("Unknown diagnostic outcome")
        if diagnostic and ref["diagnosis_hash"] not in diagnostic:
            raise ValueError("Missing exact diagnosis source")
        if diagnostic and (diagnostic[ref["diagnosis_hash"]]["diagnosis_id"] != ref["diagnosis_id"] or diagnostic[ref["diagnosis_hash"]]["outcome"] != ref["outcome"]):
            raise ValueError("Diagnosis identity/outcome reference mismatch")
    for t in priority["candidate_targets"]:
        for ref in t["source_refs"]:
            if diagnostic:
                d = diagnostic[ref["diagnosis_hash"]]
                issue = next((i for i in d["issues"] if i["issue_id"] == ref["issue_id"]), None)
                if not issue or ref["hypothesis_id"] not in issue["hypothesis_ids"] or not set(ref["evidence_refs"]) <= {e["evidence_id"] for e in d["evidence"]}:
                    raise ValueError("Diagnostic target lineage mismatch")
    if analysis_mode == "CURRENT_TARGET" and context is not None:
        current_environments = {r["environment_hash"] for r in priority["source_observations"] if r["role"] == "current"}
        if current_environments != {context["environment_hash"]}:
            raise ValueError("Explicit current context does not bind to target observation identity")
    items, relations, runs, records = {}, [], {}, {}
    for run in learning_runs:
        if (run["schema"] != "gaia_learning_run_v1" or run["evidence_hierarchy"] != list(HIERARCHY)
                or run["run_hash"] != digest({k: v for k, v in run.items() if k != "run_hash"})):
            raise ValueError("Invalid learning run")
        runs[run["run_hash"]] = run
        if any(not isinstance(h, str) or not HASH.fullmatch(h) for h in run["source_hashes"]):
            raise ValueError("Invalid learning source hash")
        for item in run["records"] + run["knowledge"]:
            validate_learning(item)
            if item["claim"].get("negative_reuse_scope", "NONE") not in ("NONE", "HISTORICAL_REJECTION_ONLY", "EXACT_CANDIDATE_EQUIVALENT_CONTEXT_ONLY"):
                raise ValueError("Unknown negative evidence scope")
            for e in item["supporting_evidence"]:
                if e["outcome"] not in ("ACCEPTED", "REJECTED", "INCONCLUSIVE") or e["rollback"] not in ("NONE", "VERIFICATION", "ADVERSE", "UNKNOWN") or type(e["promotion"]) is not bool:
                    raise ValueError("Invalid historical outcome")
                screen = e["screen"]
                if screen["status"] not in ("ok", "error", "invalid", "timeout") or type(screen["reached"]) is not bool:
                    raise ValueError("Invalid historical screen")
                if any(v is not None and (not finite(v) or v <= 0) for v in (screen["cost_s"], screen["baseline_cost_s"], e["ratio"], e["upper95"])):
                    raise ValueError("Non-numeric historical measurement")
                confirmation = e["confirmation"]
                if confirmation is not None:
                    if (confirmation["decision"] not in ("accepted", "rejected", "deferred", "pareto_alternative")
                            or any(type(confirmation[k]) is not int or confirmation[k] < 0 for k in ("pairs", "trial_count", "candidate_reached", "baseline_reached"))
                            or any(not isinstance(confirmation[k], list) or len(confirmation[k]) != confirmation["pairs"] or any(not finite(v) or v <= 0 for v in confirmation[k]) for k in ("candidate_costs", "baseline_costs"))):
                        raise ValueError("Invalid paired historical measurements")
            if item["learning_id"] in items and items[item["learning_id"]] != item:
                raise ValueError("Conflicting immutable knowledge identity")
            items[item["learning_id"]] = item
            if item["kind"] == "record":
                records[item["learning_id"]] = item
        relations += run["relations"]
    relations = list({digest(r): r for r in relations}.values())
    for relation in relations:
        if relation["from"] not in items or relation["to"] not in items or relation["relation"] not in ("supports", "weakens", "contradicts", "supersedes", "superseded_by"):
            raise ValueError("Incomplete knowledge relationship history")
        if relation["relation"] in ("supersedes", "superseded_by"):
            newer = items[relation["from"] if relation["relation"] == "supersedes" else relation["to"]]
            older = items[relation["to"] if relation["relation"] == "supersedes" else relation["from"]]
            if (newer["kind"] != "knowledge" or older["kind"] != "knowledge"
                    or newer["claim"]["group_key"] != older["claim"]["group_key"]
                    or not set(older["source_evidence_hashes"]) < set(newer["source_evidence_hashes"])):
                raise ValueError("Invalid supersession ordering/scope")
    known_evidence = {e["evidence_hash"] for r in records.values() for e in r["supporting_evidence"]}
    for run in runs.values():
        policy = learning_settings({"learning": run["settings"]})
        for item in run["knowledge"]:
            if not set(item["source_evidence_hashes"]) <= known_evidence:
                raise ValueError("Knowledge evidence not bound to raw records")
            if item["status"] == "OPERATIONAL_KNOWLEDGE" and item["quality"]["independent_positive_count"] < policy["minimum_independent_replications"]:
                raise ValueError("Knowledge violates its replication policy")
        for comparison in run["experiment_comparisons"]:
            if comparison["a"] not in known_evidence or comparison["b"] not in known_evidence:
                raise ValueError("Unbound experimental comparison")
            if comparison["kind"] not in ("INDEPENDENT_REPLICATION", "EXACT_MEASUREMENT_DUPLICATE", "EXACT_CONFIGURATION_REPEAT", "NEAR_DUPLICATE"):
                raise ValueError("Unknown experimental comparison")
        for duplicate in run["duplicates"]:
            if duplicate["kind"] != "EXACT_DUPLICATE" or duplicate["evidence_hash"] not in known_evidence or duplicate["counted_independently"] is not False:
                raise ValueError("Invalid experimental duplicate")
    for item in items.values():
        if item["kind"] == "knowledge" and (not set(item["claim"]["record_refs"]) <= records.keys()
                or any(not re.fullmatch(r"l[a-f0-9]{24}", r) for r in item["claim"]["record_refs"])):
            raise ValueError("Knowledge record lineage is incomplete")
    views = []
    for item in sorted((i for i in items.values() if i["kind"] == "knowledge"), key=lambda k: k["learning_id"]):
        superseded = any(r["relation"] == "superseded_by" and r["from"] == item["learning_id"] for r in relations)
        contradicted = item["status"] == "CONTRADICTED" or any(r["relation"] in ("weakens", "contradicts") and r["to"] == item["learning_id"] for r in relations)
        view = assess(item["applicability"], context)
        views.append({"item": item, "assessment": view, "superseded": superseded, "contradicted": contradicted})
    return {"priority": priority, "views": views, "records": list(records.values()), "runs": [runs[k] for k in sorted(runs)],
            "diagnosis_binding": "EXACT_SOURCES_CHECKED" if diagnostic else "PRIORITY_REFERENCES_ONLY"}
