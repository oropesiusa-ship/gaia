"""CPU publication rules. Filesystem commit mechanics are in atomic_publish."""
import hashlib
import json
import math
import os
from pathlib import Path

from . import genome as G, manifest, stats

ARTIFACTS = {"trainer.py", "genome.json", "manifest.json", "evidence.json"}


def genome_bytes(genome):
    # G.render embeds repr(HP). Keep insertion order when persisting the genome
    # so a reload renders byte-identical source. Identity hashes stay canonical.
    return json.dumps(genome, indent=1, ensure_ascii=True).encode()


def _hash_source(source):
    return hashlib.sha256(source.encode()).hexdigest()


def confirmation(baseline, experiment, execution):
    """Recompute the existing paired decision from complete, ordered raw trials."""
    if execution["decision"] != "accepted" or execution["promotable"] is not True:
        raise ValueError("Experiment is not accepted/promotable")
    cfg = baseline["effective_config"]
    seeds = cfg["actual_confirmation_seeds"]
    n = len(seeds)
    trials = execution["trial_metrics"]
    if n < 3 or len(trials) not in (1 + 2 * n, 1 + 4 * n):
        raise ValueError("Incomplete confirmation trial set")
    candidate_hash = experiment["candidate_trainer_hash"]
    parent_hash = experiment["parent_trainer_hash"]
    screen_seed = cfg["benchmark"]["tiers"]["screen"][0]
    expected = [(candidate_hash, screen_seed)]
    for offset, group in enumerate((seeds, cfg["extended_confirmation_seeds"])):
        if offset and len(trials) == 1 + 2 * n:
            break
        for index, seed in enumerate(group):
            order = (candidate_hash, parent_hash) if (index + offset) % 2 else (parent_hash, candidate_hash)
            expected.extend((source, seed) for source in order)
    groups = {"parent": [], "candidate": []}
    target = cfg["benchmark"]["calibrated"]["main"]["target"]
    for index, (trial, (source, seed)) in enumerate(zip(trials, expected)):
        result = trial["result"]
        proof = result["sandbox_evidence"]
        if (trial["campaign_id"] != experiment["campaign_id"] or trial["environment_hash"] != experiment["environment_hash"] or
                trial["stable_version"] != experiment["parent_version"] or trial["source_sha"] != candidate_hash or
                trial["trainer_hash"] != source or trial["data_seed"] != seed or trial["init_seed"] != seed or
                trial["task"] != "main" or result["status"] != "ok" or result["reached"] is not True or
                result["sandbox"] is not True or result["sandbox_validation"] is not True or
                result["sandbox_backend"] != "bwrap" or result["promotable"] is not True or
                result.get("reason") in ("SANDBOX_UNAVAILABLE", "SANDBOX_VIOLATION")):
            raise ValueError("Invalid trial source/seed/order/quality/sandbox")
        if (proof["validated"] is not True or not proof["checks"] or not all(proof["checks"].values()) or
                not set(("user", "pid", "net", "ipc", "uts", "rlimits", "environment", "bundle_hashes",
                         "parent_observed_namespaces", "outside_write_denied", "bundle_read_only")).issubset(proof["checks"]) or
                proof["candidate_sha256"] != source or proof["bundle_hashes"]["trainer.py"] != source or
                proof["worker_sha256"] != baseline["runtime"]["worker_sha256"] or
                proof["backend"] != "bwrap" or
                proof["active_limits"] != baseline["sandbox"]["policy"]["rlimits"] or
                proof["filesystem_policy"] != baseline["sandbox"]["policy"]["filesystem"] or
                proof["handshake"]["environment"] != baseline["runtime"]["deterministic_environment"] or
                proof["handshake"]["limits"] != baseline["sandbox"]["policy"]["rlimits"] or
                proof["handshake"]["bundle_hashes"] != proof["bundle_hashes"] or
                proof["handshake"]["home"] != "/work" or proof["handshake"]["tmpdir"] != "/tmp" or
                proof["handshake"]["cwd"] != "/work" or proof["handshake"]["parent_loopback_unreachable"] is not True or
                any(proof["handshake"][key] is not True for key in ("work_writable", "outside_write_denied", "bundle_read_only", "runtime_read_only"))):
            raise ValueError("Trial sandbox evidence does not match certified policy")
        for name, value in baseline["runtime"]["runtime_bundle"].items():
            if proof["bundle_hashes"].get(name) != value:
                raise ValueError("Trial worker/runtime bundle mismatch")
        if proof["bundle_sha256"] != hashlib.sha256(json.dumps(proof["bundle_hashes"], sort_keys=True).encode()).hexdigest():
            raise ValueError("Trial bundle hash mismatch")
        for field in ("cost_s", "peak_rss_mb", "final_acc"):
            value = result[field]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError("Non-finite/missing trial metric: " + field)
        if (result["cost_s"] <= 0 or not 0 < result["peak_rss_mb"] <= cfg["limits"]["max_ram_mb"] or
                not target <= result["final_acc"] <= 1):
            raise ValueError("Trial fails quality/resource limits")
        if index:
            # Use sequence positions, not hashes: a malformed identical source
            # must not merge candidate and parent groups.
            pair_index = index - 1
            offset, within = divmod(pair_index, 2 * n)
            pair, position = divmod(within, 2)
            candidate_first = (pair + offset) % 2 == 1
            who = "candidate" if (position == 0) == candidate_first else "parent"
            groups[who].append(result)
    first = stats.decide(groups["parent"][:n], groups["candidate"][:n], cfg["acceptance"])
    if len(trials) == 1 + 4 * n:
        if first["decision"] != "deferred":
            raise ValueError("Extended confirmation without deferred first stage")
        decision = stats.decide(groups["parent"], groups["candidate"], cfg["acceptance"])
        decision["extended"] = True
    else:
        decision = first
    decision.update(champ_costs=[r["cost_s"] for r in groups["parent"]],
                    cand_costs=[r["cost_s"] for r in groups["candidate"]])
    if decision["decision"] != "accepted" or execution["confirm"] != decision:
        raise ValueError("Stored decision differs from recomputed paired acceptance")
    return decision


