"""Limited explanatory alternatives and explicit counterevidence searches."""
from .confidence import assess
from .rules import MEASURE

CLAIMS = {
    "COMPUTE_PRESSURE": "CPU compute pressure may be limiting this workload; saturation is not proof of a bottleneck.",
    "MEMORY_PRESSURE": "Memory pressure may contribute to the observed issue; available RAM alone does not establish causation.",
    "GPU_MEMORY_PRESSURE": "Low observed VRAM availability may constrain GPU allocations; workload involvement is unknown.",
    "STORAGE_PRESSURE": "Low filesystem availability may constrain storage operations; latency and causation are unmeasured.",
    "RUNTIME_REGRESSION": "The runtime change is a plausible contributor to the slowdown; temporal association is not causal proof.",
    "RESOURCE_CONTENTION": "Competing resource demand may contribute; system utilization does not identify the competing process.",
    "MEASUREMENT_NOISE": "Measurement variability may obscure workload comparisons.",
    "QUALITY_REGRESSION": "A reproducible quality decrease is observed; its mechanism remains unestablished.",
    "CAPABILITY_GAP": "A required capability is declared unavailable; the underlying reason is not established.",
    "ENVIRONMENT_CHANGE": "Changed identities may affect cross-observation comparability; no causal contribution is established.",
    "UNKNOWN_CAUSE": "Available evidence does not distinguish a causal explanation.",
    "TRAINER_OPTIMIZATION_OPPORTUNITY": "An explicit optimization objective requests controlled trainer comparisons; no defect or achievable gain is established.",
    "INFERENCE_OPTIMIZATION_OPPORTUNITY": "An explicit optimization objective requests controlled inference configuration comparisons; no defect or achievable gain is established.",
}
NEEDED = {
    "COMPUTE_PRESSURE": ["per_core_cpu_utilization", "cpu_frequency_under_load", "thread_scaling", "memory_bandwidth"],
    "MEMORY_PRESSURE": ["swap_io_activity", "allocation_failure_events", "memory_bandwidth", "workload_rss_time_series"],
    "GPU_MEMORY_PRESSURE": ["gpu_utilization", "gpu_allocation_failure_events", "workload_gpu_participation"],
    "STORAGE_PRESSURE": ["disk_latency", "workload_io_time"],
    "RUNTIME_REGRESSION": ["controlled_runtime_comparison", "equivalent_workload_inputs"],
    "RESOURCE_CONTENTION": ["process_competition", "per_core_cpu_utilization", "scheduler_wait_time"],
    "MEASUREMENT_NOISE": ["measurement_conditions", "additional_repeated_workload_samples"],
    "QUALITY_REGRESSION": ["equivalent_quality_inputs", "result_correctness_control"],
    "CAPABILITY_GAP": ["capability_failure_evidence"],
    "ENVIRONMENT_CHANGE": ["controlled_environment_comparison"],
    "UNKNOWN_CAUSE": ["workload_resource_time_alignment", "controlled_comparison_evidence"],
    "TRAINER_OPTIMIZATION_OPPORTUNITY": ["controlled_comparison_evidence"],
    "INFERENCE_OPTIMIZATION_OPPORTUNITY": ["controlled_runtime_comparison"],
}


