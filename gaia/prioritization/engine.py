"""Pure interpretation of saved diagnostic outputs; no collection or execution."""
from datetime import datetime, timezone
import re
import time

from ..diagnosis.schema import validate as validate_diagnosis
from ..provenance import digest
from . import VERSION
from .policy import RULES, VERSION as POLICY_VERSION, decide, ordering, settings
from .schema import PRIORITY_SCHEMA, seal
from .targets import candidates


def validate_input(document):
    try:
        validate_diagnosis(document)
        if document["outcome"] != "ISSUES_DETECTED" and document["issues"]:
            raise ValueError("Inconsistent diagnosis outcome")
        for ref in document["source_observations"]:
            if (ref["role"] not in ("current", "baseline") or not re.fullmatch(r"o[0-9]{6,}", ref["observation_id"])
                    or any(not re.fullmatch(r"[a-f0-9]{64}", ref[k]) for k in ("observation_hash", "environment_hash", "source_hash"))):
                raise ValueError("Invalid observation identity reference")
        for issue in document["issues"]:
            if not re.fullmatch(r"i[0-9]{4,}", issue["issue_id"]):
                raise ValueError("Invalid issue id")
            for hid in issue["hypothesis_ids"]:
                if not re.fullmatch(r"h[0-9]{4,}", hid):
                    raise ValueError("Invalid hypothesis id")
                hypothesis = next(h for h in document["hypotheses"] if h["hypothesis_id"] == hid)
                if hypothesis["issue_id"] != issue["issue_id"]:
                    raise ValueError("Inconsistent issue/hypothesis graph")
        for entry in document["evidence"]:
            if not re.fullmatch(r"e[0-9]{4,}", entry["evidence_id"]):
                raise ValueError("Invalid evidence id")
        return document
    except (KeyError, AttributeError, TypeError, StopIteration) as exc:
        raise ValueError("Invalid diagnosis input") from exc


def prioritize(diagnoses, configuration=None, prioritization_id="p000001"):
    start = time.perf_counter()
    if not diagnoses:
        raise ValueError("Explicit diagnosis input required")
    unique = {validate_input(d)["diagnosis_hash"]: d for d in diagnoses}
    inputs = [unique[k] for k in sorted(unique)]
    cfg = settings(configuration)
    targets, exclusions = candidates(inputs, cfg)
    for t in targets:
        t["priority"], t["rule_ids"], t["reasons"] = decide(t["dimensions"], t["blocked_by"], cfg)
    observations = {digest(ref): ref for d in inputs for ref in d["source_observations"]}
    observations = {digest({k: ref[k] for k in ("role", "observation_id", "observation_hash", "environment_hash", "source_hash")}):
                    {k: ref[k] for k in ("role", "observation_id", "observation_hash", "environment_hash", "source_hash")}
                    for ref in observations.values()}
    value = {"prioritization_id": prioritization_id, "schema": PRIORITY_SCHEMA, "timestamp": datetime.now(timezone.utc).isoformat(),
             "source_diagnoses": [{"diagnosis_id": d["diagnosis_id"], "diagnosis_hash": d["diagnosis_hash"], "outcome": d["outcome"]} for d in inputs],
             "source_observations": [observations[k] for k in sorted(observations)],
             "candidate_targets": targets, "ordering": [t["target_id"] for t in ordering(targets)], "exclusions": exclusions,
             "blockers": {t["target_id"]: t["blocked_by"] for t in targets if t["blocked_by"]},
             "rationale": "Research attention only. Ordinal tiers and lexicographic dimensions, not solution recommendations.",
             "limitations": ["Priority is not a solution or an experiment design.",
                             "Impact is observed issue magnitude or UNKNOWN; costs, risk and reversibility are conceptual profiles, not measurements.",
                             "Low-confidence targets acquire evidence; diagnosis is not proof of causality.",
                             "No data collection, workload, configuration change or evolution action is authorized.",
                             "Grouping is by target class/component; historical inputs may describe different environments. Inspect all source references.",
                             "Hashes validate saved diagnostic integrity, not truth or authenticity against a hostile producer."],
             "policy": {"version": POLICY_VERSION, "interpreter_version": VERSION, "settings": cfg,
                        "hash": digest({"version": POLICY_VERSION, "settings": cfg, "rules": RULES}), "rules_evaluated": list(RULES)},
             "cost": {"duration_s": time.perf_counter() - start, "diagnoses_processed": len(inputs),
                      "targets_generated": len(targets), "rules_evaluated": len(RULES) * len(targets)}}
    return seal(value)
