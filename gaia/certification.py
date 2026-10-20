"""Prueba A: real CPU pipeline, controlled genome, isolated non-autonomous state.

There is no alternate evaluator, decision function, gate or publication path.
The chosen pair was probed on the unchanged hard workload: default SGD/float64
versus known Adam/float32/fused with one hidden layer. Selection is controlled,
not a discovery, search result, or certification of autonomous improvement.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import uuid

from . import config, engine, genome as G, ledger, manifest, provenance, publication, readiness
from .atomic_publish import fsync_directory

SCHEMA = "cpu_pipeline_certification_v1"
PREFIX = "state_certification_cpu_"
ROLLBACK_REASON = "Pipeline certification rollback"
PHASES = ("baseline_created", "gates_passed", "screening_passed", "confirmation_accepted", "pre_promotion_passed",
          "version_published", "promoted_current_verified", "promoted_version_loaded", "rollback_completed",
          "final_current_verified", "ledger_verified", "versions_immutable", "final_readiness_passed")


def controlled_pair():
    return (G.new_genome(), G.new_genome(hp={"lr": .003, "depth": 1},
            slots={"optimizer": "adam", "dtype": "float32", "backward": "fused"}))


def new_configuration(root):
    """A fresh namespace on every invocation; never read a productive gaia.json."""
    root = Path(root).resolve()
    name = PREFIX + uuid.uuid4().hex
    (root / name).mkdir(exist_ok=False)
    fsync_directory(root)
    cfg = copy.deepcopy(config.DEFAULTS)
    cfg["workload"]["state_dir"] = name
    cfg["certification_only"] = True
    cfg.update(provenance.certification_metadata(cfg))
    cfg["meta"]["enabled"] = False
    cfg["research"]["enabled"] = False
    # No changes to profile, quality, seeds, thresholds, memory or trial caps.
    return cfg


def version_hashes(store):
    if store.versions() != ["v0000", "v0001"]:
        raise ValueError("Prueba A requires exactly v0000 and v0001")
    return {f"stable/{name}/{artifact}": manifest.file_hash(store.stable / name / artifact)
            for name in store.versions() for artifact in sorted(publication.ARTIFACTS)}


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _write_report(path, value):
    value = json.loads(provenance.canonical_json(value))
    value["report_hash"] = provenance.digest({k: v for k, v in value.items() if k != "report_hash"})
    with Path(path).open("xb") as stream:
        stream.write(provenance.canonical_json(value))
        stream.flush()
        os.fchmod(stream.fileno(), 0o444)
        os.fsync(stream.fileno())
    fsync_directory(Path(path).parent)
    return value


def validate_report(eng, path):
    """Validate immutable A results, not the autonomous MVP or a new experiment."""
    result = {"ok": False, "errors": []}
    try:
        doc = path if isinstance(path, dict) else json.loads(Path(path).read_bytes())
        purpose = provenance.certification_metadata(eng.cfg)
        _require(bool(purpose) and all(doc.get(k) == v for k, v in purpose.items()), "Certification purpose missing/changed")
        _require(doc["certification_schema"] == SCHEMA and doc["autonomous_self_improvement_certified"] is False,
                 "Prueba A cannot certify autonomous improvement")
        _require(doc["report_hash"] == provenance.digest({k: v for k, v in doc.items() if k != "report_hash"}), "Certification report hash mismatch")
        _require(doc["overall_status"] in ("PASS", "FAIL", "BLOCKED"), "Invalid certification result")
        _require(type(doc["pipeline_certified"]) is bool and doc["state_id"] == eng.store.dir.name and
                 doc["state_path"] == str(eng.store.dir.resolve()) and eng.store.dir.name.startswith(PREFIX),
                 "Invalid certification state/result identity")
        if doc["pipeline_certified"] is not True:
            _require(doc["overall_status"] != "PASS", "Incomplete certification cannot be PASS")
            return {"ok": True, "errors": [], "report": doc}
        _require(doc["overall_status"] == "PASS" and set(doc["phases"]) == set(PHASES) and all(v is True for v in doc["phases"].values()),
                 "Incomplete certification phases")
        checked = ledger.verify_ledger(eng.store)
        _require(checked["ok"] and checked["last_hash"] == doc["ledger_head"], "Certification ledger mismatch")
        records = checked["records"]
        _require(len(records) == doc["ledger_records"], "Certification ledger record count mismatch")
        _require(all(r.get("certification") is True and r["payload"].get("candidate_origin") == "certification_controlled" for r in records),
                 "Certification ledger contains mixed autonomous origins")
        _require(eng.store.current_version() == doc["final_current"] == "v0000", "Certification final CURRENT mismatch")
        _require(version_hashes(eng.store) == doc["version_hashes_before_rollback"] == doc["version_hashes_after_rollback"],
                 "Certification stable artifacts changed")
        for relative, digest in doc["artifact_hashes"].items():
            _require(manifest.file_hash(manifest._state_path(eng.store.dir, relative)) == digest, "Certification artifact changed: " + relative)
        candidate = controlled_pair()[1]
        trainer_hash = hashlib.sha256(G.render(candidate).encode()).hexdigest()
        _require(doc["candidate_genome_hash"] == provenance.digest(candidate) and doc["candidate_trainer_hash"] == trainer_hash,
                 "Certification candidate identity mismatch")
        experiment = manifest._document(eng.store.dir / "experiments/e00001/manifest.json")
        _require(experiment["candidate_origin"] == "certification_controlled" and experiment["certification"] is True,
                 "Candidate was not labeled controlled")
        baseline = manifest._document(eng.store.stable / "v0000/manifest.json")
        _require(doc["baseline_version"] == "v0000" and doc["baseline_genome"] == controlled_pair()[0] and
                 doc["baseline_manifest_hash"] == baseline["manifest_hash"] and doc["source_snapshot"] == baseline["source"]["snapshot"] and
                 doc["environment_hash"] == baseline["environment_hash"] and
                 doc["benchmark_summary"] == baseline["effective_config"]["benchmark"]["calibrated"],
                 "Certification baseline/environment summary mismatch")
        execution = manifest._execution_evidence(eng.store.dir / "experiments/e00001/evidence.json", experiment, baseline)
        decision = publication.confirmation(baseline, experiment, execution)
        _require(decision == doc["confirmation"] and decision["decision"] == "accepted", "Certification confirmation not accepted")
        _require(doc["improvement_observed_percent"] == round((1 - decision["ratio"]) * 100, 4), "Certification improvement summary mismatch")
        gates = readiness.validate_report(eng, experiment, genome_hash=doc["candidate_genome_hash"],
                    trainer_hash=trainer_hash, parent="v0000", compare_current=False)
        _require(gates["ok"] and gates["report"]["gate_report_hash"] == doc["gate_report_hash"], "Certification gates invalid")
        _require(doc["gates"] == {name[:2]: gate["status"] for name, gate in gates["report"]["gates"].items()}, "Certification gates summary mismatch")
        screen = execution["trial_metrics"][0]["result"]
        reference = gates["report"]["gates"]["G2_reliability"]["details"]["median_s"]
        _require(screen["reached"] is True and screen["status"] == "ok" and
                 screen["cost_s"] <= reference * (1 - eng.acc["min_gain"] / 2), "Certification screening failed")
        _require(doc["screening"] == {key: execution["screen"].get(key) for key in (
            "status", "reached", "cost_s", "final_acc", "peak_rss_mb", "sandbox_validation")}, "Certification screening summary mismatch")
        for name in ("v0000", "v0001"):
            valid = manifest.validate_manifest(eng, eng.store.stable / name / "manifest.json")
            _require(valid["ok"], str(valid["errors"]))
        promoted = next(r for r in records if r["event_id"] == doc["promotion_event_id"])
        rolled_back = next(r for r in records if r["event_id"] == doc["rollback_event_id"])
        _require(promoted["event_type"] == "version_promoted" and promoted["payload"]["version"] == "v0001", "Missing promotion witness")
        _require(doc["promoted_version"] == doc["current_after_promotion"] == "v0001", "Certification promotion summary mismatch")
        _require(rolled_back["event_type"] == "rollback" and rolled_back["payload"]["from_version"] == "v0001" and
                 rolled_back["payload"]["to_version"] == "v0000" and rolled_back["payload"]["reason"] == ROLLBACK_REASON,
                 "Missing explicit certification rollback")
        measurement = json.loads(manifest._state_path(eng.store.dir, doc["verification_ref"]).read_bytes())
        _require(measurement["trainer_hash"] == trainer_hash and measurement["trial"]["reached"] is True and
                 measurement["trial"]["status"] == "ok" and measurement["trial"]["sandbox_validation"] is True,
                 "Promoted version did not load/reach quality")
        final = readiness.validate_report(eng, doc["final_gate_reference"], parent="v0000")
        _require(final["ok"], "Final readiness invalid")
        result.update(ok=True, report=doc)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration) as exc:
        result["errors"].append(str(exc))
    return result


def run(root, log=print):
    from . import snippets
    unlocked = set(snippets.UNLOCKED)
    try:
        return _run(root, log)
    finally:
        snippets.set_unlocked(unlocked)


def _run(root, log):
    cfg = new_configuration(root)
    directory = Path(root).resolve() / cfg["workload"]["state_dir"]
    report_path = directory / "certification-report.json"
    report = {"certification_schema": SCHEMA, **provenance.certification_metadata(cfg),
              "timestamp": manifest.timestamp(), "state_path": str(directory), "state_id": directory.name,
              "pipeline_certified": False, "overall_status": "FAIL", "phases": {phase: False for phase in PHASES},
              "report_path": str(report_path), "failure": None}
    eng = None
    phase = "initialization"
    try:
        log("PRUEBA A — controlled pipeline certification; NOT autonomous self-improvement")
        log("Certification state: " + str(directory))
        _require(not (Path(root) / "STOP").exists(), "STOP_REQUESTED")
        eng = engine.Engine(Path(root).resolve(), cfg, log=log)
        baseline_g, candidate = controlled_pair()
        _require(eng.init(initialize_mvp=True), "Certification baseline was not newly initialized")
        eng._load()
        _require(eng.store.load_version("v0000") == (baseline_g, G.render(baseline_g)), "Unexpected certification baseline")
        report["phases"]["baseline_created"] = True
        report.update(baseline_version="v0000", baseline_genome=baseline_g, candidate_genome=candidate,
                      candidate_genome_hash=provenance.digest(candidate), candidate_trainer_hash=hashlib.sha256(G.render(candidate).encode()).hexdigest(),
                      benchmark_profile=cfg["benchmark_profile"], benchmark_summary=eng.bench["calibrated"],
                      source_snapshot=eng.state["source_snapshot"], baseline_manifest_hash=eng.state["baseline_manifest_hash"])
        phase = "gates_screening_confirmation_publication"
        # Production Engine route, explicit known proposal; never Strategy.propose.
        outcome = eng.experiment(proposal=(candidate, ["optimizer", "dtype", "backward", "depth", "lr"],
                                           G.genome_hash(baseline_g), eng.bench["calibrated"]["main"]["ref_cost_s"]))
        _require(outcome == "improved", "Controlled experiment did not obtain a real promotion: " + outcome)
        execution = json.loads((directory / "experiments/e00001/evidence.json").read_bytes())
        experiment = manifest._document(directory / "experiments/e00001/manifest.json")
        gate_report = json.loads((directory / experiment["gate_report_path"]).read_bytes())
        report["phases"]["gates_passed"] = gate_report["overall"] == "PASS"
        report["phases"]["screening_passed"] = execution["screen"]["status"] == "ok" and execution["screen"]["reached"] is True
        report["phases"]["confirmation_accepted"] = execution["confirm"]["decision"] == "accepted"
        stable = manifest._document(eng.store.stable / "v0001/manifest.json")
        report["phases"]["pre_promotion_passed"] = bool(stable["pre_promotion_hash"])
        report["phases"]["version_published"] = True
        report["phases"]["promoted_current_verified"] = eng.store.current_version() == "v0001"
        report.update(gate_report_hash=experiment["gate_report_hash"],
                      gates={name[:2]: gate["status"] for name, gate in gate_report["gates"].items()},
                      screening={key: execution["screen"].get(key) for key in ("status", "reached", "cost_s", "final_acc", "peak_rss_mb", "sandbox_validation")},
                      confirmation=execution["confirm"], improvement_observed_percent=round((1 - execution["confirm"]["ratio"]) * 100, 4),
                      promoted_version="v0001", current_after_promotion=eng.store.current_version(),
                      environment_hash=stable["environment_hash"])
        phase = "promoted_version_verification"
        checked = manifest.validate_manifest(eng, eng.store.stable / "v0001/manifest.json")
        _require(checked["ok"], str(checked["errors"]))
        loaded_g, loaded_source = eng.store.load_version()
        _require(loaded_g == candidate and loaded_source == G.render(candidate), "Promoted artifact differs from controlled candidate")
        trial = eng.trial(loaded_source, eng.bench["tiers"]["screen"][0])
        _require(trial["status"] == "ok" and trial["reached"] is True and trial["sandbox_validation"] is True,
                 "Promoted trainer failed real quality verification")
        verification = {"verification_schema": "cpu_pipeline_loaded_version_v1", **provenance.certification_metadata(cfg),
                        "version": "v0001", "trainer_hash": report["candidate_trainer_hash"], "trial": trial}
        manifest.write_manifest(directory / "certification-verification.json", verification)
        report["verification_ref"] = "certification-verification.json"
        report["phases"]["promoted_version_loaded"] = True
        report["version_hashes_before_rollback"] = version_hashes(eng.store)
        rows = ledger.verify_ledger(eng.store)["records"]
        report["promotion_event_id"] = next(r["event_id"] for r in rows if r["event_type"] == "version_promoted" and r["payload"]["version"] == "v0001")
        phase = "rollback"
        rolled = eng.rollback("v0000", ROLLBACK_REASON)
        _require(rolled["status"] == "COMPLETED", "Rollback failed: " + str(rolled))
        report["rollback_event_id"] = rolled["event_id"]
        report["phases"]["rollback_completed"] = True
        report["final_current"] = eng.store.current_version()
        report["phases"]["final_current_verified"] = report["final_current"] == "v0000"
        report["version_hashes_after_rollback"] = version_hashes(eng.store)
        report["phases"]["versions_immutable"] = report["version_hashes_after_rollback"] == report["version_hashes_before_rollback"]
        phase = "final_readiness"
        final = readiness.run_gates(eng)
        _require(final["status"] == "READY_FOR_CAMPAIGN", "Final readiness failed")
        report["final_gate_reference"] = {key: final[key] for key in ("campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")}
        report["phases"]["final_readiness_passed"] = True
        chain = ledger.verify_ledger(eng.store)
        _require(chain["ok"], str(chain["errors"]))
        report["phases"]["ledger_verified"] = True
        report["ledger_head"], report["ledger_records"] = chain["last_hash"], len(chain["records"])
        paths = {"certification-verification.json", "stable/v0000/manifest.json", "stable/v0001/manifest.json"}
        paths.update(report["version_hashes_after_rollback"])
        paths.update(str(path.relative_to(directory)) for path in (directory / "experiments/e00001").iterdir() if path.is_file())
        for ref in (experiment["gate_report_path"], final["gate_report_path"]):
            paths.update((ref, str(Path(ref).with_name("evidence.json"))))
        report["artifact_hashes"] = {p: manifest.file_hash(directory / p) for p in sorted(paths)}
        _require(all(report["phases"].values()), "Not all pipeline phases completed")
        report.update(pipeline_certified=True, overall_status="PASS")
    except (Exception, KeyboardInterrupt) as exc:
        report.update(pipeline_certified=False, overall_status="FAIL", failure={"phase": phase, "type": type(exc).__name__, "reason": str(exc)})
        if not (directory / "state.json").exists():
            manifest.write_manifest(directory / "state.json", {**provenance.certification_metadata(cfg), "initialization_status": "FAILED"})
    report["finished_at"] = manifest.timestamp()
    report["report_hash"] = provenance.digest(report)
    if report["pipeline_certified"]:
        checked = validate_report(eng, report)
        if not checked["ok"]:
            report.update(pipeline_certified=False, overall_status="FAIL",
                          failure={"phase": "report_validation", "reason": str(checked["errors"])})
    return _write_report(report_path, report)
