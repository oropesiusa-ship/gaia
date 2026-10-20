"""Closed target vocabulary and explicit conceptual investigation profiles."""
from .policy import CONFIDENCE, IMPACT

CLASSES = {
    "COMPUTE_PRESSURE": ("CPU_RUNTIME_EFFICIENCY", "cpu_evolution", "LOW", "LOW", "EASY"),
    "MEMORY_PRESSURE": ("MEMORY_EFFICIENCY", "core", "MEDIUM", "LOW", "EASY"),
    "GPU_MEMORY_PRESSURE": ("GPU_RUNTIME_EFFICIENCY", "gpu", "HIGH", "MEDIUM", "MODERATE"),
    "STORAGE_PRESSURE": ("STORAGE_IO", "core", "MEDIUM", "LOW", "EASY"),
    "RESOURCE_CONTENTION": ("RESOURCE_CONTENTION", "core", "LOW", "LOW", "EASY"),
    "RUNTIME_REGRESSION": ("RUNTIME_CONFIGURATION", "core", "MEDIUM", "MEDIUM", "MODERATE"),
    "QUALITY_REGRESSION": ("QUALITY_REGRESSION", "protected_evaluator", "LOW", "LOW", "EASY"),
    "CAPABILITY_GAP": ("CAPABILITY_GAP", "core", "LOW", "LOW", "EASY"),
    "MEASUREMENT_NOISE": ("MEASUREMENT_QUALITY", "observation", "VERY_LOW", "LOW", "EASY"),
    "ENVIRONMENT_CHANGE": ("ENVIRONMENT_COMPATIBILITY", "core", "LOW", "LOW", "EASY"),
    "UNKNOWN_CAUSE": ("UNKNOWN_REQUIRES_EVIDENCE", "core", "LOW", "LOW", "EASY"),
}
TARGET_CLASSES = {v[0] for v in CLASSES.values()}
INFORMATION = {"per_core_cpu_utilization", "cpu_frequency_under_load", "thread_scaling", "memory_bandwidth",
               "swap_io_activity", "allocation_failure_events", "workload_rss_time_series", "gpu_utilization",
               "gpu_allocation_failure_events", "workload_gpu_participation", "disk_latency", "workload_io_time",
               "controlled_runtime_comparison", "equivalent_workload_inputs", "process_competition", "scheduler_wait_time",
               "measurement_conditions", "additional_repeated_workload_samples", "equivalent_quality_inputs",
               "result_correctness_control", "capability_failure_evidence", "controlled_environment_comparison",
               "workload_resource_time_alignment", "controlled_comparison_evidence", "synchronization_wait_time",
               "implementation_efficiency_control"}


def impact(issue, cfg):
    # Evidence of failure or magnitude, not the hypothesis name, determines impact.
    if issue["kind"] in ("WORKLOAD_INSTABILITY", "CAPABILITY_UNAVAILABLE") and issue["evidence_refs"]:
        return "HIGH", "recorded_functional_or_required_capability_failure"
    delta = issue.get("details", {}).get("relative_change")
    if issue["kind"] in ("PERFORMANCE_REGRESSION", "QUALITY_REGRESSION") and type(delta) in (int, float):
        return ("HIGH" if abs(delta) >= cfg["large_regression_relative"] else "MEDIUM"), "measured_significant_regression_magnitude"
    if issue["kind"] == "HIGH_MEASUREMENT_VARIABILITY":
        return "LOW", "variability_only_no_functional_loss_established"
    return "UNKNOWN", "impact_not_measured"


