"""Inference profile derived exclusively from an explicitly validated v0.2 observation."""
from ..diagnosis.evidence import validate_input
from .schema import artifact


def derive(observation):
    validate_input(observation)
    f, m = observation["sections"]["facts"], observation["sections"]["measurements"]
    h = f["host"]
    stats = m.get("resources", {}).get("statistics", {})
    def median(name):
        return stats.get(name, {}).get("median")
    tools = f["runtime"].get("inference_tooling", {})
    missing = [key for key, val in (("ram_available", median("system_ram_available_bytes")), ("filesystem_available", median("filesystem_available_bytes"))) if val is None]
    if not tools.get("vulkaninfo", {}).get("usable_probe"):
        missing.append("VULKAN_USABLE_DEVICE_NOT_OBSERVED")
    return artifact("HOST_PROFILE", {"observation_id": observation["observation_id"], "observation_hash": observation["observation_hash"],
        "host_identity": observation["host_identity"], "environment_identity": observation["environment_identity"],
        "cpu": h["cpu"], "ram_total_bytes": h["ram"].get("total_bytes"), "ram_available_bytes": median("system_ram_available_bytes"),
        "filesystem_available_bytes": median("filesystem_available_bytes"), "os": h["os"], "gpu": f["gpu"],
        "gpu_dynamic": m.get("gpu", []), "inference_tooling": tools, "missing_evidence": missing})


def budget(profile):
    p = profile["payload"]
    free, available = p["filesystem_available_bytes"], p["ram_available_bytes"]
    if not free or not available:
        raise ValueError("Resource evidence required before installation")
    return {"max_runtime_artifacts": 3, "max_runtime_builds": 2, "max_model_artifacts": 3, "max_models_simultaneous": 2,
            "max_configurations_per_model": 5, "max_stacks": 12, "max_download_bytes": min(8 * 2**30, int(free * .15)),
            "disk_budget_bytes": min(12 * 2**30, int(free * .25)), "worker_ram_bytes": int(available * .70),
            "smoke_timeout_seconds": 120, "benchmark_timeout_seconds": 900, "max_context": 1024,
            "max_generation_tokens": 96, "repeats": 3, "threads": min(8, len(p["cpu"].get("effective_cpus") or []) or p["cpu"]["logical_cores"])}
