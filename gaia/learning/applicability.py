"""Context compatibility is explicit, never silently inferred from today's host."""
from ..provenance import digest
from .schema import CONTEXT_FIELDS


def context_key(context):
    return digest(context)


def assess(scope, requested=None, cfg=None):
    if requested is None:
        return {"transferability": "UNKNOWN_TRANSFER", "status": "UNASSESSED", "differences": [],
                "reason": "explicit_context_required_no_host_recollection"}
    if not isinstance(requested, dict) or not requested or set(requested) - CONTEXT_FIELDS:
        raise ValueError("Invalid explicit applicability context")
    differences = sorted(k for k in requested if requested[k] != scope[k])
    if "workload" in differences or "trainer_family" in differences:
        transfer = "NOT_TRANSFERABLE"
    elif not differences and set(requested) == CONTEXT_FIELDS:
        transfer = "EXACT_CONTEXT"
    elif "workload" not in requested:
        transfer = "UNKNOWN_TRANSFER"
    elif any(k in differences for k in ("benchmark_hash", "quality_threshold", "baseline_version", "source_hash")):
        transfer = "RELATED_CONTEXT"
    else:
        transfer = "SAME_WORKLOAD"
    cfg = cfg or {}
    stale_keys = {"environment_hash", "benchmark_hash", "workload", "trainer_family", "source_hash", "gaia_version", "quality_threshold", "baseline_version"}
    if cfg.get("stale_on_runtime_change", True):
        stale_keys.add("runtime_hash")
    if cfg.get("stale_on_hardware_change", True):
        stale_keys.add("host_hash")
    stale = bool(stale_keys.intersection(differences))
    return {"transferability": transfer, "status": "STALE" if stale else "APPLICABLE" if transfer == "EXACT_CONTEXT" else "LIMITED",
            "differences": differences, "reason": "contextual_filter_not_global_validity"}
