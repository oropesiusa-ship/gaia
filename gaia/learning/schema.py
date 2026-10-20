"""Canonical contextual learning and portable, bounded source projections."""
from datetime import datetime
import json
import math
import re

from ..provenance import canonical_json, digest

LEARNING_SCHEMA = "gaia_experimental_learning_v1"
SOURCE_SCHEMA = "gaia_learning_sources_v1"
CLAIMS = {"OBSERVED_EFFECT", "PROMISING_DIRECTION", "REJECTED_DIRECTION", "STABLE_CONFIGURATION_FACT",
          "CONTEXT_DEPENDENT_EFFECT", "REPLICATED_EFFECT", "INCONCLUSIVE_RESULT"}
CONFIDENCE = ("VERY_LOW", "LOW", "MEDIUM", "HIGH")
REPLICATION = {"SINGLE_OBSERVATION", "SINGLE_EXPERIMENT", "REPEATED_WITHIN_EXPERIMENT", "REPLICATED_INDEPENDENTLY", "CONTRADICTED"}
HIERARCHY = ("OBSERVATION", "HYPOTHESIS", "EXPERIMENTAL_EVIDENCE", "REPLICATED_EVIDENCE", "OPERATIONAL_KNOWLEDGE")
HASH = re.compile(r"[a-f0-9]{64}")
CONTEXT_HASHES = ("environment_hash", "host_hash", "runtime_hash", "benchmark_hash", "source_hash")
CONTEXT_FIELDS = {*CONTEXT_HASHES, "workload", "trainer_family", "quality_threshold", "gaia_version", "baseline_version"}
HP = {"batch", "beta1", "beta2", "clip", "depth", "hidden", "horizon", "init_scale", "lr", "momentum", "warm", "wd", "sched"}
SLOTS = {"act": {"relu", "tanh", "gelu"}, "backward": {"naive", "fused", "inplace"}, "dtype": {"float32", "float64"},
         "optimizer": {"sgd", "momentum", "adam", "adam_inplace"}, "sampler": {"randint", "perm", "shuffle"}}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def independent_count(evidence):
    owners = {}
    for e in evidence:
        owners[e["measurement_hash"]] = min(owners.get(e["measurement_hash"], e["execution_hash"]), e["execution_hash"])
    return len(set(owners.values()))


def valid_context(value):
    if set(value) != CONTEXT_FIELDS or any(not isinstance(value[k], str) or not HASH.fullmatch(value[k]) for k in CONTEXT_HASHES):
        raise ValueError("Invalid context hashes")
    if value["workload"] != "numpy_mlp" or value["trainer_family"] != "numpy_mlp":
        raise ValueError("Unsupported ingestion domain/family")
    if not finite(value["quality_threshold"]) or not 0 <= value["quality_threshold"] <= 1:
        raise ValueError("Invalid quality threshold")
    if not re.fullmatch(r"gaia-v[0-9]+\.[0-9]+", value["gaia_version"]) or not re.fullmatch(r"v[0-9]{4,}", value["baseline_version"]):
        raise ValueError("Invalid version scope")


def valid_configuration(value):
    if set(value) != {"genome_hash", "code_variation_hash", "hp", "slots"} or any(not HASH.fullmatch(value[k]) for k in ("genome_hash", "code_variation_hash")):
        raise ValueError("Invalid configuration identity")
    if set(value["hp"]) != HP or set(value["slots"]) != set(SLOTS):
        raise ValueError("Incomplete configuration projection")
    for key, val in value["hp"].items():
        if key == "sched":
            if val not in ("const", "cosine"):
                raise ValueError("Unknown schedule")
        elif not finite(val):
            raise ValueError("Invalid hyperparameter")
    if value["hp"]["lr"] <= 0:
        raise ValueError("Invalid learning rate")
    if any(value["slots"][k] not in choices for k, choices in SLOTS.items()):
        raise ValueError("Unsupported slot")


