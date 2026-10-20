"""Experimental history becomes bounded claims, not global laws or new candidates."""
from ..provenance import digest
from .schema import LEARNING_SCHEMA, seal

LIMITATIONS = ["Local evidence only; no global optimum or cross-domain generalization established.",
               "Configuration changes can be confounded; association is not isolated causal attribution.",
               "Repeated seeds within one experiment are not independent experimental replication.",
               "Promotion alone is not HIGH confidence; verification rollback is not adverse performance evidence.",
               "Negative evidence concerns an exact tested configuration, not an entire parameter region."]


def experiment_identity(exp):
    return digest({"context": exp["context"], "candidate": exp["candidate"]["genome_hash"],
                   "baseline": exp["baseline"]["genome_hash"]})


def measurement_identity(exp):
    return digest({"experiment": experiment_identity(exp),
                   "measurements": exp["confirmation"] if exp["confirmation"] is not None else exp["screen"]})


def direction(exp, cfg):
    candidate, baseline = exp["candidate"], exp["baseline"]
    same_structure = (candidate["slots"] == baseline["slots"] and candidate["code_variation_hash"] == baseline["code_variation_hash"]
                      and all(candidate["hp"][k] == baseline["hp"][k] for k in ("hidden", "depth", "batch")))
    if same_structure and candidate["hp"]["lr"] >= baseline["hp"]["lr"] * cfg["higher_lr_factor"]:
        return "HIGHER_LR_REGION"
    return "EXACT_CONFIGURATION"


def interpretation(exp):
    c = exp["confirmation"]
    if exp["outcome"] == "ACCEPTED":
        return "OBSERVED_EFFECT", "CONFIRMED_LOWER_COST", "MEDIUM"
    if exp["outcome"] == "INCONCLUSIVE":
        if c and c["decision"] == "pareto_alternative":
            return "INCONCLUSIVE_RESULT", "RESOURCE_TRADEOFF_UNRESOLVED", "LOW"
        if c and c["ratio"] is not None and c["ratio"] < 1 - c["min_gain"]:
            return "PROMISING_DIRECTION", "FAVORABLE_SIGNAL_UNRESOLVED_INTERVAL", "LOW"
        return "INCONCLUSIVE_RESULT", "UNRESOLVED_EFFECT", "VERY_LOW"
    if c and c["candidate_reached"] < c["baseline_reached"]:
        return "REJECTED_DIRECTION", "QUALITY_GUARD_NOT_MET", "MEDIUM"
    if exp["screen"]["status"] != "ok":
        return "REJECTED_DIRECTION", "EXECUTION_NOT_SUCCESSFUL", "LOW"
    if not exp["screen"]["reached"]:
        return "REJECTED_DIRECTION", "QUALITY_GUARD_NOT_MET", "LOW"
    return "REJECTED_DIRECTION", "NO_VERIFIED_COST_GAIN", "MEDIUM" if c else "LOW"


def make_record(exp, cfg):
    claim_type, effect, confidence = interpretation(exp)
    exact = experiment_identity(exp)
    subject = {"configuration_hash": exp["candidate"]["genome_hash"], "baseline_hash": exp["baseline"]["genome_hash"],
               "configuration": exp["candidate"], "direction": direction(exp, cfg), "effect": effect,
               "outcome": exp["outcome"], "exact_identity": exact,
               "negative_reuse_scope": ("EXACT_CANDIDATE_EQUIVALENT_CONTEXT_ONLY" if exp["confirmation"] and exp["confirmation"]["pairs"] >= 3 else "HISTORICAL_REJECTION_ONLY") if exp["outcome"] == "REJECTED" else "NONE",
               "template": "tested_configuration_effect_within_declared_context"}
    evidence = {"experiment_id": exp["experiment_id"], "evidence_hash": exp["evidence_hash"], "manifest_hash": exp["manifest_hash"],
                "execution_hash": exp["execution_hash"], "experiment_identity": exact, "outcome": exp["outcome"],
                "measurement_hash": measurement_identity(exp),
                "ratio": exp["confirmation"]["ratio"] if exp["confirmation"] else None,
                "upper95": exp["confirmation"]["upper95"] if exp["confirmation"] else None,
                "screen": exp["screen"], "confirmation": exp["confirmation"], "promotion": exp["promotion"], "rollback": exp["rollback"],
                "artifacts": exp["artifacts"], "ledger_refs": exp["ledger_refs"],
                "missing_evidence": ["independent_replication"] + (["resource_tradeoff_resolution" if effect == "RESOURCE_TRADEOFF_UNRESOLVED" else "interval_below_acceptance_threshold"] if exp["outcome"] == "INCONCLUSIVE" else [])}
    contrary = [evidence] if exp["rollback"] in ("ADVERSE", "UNKNOWN") else []
    repeated = bool(exp["confirmation"] and exp["confirmation"]["pairs"] >= 3)
    return seal({"learning_id": "l" + digest({"evidence_hash": exp["evidence_hash"], "experiment_identity": exact, "rules": cfg})[:24],
                 "schema": LEARNING_SCHEMA, "kind": "record", "source_experiments": [exp["experiment_id"]], "source_versions": exp["versions"],
                 "source_evidence_hashes": [exp["evidence_hash"]], "domain": "CPU_NUMPY_MLP", "component": "cpu_evolution",
                 "claim": subject, "claim_type": claim_type, "applicability": exp["context"], "supporting_evidence": [evidence],
                 "contradictory_evidence": contrary, "confidence": "LOW" if contrary else confidence,
                 "replication_status": "CONTRADICTED" if contrary else "REPEATED_WITHIN_EXPERIMENT" if repeated else "SINGLE_EXPERIMENT",
                 "status": "CONTRADICTED" if contrary else "ACTIVE", "limitations": LIMITATIONS, "created_at": exp["finished_at"],
                 "supersedes": [], "superseded_by": [], "quality": {"evidence_count": 1, "independent_evidence_count": 1,
                     "contradictions_count": len(contrary), "context_specificity": "EXACT_CONTEXT"}, "hierarchy": "EXPERIMENTAL_EVIDENCE"})
