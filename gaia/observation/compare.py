"""Factual recursive differences and noise-aware descriptive metric comparisons."""
from .schema import validate


def differences(a, b, path=""):
    result = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(a.keys() | b.keys()):
            field = path + "." + key if path else key
            if key not in a:
                result.append({"field": field, "kind": "added", "after": b[key]})
            elif key not in b:
                result.append({"field": field, "kind": "removed", "before": a[key]})
            else:
                result.extend(differences(a[key], b[key], field))
    elif a != b:
        result.append({"field": path, "kind": "changed", "before": a, "after": b})
    return result


def metric_change(a, b, relative_threshold):
    result = {"before_median": a.get("median"), "after_median": b.get("median"),
              "relative_change": None, "classification": "INSUFFICIENT_DATA"}
    if (any(x.get("count", 0) < 3 or x.get("median") is None or x.get("standard_deviation") is None for x in (a, b))
            or a["median"] == 0):
        return result
    delta = b["median"] - a["median"]
    relative = delta / abs(a["median"])
    noise = 2 * max(a["standard_deviation"], b["standard_deviation"])
    result.update(relative_change=relative, absolute_change=delta, noise_band=noise,
                  relative_threshold=relative_threshold,
                  classification="POSSIBLY_SIGNIFICANT" if abs(relative) >= relative_threshold and abs(delta) > noise else "WITHIN_NOISE")
    return result


def compare(a, b, relative_threshold=0.15):
    validate(a)
    validate(b)
    facts_a, facts_b = a["sections"]["facts"], b["sections"]["facts"]
    changes = differences(facts_a, facts_b, "facts")
    caps_a = {c["name"]: c for c in a["sections"]["capabilities"]}
    caps_b = {c["name"]: c for c in b["sections"]["capabilities"]}
    capabilities = differences(caps_a, caps_b, "capabilities")
    metrics = []
    for scope in ("resources", "workload"):
        left, right = a["sections"]["measurements"].get(scope, {}), b["sections"]["measurements"].get(scope, {})
        compatible = scope != "workload" or (left.get("protocol_hash") is not None and left.get("protocol_hash") == right.get("protocol_hash"))
        for key in sorted(left.get("statistics", {}).keys() | right.get("statistics", {}).keys()):
            entry = metric_change(left.get("statistics", {}).get(key, {}), right.get("statistics", {}).get(key, {}), relative_threshold)
            if not compatible:
                entry["classification"] = "INSUFFICIENT_DATA"
                entry["reason"] = "different_workload_protocols"
            metrics.append({"metric": scope + "." + key, **entry})
    return {"schema": "gaia_observation_comparison_v1", "a": a["observation_id"], "b": b["observation_id"],
            "a_hash": a["observation_hash"], "b_hash": b["observation_hash"],
            "hardware_changed": a["host_identity"] != b["host_identity"],
            "runtime_changed": a["runtime_identity"] != b["runtime_identity"],
            "source_changed": a["source_identity"] != b["source_identity"],
            "capability_changed": bool(capabilities), "fields": changes + capabilities, "measurements": metrics}
