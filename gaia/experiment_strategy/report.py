"""Explain advisory plans and evidence; no commands, code, or implied execution."""


def render(document):
    lines = ["GAIA EXPERIMENT STRATEGY " + document["strategy_id"], "MODE: SHADOW — NO PLAN EXECUTION",
             "ANALYSIS: " + document["analysis_mode"], "CONTEXT BINDING: " + document["context_binding"]]
    indexed = {p["plan_id"]: p for p in document["candidate_plans"]}
    for index, pid in enumerate(document["ranking"], 1):
        p = indexed[pid]
        lines += ["", f"TARGET {p['target_ref']['target_class']} ({p['target_ref']['priority']})",
                  f"RANK {index}: {p['class']} / {p['mode']}", "WHY: " + ", ".join(p["rationale"]),
                  "VARIABLES: " + ", ".join(p["variables"]), "DESIGN: " + p["design"],
                  "ESTIMATES: " + str(p["estimates"]), "NOVELTY: " + p["novelty"],
                  "DUPLICATION: " + str(p["duplication"]), "UTILITY COMPONENTS: " + str(p["utility"]["components"]),
                  "STOPPING: " + str(p["stopping_rules"])]
    if not document["ranking"]:
        lines.append("NO ELIGIBLE PLAN: no significant eligible target or required context/authority missing")
    for p in document["candidate_plans"]:
        if p["blocked_by"]:
            lines += ["AVOID / BLOCKED: " + p["class"], ", ".join(p["blocked_by"])]
    lines += ["", "META-METRICS (historical snapshot, small-sample limitations): " + str(document["meta_metrics"]), "LIMITATIONS"]
    lines += document["limitations"] + ["Output hash: " + document["output_hash"]]
    return "\n".join(lines)