def validate_candidate(eng, genome, source, provided, *, _preparing=False):
    from .ledger import verify_ledger
    ledger = verify_ledger(eng.store)
    if not ledger["ok"]:
        raise ValueError("LEDGER_INVALID: " + str(ledger["errors"]))
    if source != G.render(genome):
        raise ValueError("Trainer does not equal G.render(genome)")
    path = manifest._state_path(eng.store.dir, provided["experiment_manifest_path"])
    checked = manifest.validate_manifest(eng, path, expected_hash=provided["experiment_manifest_hash"],
                                         require_current_parent=True)
    if not checked["ok"]:
        raise ValueError("; ".join(checked["errors"]))
    experiment, baseline = checked["experiment"], checked["baseline"]
    if any(provided.get(k) != v for k, v in manifest.provenance.purpose_metadata(baseline).items()):
        raise ValueError("Certification promotion purpose mismatch")
    if any(r["event_type"] == "version_promoted" and r["payload"].get("experiment_id") == experiment["experiment_id"]
           for r in ledger["records"]):
        raise ValueError("Experiment already has a certified promotion")
    if (manifest.digest(genome) != experiment["candidate_genome_hash"] or
            _hash_source(source) != experiment["candidate_trainer_hash"] or provided["experiment"] != experiment["experiment_id"]):
        raise ValueError("Candidate belongs to another experiment")
    for key in ("environment_hash", *manifest.HASHES):
        if provided[key] != baseline[key]:
            raise ValueError("Promotion identity mismatch: " + key)
    if provided["baseline_manifest_hash"] != baseline["manifest_hash"]:
        raise ValueError("Promotion baseline manifest mismatch")
    if provided["source_snapshot"] != baseline["source"]["snapshot"]:
        raise ValueError("Promotion snapshot mismatch")
    evidence_path = manifest._state_path(eng.store.dir, provided["experiment_evidence_path"])
    if evidence_path != path.with_name("evidence.json"):
        raise ValueError("Experiment evidence path mismatch")
    execution = manifest._execution_evidence(evidence_path, experiment, baseline)
    if provided["experiment_evidence_hash"] != execution["evidence_hash"]:
        raise ValueError("Promotion experiment evidence hash mismatch")
    decision = confirmation(baseline, experiment, execution)
    if not any(r["event_type"] == "candidate_accepted" and r["payload"].get("id") == experiment["experiment_id"]
               for r in ledger["records"]):
        raise ValueError("Publication requires candidate_accepted in verified ledger")
    from . import readiness
    gates = readiness.validate_report(eng, experiment, genome_hash=manifest.digest(genome), trainer_hash=_hash_source(source),
                                      parent=experiment["parent_version"])
    if not gates["ok"]:
        raise ValueError(str(gates["errors"]))
    if not _preparing:
        readiness.validate_pre_promotion(eng, provided, experiment, execution)
    return baseline, experiment, execution, decision


