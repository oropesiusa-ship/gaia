"""Versioned explicit signal rules. Signals are not causal conclusions."""
from ..observation.compare import compare, metric_change
from ..provenance import digest
from .evidence import number, pointer

RULE_VERSION = "diagnostic_rules_v1"
RULES = {
    "RULE_PERFORMANCE_001": "Stable successful same-protocol workload: significant wall increase",
    "RULE_QUALITY_001": "Stable successful same-protocol workload: significant quality decrease",
    "RULE_NOISE_001": "Repeated workload wall CV exceeds configured threshold",
    "RULE_MEMORY_001": "System MemAvailable/total below threshold; not MemFree",
    "RULE_CPU_001": "System CPU high; workload CPU evidence evaluated independently",
    "RULE_STORAGE_001": "Filesystem available/total below threshold; no storage causation implied",
    "RULE_GPU_MEMORY_001": "Passive VRAM available/total low; no GPU workload causation implied",
    "RULE_EXECUTION_001": "Recorded workload failed or has error status",
    "RULE_CAPABILITY_001": "Required CPU/sandbox capability unavailable, excluding frozen/unconfigured capabilities",
    "RULE_ENVIRONMENT_001": "v0.2 comparison reports identity changes",
}
MEASURE = "/sections/measurements/"


def statistics(doc, scope, metric):
    value = pointer(doc, MEASURE + scope + "/statistics/" + metric)
    return value if isinstance(value, dict) else {}


def median(doc, scope, metric):
    stats = statistics(doc, scope, metric)
    return number(stats.get("median")) if stats.get("count", 0) >= 3 else None