def build(evaluation, evidence, cfg):
    signals = evaluation["signals"]
    stable = signals["stable"]
    cpu = signals["cpu_system"]["value"]
    cpu_high = cpu is not None and cpu >= cfg["cpu_utilization_high"]
    ratio = signals["cpu_ratio"]
    ratio_high = ratio is not None and ratio >= cfg["process_cpu_wall_high"]
    ratio_low = signals["exact_cpu"] and ratio is not None and ratio < cfg["process_cpu_wall_low"]
    hypotheses = []
    def ref(name):
        entry = signals.get(name, {})
        refs = entry.get("evidence", [])
        return [refs] if isinstance(refs, str) else refs
    def negative(ids, relation, strength="MODERATE"):
        result = []
        for eid in ids:
            original = evidence.by_id(eid)
            result.append(evidence.add(original["observation_ref"]["role"], original["field"], relation,
                                       original["group"], kind="NEGATIVE", strength=strength))
        return result
    for issue in evaluation["issues"]:
        kind = issue["kind"]
        if kind == "PERFORMANCE_REGRESSION":
            kinds = []
            if cpu_high and ratio_high:
                kinds.append("COMPUTE_PRESSURE")
            if signals["memory_low"]:
                kinds.append("MEMORY_PRESSURE")
            if cpu_high and not ratio_high:
                kinds.append("RESOURCE_CONTENTION")
            if signals["runtime_changed"]:
                kinds.append("RUNTIME_REGRESSION")
            kinds.append("UNKNOWN_CAUSE")
        elif kind == "SYSTEM_CPU_UTILIZATION_HIGH":
            kinds = ["COMPUTE_PRESSURE", "RESOURCE_CONTENTION", "UNKNOWN_CAUSE"] if ratio_high else ["RESOURCE_CONTENTION", "UNKNOWN_CAUSE"] if ratio_low else ["UNKNOWN_CAUSE", "RESOURCE_CONTENTION"]
        else:
            mapped = {"MEMORY_AVAILABLE_LOW": "MEMORY_PRESSURE", "STORAGE_AVAILABLE_LOW": "STORAGE_PRESSURE",
                      "GPU_MEMORY_AVAILABLE_LOW": "GPU_MEMORY_PRESSURE", "HIGH_MEASUREMENT_VARIABILITY": "MEASUREMENT_NOISE",
                      "QUALITY_REGRESSION": "QUALITY_REGRESSION", "CAPABILITY_UNAVAILABLE": "CAPABILITY_GAP",
                       "WORKLOAD_INSTABILITY": "UNKNOWN_CAUSE", "RESOURCE_AVAILABILITY_CHANGED": "UNKNOWN_CAUSE",
                       "WORKLOAD_VERIFICATION_GAP": "UNKNOWN_CAUSE",
                       "WORKLOAD_OPTIMIZATION_OBJECTIVE": "TRAINER_OPTIMIZATION_OPPORTUNITY",
                       "INFERENCE_OPTIMIZATION_OBJECTIVE": "INFERENCE_OPTIMIZATION_OPPORTUNITY"}
            primary = mapped.get(kind, "ENVIRONMENT_CHANGE")
            kinds = [primary] + (["UNKNOWN_CAUSE"] if primary != "UNKNOWN_CAUSE" else [])
        issue_hypotheses = []
        for hypothesis_kind in kinds:
            supports, contradictions = list(issue["evidence_refs"]), []
            searches = []
            missing = list(NEEDED[hypothesis_kind])
            if hypothesis_kind in ("COMPUTE_PRESSURE", "RESOURCE_CONTENTION", "MEMORY_PRESSURE"):
                searches = [{"check": "workload_wall_stability", "result": "STABLE" if stable else "UNSTABLE_OR_MISSING"},
                            {"check": "memory_available_ratio", "result": "LOW" if signals["memory_low"] else "NORMAL" if signals["memory_normal"] else "MISSING"},
                            {"check": "workload_cpu_scope", "result": "EXACT" if signals["exact_cpu"] else "LOWER_BOUND_OR_MISSING"}]
                if not stable and ref("wall_cv"):
                    contradictions += negative(ref("wall_cv"), "unstable workload measurements weaken attribution", "STRONG")
            else:
                searches = [{"check": "stable_successful_workload_control", "result": "PRESENT" if stable else "MISSING"},
                            {"check": "causal_control", "result": "NOT_AVAILABLE_IN_OBSERVATION_V1"}]
            if hypothesis_kind == "COMPUTE_PRESSURE":
                if cpu_high:
                    supports += ref("cpu_system")
                if ratio_high:
                    supports += ref("cpu_workload") + ref("wall")
                if ratio_low:
                    contradictions += negative(ref("cpu_workload") + ref("wall"), "exact workload CPU/wall is low", "STRONG")
                if signals["memory_low"]:
                    contradictions += negative(ref("memory_available"), "memory pressure remains an alternative contributor", "STRONG")
                missing += ["synchronization_wait_time", "implementation_efficiency_control"]
            elif hypothesis_kind == "RESOURCE_CONTENTION":
                supports += ref("cpu_system") if cpu_high else []
                if ratio_low:
                    supports += ref("cpu_workload") + ref("wall")
                if ratio_high:
                    contradictions += negative(ref("cpu_workload") + ref("wall"), "workload consumes CPU itself; competing demand not isolated")
            elif hypothesis_kind == "MEMORY_PRESSURE":
                supports += ref("memory_available") + ref("memory_total") if signals["memory_low"] else []
                if signals["memory_normal"]:
                    contradictions += negative(ref("memory_available"), "normal MemAvailable weakens memory pressure", "STRONG")
                for name in ("swap_consumption", "rss_growth"):
                    entry = signals[name]
                    searches.append({"check": name, "result": "INCREASE" if entry["active"] else "NO_INCREASE" if entry["known"] else "MISSING"})
                    if entry["active"]:
                        supports += ref(name)
                    elif entry["known"]:
                        contradictions += negative(ref(name), "no measured swap-occupancy or repeated peak-RSS increase")
            elif hypothesis_kind == "RUNTIME_REGRESSION":
                supports += [e for i in evaluation["issues"] if i["kind"] == "RUNTIME_CHANGED" for e in i["evidence_refs"]]
            elif hypothesis_kind == "MEASUREMENT_NOISE":
                searches.append({"check": "variability_scope", "result": issue["details"].get("metric", "wall_s")})
            if stable and hypothesis_kind not in ("MEASUREMENT_NOISE", "UNKNOWN_CAUSE"):
                searches.append({"check": "measurement_noise_alternative", "result": "WEAKENED_BY_STABLE_WALL"})
            hid = f"h{len(hypotheses) + 1:04d}"
            supports = list(dict.fromkeys(supports))
            contradictions = list(dict.fromkeys(contradictions))
            # Identity/occupancy/saturation evidence alone is observational, never a controlled intervention.
            attribution_stable = stable
            if hypothesis_kind in ("COMPUTE_PRESSURE", "RESOURCE_CONTENTION"):
                attribution_stable = stable and signals["workload_cpu_stable"]
                searches.append({"check": "workload_cpu_stability", "result": "STABLE" if signals["workload_cpu_stable"] else "UNSTABLE_OR_MISSING"})
            if hypothesis_kind == "MEASUREMENT_NOISE":
                attribution_stable = False
            critical_missing = not attribution_stable or (hypothesis_kind in ("COMPUTE_PRESSURE", "RESOURCE_CONTENTION") and ratio is None)
            rule_ids = [issue["rule_id"]]
            related_rule = {"COMPUTE_PRESSURE": "RULE_CPU_001", "RESOURCE_CONTENTION": "RULE_CPU_001",
                            "MEMORY_PRESSURE": "RULE_MEMORY_001", "RUNTIME_REGRESSION": "RULE_ENVIRONMENT_001"}.get(hypothesis_kind)
            if related_rule and related_rule not in rule_ids:
                rule_ids.append(related_rule)
            basis = assess([evidence.by_id(e) for e in supports], [evidence.by_id(e) for e in contradictions],
                           stable=attribution_stable, searched=bool(searches), alternative_weakened=stable,
                           missing_critical=critical_missing, minimum_independent=cfg["confidence_min_evidence"], unknown=hypothesis_kind == "UNKNOWN_CAUSE", rule_ids=rule_ids)
            hypothesis = {"hypothesis_id": hid, "issue_id": issue["issue_id"], "kind": hypothesis_kind,
                          "claim": CLAIMS[hypothesis_kind], "causality": "NOT_ESTABLISHED", "rule_ids": rule_ids,
                          "supports": supports, "contradictions": contradictions, "contradiction_search": searches,
                          "alternative_ids": [], "missing_evidence": missing, "confidence": basis["level"], "confidence_basis": basis}
            for e in supports:
                evidence.by_id(e)["supports"].append(hid)
            for e in contradictions:
                evidence.by_id(e)["contradicts"].append(hid)
            hypotheses.append(hypothesis)
            issue_hypotheses.append(hypothesis)
        for hypothesis in issue_hypotheses:
            hypothesis["alternative_ids"] = [h["hypothesis_id"] for h in issue_hypotheses if h is not hypothesis]
        issue["hypothesis_ids"] = [h["hypothesis_id"] for h in issue_hypotheses]
        issue["primary_hypothesis"] = issue["hypothesis_ids"][0]
    return hypotheses
