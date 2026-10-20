"""Ordinal, inspectable research-attention policy. Estimates are not measured costs."""
VERSION = "research_attention_v1"
DEFAULTS = {"large_regression_relative": 0.30, "min_impact_for_p1": "HIGH",
            "max_cost_for_p1": "LOW", "blocking_priority_boost": True,
            "frozen_component_policy": "DEFER"}
IMPACT = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
CONFIDENCE = {"VERY_LOW": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
COST = {"VERY_LOW": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
RULES = ("POLICY_BLOCKED_001", "POLICY_CRITICAL_001", "POLICY_INFORMATION_001",
         "POLICY_BLOCKING_001", "POLICY_VALUE_001", "POLICY_CAUTION_001", "POLICY_DEFAULT_001")


def settings(configuration=None):
    supplied = (configuration or {}).get("prioritization", {})
    if set(supplied) - DEFAULTS.keys():
        raise ValueError("Unknown prioritization configuration")
    value = {**DEFAULTS, **supplied}
    if (type(value["large_regression_relative"]) not in (int, float) or not 0.15 <= value["large_regression_relative"] <= 1
            or value["min_impact_for_p1"] not in ("MEDIUM", "HIGH") or value["max_cost_for_p1"] not in COST
            or type(value["blocking_priority_boost"]) is not bool or value["frozen_component_policy"] != "DEFER"):
        raise ValueError("Invalid prioritization policy")
    return value


def decide(dimensions, blockers, cfg):
    d = dimensions
    reasons = []
    if blockers:
        return "DEFER", ["POLICY_BLOCKED_001"], sorted(set(blockers))
    if d["diagnostic_confidence"] == "VERY_LOW" and d["information_value"] == "LOW":
        return "DEFER", ["POLICY_INFORMATION_001"], ["weak_evidence_and_low_information_value"]
    if (d["impact"] == "HIGH" and d["diagnostic_confidence"] == "HIGH" and d["blocking_power"] == "HIGH"
            and COST[d["investigation_cost"]] <= 1 and d["risk"] == "LOW" and d["reversibility"] == "EASY"
            and d["evidence_completeness"] == "SUFFICIENT"):
        return "P0", ["POLICY_CRITICAL_001"], ["strongly_supported_critical_blocker"]
    if (cfg["blocking_priority_boost"] and d["blocking_power"] == "HIGH" and COST[d["investigation_cost"]] <= 1
            and d["risk"] == "LOW" and d["diagnostic_confidence"] != "VERY_LOW"):
        tier, rule = "P1", "POLICY_BLOCKING_001"
        reasons.append("measurement_evidence_blocks_other_research")
    elif (IMPACT[d["impact"]] >= IMPACT[cfg["min_impact_for_p1"]] and COST[d["investigation_cost"]] <= COST[cfg["max_cost_for_p1"]]
          and (CONFIDENCE[d["diagnostic_confidence"]] >= 2 or d["information_value"] == "HIGH")):
        tier, rule = "P1", "POLICY_VALUE_001"
        reasons.append("high_impact_with_support_or_discriminating_information")
    elif d["impact"] == "MEDIUM" or d["information_value"] == "HIGH" or d["diagnostic_confidence"] in ("MEDIUM", "HIGH"):
        tier, rule = "P2", "POLICY_VALUE_001"
        reasons.append("useful_research_value_without_critical_blockage")
    else:
        tier, rule = "P3", "POLICY_DEFAULT_001"
        reasons.append("limited_current_impact_or_support")
    rules = [rule]
    if d["investigation_cost"] == "HIGH" or d["risk"] != "LOW" or d["reversibility"] in ("DIFFICULT", "UNKNOWN"):
        tier = "P3" if tier in ("P1", "P2") else tier
        rules.append("POLICY_CAUTION_001")
        reasons.append("cost_risk_or_reversibility_reduces_priority")
    return tier, rules, reasons


def ordering(targets):
    # A lexicographic ordering, never a falsely precise utility score.
    return sorted(targets, key=lambda t: (("P0", "P1", "P2", "P3", "DEFER").index(t["priority"]),
                                        -IMPACT[t["dimensions"]["impact"]],
                                        -IMPACT[t["dimensions"]["information_value"]],
                                        -CONFIDENCE[t["dimensions"]["diagnostic_confidence"]],
                                        COST[t["dimensions"]["investigation_cost"]],
                                        ("LOW", "MEDIUM", "HIGH").index(t["dimensions"]["risk"]),
                                        ("EASY", "MODERATE", "DIFFICULT", "UNKNOWN").index(t["dimensions"]["reversibility"]), t["target_id"]))
