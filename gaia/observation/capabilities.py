"""Observable availability with explicit conditions, never recommendations."""


def collect(runtime, gpu, components):
    inventory = {c["component_id"]: c for c in components}
    numpy = bool(runtime.get("libraries", {}).get("numpy"))
    sandbox = runtime.get("sandbox", {}).get("verified", False)
    def cap(name, status, evidence, conditions):
        return {"name": name, "status": status, "evidence": evidence, "conditions": conditions}
    return [
        cap("cpu_numpy_workload_available", "AVAILABLE" if numpy and sandbox else "UNAVAILABLE",
            {"numpy": numpy, "bwrap_verified": sandbox}, ["protected evaluator", "fixed observation protocol"]),
        cap("bwrap_sandbox_available", "AVAILABLE" if sandbox else "UNAVAILABLE", runtime.get("sandbox", {}), ["local namespace smoke test"]),
        cap("cpu_campaign_available", "AVAILABLE" if numpy and sandbox and inventory["cpu_evolution"]["code_present"] else "UNAVAILABLE",
            {"code_present": inventory["cpu_evolution"]["code_present"], "prerequisites_observed": numpy and sandbox,
             "current_campaign_certified": False}, ["campaign requires separate G0–G5; not executed by observation"]),
        cap("cuda_runtime_detected", "AVAILABLE" if gpu.get("cuda_runtime_detected") else "UNKNOWN",
            {"local_library_detected": gpu.get("cuda_runtime_detected")}, ["library detection does not certify execution"]),
        cap("torch_cuda_available", "UNKNOWN", {"probe": "not_executed", "torch_version": runtime.get("libraries", {}).get("torch")}, ["no Torch import or GPU execution"]),
        cap("gpu_campaign_code_present", "FROZEN", {"code_present": inventory["gpu"]["code_present"], "certified_equivalent_to_cpu": False}, ["GPU frozen"]),
        cap("appliance_code_present", "FROZEN", {"code_present": inventory["appliance"]["code_present"], "certified_equivalent_to_cpu": False}, ["appliance frozen"]),
        cap("internet_access_not_tested", "UNKNOWN", {"tested": False}, ["offline observation"]),
        cap("llm_runtime_not_configured", "NOT_CONFIGURED", {"observation_llm_integration": False}, ["no LLM integration in GAIA 0.2"]),
    ]
