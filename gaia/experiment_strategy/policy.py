"""Versioned ordinal utility components, never a claim of calibrated expected value."""
from ..provenance import digest

VERSION = "shadow_research_policy_v1"
DEFAULTS = {"replication_bonus": 4, "exact_repeat_penalty": 20, "information_value_weight": 3,
            "improvement_potential_weight": 1, "cost_penalty": 2, "risk_penalty": 3,
            "verification_bonus": 2, "exploitation_bonus": 3, "exploration_floor": 1,
            "knowledge_validation_bonus": 3,
            "max_candidate_plans": 24, "max_trials_per_plan": 20}
ORDINAL = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
CONFIDENCE = {"VERY_LOW": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
COST = {"VERY_LOW": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
RULES = ("META_REPLICATE_001", "META_INCONCLUSIVE_001", "META_CONTRADICTION_001", "META_STALE_001",
         "META_NEGATIVE_001", "META_MEASUREMENT_001", "META_EXPLORE_001", "META_EXPLOIT_001",
         "META_BASELINE_001", "META_FACTORIAL_001", "META_AUTHORITY_001", "META_BUDGET_001")


def settings(configuration=None):
    supplied = (configuration or {}).get("meta_strategy", {})
    if set(supplied) - DEFAULTS.keys():
        raise ValueError("Unknown meta strategy configuration")
    cfg = {**DEFAULTS, **supplied}
    for key, val in cfg.items():
        low, high = (1, 100) if key == "max_candidate_plans" else (5, 100) if key == "max_trials_per_plan" else (0, 2) if key == "exploration_floor" else (1, 50)
        if type(val) is not int or not low <= val <= high:
            raise ValueError("Invalid meta strategy bound")
    if cfg["exploration_floor"] > cfg["max_candidate_plans"]:
        raise ValueError("Exploration floor exceeds plan budget")
    return cfg


def identity(cfg):
    return {"version": VERSION, "settings": cfg, "rules": list(RULES),
            "policy_hash": digest({"version": VERSION, "settings": cfg, "rules": RULES})}


def score(plan, cfg):
    d = plan["estimates"]
    penalty = cfg["exact_repeat_penalty"] if plan["duplication"]["risk"] == "HIGH" and not plan["duplication"]["intentional"] else 0
    return {"information": ORDINAL[d["information_value"]] * cfg["information_value_weight"],
            "improvement": ORDINAL[d["improvement_potential"]] * cfg["improvement_potential_weight"],
            "confidence": CONFIDENCE[plan["confidence"]],
            "replication": cfg["replication_bonus"] if plan["class"] == "REPLICATION" else 0,
            "verification": cfg["verification_bonus"] if plan["mode"] == "VERIFY" else 0,
            "scope_validation": cfg["knowledge_validation_bonus"] if plan["class"] == "KNOWLEDGE_VALIDATION" else 0,
            "exploitation": cfg["exploitation_bonus"] if plan["mode"] == "EXPLOIT" and plan["confidence"] == "HIGH" else 0,
            "cost": -COST[d["cost"]] * cfg["cost_penalty"],
            "risk": -(ORDINAL[d["risk"]] - 1) * cfg["risk_penalty"],
            "reversibility": -{"EASY": 0, "MODERATE": 1, "DIFFICULT": 3, "UNKNOWN": 3}[d["reversibility"]],
            "duplication": -penalty}


def rank(plans):
    return sorted((p for p in plans if not p["blocked_by"]), key=lambda p: (
        ("P0", "P1", "P2", "P3", "DEFER").index(p["target_ref"]["priority"]),
        -p["utility"]["ordinal_total"], -ORDINAL[p["target_ref"]["impact"]],
        -ORDINAL[p["estimates"]["information_value"]], COST[p["estimates"]["cost"]], p["plan_id"]))
