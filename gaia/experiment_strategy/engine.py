"""Pure shadow planning, separate from gaia.engine, search.Strategy and gaia.meta."""
from datetime import datetime, timezone
import time

from ..provenance import digest
from .history import summarize
from .inputs import ingest
from .plans import build
from .policy import identity, outcome_statistics, rank, settings
from .schema import SCHEMA, seal


def plan_experiments(priority, learning_runs=(), *, context=None, diagnoses=(), analysis_mode="CURRENT_TARGET", configuration=None, strategy_id="s000001",
                     context_scope="OBSERVATION_ENVIRONMENT", outcomes=None):
    start = time.perf_counter()
    cfg = settings(configuration)
    try:
        inputs = ingest(priority, learning_runs, context, diagnoses, analysis_mode, context_scope)
        linked = None if outcomes is None else validate_outcomes(outcomes)
        stats = None if linked is None else outcome_statistics(linked)
        plans, exclusions = build(inputs, context, analysis_mode, cfg, stats)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid explicit strategy inputs") from exc
    eligible = rank(plans)
    retained = eligible[:cfg["max_candidate_plans"]]
    # Exploration floor is a visible policy budget choice only when coverage is absent,
    # not a novelty bonus or automatic preference for unsupported newness.
    if not any(not v["superseded"] and v["assessment"]["transferability"] == "EXACT_CONTEXT" for v in inputs["views"]):
        explores = [p for p in eligible if p["mode"] == "EXPLORE"][:cfg["exploration_floor"]]
        protected = {p["plan_id"] for p in explores}
        for p in explores:
            if p not in retained:
                if len(retained) == cfg["max_candidate_plans"]:
                    removable = next((p for p in reversed(retained) if p["plan_id"] not in protected), None)
                    if removable is None:
                        continue
                    retained.remove(removable)
                retained.append(p)
    for p in plans:
        if p["blocked_by"] and len(retained) < cfg["max_candidate_plans"]:
            retained.append(p)
    ids = {p["plan_id"] for p in retained}
    for p in plans:
        if p["plan_id"] not in ids:
            exclusions.append({"plan_id": p["plan_id"], "target_ref": p["target_ref"], "reason": "CANDIDATE_PLAN_BUDGET"})
    retained.sort(key=lambda p: p["plan_id"])
    history = summarize(inputs["records"], inputs["runs"])
    metrics = history.pop("metrics")
    history["proposed_plans"] = [{"plan_id": p["plan_id"], "class": p["class"], "mode": p["mode"],
                                    "target_ref": p["target_ref"], "executed_by_subsystem": False,
                                    "eventual_execution": "UNKNOWN_UNLINKED", "linked_experiments": [],
                                    "outcome": None, "information_gained": None, "improvement_found": None, "actual_cost_s": None} for p in retained]
    history["history_hash"] = digest(history)
    value = {"strategy_id": strategy_id, "schema": SCHEMA, "timestamp": datetime.now(timezone.utc).isoformat(), "mode": "SHADOW",
             "analysis_mode": analysis_mode, "context": context,
             "context_binding": "CONTROLLED_HISTORICAL_SCOPE_NOT_CURRENT_HOST" if analysis_mode == "HISTORICAL_ANALYSIS" else "EXPLICIT_EXECUTION_MANIFEST_NOT_OBSERVATION_IDENTITY" if context and context_scope == "EXECUTION_MANIFEST" else "EXPLICIT_OBSERVATION_ENVIRONMENT" if context else "NOT_PROVIDED",
             "priority_ref": {"prioritization_id": priority["prioritization_id"], "hash": priority["prioritization_hash"]},
             "diagnosis_refs": [{"diagnosis_id": r["diagnosis_id"], "hash": r["diagnosis_hash"]} for r in priority["source_diagnoses"]],
             "diagnosis_binding": inputs["diagnosis_binding"],
             "learning_refs": [{"run_hash": r["run_hash"], "source_hashes": sorted(r["source_hashes"])} for r in inputs["runs"]],
             "candidate_plans": retained, "ranking": [p["plan_id"] for p in rank(retained)], "exclusions": exclusions,
             "history": history, "meta_metrics": metrics, "policy": identity(cfg),
             "rationale": "PRIORITY_TIERS_PRESERVED_THEN_ORDINAL_INFORMATION_UTILITY_WITH_EXPLICIT_PENALTIES",
             "confidence": "LOW" if metrics["small_sample"] else "MEDIUM",
             "limitations": ["SHADOW ONLY: no experiment executed, no code generated and no mutation authorized.",
                             "Historical analysis with controlled targets is not evidence of a current host problem.",
                             "Ordinal utility is a transparent policy, not calibrated scientific expected utility.",
                             "Knowledge applicability is relative to the explicit supplied context, never a recollected host.",
                             "Execution identities and saved evidence are not proof of statistical independence or causality.",
                             "Historical trials are not linked to newly proposed plans; no retrospective strategy attribution without evidence.",
                             "Usefulness metrics are descriptive information proxies; a small sample proves no general strategy improvement.",
                             "Symbolic factors require separate future operational design and authorization; protected criteria stay fixed.",
                             "Symbolic local variations may overlap; no novel candidate configuration is certified without actual future factor values.",
                             "Explicit learning snapshots may omit later history; only the supplied history is assessed."],
             "cost": {"duration_s": time.perf_counter() - start, "targets_processed": len(priority["candidate_targets"]),
                      "plans_generated": len(retained), "plans_considered": len(plans), "learning_runs_processed": len(inputs["runs"])}}
    if linked is not None:
        value["outcome_statistics"] = {"mode": "LINKED_EXECUTED_OUTCOMES", "outcomes": linked, "by_class": stats,
                                       "static_ranking": [p["plan_id"] for p in rank(retained, static=True)],
                                       "bound": "LINKED_COMPONENT_WITHIN_PLUS_MINUS_3_POLICY_DEFAULTS_UNCHANGED"}
    return seal(value)


def validate_outcomes(outcomes):
    keys = {"experiment_id", "class", "target_class", "outcome", "hypothesis_assessment", "cost_s"}
    result = []
    for o in outcomes:
        if (not isinstance(o, dict) or set(o) != keys or o["outcome"] not in ("ACCEPTED", "REJECTED", "INCONCLUSIVE")
                or o["hypothesis_assessment"] not in ("SUPPORTED", "NOT_SUPPORTED", "INCONCLUSIVE") or not isinstance(o["class"], str)
                or not isinstance(o["target_class"], str) or not (o["cost_s"] is None or type(o["cost_s"]) in (int, float))):
            raise ValueError("Invalid linked strategy outcome")
        result.append(dict(o))
    return result
