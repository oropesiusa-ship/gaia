"""Read-only diagnostic composition; no connection to the evolutionary Engine."""
from datetime import datetime, timezone
import time

from ..provenance import digest
from ..config import DEFAULTS as CONFIG_DEFAULTS
from . import VERSION
from .evidence import Evidence, identity_reference, validate_input
from .hypotheses import build
from .rules import RULE_VERSION, evaluate
from .schema import DIAGNOSIS_SCHEMA, seal

DEFAULTS = CONFIG_DEFAULTS["diagnosis"]


def settings(configuration=None):
    supplied = (configuration or {}).get("diagnosis", {})
    if set(supplied) - DEFAULTS.keys():
        raise ValueError("Unknown diagnosis configuration key")
    cfg = {**DEFAULTS, **supplied}
    for key, value in cfg.items():
        if key == "confidence_min_evidence":
            if type(value) is not int or not 3 <= value <= 10:
                raise ValueError("Invalid confidence evidence minimum")
        elif type(value) not in (int, float) or not 0 < value <= (100 if key == "cpu_utilization_high" else 2**40 if key == "swap_consumption_bytes" else 1):
            raise ValueError("Invalid diagnosis threshold")
    if cfg["process_cpu_wall_low"] >= cfg["process_cpu_wall_high"]:
        raise ValueError("Inconsistent CPU ratio thresholds")
    return cfg


def diagnose(current, baseline=None, configuration=None, diagnosis_id="d000001", *, verification_objective=None):
    start = time.perf_counter()
    validate_input(current)
    if baseline is not None:
        validate_input(baseline)
    cfg = settings(configuration)
    evidence = Evidence(current, baseline)
    evaluated = evaluate(current, baseline, cfg, evidence)
    if verification_objective is not None:
        if verification_objective != 'VERIFY_NUMPY_MLP_EXISTING_CRITERIA':
            raise ValueError('Unsupported explicit verification objective')
        # v0.2 observation is fixed-batch, not paired cost-to-target evidence.
        # A requested verification gap is not an invented performance regression.
        rule='RULE_OBJECTIVE_VERIFICATION_001'
        reference=evidence.add('current','/sections/measurements/workload/status',
            'requested paired numpy_mlp verification is not established by this observation protocol','verification',kind='CONTEXTUAL')
        evaluated['issues'].append({'issue_id':f"i{len(evaluated['issues'])+1:04d}",'kind':'WORKLOAD_VERIFICATION_GAP',
            'rule_id':rule,'evidence_refs':[reference],'details':{'objective':verification_objective,'scope':'MISSING_CONTROLLED_VERIFICATION_NOT_A_DETECTED_REGRESSION'}})
        evaluated['rules_evaluated'].append(rule)
        evaluated['rule_hash']=digest({'base':evaluated['rule_hash'],'objective':verification_objective,'rule':rule})
    hypotheses = build(evaluated, evidence, cfg)
    missing = sorted(set(evaluated["missing"] + [item for h in hypotheses for item in h["missing_evidence"]]))
    complete = evaluated["signals"]["stable"] and "complete_source_inventory" not in missing
    if baseline is not None:
        complete = complete and not {"matching_workload_protocols", "comparable_baseline_samples"}.intersection(missing)
    outcome = "ISSUES_DETECTED" if evaluated["issues"] else "NO_SIGNIFICANT_ISSUE" if complete else "INSUFFICIENT_EVIDENCE"
    source_refs = [identity_reference(current, "current")]
    if baseline is not None:
        source_refs.append(identity_reference(baseline, "baseline"))
    raw_comparison = evaluated["comparison"]
    # Do not echo arbitrary changed field values or strings from input observations.
    comparison = {key: raw_comparison[key] for key in ("schema", "a", "b", "a_hash", "b_hash", "hardware_changed",
                                                       "runtime_changed", "source_changed", "capability_changed", "measurements")} if raw_comparison else None
    if comparison:
        allowed_metrics = {"workload.wall_s", "workload.final_acc", "workload.peak_rss_mb", "workload.t_train",
                           "workload.descendant_cpu_s_lower_bound", "workload.evaluator_cpu_s",
                           "resources.system_cpu_utilization_percent", "resources.system_ram_available_bytes",
                           "resources.filesystem_available_bytes", "resources.swap_available_bytes"}
        comparison["measurements"] = [m for m in comparison["measurements"] if m["metric"] in allowed_metrics]
    value = {"diagnosis_id": diagnosis_id, "schema": DIAGNOSIS_SCHEMA, "timestamp": datetime.now(timezone.utc).isoformat(),
             "source_observations": source_refs, "identity": {"interpreter_version": VERSION, "rules_version": RULE_VERSION,
                                                              "rules_hash": evaluated["rule_hash"], "configuration_hash": digest(cfg)},
             "outcome": outcome, "issues": evaluated["issues"], "hypotheses": hypotheses,
             "alternatives": {i["issue_id"]: i["hypothesis_ids"][1:] for i in evaluated["issues"]},
             "evidence": evidence.items, "contradictions": {h["hypothesis_id"]: h["contradictions"] for h in hypotheses},
             "missing_evidence": missing, "confidence": {h["hypothesis_id"]: h["confidence"] for h in hypotheses},
             "limitations": ["Diagnosis is a hypothesis, not proof of causality.",
                             "No causal interventions or diagnostic experiments were executed.",
                             "System metrics and sampled descendant CPU do not identify a bottleneck alone.",
                             "Source aggregate identity is referenced; its original configuration is not reconstructible from observation alone.",
                             "Missing optional evidence limits attribution; HIGH requires strong direct/control evidence."],
             "rules": {"version": RULE_VERSION, "evaluated": evaluated["rules_evaluated"], "thresholds": cfg},
             "comparison": comparison, "cost": {"duration_s": time.perf_counter() - start,
                                                 "rules_evaluated": len(evaluated["rules_evaluated"]), "hypotheses_generated": len(hypotheses)}}
    return seal(value)