def artifacts(eng, version, genome, source, provided):
    baseline, experiment, execution, decision = validate_candidate(eng, genome, source, provided)
    timestamp = manifest.timestamp()
    evidence = {**provided, "type": "promotion", "version": version, "parent_version": experiment["parent_version"],
                **manifest.provenance.purpose_metadata(baseline),
                "execution_id": experiment["execution_id"],
                "promoted_from": experiment["experiment_id"], "experiment_id": experiment["experiment_id"],
                "decision": "accepted", "confirm": decision, "timestamp": timestamp,
                "trainer_hash": _hash_source(source), "genome_hash": manifest.digest(genome)}
    # No circular hashes: manifest seals the evidence payload; evidence then
    # references the sealed manifest. Both definitions are checked on load.
    evidence.pop("manifest_hash", None)
    evidence.pop("evidence_hash", None)
    evidence_hash = manifest.digest(evidence)
    document = manifest.seal({"manifest_schema": manifest.MANIFEST_SCHEMA, "kind": "stable", "version": version,
                              **manifest.provenance.purpose_metadata(baseline),
                              "parent_version": experiment["parent_version"], "experiment_id": experiment["experiment_id"],
                              "parent_manifest_hash": manifest._document(eng.store.stable / experiment["parent_version"] / "manifest.json")["manifest_hash"],
                              "created_at": timestamp, "execution_id": experiment["execution_id"],
                              "baseline_version": "v0000", "baseline_manifest_hash": baseline["manifest_hash"],
                              **{key: baseline[key] for key in ("environment_hash", *manifest.HASHES)},
                              "source_snapshot": baseline["source"]["snapshot"],
                              "effective_config_hash": baseline["config_hash"],
                              "candidate_trainer_hash": experiment["candidate_trainer_hash"],
                              "candidate_genome_hash": experiment["candidate_genome_hash"],
                              "experiment_manifest_path": provided["experiment_manifest_path"],
                              "experiment_manifest_hash": experiment["manifest_hash"],
                              "experiment_evidence_path": provided["experiment_evidence_path"],
                              "experiment_evidence_hash": execution["evidence_hash"], "evidence_hash": evidence_hash})
    if experiment.get("proposal_trace_path"):
        document = manifest.seal({**document, **{key: experiment[key] for key in (
            "proposal_trace_path", "proposal_trace_hash", "candidate_origin")}})
    document = manifest.seal({**document, "pre_promotion_path": provided["pre_promotion_path"],
                              "pre_promotion_hash": provided["pre_promotion_hash"],
                              "campaign_id": experiment["campaign_id"], "gate_report_hash": experiment["gate_report_hash"]})
    evidence.update(manifest_hash=document["manifest_hash"], evidence_hash=evidence_hash)
    return {"trainer.py": source.encode(), "genome.json": genome_bytes(genome),
            "manifest.json": manifest.canonical_json(document), "evidence.json": manifest.canonical_json(evidence)}


def durable_references(eng, provided=None):
    from .atomic_publish import fsync_directory, sync_tree
    for name in ("state.json", "benchmark.json"):
        with (eng.store.dir / name).open("rb") as stream:
            os.fsync(stream.fileno())
    sync_tree(eng.store.dir / "provenance")
    if provided is not None:
        path = manifest._state_path(eng.store.dir, provided["experiment_manifest_path"]).parent
        sync_tree(path)
        fsync_directory(path.parent)
        experiment = manifest._document(path / "manifest.json")
        if experiment.get("proposal_trace_path"):
            trace_path = manifest._state_path(eng.store.dir, experiment["proposal_trace_path"])
            with trace_path.open("rb") as stream:
                os.fsync(stream.fileno())
            fsync_directory(trace_path.parent)
        gates = manifest._state_path(eng.store.dir, experiment["gate_report_path"]).parent
        sync_tree(gates)
        fsync_directory(gates.parent)
    fsync_directory(eng.store.dir)
