"""Ordinal confidence policy; counts independent evidence groups, not repeated fields."""
LEVELS = ("VERY_LOW", "LOW", "MEDIUM", "HIGH")


def assess(supports, contradictions, *, stable, searched, alternative_weakened,
           missing_critical, minimum_independent=3, unknown=False, rule_ids=()):
    groups = {e["group"] for e in supports if e["strength"] != "WEAK"}
    strong_contradiction = any(e["strength"] == "STRONG" for e in contradictions)
    controlled = any(e["type"] in ("DIRECT", "CONTROL") and e["strength"] == "STRONG" for e in supports)
    level = 0 if not groups else 1 if len(groups) < 2 else 2
    if (len(groups) >= minimum_independent and len(set(rule_ids)) >= 2 and controlled and stable and searched
            and alternative_weakened and not contradictions and not missing_critical):
        level = 3
    if strong_contradiction:
        level = max(0, level - 1)
    if not stable or missing_critical or not searched:
        level = min(level, 1)
    if unknown:
        level = min(level, 1)
    return {"level": LEVELS[level], "independent_support_groups": sorted(groups),
            "strong_contradiction": strong_contradiction, "stable_measurement": stable,
            "contradictions_searched": searched, "alternative_weakened": alternative_weakened,
            "missing_critical": missing_critical, "strong_direct_or_control": controlled,
            "rules_considered": sorted(set(rule_ids)),
            "minimum_independent": minimum_independent, "policy": "ordinal_evidence_v1"}
