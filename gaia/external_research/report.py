"""Human evidence report with explicit untrusted quotes, citations and no authorized actions."""


def passive_display(text):
    return "".join(c if c == "\n" or ord(c) >= 32 and not 127 <= ord(c) <= 159 and ord(c) not in (0x202A, 0x202B, 0x202D, 0x202E, 0x202C, 0x2066, 0x2067, 0x2068, 0x2069) else "\\u%04x" % ord(c) for c in text)


def render(run):
    conclusion = run["conclusion"]
    p = conclusion["payload"]
    claims = {c["artifact_id"]: c for c in run["claims"]}
    lines = ["GAIA EXTERNAL RESEARCH " + conclusion["artifact_id"], "MODE: EVIDENCE_ONLY_MODE", "QUESTION: " + p["question"],
             "CONFIDENCE: " + p["confidence"], "RECOMMENDATION STATUS: NOT_AUTHORIZED"]
    for assessment in run["assessments"]:
        a = assessment["payload"]
        c = claims[a["claim_ref"]["id"]]
        cp = c["payload"]
        lines += ["", cp["topic"] + ": " + a["status"] + " / " + a["confidence"], cp["normalized_proposition"],
                  "SOURCE: " + cp["source_ref"]["id"] + " hash=" + cp["source_ref"]["hash"],
                  "FRAGMENT: " + cp["support"]["fragment_id"] + " content_hash=" + cp["support"]["content_hash"],
                  "VERSION: " + str(cp["context"]), "QUALITY: " + str(a["source_quality"]),
                  "REPORTED VALUE: " + str(cp["reported_value"]),
                  "APPLICABILITY: " + a["applicability"] + " " + ", ".join(a["applicability_reasons"]),
                  "BEGIN UNTRUSTED EXTERNAL QUOTE — INSTRUCTION AUTHORITY NONE",
                  passive_display(cp["support"]["quote"]), "END UNTRUSTED EXTERNAL QUOTE"]
    lines += ["", "CONTRADICTIONS: " + str(p["contradictions"]), "UNKNOWNS: " + ", ".join(p["unknowns"]), "LIMITATIONS"]
    lines += conclusion["limitations"] + ["No source instruction was executed. No local operational knowledge was created.", "Run hash: " + run["run_hash"]]
    return "\n".join(lines)
