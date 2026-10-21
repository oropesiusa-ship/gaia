"""Evidence-bound static rejection and immutable qualification state transitions."""
from ..provenance import digest
import re
from .schema import STATES, artifact, ref, validate

LICENSES={'mit','apache-2.0','agpl-3.0','agpl-3.0-only','bsd-3-clause'}


def runtime_eligibility(runtime, profile, *, backend="CPU"):
    validate(runtime); validate(profile)
    r, h = runtime["payload"], profile["payload"]
    reasons, missing = [], []
    if str(r.get('license')).lower()not in LICENSES:reasons.append('LICENSE_NOT_QUALIFIED')
    if r.get('runtime_type')=='NOT_AN_LLM_RUNTIME':reasons.append('OUT_OF_SCOPE_NOT_AN_LLM_RUNTIME')
    if r["supported_OS"] and h["os"]["system"] not in r["supported_OS"]:
        (reasons if r.get('os_support_exhaustive')else missing).append('OS_NOT_SUPPORTED'if r.get('os_support_exhaustive')else'HOST_OS_SUPPORT_NOT_DOCUMENTED')
    if r["supported_CPU_arch"] and h["cpu"]["architecture"] not in r["supported_CPU_arch"]:
        (reasons if r.get('cpu_arch_support_exhaustive')else missing).append('CPU_ARCH_NOT_SUPPORTED'if r.get('cpu_arch_support_exhaustive')else'HOST_CPU_ARCH_SUPPORT_NOT_DOCUMENTED')
    if set(r["supported_CPU_ISA"]) - set(h["cpu"]["instruction_flags"]):
        reasons.append("CPU_ISA_REQUIREMENT_NOT_MET")
    if backend == "CUDA":
        actual = [d.get("compute_capability") for d in h["gpu"].get("devices", []) if d.get("vendor") == "NVIDIA"]
        required = r.get("minimum_compute_capability")
        if not actual or any(v is None for v in actual):
            missing.append("OBSERVED_CUDA_CAPABILITY_MISSING")
        elif required and max(tuple(map(int, v.split('.'))) for v in actual) < tuple(map(int, required.split('.'))):
            reasons.append("OBSERVED_GPU_BELOW_DOCUMENTED_MINIMUM")
    if backend == "VULKAN" and "VULKAN_USABLE_DEVICE_NOT_OBSERVED" in h["missing_evidence"]:
        missing.append("VULKAN_DEVICE_REQUIRES_BOUNDED_RUNTIME_SMOKE")
    if not r["evidence_refs"]:
        missing.append("UPSTREAM_COMPATIBILITY_EVIDENCE_MISSING")
    return {"status": "STATICALLY_INCOMPATIBLE" if reasons else "ELIGIBLE_FOR_INSTALL", "backend": backend,
            "reasons": reasons, "missing_evidence": missing, "runtime_ref": ref(runtime), "host_ref": ref(profile),
            "scope": "DOCUMENTED_BACKEND_REQUIREMENTS_NOT_UNIVERSAL_RUNTIME_REJECTION"}


def model_eligibility(model, profile, runtime, budget, *, mode="CPU_ONLY", context=1024):
    validate(model);validate(profile);validate(runtime)
    m, h, r = model["payload"], profile["payload"], runtime["payload"]
    reasons, missing = [], []
    if m["architecture"] not in r["supported_model_architectures"]:
        if r.get('architecture_support_exhaustive'):
            reasons.append("MODEL_ARCHITECTURE_EXPLICITLY_NOT_SUPPORTED")
        else:
            missing.append("MODEL_ARCHITECTURE_REQUIRES_BOUNDED_COMPATIBILITY_SMOKE")
    if not set(m["model_formats_available"]) & set(r["model_formats"]):
        (reasons if r.get('format_support_exhaustive') else missing).append("MODEL_FORMAT_NOT_SUPPORTED" if r.get('format_support_exhaustive') else "MODEL_FORMAT_REQUIRES_BOUNDED_COMPATIBILITY_SMOKE")
    required = m.get("estimated_memory_bytes")
    if required is None:
        missing.append("MODEL_MEMORY_ESTIMATE_MISSING")
    elif not m.get('selected_weight_sha256')and not m.get('memory_estimate_is_selected_variant'):
        missing.append('MODEL_VARIANT_MEMORY_REQUIRES_SELECTION')
    elif required > budget["worker_ram_bytes"] + (sum(d.get("vram_total_bytes", 0) for d in h["gpu"].get("devices", [])) if mode != "CPU_ONLY" else 0):
        reasons.append("MODEL_EXCEEDS_SAFE_COMBINED_MEMORY_BUDGET")
    if m.get("download_bytes", 0) > budget["max_download_bytes"]:
        reasons.append("MODEL_EXCEEDS_DOWNLOAD_BUDGET")
    if type(m["context"]) is not int:missing.append('MODEL_CONTEXT_LIMIT_MISSING')
    if context > min(budget["max_context"], m["context"] if type(m['context']) is int else budget['max_context']):
        reasons.append("CONTEXT_BUDGET_EXCEEDED")
    if str(m["license"]).lower()not in LICENSES:
        reasons.append("LICENSE_NOT_QUALIFIED")
    return {"status": "STATICALLY_INCOMPATIBLE" if reasons else "ELIGIBLE_FOR_INSTALL", "mode": mode, "reasons": reasons,
            "missing_evidence": missing, "model_ref": ref(model), "runtime_ref": ref(runtime), "host_ref": ref(profile)}


def transition(record, state, evidence):
    validate(record)
    if (not isinstance(evidence,list)or not evidence or any(not isinstance(r,dict)or set(r)!={'id','hash'}
            or not re.fullmatch(r'(?:li|src|cl|ex|acq)[a-f0-9]{24}',str(r['id']))or not re.fullmatch(r'[a-f0-9]{64}',str(r['hash']))for r in evidence)):
        raise ValueError('Typed hashed qualification evidence required')
    if state not in STATES:
        raise ValueError("Unknown qualification state")
    previous = record["payload"]["qualification_status"]
    allowed = {"DISCOVERED": {"STATICALLY_EVALUATED"}, "STATICALLY_EVALUATED": {"STATICALLY_INCOMPATIBLE", "ELIGIBLE_FOR_INSTALL"},
               "ELIGIBLE_FOR_INSTALL": {"INSTALLED_OR_BUILT"}, "INSTALLED_OR_BUILT": {"SMOKE_TESTED"}, "SMOKE_TESTED": {"MODEL_COMPATIBLE"},
               "MODEL_COMPATIBLE": {"BENCHMARKED"}, "BENCHMARKED": {"QUALIFIED", "NOT_SELECTED"}, "QUALIFIED": {"SELECTED", "NOT_SELECTED"}}
    if state != "QUALIFICATION_FAILED" and state not in allowed.get(previous, set()) or not evidence:
        raise ValueError("Invalid or unevidenced qualification transition")
    return artifact(record["kind"], {**record["payload"], "qualification_status": state, "previous_ref": ref(record), "transition_evidence": evidence})


def ancestry_groups(runtimes):
    return {r["payload"]["runtime_id"]: r["payload"]["shared_compute_ancestry"] or [r["payload"]["runtime_id"]] for r in runtimes}
