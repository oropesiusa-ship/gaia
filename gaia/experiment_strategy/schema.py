"""Canonical shadow decisions; validate immutable plan guards and reproducible policy ranks."""
from datetime import datetime
import json
import re

from ..provenance import canonical_json, digest
from .model import CLASSES, GUARDS, NOVELTY, PROFILE, template
from .policy import CONFIDENCE, COST, ORDINAL, identity, rank, score, settings

SCHEMA = "gaia_experiment_strategy_v1"
FIELDS = {"strategy_id", "schema", "timestamp", "mode", "analysis_mode", "context", "context_binding", "priority_ref",
          "diagnosis_refs", "diagnosis_binding", "learning_refs", "candidate_plans", "ranking", "exclusions",
          "history", "meta_metrics", "policy", "rationale", "confidence", "limitations", "cost", "output_hash"}


def seal(document):
    value = json.loads(canonical_json(document))
    value["output_hash"] = digest({k: v for k, v in value.items() if k != "output_hash"})
    validate(value)
    return value


def validate(value):
    if set(value) != FIELDS or value["schema"] != SCHEMA or not re.fullmatch(r"s[0-9]{6,}", value["strategy_id"]):
        raise ValueError("Invalid strategy schema/id")
    if value["mode"] != "SHADOW" or value["analysis_mode"] not in ("CURRENT_TARGET", "HISTORICAL_ANALYSIS") or datetime.fromisoformat(value["timestamp"]).tzinfo is None:
        raise ValueError("Invalid strategy mode/timestamp")
    cfg = settings({"meta_strategy": value["policy"]["settings"]})
    if value["policy"] != identity(cfg):
        raise ValueError("Strategy policy hash mismatch")
    plans = value["candidate_plans"]
    if len(plans) > cfg["max_candidate_plans"] or len({p["plan_id"] for p in plans}) != len(plans):
        raise ValueError("Invalid candidate budget/duplicate plan id")
    for plan in plans:
        expected_fields = {"plan_id", "target_ref", "knowledge_refs", "class", "mode", "design", "variables", "controlled_variables",
                           "baseline", "candidate_variation", "metrics", "guards", "discriminates", "stopping_rules", "estimates",
                           "novelty", "duplication", "blocked_by", "rationale", "rule_ids", "confidence", "execution", "utility", "plan_hash"}
        if set(plan) != expected_fields:
            raise ValueError("Unexpected plan fields")
        if not re.fullmatch(r"xp[a-f0-9]{24}", plan["plan_id"]) or plan["class"] not in CLASSES or plan["mode"] not in ("EXPLORE", "EXPLOIT", "VERIFY") or plan["novelty"] not in NOVELTY:
            raise ValueError("Invalid plan class/mode/novelty")
        if plan["mode"] != PROFILE[plan["class"]][0]:
            raise ValueError("Class/mode mismatch")
        if plan["target_ref"]["priority"] == "DEFER" or plan["target_ref"]["component_id"] in ("gpu", "appliance"):
            raise ValueError("Plan for deferred/frozen target")
        if plan["guards"] != GUARDS or plan["execution"] != {"mode": "SHADOW", "authorized": False, "executed": False, "code_generated": False}:
            raise ValueError("Plan has execution or mutation authority")
        if plan["candidate_variation"]["numeric_values"] is not None or plan["candidate_variation"]["code"] is not None:
            raise ValueError("Plan contains generated values/code")
        if plan["design"] == "CONTROLLED_FACTORIAL" and plan["class"] != "DISCRIMINATION":
            raise ValueError("Uncontrolled multifactor plan")
        spec = template(plan["class"], plan["target_ref"]["target_class"], factorial=plan["design"] == "CONTROLLED_FACTORIAL", knowledge=bool(plan["knowledge_refs"]))
        if plan["class"] == "KNOWLEDGE_VALIDATION":
            spec["controlled_variables"] = [v for v in spec["controlled_variables"] if v != "runtime_identity"]
        if plan["duplication"]["risk"] == "HIGH" and not plan["duplication"]["intentional"]:
            spec["variables"] = ["accidental_exact_configuration_repeat"]
            spec["design"] = "PAIRED_REPLICATION"
            spec["candidate_variation"]["kind"] = "REPEAT_REFERENCE_CONFIGURATION"
        for field in ("design", "variables", "controlled_variables", "metrics", "discriminates"):
            if plan[field] != spec[field]:
                raise ValueError("Plan deviates from closed scientific template")
        if plan["candidate_variation"]["kind"] != spec["candidate_variation"]["kind"]:
            raise ValueError("Invalid candidate comparison")
        if plan["class"] in ("CONTROL_EXPERIMENT", "BASELINE_RECONFIRMATION") and plan["candidate_variation"]["reference_configuration_hash"] != plan["baseline"]["configuration_hash"]:
            raise ValueError("Identical-baseline control references a different candidate")
        if plan["mode"] == "EXPLOIT" and (not plan["knowledge_refs"] or any(k["stale"] or k["effective_status"] == "CONTRADICTED" or k["applicability"] != "EXACT_CONTEXT" for k in plan["knowledge_refs"])):
            raise ValueError("Exploitation of stale/contradicted/unbound knowledge")
        estimates = plan["estimates"]
        if (estimates["information_value"] not in ("LOW", "MEDIUM", "HIGH") or estimates["improvement_potential"] not in ORDINAL
                or estimates["cost"] not in COST or estimates["risk"] not in ("LOW", "MEDIUM", "HIGH")
                or estimates["reversibility"] not in ("EASY", "MODERATE", "DIFFICULT", "UNKNOWN") or plan["confidence"] not in CONFIDENCE
                or estimates["future_seconds_estimate"] is not None):
            raise ValueError("Invalid plan estimates")
        stops = plan["stopping_rules"]
        if (not stops["success_condition"] or not stops["rejection_condition"] or not stops["inconclusive_condition"]
                or type(stops["max_evidence_budget"]) is not int or not 1 <= stops["max_evidence_budget"] <= cfg["max_trials_per_plan"]
                or stops["automatic_extension"] is not False or stops["stop_on_guard_failure"] is not True):
            raise ValueError("Invalid stopping budget/guards")
        if stops["minimum_evidence_budget"] > stops["max_evidence_budget"] and "INSUFFICIENT_CONCEPTUAL_EVIDENCE_BUDGET" not in plan["blocked_by"]:
            raise ValueError("Insufficient plan budget unblocked")
        if (estimates["risk"] == "HIGH" or estimates["reversibility"] in ("DIFFICULT", "UNKNOWN")) and "SENSITIVE_OR_UNBOUNDED_INVESTIGATION" not in plan["blocked_by"]:
            raise ValueError("Sensitive plan without blocker")
        components = score(plan, cfg)
        if plan["utility"] != {"components": components, "ordinal_total": sum(components.values()), "calibrated_expected_value": False}:
            raise ValueError("Utility components mismatch")
        if plan["plan_hash"] != digest({k: v for k, v in plan.items() if k != "plan_hash"}):
            raise ValueError("Plan hash mismatch")
        if plan["plan_id"] != "xp" + digest({k: v for k, v in plan.items() if k not in ("plan_id", "plan_hash")})[:24]:
            raise ValueError("Plan identity mismatch")
    if value["ranking"] != [p["plan_id"] for p in rank(plans)]:
        raise ValueError("Strategy ranking mismatch")
    metrics = value["meta_metrics"]
    if metrics["metrics_hash"] != digest({k: v for k, v in metrics.items() if k != "metrics_hash"}):
        raise ValueError("Meta-metrics hash mismatch")
    history = value["history"]
    if history["history_hash"] != digest({k: v for k, v in history.items() if k != "history_hash"}):
        raise ValueError("Strategy history hash mismatch")
    if any(p["executed_by_subsystem"] is not False or p["eventual_execution"] != "UNKNOWN_UNLINKED" or p["linked_experiments"]
           or any(p[k] is not None for k in ("outcome", "information_gained", "improvement_found", "actual_cost_s")) for p in history["proposed_plans"]):
        raise ValueError("Invented plan execution linkage")
    if {p["plan_id"] for p in history["proposed_plans"]} != {p["plan_id"] for p in plans}:
        raise ValueError("Incomplete proposal history")
    if not value["limitations"] or value["output_hash"] != digest({k: v for k, v in value.items() if k != "output_hash"}):
        raise ValueError("Strategy output hash/limitations invalid")
    canonical_json(value)
    return value
