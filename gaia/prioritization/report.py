"""Research targets and reasons, without interventions or procedures."""


def render(document):
    targets = {t["target_id"]: t for t in document["candidate_targets"]}
    lines = ["GAIA TARGET PRIORITIZATION " + document["prioritization_id"]]
    if not targets:
        lines.append("NO TARGETS: no significant issue with a supported research target")
    for tid in document["ordering"]:
        t = targets[tid]
        lines += ["", t["priority"] + " " + t["target_class"] + " (" + tid + ")", "INTENT: " + t["intent"],
                  "DIMENSIONS: " + str(t["dimensions"]), "WHY: " + ", ".join(t["reasons"]),
                  "BASIS: " + ", ".join(t["dimension_basis"]), "BLOCKERS: " + ", ".join(t["blocked_by"]),
                  "DEPENDENCIES: " + ", ".join(t["dependencies"]), "INFORMATION NEEDED: " + ", ".join(t["information_needed"]),
                  "RULES: " + ", ".join(t["rule_ids"])]
    lines += ["", "LIMITATIONS"] + document["limitations"] + ["COST: " + str(document["cost"]), "Hash: " + document["prioritization_hash"]]
    return "\n".join(lines)
