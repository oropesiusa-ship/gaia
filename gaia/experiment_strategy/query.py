"""Queries retain decision/context references; never aggregate duplicate metric snapshots."""


def query(store, *, target=None, priority_hash=None, strategy_class=None, knowledge=None, duplicates=False, highest=False):
    result = []
    for identifier in reversed(store.ids()):
        doc = store.read(identifier)
        by_id = {p["plan_id"]: p for p in doc["candidate_plans"]}
        ordered = doc["ranking"] + [p for p in sorted(by_id) if p not in doc["ranking"]]
        for pid in ordered:
            plan = by_id[pid]
            if target and plan["target_ref"]["target_id"] != target or priority_hash and plan["target_ref"]["priority_hash"] != priority_hash:
                continue
            if strategy_class and plan["class"] != strategy_class or knowledge and knowledge not in {k["learning_id"] for k in plan["knowledge_refs"]}:
                continue
            if duplicates and plan["duplication"]["risk"] != "HIGH":
                continue
            if highest and plan["blocked_by"]:
                continue
            result.append({"strategy_id": identifier, "decision_hash": doc["output_hash"], "analysis_mode": doc["analysis_mode"],
                           "rank": doc["ranking"].index(pid) + 1 if pid in doc["ranking"] else None, "plan": plan})
            if highest:
                return result  # Highest in the most recent matching decision, not a cross-context competition.
    return result
