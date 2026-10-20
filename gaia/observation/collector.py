"""Compose facts, measurements, capabilities and context without Engine access."""
from datetime import datetime, timezone
from pathlib import Path
import time

from ..provenance import digest
from ..config import DEFAULTS as CONFIG_DEFAULTS
from . import COLLECTOR_VERSION, capabilities, components, gpu, host, resources, runtime, workload
from .local import unavailable
from .schema import OBSERVATION_SCHEMA

DEFAULTS = CONFIG_DEFAULTS["observation"]


def settings(cfg):
    value = {**DEFAULTS, **cfg.get("observation", {})}
    for name in ("quick_samples", "full_samples"):
        if type(value[name]) is not int or not 1 <= value[name] <= 30:
            raise ValueError(name + " must be an integer in 1..30")
    for name, low, high in (("sample_interval_ms", 0, 1000), ("max_duration_seconds", 1, 300),
                            ("stability_cv_threshold", 0.01, 0.5), ("significant_relative_change", 0.01, 1)):
        if type(value[name]) not in (int, float) or not low <= value[name] <= high:
            raise ValueError(name + " outside observation bounds")
    if type(value["include_workload"]) is not bool:
        raise ValueError("include_workload must be boolean")
    return value


def optional(name, callback, errors):
    try:
        return callback()
    except Exception as exc:
        failure = unavailable(name, type(exc).__name__, "ERROR")
        errors.append(failure)
        return failure


def collect(root, state, cfg, quick=False):
    root = Path(root).resolve()
    options = settings(cfg)
    start = time.perf_counter()
    deadline = start + options["max_duration_seconds"]
    errors = []
    facts_host = optional("host", lambda: host.collect(root, state), errors)
    facts_runtime = optional("runtime", lambda: runtime.collect(root, cfg), errors)
    facts_gpu = optional("gpu", gpu.collect, errors)
    # Separate volatile VRAM before constructing the hardware identity.
    gpu_dynamic = [{"vram_available_bytes": d.pop("vram_available_bytes")} for d in facts_gpu.get("devices", [])
                   if "vram_available_bytes" in d]
    source = runtime.source(root, cfg)  # Source integrity is critical, unlike optional devices.
    inventory = components.collect(root)
    caps = capabilities.collect(facts_runtime, facts_gpu, inventory)
    host_id = {"stable_hash": digest({"host": facts_host, "gpu": facts_gpu})}
    runtime_id = {"stable_hash": facts_runtime.get("identity_hash", digest(facts_runtime))}
    source_id = {k: source[k] for k in ("source_aggregate_hash", "observation_source_hash", "protected_source_identity", "inventory_complete")}
    environment_id = {"identity_hash": digest({"host": host_id, "runtime": runtime_id, "source": source_id})}
    count = options["quick_samples" if quick else "full_samples"]
    sampling = optional("resources", lambda: resources.collect(root, count, options["sample_interval_ms"],
                                                              options["stability_cv_threshold"], deadline), errors)
    measured_workload = {"status": "NOT_CONFIGURED", "reason": "quick_mode" if quick else "disabled_by_config"}
    if not quick and options["include_workload"]:
        if not facts_runtime.get("sandbox", {}).get("verified") or not facts_runtime.get("libraries", {}).get("numpy"):
            measured_workload = unavailable("numpy_mlp", "numpy_or_verified_bwrap_unavailable")
        else:
            measured_workload = optional("numpy_mlp", lambda: workload.collect(cfg, count, options["stability_cv_threshold"], deadline, environment_id), errors)
    facts = {"host": facts_host, "runtime": facts_runtime, "gpu": facts_gpu,
             "components": inventory, "source_files": source["files"]}
    context = {"mode": "quick" if quick else "full", "settings": options, "git": runtime.git(root),
               "failures": errors, "privacy_policy": "explicit_local_field_allowlist_v1",
               "cost": {"sampling_duration_s": sampling.get("duration_s", 0),
                        "workload_duration_s": measured_workload.get("duration_s", 0)},
               "authority": "read_only_and_controlled_measurement", "deadline_reached": time.perf_counter() >= deadline}
    context["cost"]["total_duration_s"] = time.perf_counter() - start
    return {"schema": OBSERVATION_SCHEMA, "timestamp": datetime.now(timezone.utc).isoformat(),
            "collector_version": COLLECTOR_VERSION, "source_identity": source_id, "host_identity": host_id,
            "runtime_identity": runtime_id, "environment_identity": environment_id,
            "sections": {"facts": facts, "measurements": {"resources": sampling, "workload": measured_workload,
                                                         "gpu": gpu_dynamic},
                         "capabilities": caps, "context": context}}
