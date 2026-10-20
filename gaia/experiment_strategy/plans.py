"""Construct closed, non-executable research comparisons from contextual evidence."""
import statistics

from ..learning.schema import HASH
from ..provenance import digest
from .model import GUARDS, PROFILE, finish_plan, template
from .policy import CONFIDENCE, ORDINAL, score


def build(inputs, context, analysis_mode, cfg):
    priority = inputs["priority"]
    plans, exclusions = [], []
    record_map = {r["learning_id"]: r for r in inputs["records"]}
    context_hash = digest(context) if context is not None else None
    rejected_points = {}
    for v in inputs["views"]:
        k = v["item"]
        if (not v["superseded"] and not v["contradicted"] and v["assessment"]["transferability"] == "EXACT_CONTEXT"
                and k["claim"]["subject"] == "EXACT_CONFIGURATION" and k["claim_type"] == "REJECTED_DIRECTION"
                and k["claim"].get("negative_reuse_scope") == "EXACT_CANDIDATE_EQUIVALENT_CONTEXT_ONLY"):
            for r in k["claim"]["record_refs"]:
                if r in record_map:
                    point = (record_map[r]["claim"]["configuration_hash"], record_map[r]["claim"]["baseline_hash"])
                    rejected_points.setdefault(point, []).append({"learning_id": k["learning_id"], "hash": k["hash"],
                        "claim_type": k["claim_type"], "effective_status": k["status"], "applicability": "EXACT_CONTEXT", "stale": False})
    def target_ref(t):
        return {"priority_id": priority["prioritization_id"], "priority_hash": priority["prioritization_hash"],
                "target_id": t["target_id"], "target_class": t["target_class"], "component_id": t["component_id"],
                "priority": t["priority"], "impact": t["dimensions"]["impact"], "context_hash": context_hash,
                "diagnosis_refs": [{k: r[k] for k in ("diagnosis_id", "diagnosis_hash", "issue_id", "hypothesis_id", "evidence_refs")} for r in t["source_refs"]]}
    def add(t, cls, rule, reason, view=None, *, factorial=False, accidental=False):
        mode, information, improvement, cost, maximum = PROFILE[cls]
        spec = template(cls, t["target_class"], factorial=factorial, knowledge=view is not None)
        knowledge = view["item"] if view else None
        refs, baseline_hash, reference_hash, historical_cost = [], None, None, None
        confidence = t["dimensions"]["diagnostic_confidence"]
        novelty, duplicate_risk, intentional, negative_scope = "UNKNOWN", "LOW", False, "NONE"
        blocked = []
        if knowledge:
            refs = [{"learning_id": knowledge["learning_id"], "hash": knowledge["hash"], "claim_type": knowledge["claim_type"],
                     "effective_status": "CONTRADICTED" if view["contradicted"] else knowledge["status"],
                     "applicability": view["assessment"]["transferability"], "stale": view["assessment"]["status"] == "STALE"}]
            candidates = [record_map[r] for r in knowledge["claim"]["record_refs"] if r in record_map]
            candidates.sort(key=lambda r: (r["claim"]["outcome"] != "ACCEPTED", r["learning_id"]))
            if not candidates:
                raise ValueError("Knowledge lacks its raw learning records")
            reference_hash, baseline_hash = candidates[0]["claim"]["configuration_hash"], candidates[0]["claim"]["baseline_hash"]
            if not HASH.fullmatch(reference_hash) or not HASH.fullmatch(baseline_hash):
                raise ValueError("Invalid known configuration reference")
            costs = [v for e in knowledge["supporting_evidence"] if e["confirmation"] for v in e["confirmation"]["candidate_costs"]]
            historical_cost = statistics.median(costs) if costs else None
            confidence = min((confidence, knowledge["confidence"]), key=CONFIDENCE.get)
            if view["contradicted"] or view["assessment"]["status"] == "STALE":
                confidence = "LOW"
            novelty = "EXACT_REPEAT" if cls in ("REPLICATION", "BASELINE_RECONFIRMATION") or cls == "DISCRIMINATION" and not factorial or accidental else "KNOWN_REGION"
            intentional = cls == "REPLICATION" or cls == "DISCRIMINATION" and not factorial
            negative_scope = knowledge["claim"].get("negative_reuse_scope", "NONE")
            if accidental:
                novelty, duplicate_risk = "EXACT_REPEAT", "HIGH"
                if negative_scope == "EXACT_CANDIDATE_EQUIVALENT_CONTEXT_ONLY":
                    blocked.append("EXACT_REJECTED_CONFIGURATION")
                spec["candidate_variation"]["kind"] = "REPEAT_REFERENCE_CONFIGURATION"
                spec["variables"] = ["accidental_exact_configuration_repeat"]
                spec["design"] = "PAIRED_REPLICATION"
                improvement, information = "LOW", "LOW"
            if cls in ("PARAMETER_LOCAL_SEARCH", "EXPLOITATION"):
                novelty = "NEAR_REPEAT" if knowledge["claim"]["subject"] == "EXACT_CONFIGURATION" else "KNOWN_REGION"
                duplicate_risk = "MEDIUM"  # Symbolic variations cannot certify a new config hash yet.
            if cls == "EXPLORATION" and not accidental:
                novelty, duplicate_risk = "NEAR_REPEAT", "MEDIUM"
            # A regional summary must not smuggle a known exact rejection back
            # into ranking as an apparently inconclusive paired repeat.
            if ((reference_hash, baseline_hash) in rejected_points and spec["candidate_variation"]["kind"] == "REPEAT_REFERENCE_CONFIGURATION"
                    and not view["contradicted"]):
                blocked.append("EXACT_REJECTED_CONFIGURATION")
                accidental = True
                novelty, duplicate_risk, intentional = "EXACT_REPEAT", "HIGH", False
                negative_scope = "EXACT_CANDIDATE_EQUIVALENT_CONTEXT_ONLY"
                spec["variables"] = ["accidental_exact_configuration_repeat"]
                spec["design"] = "PAIRED_REPLICATION"
                information, improvement = "LOW", "LOW"
                refs += rejected_points[(reference_hash, baseline_hash)]
                refs = [r for _, r in sorted({r["hash"]: r for r in refs}.items())]
        if cls == "EXPLORATION" and not knowledge:
            novelty = "UNKNOWN"  # No history is not proof of a genuinely new region.
        if factorial:
            cost, maximum = "MEDIUM", 20
        risk = t["dimensions"]["risk"]
        reversibility = t["dimensions"]["reversibility"]
        if risk == "HIGH" or reversibility in ("DIFFICULT", "UNKNOWN"):
            blocked.append("SENSITIVE_OR_UNBOUNDED_INVESTIGATION")
        if knowledge and context is None:
            blocked.append("CONTEXT_NOT_BOUND")
        if spec["candidate_variation"]["kind"] == "CURRENT_CONTEXT_VS_DECLARED_KNOWLEDGE_SCOPE":
            spec["controlled_variables"] = [v for v in spec["controlled_variables"] if v != "runtime_identity"]
        minimum = 20 if factorial else 3 if cls == "MEASUREMENT_REFINEMENT" else 5
        if cfg["max_trials_per_plan"] < minimum:
            blocked.append("INSUFFICIENT_CONCEPTUAL_EVIDENCE_BUDGET")
        max_trials = min(maximum, cfg["max_trials_per_plan"])
        guards = dict(GUARDS)
        candidate = {**spec.pop("candidate_variation"), "reference_configuration_hash": reference_hash}
        plan = {"target_ref": target_ref(t), "knowledge_refs": refs, "class": cls, "mode": mode, **spec,
                "baseline": {"kind": "KNOWN_EXPERIMENT_BASELINE" if baseline_hash else "EXISTING_TARGET_BASELINE", "configuration_hash": baseline_hash},
                "candidate_variation": candidate, "guards": guards,
                "stopping_rules": {"success_condition": "EVIDENCE_DISCRIMINATES_UNDER_EXISTING_PROTECTED_CRITERIA",
                                   "rejection_condition": "QUALITY_GUARD_FAILURE_OR_NO_VERIFIED_EFFECT_AT_BUDGET",
                                   "inconclusive_condition": "INTERVAL_SCOPE_OR_COMPETING_HYPOTHESES_UNRESOLVED_AT_BUDGET",
                                   "max_evidence_budget": max_trials, "minimum_evidence_budget": minimum,
                                   "budget_unit": "CONDITION_TRIAL_OBSERVATIONS" if factorial else "MEASUREMENT_SAMPLES" if cls == "MEASUREMENT_REFINEMENT" else "PAIRED_TRIALS",
                                   "independence_requirement": "NEW_EXECUTION_AND_MEASUREMENTS_NOT_COPIED_CONFIRMATIONS",
                                   "stop_on_guard_failure": True, "automatic_extension": False},
                "estimates": {"information_value": information, "improvement_potential": improvement, "cost": cost,
                              "risk": risk, "reversibility": reversibility,
                              "target_investigation_cost": t["dimensions"]["investigation_cost"],
                              "historical_candidate_cost_median_s": historical_cost,
                              "historical_cost_scope": "COST_TO_QUALITY_SAMPLES_NOT_PROJECTED_WALL_TIME",
                              "future_seconds_estimate": None},
                "novelty": novelty, "duplication": {"risk": duplicate_risk, "intentional": intentional,
                                                     "negative_reuse_scope": negative_scope,
                                                     "exact_new_configuration_proven": False},
                "blocked_by": sorted(set(blocked)), "rationale": [reason], "rule_ids": [rule], "confidence": confidence,
                "execution": {"mode": "SHADOW", "authorized": False, "executed": False, "code_generated": False}}
        if factorial:
            plan["rationale"].append("CO_CHANGED_LR_WD_ARE_CONFOUNDING_NOT_ESTABLISHED_INTERACTION")
            plan["rule_ids"].append("META_FACTORIAL_001")
        if "EXACT_REJECTED_CONFIGURATION" in blocked and "META_NEGATIVE_001" not in plan["rule_ids"]:
            plan["rule_ids"].append("META_NEGATIVE_001")
            plan["rationale"].append("EXACT_NEGATIVE_EVIDENCE_OVERRIDES_REGIONAL_REUSE")
        if blocked:
            plan["rule_ids"].append("META_AUTHORITY_001")
        components = score(plan, cfg)
        plan["utility"] = {"components": components, "ordinal_total": sum(components.values()), "calibrated_expected_value": False}
        plans.append(finish_plan(plan))
    for t in priority["candidate_targets"]:
        if t["priority"] == "DEFER" or t["blocked_by"] or t["component_id"] in ("gpu", "appliance"):
            exclusions.append({"target_ref": target_ref(t), "reason": "FROZEN_COMPONENT" if t["component_id"] in ("gpu", "appliance") else "TARGET_DEFERRED_OR_BLOCKED"})
            continue
        if t["target_class"] == "MEASUREMENT_QUALITY":
            add(t, "MEASUREMENT_REFINEMENT", "META_MEASUREMENT_001", "MEASUREMENT_SCOPE_QUALITY_BEFORE_ATTRIBUTION")
            continue
        if t["target_class"] == "GPU_RUNTIME_EFFICIENCY":
            exclusions.append({"target_ref": target_ref(t), "reason": "FROZEN_COMPONENT"})
            continue
        relevant = []
        for view in inputs["views"]:
            k = view["item"]
            if view["superseded"]:
                continue
            if k["component"] != t["component_id"] and t["target_class"] not in ("UNKNOWN_REQUIRES_EVIDENCE", "QUALITY_REGRESSION", "MEMORY_EFFICIENCY"):
                continue
            if view["assessment"]["transferability"] == "NOT_TRANSFERABLE":
                continue
            relevant.append(view)
        for view in relevant:
            k = view["item"]
            if view["assessment"]["status"] in ("STALE", "UNASSESSED", "LIMITED"):
                add(t, "KNOWLEDGE_VALIDATION", "META_STALE_001", "SCOPE_VALIDATION_BEFORE_KNOWLEDGE_REUSE", view)
            elif view["contradicted"]:
                add(t, "DISCRIMINATION", "META_CONTRADICTION_001", "CONFLICTING_EVIDENCE_MUST_BE_DISCRIMINATED_NOT_EXPLOITED", view)
            elif k["claim_type"] == "REJECTED_DIRECTION":
                add(t, "EXPLORATION", "META_NEGATIVE_001", "EXACT_NEGATIVE_REPEAT_NOT_A_REGIONAL_BAN", view, accidental=True)
                add(t, "EXPLORATION", "META_EXPLORE_001", "NEARBY_SYMBOLIC_VARIATION_NOT_EXCLUDED_BY_ONE_NEGATIVE_POINT", view)
            elif k["claim_type"] in ("PROMISING_DIRECTION", "INCONCLUSIVE_RESULT"):
                add(t, "DISCRIMINATION", "META_INCONCLUSIVE_001", "FAVORABLE_OR_UNRESOLVED_RESULT_NEEDS_DISCRIMINATING_EVIDENCE", view)
            elif k["claim"]["subject"] == "EXACT_CONFIGURATION" and k["claim_type"] == "OBSERVED_EFFECT":
                add(t, "REPLICATION", "META_REPLICATE_001", "ACCEPTED_EFFECT_LACKS_INDEPENDENT_REPLICATION", view)
                add(t, "PARAMETER_LOCAL_SEARCH", "META_EXPLOIT_001", "FAVORABLE_POINT_IS_A_LIMITED_PRIOR_NOT_AN_OPTIMUM", view)
            elif k["status"] == "OPERATIONAL_KNOWLEDGE":
                add(t, "EXPLOITATION", "META_EXPLOIT_001", "REPLICATED_EXACT_CONTEXT_KNOWLEDGE_CAN_INFORM_CONTROLLED_REUSE", view)
                add(t, "BASELINE_RECONFIRMATION", "META_BASELINE_001", "BASELINE_CONTROL_REMAINS_REQUIRED", view)
            elif k["claim_type"] == "CONTEXT_DEPENDENT_EFFECT":
                add(t, "PARAMETER_LOCAL_SEARCH", "META_EXPLOIT_001", "PROMISING_REGION_IS_CONTEXT_LIMITED", view)
                if k["claim"].get("template") == "higher_lr_points_promising_and_confirmed_configuration_observed_not_isolated_wd_causality":
                    add(t, "DISCRIMINATION", "META_FACTORIAL_001", "SEPARATE_LR_WD_AND_INTERACTION_OR_CONFOUNDING", view, factorial=True)
        add(t, "CONTROL_EXPERIMENT", "META_BASELINE_001", "CHEAP_INFORMATION_CONTROL_WITHOUT_CHANGING_TARGET_PRIORITY")
        if not relevant:
            if t["intent"] == "ACQUIRE_EVIDENCE" and t["target_class"] in ("CPU_RUNTIME_EFFICIENCY", "MEMORY_EFFICIENCY", "RESOURCE_CONTENTION", "UNKNOWN_REQUIRES_EVIDENCE"):
                add(t, "DISCRIMINATION", "META_INCONCLUSIVE_001", "TARGET_UNCERTAINTY_REQUIRES_HYPOTHESIS_DISCRIMINATION_BEFORE_OPTIMIZATION")
            add(t, "EXPLORATION", "META_EXPLORE_001", "NO_APPLICABLE_KNOWLEDGE_REQUIRES_CONTROLLED_EXPLORATION")
    return sorted({p["plan_id"]: p for p in plans}.values(), key=lambda p: p["plan_id"]), exclusions
