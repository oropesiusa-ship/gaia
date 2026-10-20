"""Exact-configuration corroboration and cautious contextual direction synthesis."""
from ..provenance import digest
from .records import LIMITATIONS
from .schema import CONFIDENCE, LEARNING_SCHEMA, independent_count, seal


def consolidate(records, cfg):
    groups = {}
    for record in records:
        context = digest(record["applicability"])
        exact = (context, "EXACT_CONFIGURATION", record["claim"]["exact_identity"])
        groups.setdefault(exact, []).append(record)
        if record["claim"]["direction"] == "HIGHER_LR_REGION":
            # No invented numeric interval: list the actually tested points and confounders.
            groups.setdefault((context, "HIGHER_LR_REGION", record["claim"]["baseline_hash"]), []).append(record)
    knowledge = []
    for key, items in sorted(groups.items()):
        unique = {e["evidence_hash"]: e for r in items for e in r["supporting_evidence"]}
        if len(unique) < cfg["minimum_evidence_for_consolidation"]:
            continue
        evidence = [unique[k] for k in sorted(unique)]
        accepted = [e for e in evidence if e["outcome"] == "ACCEPTED"]
        rejected = [e for e in evidence if e["outcome"] == "REJECTED"]
        favorable = [r for r in items if r["claim_type"] == "PROMISING_DIRECTION"]
        contrary = [e for e in evidence if e["rollback"] in ("ADVERSE", "UNKNOWN")]
        if accepted and rejected:
            contrary += rejected
        contrary = list({e["evidence_hash"]: e for e in contrary}.values())
        independent = {e["execution_hash"] for e in evidence}
        independent_positive = {e["execution_hash"] for e in accepted}
        distinct_count = independent_count(evidence)
        positive_count = independent_count(accepted)
        replicated = (key[1] == "EXACT_CONFIGURATION" and positive_count >= cfg["minimum_independent_replications"])
        confidence = "HIGH" if replicated and not contrary else "MEDIUM" if accepted or len(rejected) > 1 else "LOW" if favorable or rejected else "VERY_LOW"
        if contrary:
            confidence = CONFIDENCE[max(0, CONFIDENCE.index(confidence) - cfg["contradiction_confidence_penalty"])]
        if key[1] == "HIGHER_LR_REGION":
            claim_type = "CONTEXT_DEPENDENT_EFFECT" if accepted else "PROMISING_DIRECTION" if favorable else "INCONCLUSIVE_RESULT"
        else:
            claim_type = "REPLICATED_EFFECT" if replicated and not contrary else "OBSERVED_EFFECT" if accepted else "REJECTED_DIRECTION" if rejected else "PROMISING_DIRECTION" if favorable else "INCONCLUSIVE_RESULT"
        replication = "CONTRADICTED" if contrary else "REPLICATED_INDEPENDENTLY" if replicated else "REPEATED_WITHIN_EXPERIMENT" if any(r["replication_status"] == "REPEATED_WITHIN_EXPERIMENT" for r in items) else "SINGLE_EXPERIMENT"
        operational = replicated and not contrary and confidence == "HIGH"
        identifier = "k" + digest({"group": key, "records": sorted(r["hash"] for r in items), "config": cfg})[:24]
        knowledge.append(seal({"learning_id": identifier, "schema": LEARNING_SCHEMA, "kind": "knowledge",
            "source_experiments": sorted({eid for r in items for eid in r["source_experiments"]}),
            "source_versions": sorted({v for r in items for v in r["source_versions"]}), "source_evidence_hashes": sorted(unique),
            "domain": "CPU_NUMPY_MLP", "component": "cpu_evolution", "claim": {
                "group_key": digest(key), "subject": key[1], "record_refs": sorted({r["learning_id"] for r in items}),
                "tested_configurations": sorted({r["claim"]["configuration_hash"] for r in items}),
                "tested_lr_values": sorted({r["claim"]["configuration"]["hp"]["lr"] for r in items}),
                "tested_wd_values": sorted({r["claim"]["configuration"]["hp"]["wd"] for r in items}),
                "template": "higher_lr_points_promising_and_confirmed_configuration_observed_not_isolated_wd_causality" if key[1] == "HIGHER_LR_REGION" and accepted and favorable else "contextual_evidence_summary_not_global_optimum",
                "negative_reuse_scope": ("EXACT_CANDIDATE_EQUIVALENT_CONTEXT_ONLY" if distinct_count >= 2 or any(e["confirmation"] and e["confirmation"]["pairs"] >= 3 for e in rejected) else "HISTORICAL_REJECTION_ONLY") if rejected and not accepted and key[1] == "EXACT_CONFIGURATION" else "NONE"},
            "claim_type": claim_type, "applicability": items[0]["applicability"], "supporting_evidence": evidence,
            "contradictory_evidence": contrary, "confidence": confidence, "replication_status": replication,
            "status": "CONTRADICTED" if contrary else "OPERATIONAL_KNOWLEDGE" if operational else "ACTIVE",
            "limitations": LIMITATIONS + ["Direction synthesis may combine changed weight decay or other hyperparameters; no isolated causal effect or regional ban."],
            "created_at": max(r["created_at"] for r in items), "supersedes": [], "superseded_by": [],
            "quality": {"evidence_count": len(evidence), "independent_evidence_count": distinct_count,
                        "independent_positive_count": positive_count, "contradictions_count": len(contrary),
                        "context_specificity": "EXACT_CONTEXT", "record_count": len(items)},
            "hierarchy": "OPERATIONAL_KNOWLEDGE" if operational else "REPLICATED_EVIDENCE" if replicated and not contrary else "EXPERIMENTAL_EVIDENCE"}))
    return knowledge
