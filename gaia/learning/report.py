"""Fixed-vocabulary contextual engineering memory report, without future interventions."""


def render(item):
    lines = ["GAIA EXPERIMENTAL LEARNING " + item["learning_id"], "DOMAIN " + item["domain"],
             "COMPONENT " + item["component"], "CLAIM " + item["claim_type"], "STATUS " + item["status"],
             "SUBJECT " + str(item["claim"]), "CONFIDENCE " + item["confidence"],
             "REPLICATION " + item["replication_status"], "HIERARCHY " + item["hierarchy"],
             "EVIDENCE " + ", ".join(item["source_experiments"]), "CONTRADICTIONS " + str(item["quality"]["contradictions_count"]),
             "APPLICABILITY " + str(item["applicability"]), "LIMITATIONS"]
    return "\n".join(lines + item["limitations"] + ["Hash: " + item["hash"]])