def validate_source(value):
    if set(value) != {"schema", "provenance", "experiments", "source_hash"} or value["schema"] != SOURCE_SCHEMA:
        raise ValueError("Invalid learning source schema")
    if value["source_hash"] != digest({k: v for k, v in value.items() if k != "source_hash"}):
        raise ValueError("Source hash mismatch")
    provenance = value["provenance"]
    if set(provenance) != {"kind", "archive_aggregate", "projection_version"} or provenance["kind"] not in ("CURATED_CPU_ARCHIVE", "SYNTHETIC") or provenance["projection_version"] != "cpu_projection_v1":
        raise ValueError("Unknown provenance")
    if not HASH.fullmatch(provenance["archive_aggregate"]):
        raise ValueError("Invalid archive identity")
    if not value["experiments"]:
        raise ValueError("Empty source")
    for exp in value["experiments"]:
        expected = {"experiment_id", "execution_hash", "evidence_hash", "manifest_hash", "context", "candidate", "baseline",
                    "outcome", "screen", "confirmation", "versions", "promotion", "rollback", "ledger_refs", "artifacts", "finished_at"}
        if set(exp) != expected or not re.fullmatch(r"e[0-9]{5,}", exp["experiment_id"]):
            raise ValueError("Invalid experiment projection")
        for key in ("execution_hash", "evidence_hash", "manifest_hash"):
            if not HASH.fullmatch(exp[key]):
                raise ValueError("Invalid source evidence identity")
        valid_context(exp["context"])
        valid_configuration(exp["candidate"])
        valid_configuration(exp["baseline"])
        if exp["outcome"] not in ("ACCEPTED", "REJECTED", "INCONCLUSIVE"):
            raise ValueError("Invalid experimental outcome")
        if type(exp["promotion"]) is not bool or exp["rollback"] not in ("NONE", "VERIFICATION", "ADVERSE", "UNKNOWN"):
            raise ValueError("Invalid publication context")
        if any(not re.fullmatch(r"v[0-9]{4,}", v) for v in exp["versions"]):
            raise ValueError("Invalid source version")
        if datetime.fromisoformat(exp["finished_at"]).tzinfo is None:
            raise ValueError("Invalid source timestamp")
        screen = exp["screen"]
        if set(screen) != {"status", "reached", "cost_s", "baseline_cost_s"} or screen["status"] not in ("ok", "error", "invalid", "timeout") or type(screen["reached"]) is not bool:
            raise ValueError("Invalid screening projection")
        if any(v is not None and (not finite(v) or v <= 0) for v in (screen["cost_s"], screen["baseline_cost_s"])):
            raise ValueError("Invalid screening cost")
        confirmation = exp["confirmation"]
        if confirmation is not None:
            keys = {"pairs", "trial_count", "candidate_costs", "baseline_costs", "candidate_reached", "baseline_reached", "ratio", "upper95", "min_gain", "decision"}
            if set(confirmation) != keys or confirmation["decision"] not in ("accepted", "rejected", "deferred", "pareto_alternative"):
                raise ValueError("Invalid confirmation")
            n = confirmation["pairs"]
            trials = confirmation["trial_count"]
            if type(n) is not int or type(trials) is not int or not 0 <= n <= trials or any(type(confirmation[k]) is not int or not 0 <= confirmation[k] <= trials for k in ("candidate_reached", "baseline_reached")):
                raise ValueError("Invalid paired sample counts")
            if n > min(confirmation["candidate_reached"], confirmation["baseline_reached"]):
                raise ValueError("Valid cost pairs cannot exceed successful trials")
            if any(not isinstance(confirmation[k], list) or len(confirmation[k]) != n or any(not finite(x) or x <= 0 for x in confirmation[k]) for k in ("candidate_costs", "baseline_costs")):
                raise ValueError("Invalid confirmation samples")
            if not finite(confirmation["min_gain"]) or not 0 < confirmation["min_gain"] < 1:
                raise ValueError("Invalid confirmation threshold")
            for key in ("ratio", "upper95"):
                if confirmation[key] is not None and (not finite(confirmation[key]) or confirmation[key] <= 0):
                    raise ValueError("Invalid confirmation ratio")
            if confirmation["ratio"] is not None and confirmation["upper95"] is not None and confirmation["upper95"] + .00011 < confirmation["ratio"]:
                raise ValueError("Upper interval below observed ratio")
            if n >= 3:
                measured = math.exp(sum(math.log(b / a) for a, b in zip(confirmation["baseline_costs"], confirmation["candidate_costs"])) / n)
                if confirmation["ratio"] is None or abs(measured - confirmation["ratio"]) > 0.00011:
                    raise ValueError("Confirmation ratio inconsistent with paired samples")
            if exp["outcome"] == "ACCEPTED" and (n < 3 or confirmation["candidate_reached"] != trials or confirmation["decision"] != "accepted" or confirmation["upper95"] is None or confirmation["upper95"] >= 1 - confirmation["min_gain"]):
                raise ValueError("Accepted outcome lacks paired confirmation")
            if exp["outcome"] == "INCONCLUSIVE" and confirmation["decision"] not in ("deferred", "pareto_alternative"):
                raise ValueError("Inconclusive outcome is not rejected/success")
            if exp["outcome"] == "REJECTED" and confirmation["decision"] != "rejected":
                raise ValueError("Rejection cannot relabel accepted/inconclusive confirmation")
            adequate_quality = confirmation["candidate_reached"] >= max(confirmation["baseline_reached"], math.ceil(.8 * trials))
            if (confirmation["decision"] in ("deferred", "rejected") and n >= 3 and adequate_quality
                    and confirmation["upper95"] is not None and confirmation["upper95"] < 1 - confirmation["min_gain"]):
                raise ValueError("Recorded decision contradicts confirmation interval")
        elif exp["outcome"] == "ACCEPTED":
            raise ValueError("Acceptance without confirmation")
        if exp["promotion"] and exp["outcome"] != "ACCEPTED":
            raise ValueError("Promotion cannot turn inconclusive/rejected evidence into success")
        for ref in exp["artifacts"]:
            if set(ref) != {"path", "sha256"} or not re.fullmatch(r"(?:experiments/e[0-9]{5,}|stable/v[0-9]{4,})/(?:manifest|evidence|genome)\.json|benchmark\.json|ledger\.jsonl", ref["path"]) or not HASH.fullmatch(ref["sha256"]):
                raise ValueError("Invalid artifact reference")
        if any(not HASH.fullmatch(ref) for ref in exp["ledger_refs"]):
            raise ValueError("Invalid ledger reference")
        if not exp["artifacts"]:
            raise ValueError("Missing source artifacts")
    canonical_json(value)
    return value


