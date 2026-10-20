"""Append-only relations: old payloads are never rewritten to add backlinks."""
from ..provenance import digest
from .schema import CONFIDENCE, seal


def with_history(run, previous_knowledge=()):
    previous = {k["learning_id"]: k for k in previous_knowledge}
    result = {**run, "knowledge": [], "relations": list(run["relations"])}
    for item in run["knowledge"]:
        links = []
        for old in previous.values():
            if old["learning_id"] == item["learning_id"] or old["claim"]["group_key"] != item["claim"]["group_key"]:
                continue
            if not set(old["source_evidence_hashes"]) < set(item["source_evidence_hashes"]):
                continue
            if item["contradictory_evidence"]:
                strong = any(e["rollback"] == "ADVERSE" or e["outcome"] == "REJECTED" and e["confirmation"] and e["confirmation"]["pairs"] >= 3
                             for e in item["contradictory_evidence"])
                relation = "contradicts" if strong else "weakens"
                result["relations"].append({"from": item["learning_id"], "to": old["learning_id"], "relation": relation})
            elif (CONFIDENCE.index(item["confidence"]) > CONFIDENCE.index(old["confidence"])
                  or item["quality"]["independent_evidence_count"] > old["quality"]["independent_evidence_count"]):
                links.append(old["learning_id"])
                result["relations"].append({"from": item["learning_id"], "to": old["learning_id"], "relation": "supersedes"})
                result["relations"].append({"from": old["learning_id"], "to": item["learning_id"], "relation": "superseded_by"})
            else:
                result["relations"].append({"from": item["learning_id"], "to": old["learning_id"], "relation": "supports"})
        result["knowledge"].append(seal({**item, "supersedes": sorted(links)}))
    result["relations"] = sorted({digest(r): r for r in result["relations"]}.values(), key=lambda r: (r["from"], r["to"], r["relation"]))
    result["run_hash"] = digest({k: v for k, v in result.items() if k != "run_hash"})
    return result
