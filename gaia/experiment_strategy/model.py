"""Closed plan templates: declarative comparisons, never executable code or commands."""
from ..provenance import digest

CLASSES = {"REPLICATION", "DISCRIMINATION", "PARAMETER_LOCAL_SEARCH", "CONTROL_EXPERIMENT", "MEASUREMENT_REFINEMENT",
           "BASELINE_RECONFIRMATION", "KNOWLEDGE_VALIDATION", "EXPLORATION", "EXPLOITATION"}
NOVELTY = {"EXACT_REPEAT", "NEAR_REPEAT", "KNOWN_REGION", "NEW_REGION", "UNKNOWN"}
PROFILE = {
    "REPLICATION": ("VERIFY", "HIGH", "LOW", "LOW", 10),
    "DISCRIMINATION": ("VERIFY", "HIGH", "LOW", "LOW", 10),
    "PARAMETER_LOCAL_SEARCH": ("EXPLOIT", "MEDIUM", "MEDIUM", "MEDIUM", 10),
    "CONTROL_EXPERIMENT": ("VERIFY", "MEDIUM", "LOW", "VERY_LOW", 5),
    "MEASUREMENT_REFINEMENT": ("VERIFY", "HIGH", "LOW", "VERY_LOW", 7),
    "BASELINE_RECONFIRMATION": ("VERIFY", "MEDIUM", "LOW", "LOW", 5),
    "KNOWLEDGE_VALIDATION": ("VERIFY", "HIGH", "UNKNOWN", "MEDIUM", 10),
    "EXPLORATION": ("EXPLORE", "MEDIUM", "UNKNOWN", "MEDIUM", 10),
    "EXPLOITATION": ("EXPLOIT", "MEDIUM", "MEDIUM", "LOW", 10),
}
CONTROLS = ["workload", "architecture", "dataset_protocol", "benchmark_identity", "quality_threshold",
            "paired_seed_protocol", "runtime_identity", "resource_limits", "sandbox_policy"]
GUARDS = {"execution_authorized": False, "protected_evaluator_unchanged": True, "benchmark_unchanged": True,
          "acceptance_criteria_unchanged": True, "sandbox_required_for_any_future_trial": True,
          "no_source_or_hardware_changes": True}


def template(cls, target_class, *, factorial=False, knowledge=False):
    if cls == "REPLICATION":
        variables, variation, design = ["independent_execution"], "REPEAT_REFERENCE_CONFIGURATION", "PAIRED_REPLICATION"
    elif cls == "MEASUREMENT_REFINEMENT":
        variables, variation, design = ["measurement_conditions"], "REPEAT_WITH_EXPLICIT_MEASUREMENT_SCOPE", "REPEATED_MEASUREMENT"
    elif cls in ("CONTROL_EXPERIMENT", "BASELINE_RECONFIRMATION"):
        variables, variation, design = ["measurement_control"], "BASELINE_VS_IDENTICAL_BASELINE", "PAIRED_CONTROL"
    elif cls == "KNOWLEDGE_VALIDATION":
        variables, variation, design = ["context_compatibility"], "CURRENT_CONTEXT_VS_DECLARED_KNOWLEDGE_SCOPE", "CONTEXT_VALIDATION"
    elif factorial:
        variables, variation, design = ["learning_rate", "weight_decay"], "SYMBOLIC_CONTROLLED_FACTOR_COMBINATIONS", "CONTROLLED_FACTORIAL"
    elif cls == "DISCRIMINATION" and knowledge:
        variables, variation, design = ["independent_paired_evidence"], "REPEAT_REFERENCE_CONFIGURATION", "PAIRED_DISCRIMINATION"
    elif cls == "DISCRIMINATION":
        variables, variation, design = ["parallelism"], "CONTROLLED_SINGLE_FACTOR_COMPARISON", "ONE_FACTOR"
    else:
        variable = {"CPU_RUNTIME_EFFICIENCY": "learning_rate", "MEMORY_EFFICIENCY": "batch_size",
                    "RESOURCE_CONTENTION": "parallelism", "QUALITY_REGRESSION": "result_validation",
                    "STORAGE_IO": "io_measurement_scope", "RUNTIME_CONFIGURATION": "runtime_identity"}.get(target_class, "single_factor_to_identify")
        variables, variation, design = [variable], "LOCAL_SYMBOLIC_PERTURBATION", "ONE_FACTOR"
    metrics = ["wall_s", "process_cpu_s", "peak_rss", "quality", "measurement_cv"]
    if target_class in ("CPU_RUNTIME_EFFICIENCY", "MEMORY_EFFICIENCY", "RESOURCE_CONTENTION"):
        metrics += ["per_core_utilization", "memory_bandwidth_if_available"]
    return {"design": design, "variables": variables, "controlled_variables": [v for v in CONTROLS if v not in variables] + ["all_other_candidate_factors"],
            "candidate_variation": {"kind": variation, "numeric_values": None, "code": None}, "metrics": metrics,
            "discriminates": ["COMPUTE_PRESSURE", "MEMORY_PRESSURE", "RESOURCE_CONTENTION", "MEASUREMENT_ARTIFACT"] if cls == "DISCRIMINATION" and not factorial and not knowledge else
                             ["MAIN_EFFECT_VS_INTERACTION_OR_CONFOUNDING"] if factorial else ["REPRODUCIBLE_EFFECT_VS_CONTEXT_OR_MEASUREMENT_VARIATION"]}


def finish_plan(plan):
    value = dict(plan)
    value["plan_id"] = "xp" + digest({k: v for k, v in value.items() if k not in ("plan_id", "plan_hash")})[:24]
    value["plan_hash"] = digest({k: v for k, v in value.items() if k != "plan_hash"})
    return value