def seal_source(value):
    result = json.loads(canonical_json(value))
    result["source_hash"] = digest({k: v for k, v in result.items() if k != "source_hash"})
    return validate_source(result)


def seal(value):
    result = json.loads(canonical_json(value))
    result["hash"] = digest({k: v for k, v in result.items() if k != "hash"})
    return validate(result)


def validate(value):
    required = {"learning_id", "schema", "kind", "source_experiments", "source_versions", "source_evidence_hashes", "domain", "component",
                "claim", "claim_type", "applicability", "supporting_evidence", "contradictory_evidence", "confidence", "replication_status",
                "status", "limitations", "created_at", "supersedes", "superseded_by", "quality", "hierarchy", "hash"}
    if set(value) != required or value["schema"] != LEARNING_SCHEMA or value["kind"] not in ("record", "knowledge"):
        raise ValueError("Invalid learning schema")
    prefix = "l" if value["kind"] == "record" else "k"
    if not re.fullmatch(prefix + r"[a-f0-9]{24}", value["learning_id"]):
        raise ValueError("Invalid learning id")
    if value["claim_type"] not in CLAIMS or value["confidence"] not in CONFIDENCE or value["replication_status"] not in REPLICATION:
        raise ValueError("Invalid learning interpretation")
    if value["hierarchy"] not in HIERARCHY or value["status"] not in ("ACTIVE", "CONTRADICTED", "OPERATIONAL_KNOWLEDGE"):
        raise ValueError("Invalid hierarchy/status")
    if value["domain"] != "CPU_NUMPY_MLP" or value["component"] != "cpu_evolution":
        raise ValueError("Unsupported learning scope")
    valid_context(value["applicability"])
    if datetime.fromisoformat(value["created_at"]).tzinfo is None or not value["limitations"]:
        raise ValueError("Missing timestamp/limitations")
    q = value["quality"]
    supporting = value["supporting_evidence"]
    if not supporting:
        raise ValueError("Learning requires source evidence")
    for evidence in supporting:
        if (not re.fullmatch(r"e[0-9]{5,}", evidence["experiment_id"])
                or any(not HASH.fullmatch(evidence[k]) for k in ("evidence_hash", "execution_hash", "experiment_identity", "measurement_hash", "manifest_hash"))):
            raise ValueError("Invalid experimental evidence reference")
        expected = digest({"experiment": evidence["experiment_identity"], "measurements": evidence["confirmation"] if evidence["confirmation"] is not None else evidence["screen"]})
        if evidence["measurement_hash"] != expected:
            raise ValueError("Measurement identity mismatch")
    hashes = sorted({e["evidence_hash"] for e in supporting})
    if (value["source_evidence_hashes"] != hashes or q["evidence_count"] != len(hashes)
            or q["independent_evidence_count"] != independent_count(supporting)
            or q["contradictions_count"] != len(value["contradictory_evidence"])
            or any(e not in supporting for e in value["contradictory_evidence"])):
        raise ValueError("Invalid evidence accounting")
    positive = independent_count([e for e in supporting if e["outcome"] == "ACCEPTED"])
    if value["kind"] == "knowledge" and q["independent_positive_count"] != positive:
        raise ValueError("Invalid positive evidence accounting")
    if any(not re.fullmatch(r"k[a-f0-9]{24}", ref) or ref == value["learning_id"] for ref in value["supersedes"] + value["superseded_by"]):
        raise ValueError("Invalid supersession reference")
    replicated = value["replication_status"] == "REPLICATED_INDEPENDENTLY"
    if (value["claim_type"] == "REPLICATED_EFFECT" or value["hierarchy"] in ("REPLICATED_EVIDENCE", "OPERATIONAL_KNOWLEDGE")) and (not replicated or positive < 2 or value["kind"] != "knowledge" or value["claim"]["subject"] != "EXACT_CONFIGURATION"):
        raise ValueError("Replication requires independent experiments")
    if value["confidence"] == "HIGH" and (q["independent_evidence_count"] < 2 or value["contradictory_evidence"]):
        raise ValueError("HIGH requires independent uncontradicted evidence")
    if HIERARCHY.index(value["hierarchy"]) < HIERARCHY.index("EXPERIMENTAL_EVIDENCE"):
        raise ValueError("Experimental learning cannot be downgraded to untested observations")
    if value["status"] == "OPERATIONAL_KNOWLEDGE" and (value["hierarchy"] != "OPERATIONAL_KNOWLEDGE" or value["confidence"] != "HIGH"):
        raise ValueError("Invalid operational knowledge")
    if value["contradictory_evidence"] and (value["status"] != "CONTRADICTED" or value["replication_status"] != "CONTRADICTED"):
        raise ValueError("Contradiction must remain explicit")
    if value["hash"] != digest({k: v for k, v in value.items() if k != "hash"}):
        raise ValueError("Learning hash mismatch")
    canonical_json(value)
    return value
