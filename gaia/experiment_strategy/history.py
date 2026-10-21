"""Retrospective process metrics with explicit denominators and no invented execution links."""
from ..provenance import digest


def summarize(records, runs):
    unique = {}
    for record in records:
        for evidence in record["supporting_evidence"]:
            key = evidence["evidence_hash"]
            if key in unique and unique[key] != evidence:
                raise ValueError("Conflicting historical evidence")
            unique[key] = evidence
    rows = [unique[k] for k in sorted(unique)]
    counts = {outcome: sum(e["outcome"] == outcome for e in rows) for outcome in ("ACCEPTED", "REJECTED", "INCONCLUSIVE")}
    informative = []
    for e in rows:
        # Transparent descriptive proxy, not a claim of global research usefulness.
        informative.append(e["confirmation"] is not None or e["screen"]["status"] != "ok" or not e["screen"]["reached"]
                           or e["screen"]["cost_s"] is not None and e["screen"]["baseline_cost_s"] is not None)
    comparisons = {digest(c): c for run in runs for c in run["experiment_comparisons"]}
    duplicates = {c["b"] for c in comparisons.values() if c["kind"] == "EXACT_MEASUREMENT_DUPLICATE"}
    for run in runs:
        duplicates.update(d["evidence_hash"] for d in run["duplicates"])
    n = len(rows)
    history = [{"evidence_hash": e["evidence_hash"], "experiment_id": e["experiment_id"],
                "execution_hash": e["execution_hash"], "classification": "UNATTRIBUTED_HISTORICAL_EXPERIMENT",
                "strategy_class": None, "linked_plan_id": None, "historical_trials_present": True,
                "outcome": e["outcome"], "information_produced_proxy": informative[i],
                "accepted_improvement_recorded": e["outcome"] == "ACCEPTED",
                "known_candidate_confirmation_cost_s": sum(e["confirmation"]["candidate_costs"]) if e["confirmation"] else None}
               for i, e in enumerate(rows)]
    episodes = []
    for c in sorted(comparisons.values(), key=lambda c: (c["a"], c["b"])):
        if c["kind"] != "INDEPENDENT_REPLICATION" or c["a"] not in unique or c["b"] not in unique:
            continue
        a, b = unique[c["a"]], unique[c["b"]]
        if a["execution_hash"] == b["execution_hash"] or a["measurement_hash"] == b["measurement_hash"] or a["experiment_identity"] != b["experiment_identity"]:
            raise ValueError("Invalid inferred historical replication")
        episodes.append({"class": "REPLICATION", "source_evidence": [c["a"], c["b"]],
                         "basis": "EXACT_CONTEXT_DISTINCT_EXECUTIONS_AND_MEASUREMENTS", "proposed_plan_link": None,
                         "outcome": "CORROBORATION" if a["outcome"] == b["outcome"] == "ACCEPTED" else "CONTRADICTORY_OR_UNRESOLVED",
                         "confidence": "LOW", "utility_generalization": "NOT_ESTABLISHED"})
    metrics = {"schema": "gaia_strategy_metrics_v1", "experiments": n, "accepted": counts["ACCEPTED"],
               "rejected": counts["REJECTED"], "inconclusive": counts["INCONCLUSIVE"],
               "accepted_improvement_rate": counts["ACCEPTED"] / n if n else None,
               "rejected_rate": counts["REJECTED"] / n if n else None,
               "inconclusive_rate": counts["INCONCLUSIVE"] / n if n else None,
               "information_producing_count": sum(informative), "information_producing_rate": sum(informative) / n if n else None,
               "useful_experiment_rate": sum(informative) / n if n else None,
               "usefulness_definition": "DESCRIPTIVE_OUTCOME_INFORMATION_PROXY_NOT_MEASURED_STRATEGY_UTILITY",
               "exact_duplicate_evidence_count": len(duplicates), "duplicate_experiment_rate": len(duplicates) / (n + len(duplicates)) if n + len(duplicates) else None,
               "duplicate_denominator": "UNIQUE_EVIDENCE_PLUS_DISTINCT_DUPLICATED_EVIDENCE_IDENTITIES_NOT_INGESTION_FREQUENCY",
               "experiments_per_accepted_improvement": n / counts["ACCEPTED"] if counts["ACCEPTED"] else None,
               "cost_per_useful_experiment_s": None, "cost_unavailable_reason": "TOTAL_EXPERIMENT_COST_NOT_IN_LEARNING_PROJECTION",
               "known_candidate_confirmation_cost_s": sum(sum(e["confirmation"]["candidate_costs"]) for e in rows if e["confirmation"]),
               "known_cost_scope": "COST_TO_QUALITY_SAMPLES_ONLY_NOT_WALL_OR_FULL_CAMPAIGN_COST",
               "small_sample": n < 20, "strategy_utility_improvement_demonstrated": False}
    metrics["metrics_hash"] = digest(metrics)
    return {"retrospective_experiments": history, "inferred_strategy_episodes": episodes, "metrics": metrics}
