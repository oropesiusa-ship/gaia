"""Explicit, deterministic history interpretation. Never executes an experiment."""
import time
from ..provenance import digest
from .consolidation import consolidate
from .records import experiment_identity, measurement_identity, make_record
from . import VERSION
from .schema import HIERARCHY, validate_source

DEFAULTS = {"minimum_evidence_for_consolidation": 1, "minimum_independent_replications": 2,
            "stale_on_runtime_change": True, "stale_on_hardware_change": True,
            "contradiction_confidence_penalty": 1, "higher_lr_factor": 1.10}


def settings(configuration=None):
    supplied = (configuration or {}).get("learning", {})
    if set(supplied) - DEFAULTS.keys():
        raise ValueError("Unknown learning config")
    cfg = {**DEFAULTS, **supplied}
    for key in ("minimum_evidence_for_consolidation", "minimum_independent_replications", "contradiction_confidence_penalty"):
        lower = 2 if key == "minimum_independent_replications" else 1
        if type(cfg[key]) is not int or not lower <= cfg[key] <= 10:
            raise ValueError("Invalid learning evidence threshold")
    for key in ("stale_on_runtime_change", "stale_on_hardware_change"):
        if type(cfg[key]) is not bool:
            raise ValueError("Invalid staleness policy")
    if type(cfg["higher_lr_factor"]) not in (int, float) or not 1 < cfg["higher_lr_factor"] <= 2:
        raise ValueError("Invalid direction threshold")
    return cfg


def learn(sources, configuration=None):
    start = time.perf_counter()
    cfg = settings(configuration)
    sources = {validate_source(s)["source_hash"]: s for s in sources}
    if not sources:
        raise ValueError("Explicit experimental sources required")
    experiments, duplicates, comparisons = {}, [], []
    for sh in sorted(sources):
        for exp in sources[sh]["experiments"]:
            key = exp["evidence_hash"]
            if key in experiments:
                if experiments[key] != exp:
                    raise ValueError("Same evidence hash with different projection")
                duplicates.append({"kind": "EXACT_DUPLICATE", "evidence_hash": key, "counted_independently": False})
            else:
                experiments[key] = exp
    ordered = [experiments[k] for k in sorted(experiments)]
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if experiment_identity(a) == experiment_identity(b):
                independent = a["execution_hash"] != b["execution_hash"] and measurement_identity(a) != measurement_identity(b)
                kind = "EXACT_MEASUREMENT_DUPLICATE" if measurement_identity(a) == measurement_identity(b) else "INDEPENDENT_REPLICATION" if independent else "EXACT_CONFIGURATION_REPEAT"
            elif a["context"] == b["context"] and a["candidate"]["slots"] == b["candidate"]["slots"]:
                kind, independent = "NEAR_DUPLICATE", False
            else:
                continue
            comparisons.append({"a": a["evidence_hash"], "b": b["evidence_hash"], "kind": kind, "counted_independently": independent})
    records = [make_record(exp, cfg) for exp in ordered]
    knowledge = consolidate(records, cfg)
    relations = []
    for k in knowledge:
        for ref in k["claim"]["record_refs"]:
            record = next(r for r in records if r["learning_id"] == ref)
            relation = "contradicts" if record["source_evidence_hashes"][0] in {e["evidence_hash"] for e in k["contradictory_evidence"]} else "supports"
            relations.append({"from": ref, "to": k["learning_id"], "relation": relation})
    result = {"schema": "gaia_learning_run_v1", "interpreter_version": VERSION, "evidence_hierarchy": list(HIERARCHY),
              "source_hashes": sorted(sources), "settings": cfg, "records": records,
              "knowledge": knowledge, "relations": relations, "duplicates": duplicates, "experiment_comparisons": comparisons,
              "cost": {"duration_s": time.perf_counter() - start, "records_processed": len(records), "knowledge_items_generated": len(knowledge)}}
    result["run_hash"] = digest({k: v for k, v in result.items() if k != "run_hash"})
    return result