def evaluate(current, baseline, cfg, evidence):
    issues, signals, missing = [], {}, []
    def metric(key, scope, field, group, relation):
        path = MEASURE + scope + "/statistics/" + field + "/median"
        value = median(current, scope, field)
        signals[key] = {"value": value, "evidence": evidence.add("current", path, relation, group) if value is not None else None}
        return value
    def fact(key, path, group, relation):
        value = number(pointer(current, path))
        signals[key] = {"value": value, "evidence": evidence.add("current", path, relation, group) if value is not None else None}
        return value
    def issue(kind, rule, refs, details=None):
        issues.append({"issue_id": f"i{len(issues) + 1:04d}", "kind": kind, "rule_id": rule,
                       "evidence_refs": list(dict.fromkeys(e for e in refs if e)), "details": details or {}})
    wall = statistics(current, "workload", "wall_s")
    cv = number(wall.get("coefficient_of_variation"))
    success = pointer(current, MEASURE + "workload/status") == "AVAILABLE"
    stable = success and wall.get("count", 0) >= 3 and cv is not None and cv <= cfg["max_noise_cv"]
    cv_e = evidence.add("current", MEASURE + "workload/statistics/wall_s/coefficient_of_variation",
                        "wall CV compared with max_noise_cv", "stability")
    signals["wall_cv"] = {"value": cv, "evidence": cv_e}
    signals["stable"] = stable
    if wall.get("count", 0) >= 3 and cv is not None and cv > cfg["max_noise_cv"]:
        issue("HIGH_MEASUREMENT_VARIABILITY", "RULE_NOISE_001", [cv_e], {"cv": cv, "threshold": cfg["max_noise_cv"]})
    if not stable:
        missing.append("stable_successful_workload_wall_samples")
    cpu = metric("cpu_system", "resources", "system_cpu_utilization_percent", "cpu_system", "system CPU utilization relative to configured high threshold")
    cpu_s = metric("cpu_workload", "workload", "process_cpu_s", "cpu_workload", "exact workload process CPU compared with workload wall")
    exact = pointer(current, MEASURE + "workload/cpu_measurement_method") == "process_cpu_clock"
    if not exact:
        cpu_s = metric("cpu_workload", "workload", "descendant_cpu_s_lower_bound", "cpu_workload", "sampled descendant CPU is only a lower bound")
    wall_s = metric("wall", "workload", "wall_s", "cpu_workload", "wall denominator for workload CPU/wall ratio")
    signals["cpu_ratio"] = cpu_s / wall_s if cpu_s is not None and wall_s and wall_s > 0 else None
    signals["exact_cpu"] = exact
    if cpu is not None and cpu >= cfg["cpu_utilization_high"]:
        issue("SYSTEM_CPU_UTILIZATION_HIGH", "RULE_CPU_001", [signals["cpu_system"]["evidence"]], {"percent": cpu})
    available = metric("memory_available", "resources", "system_ram_available_bytes", "memory", "MemAvailable compared with total RAM, not free pages")
    total = fact("memory_total", "/sections/facts/host/ram/total_bytes", "memory", "total RAM denominator")
    ratio = available / total if available is not None and total and total > 0 else None
    signals["memory_low"] = ratio is not None and ratio < cfg["memory_available_low_ratio"]
    signals["memory_normal"] = ratio is not None and ratio >= cfg["memory_available_low_ratio"]
    if signals["memory_low"]:
        issue("MEMORY_AVAILABLE_LOW", "RULE_MEMORY_001", [signals[k]["evidence"] for k in ("memory_available", "memory_total")], {"available_ratio": ratio})
    for key, scope, name, group, growth in (("swap_consumption", "resources", "swap_available_bytes", "paging", False),
                                           ("rss_growth", "workload", "peak_rss_mb", "rss", True)):
        values = statistics(current, scope, name).get("samples", [])
        first, last = (number(values[0]), number(values[-1])) if len(values) >= 3 else (None, None)
        delta = last - first if first is not None and last is not None else None
        active = (delta / first >= cfg["rss_growth_relative"] if first and delta is not None else False) if growth else (delta is not None and -delta >= cfg["swap_consumption_bytes"])
        refs = []
        if delta is not None:
            for index in (0, len(values) - 1):
                refs.append(evidence.add("current", MEASURE + scope + "/statistics/" + name + f"/samples/{index}",
                                         "repeated peak RSS growth" if growth else "swap free delta measures occupancy, not swap I/O activity", group))
        signals[key] = {"active": active, "known": delta is not None, "evidence": refs}
    free = metric("storage_available", "resources", "filesystem_available_bytes", "storage", "filesystem available relative to total")
    disk_total = fact("storage_total", "/sections/facts/host/storage/source/total_bytes", "storage", "filesystem total denominator")
    if free is not None and disk_total and disk_total > 0 and free / disk_total < cfg["storage_available_low_ratio"]:
        issue("STORAGE_AVAILABLE_LOW", "RULE_STORAGE_001", [signals[k]["evidence"] for k in ("storage_available", "storage_total")], {"available_ratio": free / disk_total})
    gpu = pointer(current, MEASURE + "gpu")
    devices = pointer(current, "/sections/facts/gpu/devices")
    if isinstance(gpu, list) and isinstance(devices, list):
        for index, (measurement, device) in enumerate(zip(gpu, devices)):
            free, total = number(measurement.get("vram_available_bytes")), number(device.get("vram_total_bytes"))
            if free is not None and total and total > 0 and free / total < cfg["gpu_memory_available_low_ratio"]:
                ref = evidence.add("current", MEASURE + f"gpu/{index}/vram_available_bytes", "passive VRAM availability, no utilization evidence", "gpu_memory")
                issue("GPU_MEMORY_AVAILABLE_LOW", "RULE_GPU_MEMORY_001", [ref], {"available_ratio": free / total})
    status = pointer(current, MEASURE + "workload/status")
    if status in ("ERROR", "UNAVAILABLE"):
        ref = evidence.add("current", MEASURE + "workload/status", "recorded workload failure; cause not established", "execution", kind="DIRECT", strength="STRONG")
        issue("WORKLOAD_INSTABILITY", "RULE_EXECUTION_001", [ref])
    for index, capability in enumerate(current["sections"]["capabilities"]):
        if capability["name"] in ("cpu_numpy_workload_available", "bwrap_sandbox_available") and capability["status"] == "UNAVAILABLE":
            ref = evidence.add("current", f"/sections/capabilities/{index}/status", "required declared capability unavailable", "capability", kind="DIRECT")
            issue("CAPABILITY_UNAVAILABLE", "RULE_CAPABILITY_001", [ref])
    comparison = compare(baseline, current, cfg["performance_regression_relative"]) if baseline is not None else None
    signals["runtime_changed"] = bool(comparison and comparison["runtime_changed"])
    if comparison:
        for name in ("runtime", "hardware", "source"):
            if comparison[name + "_changed"]:
                path = {"runtime": "/runtime_identity/stable_hash", "hardware": "/host_identity/stable_hash",
                        "source": "/source_identity/observation_source_hash"}[name]
                refs = [evidence.add(role, path, "identity differs in v0.2 comparison; temporal association is not causation",
                                     "identity", kind="CONTEXTUAL") for role in ("baseline", "current")]
                issue(name.upper() + "_CHANGED", "RULE_ENVIRONMENT_001", refs, {"identity_changed": True, "comparison_field": name + "_changed"})
        baseline_wall = statistics(baseline, "workload", "wall_s")
        baseline_cv = number(baseline_wall.get("coefficient_of_variation"))
        baseline_stable = (baseline_wall.get("count", 0) >= 3 and baseline_cv is not None
                           and baseline_cv <= cfg["max_noise_cv"])
        compatible = pointer(current, MEASURE + "workload/protocol_hash") is not None and pointer(current, MEASURE + "workload/protocol_hash") == pointer(baseline, MEASURE + "workload/protocol_hash")
        for name, kind, rule, threshold, direction in (("wall_s", "PERFORMANCE_REGRESSION", "RULE_PERFORMANCE_001", cfg["performance_regression_relative"], 1),
                                                        ("final_acc", "QUALITY_REGRESSION", "RULE_QUALITY_001", cfg["quality_regression_relative"], -1)):
            change = metric_change(statistics(baseline, "workload", name), statistics(current, "workload", name), threshold)
            if (stable and baseline_stable and compatible and pointer(baseline, MEASURE + "workload/status") == "AVAILABLE"
                    and change["classification"] == "POSSIBLY_SIGNIFICANT" and change["relative_change"] * direction > 0):
                refs = [evidence.add(role, MEASURE + "workload/statistics/" + name + "/median",
                                     "noise-aware same-protocol comparison", "comparison" if name == "wall_s" else "quality") for role in ("baseline", "current")]
                issue(kind, rule, refs, {"metric": name, **change})
        if not compatible:
            missing.append("matching_workload_protocols")
        if not baseline_stable or pointer(baseline, MEASURE + "workload/status") != "AVAILABLE":
            missing.append("comparable_baseline_samples")
    if current["source_identity"].get("inventory_complete") is not True:
        missing.append("complete_source_inventory")
    if not comparison:
        missing.append("baseline_for_temporal_inference")
    return {"issues": issues, "signals": signals, "missing": missing, "comparison": comparison,
            "rules_evaluated": list(RULES), "rule_hash": digest({"version": RULE_VERSION, "rules": RULES, "thresholds": cfg})}