def candidates(diagnoses, cfg):
    groups, exclusions = {}, []
    for diagnosis in diagnoses:
        dh = diagnosis["diagnosis_hash"]
        if diagnosis["outcome"] != "ISSUES_DETECTED":
            exclusions.append({"diagnosis_hash": dh, "reason": diagnosis["outcome"]})
            continue
        hypotheses = {h["hypothesis_id"]: h for h in diagnosis["hypotheses"]}
        for issue in diagnosis["issues"]:
            entries = [hypotheses[h] for h in issue["hypothesis_ids"]]
            # Unknown alongside a named plausible explanation stays an alternative,
            # rather than duplicating the same research question as another target.
            named = [h for h in entries if h["kind"] != "UNKNOWN_CAUSE"]
            for h in named or entries:
                cls, component, cost, risk, reversal = CLASSES[h["kind"]]
                key = (cls, component)
                magnitude, reason = impact(issue, cfg)
                info = sorted(set(h["missing_evidence"]) & INFORMATION)
                dims = {"impact": magnitude, "diagnostic_confidence": h["confidence"], "investigation_cost": cost,
                        "risk": risk, "reversibility": reversal, "evidence_completeness": "PARTIAL" if info else "SUFFICIENT",
                        "information_value": "HIGH" if len(entries) > 1 and magnitude in ("MEDIUM", "HIGH") else "MEDIUM" if info else "LOW",
                        "blocking_power": "HIGH" if issue["kind"] in ("WORKLOAD_INSTABILITY", "CAPABILITY_UNAVAILABLE") else "NONE"}
                ref = {"diagnosis_id": diagnosis["diagnosis_id"], "diagnosis_hash": dh, "issue_id": issue["issue_id"],
                       "hypothesis_id": h["hypothesis_id"], "evidence_refs": sorted(set(issue["evidence_refs"] + h["supports"] + h["contradictions"]))}
                if key not in groups:
                    groups[key] = {"target_id": "", "component_id": component, "target_class": cls, "source_refs": [],
                                   "dimensions": dims, "dimension_basis": [reason, "conceptual_profile_v1_not_measured_cost"],
                                   "information_needed": [], "dependencies": [], "blocked_by": [], "exclusion_reasons": [],
                                   "priority": "DEFER", "rule_ids": [], "reasons": [], "intent": "ACQUIRE_EVIDENCE" if h["confidence"] in ("LOW", "VERY_LOW") or cls == "UNKNOWN_REQUIRES_EVIDENCE" else "INVESTIGATE_ISSUE"}
                t = groups[key]
                t["dimension_basis"] = sorted(set(t["dimension_basis"] + [reason]))
                t["source_refs"].append(ref)
                t["information_needed"] = sorted(set(t["information_needed"] + info))
                old = t["dimensions"]
                old["impact"] = max((old["impact"], magnitude), key=IMPACT.get)
                # Consolidation never upgrades confidence by counting repeated diagnoses.
                old["diagnostic_confidence"] = min((old["diagnostic_confidence"], h["confidence"]), key=CONFIDENCE.get)
                if old["diagnostic_confidence"] in ("LOW", "VERY_LOW"):
                    t["intent"] = "ACQUIRE_EVIDENCE"
                if "HIGH" in (old["information_value"], dims["information_value"]):
                    old["information_value"] = "HIGH"
                if "PARTIAL" in (old["evidence_completeness"], dims["evidence_completeness"]):
                    old["evidence_completeness"] = "PARTIAL"
                if "HIGH" in (old["blocking_power"], dims["blocking_power"]):
                    old["blocking_power"] = "HIGH"
                if component in ("gpu", "appliance"):
                    t["blocked_by"] = ["FROZEN_COMPONENT"]
    targets = [groups[k] for k in sorted(groups)]
    for i, t in enumerate(targets, 1):
        t["target_id"] = f"t{i:04d}"
        t["source_refs"] = sorted({str(r): r for r in t["source_refs"]}.values(), key=lambda r: (r["diagnosis_hash"], r["issue_id"], r["hypothesis_id"]))
        if t["blocked_by"]:
            t["exclusion_reasons"] = list(t["blocked_by"])
    # Dependencies are scoped to the same exact diagnosis, not unrelated histories.
    for measurement in (t for t in targets if t["target_class"] == "MEASUREMENT_QUALITY"):
        for dependent in targets:
            shared = {r["diagnosis_hash"] for r in measurement["source_refs"]} & {r["diagnosis_hash"] for r in dependent["source_refs"]}
            wall_noisy = any(i["kind"] == "HIGH_MEASUREMENT_VARIABILITY" and i["details"].get("metric") == "wall_s"
                             for d in diagnoses if d["diagnosis_hash"] in shared for i in d["issues"])
            if dependent is not measurement and wall_noisy and dependent["target_class"] in ("CPU_RUNTIME_EFFICIENCY", "MEMORY_EFFICIENCY", "RESOURCE_CONTENTION", "UNKNOWN_REQUIRES_EVIDENCE"):
                dependent["dependencies"].append(measurement["target_id"])
                dependent["blocked_by"].append("DEPENDENT_TARGET")
                measurement["dimensions"]["blocking_power"] = "HIGH"
                measurement["dimensions"]["information_value"] = "HIGH"
                measurement["dimension_basis"].append("wall_variability_limits_dependent_inference")
    for t in targets:
        relevant = {r["diagnosis_hash"] for r in t["source_refs"]}
        gap = any(i["kind"] == "CAPABILITY_UNAVAILABLE" for d in diagnoses if d["diagnosis_hash"] in relevant for i in d["issues"])
        if gap and t["target_class"] in ("CPU_RUNTIME_EFFICIENCY", "QUALITY_REGRESSION"):
            t["blocked_by"].append("CAPABILITY_UNAVAILABLE")
        t["blocked_by"] = sorted(set(t["blocked_by"]))
        t["exclusion_reasons"] = list(t["blocked_by"])
    return targets, exclusions
