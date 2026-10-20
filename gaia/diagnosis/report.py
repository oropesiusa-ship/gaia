"""Human-readable, explicitly uncertain explanations; no optimization advice."""


def render(value):
    evidence = {e["evidence_id"]: e for e in value["evidence"]}
    lines = ["GAIA DIAGNOSIS " + value["diagnosis_id"], "OUTCOME: " + value["outcome"]]
    for issue in value["issues"]:
        lines += ["", "ISSUE " + issue["issue_id"] + ": " + issue["kind"], str(issue["details"])]
        for hypothesis in (h for h in value["hypotheses"] if h["issue_id"] == issue["issue_id"]):
            label = "PRIMARY HYPOTHESIS" if hypothesis["hypothesis_id"] == issue["primary_hypothesis"] else "ALTERNATIVE"
            lines += [label + ": " + hypothesis["kind"], "Confidence: " + hypothesis["confidence"], hypothesis["claim"]]
            for field, heading in (("supports", "SUPPORTS"), ("contradictions", "CONTRADICTS")):
                lines.append(heading)
                for eid in hypothesis[field]:
                    e = evidence[eid]
                    lines.append(f"- {eid} {e['observation_ref']['role']} {e['field']} = {e['value']} ({e['type']}, {e['strength']})")
                if not hypothesis[field]:
                    lines.append("- none recorded; contradiction search is in the rule trace")
            lines += ["MISSING EVIDENCE: " + ", ".join(hypothesis["missing_evidence"]),
                      "RULES: " + ", ".join(hypothesis["rule_ids"])]
    lines += ["", "MISSING EVIDENCE: " + ", ".join(value["missing_evidence"]), "LIMITATIONS"]
    lines += ["- " + limitation for limitation in value["limitations"]]
    lines += ["COST: " + str(value["cost"]), "Diagnosis hash: " + value["diagnosis_hash"]]
    return "\n".join(lines)
