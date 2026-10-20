"""Filtered knowledge views and append-only relation overlays; no automatic policy adoption."""
from .applicability import assess
from .schema import CLAIMS, CONFIDENCE


def query(store, *, component=None, workload=None, environment=None, claim_type=None, minimum_confidence="VERY_LOW",
          context=None, transferability=None, include_stale=False, include_superseded=False, replicated_only=False):
    if not any((component, workload, environment, claim_type, context, transferability, replicated_only)):
        raise ValueError("Query requires an explicit relevance filter")
    if minimum_confidence not in CONFIDENCE or claim_type is not None and claim_type not in CLAIMS:
        raise ValueError("Invalid query filter")
    if transferability is not None and transferability not in ("EXACT_CONTEXT", "SAME_WORKLOAD", "RELATED_CONTEXT", "UNKNOWN_TRANSFER", "NOT_TRANSFERABLE"):
        raise ValueError("Invalid transferability filter")
    batches = store.batches()
    settings = batches[-1]["run"]["settings"] if batches else {}
    relations = [r for b in batches for r in b["run"]["relations"]]
    result = []
    for item in store.items("knowledge"):
        superseded = sorted({r["to"] for r in relations if r["relation"] == "superseded_by" and r["from"] == item["learning_id"]})
        weakened = sorted({r["from"] for r in relations if r["relation"] in ("weakens", "contradicts") and r["to"] == item["learning_id"]})
        if superseded and not include_superseded:
            continue
        if component and item["component"] != component or workload and item["applicability"]["workload"] != workload:
            continue
        if environment and item["applicability"]["environment_hash"] != environment or claim_type and item["claim_type"] != claim_type:
            continue
        effective_confidence = CONFIDENCE[max(0, CONFIDENCE.index(item["confidence"]) - settings.get("contradiction_confidence_penalty", 1))] if weakened else item["confidence"]
        if CONFIDENCE.index(effective_confidence) < CONFIDENCE.index(minimum_confidence):
            continue
        if replicated_only and (weakened or item["replication_status"] != "REPLICATED_INDEPENDENTLY"):
            continue
        applicability = assess(item["applicability"], context, settings)
        if applicability["status"] == "STALE" and not include_stale:
            continue
        if transferability and applicability["transferability"] != transferability:
            continue
        # A contradicted old item must never remain operational merely because its bytes are immutable.
        effective = "SUPERSEDED" if superseded else "CONTRADICTED" if weakened else item["status"]
        result.append({"item": item, "applicability_assessment": applicability, "effective_status": effective,
                       "effective_confidence": effective_confidence,
                       "effective_superseded_by": superseded, "weakened_by": weakened,
                       "usable_as_operational_knowledge": item["status"] == "OPERATIONAL_KNOWLEDGE" and not superseded and not weakened and applicability["status"] == "APPLICABLE"})
    return sorted(result, key=lambda r: r["item"]["learning_id"])
