"""Prueba B: one normal Engine.run(), frozen normal budget, verification only.

No candidate/strategy selector or retry loop lives here. Proposal replay is
post-run verification with a separate RNG; its output is never submitted.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import uuid

import numpy as np

from . import config, engine, genome as G, ledger, manifest, provenance, publication, readiness, search, snippets
from .atomic_publish import fsync_directory
from .protected import benchmark

SCHEMA = "mvp_cpu_autonomous_report_v1"
PREFIX = "state_autonomous_mvp_cpu_"
ROLLBACK_REASON = "Autonomous MVP verification rollback"


def _require(ok, reason):
    if not ok:
        raise ValueError(reason)


def new_configuration(root):
    cfg = config.load(root)  # The current normal CPU config, not A or a tuned profile.
    _require(cfg["workload"]["id"] == "numpy_mlp" and not cfg.get("certification_only") and
             not cfg.get("certification") and cfg.get("state_purpose") != "pipeline_certification", "B requires normal CPU configuration")
    name = PREFIX + uuid.uuid4().hex
    (Path(root) / name).mkdir(exist_ok=False)
    fsync_directory(root)
    cfg["workload"]["state_dir"] = name
    cfg.update(state_purpose="autonomous_mvp", certification=False, certification_only=False)
    return cfg


def frozen_budget(cfg):
    spec = copy.deepcopy(benchmark.PROFILES[cfg["benchmark_profile"]])
    spec.pop("calibrated", None)
    value = {"budget_schema": "mvp_cpu_autonomous_budget_v1", "frozen_at": manifest.timestamp(),
             "max_proposals": cfg["limits"]["max_experiments"], "max_experiments": cfg["limits"]["max_experiments"],
             "minutes": cfg["limits"]["max_total_minutes"], "limits": copy.deepcopy(cfg["limits"]),
             "acceptance": copy.deepcopy(cfg["acceptance"]), "benchmark_profile": cfg["benchmark_profile"],
             "benchmark_spec_hash": provenance.digest(spec), "config": provenance.experimental_config(cfg),
             "engine_run_arguments": {}, "skip_gate": False, "force": False,
             "normal_internal_strategy_retry_policy": "unchanged gaia.search.Strategy.propose"}
    value["budget_hash"] = provenance.digest(value)
    return value


def validate_budget(cfg, budget, baseline):
    _require(budget["budget_hash"] == provenance.digest({k: v for k, v in budget.items() if k != "budget_hash"}), "BUDGET_CHANGED")
    _require(budget["config"] == provenance.experimental_config(cfg) and budget["limits"] == cfg["limits"] and
             budget["acceptance"] == cfg["acceptance"] and budget["minutes"] == cfg["limits"]["max_total_minutes"] and
             budget["max_proposals"] == budget["max_experiments"] == cfg["limits"]["max_experiments"] and
             budget["engine_run_arguments"] == {} and budget["skip_gate"] is False and budget["force"] is False,
             "BUDGET_OR_THRESHOLD_OVERRIDE")
    frozen = copy.deepcopy(baseline["effective_config"]["benchmark"])
    frozen.pop("calibrated", None)
    _require(provenance.experimental_config(baseline["effective_config"]) == budget["config"] and
             provenance.digest(frozen) == budget["benchmark_spec_hash"] and baseline["effective_config"]["acceptance"] == budget["acceptance"],
             "BENCHMARK_OR_SEED_OVERRIDE")


def _history(store, rows, baseline):
    history = search.History()
    history.add(G.new_genome(), baseline["effective_config"]["benchmark"]["calibrated"]["main"]["ref_cost_s"], "ok", None, [])
    for row in rows:
        payload = row["payload"]
        if row["event_type"] in ("experiment_completed", "experiment_aborted") and payload.get("screen") and payload.get("genome"):
            path = manifest._state_path(store.dir, f"experiments/{payload['id']}/genome.json")
            genome = json.loads(path.read_bytes())  # Preserve live genotype key order, including crossover slots.
            _require(provenance.digest(genome) == provenance.digest(payload["genome"]), "HISTORY_GENOME_MISMATCH")
            history.add(genome, payload["screen"].get("cost_s"), payload["screen"]["status"], payload.get("parent_cost"), payload.get("ops", []))
    return history


def verify_proposals(eng, baseline, chain):
    summaries = []
    expected_rng = np.random.default_rng(13).bit_generator.state  # Existing Engine._load seed at n=0, not an override.
    gate_reports = []
    for path in (eng.store.dir / "campaigns").glob("*/gates.json"):
        doc = json.loads(path.read_bytes())
        gate_reports.append((path, doc))
    for index, path in enumerate(sorted((eng.store.dir / "proposals").glob("p[0-9]*.json")), 1):
        trace = json.loads(path.read_bytes())
        _require(all(trace.get(k) == v for k, v in provenance.purpose_metadata(eng.cfg).items()), "PROPOSAL_PURPOSE_MISMATCH")
        _require(trace["proposal_schema"] == "cpu_search_proposal_v1" and trace["proposal_index"] == index and
                 trace["trace_hash"] == provenance.digest({k: v for k, v in trace.items() if k != "trace_hash"}), "PROPOSAL_TRACE_INVALID")
        inp = trace["input"]
        rows = chain["records"][:inp["ledger_sequence"]]
        _require(bool(rows) and rows[-1]["record_hash"] == inp["ledger_head"], "PROPOSAL_HISTORY_NOT_THIS_LEDGER")
        history = _history(eng.store, rows, baseline)
        identity = {"items": history.items, "seen": sorted(history.seen), "op_n": history.op_n, "op_sum": history.op_sum,
                    "since_improve": history.since_improve, "best": history.best}
        _require(provenance.digest(identity) == inp["history_hash"] and len(history.items) == inp["history_items"], "PROPOSAL_HISTORY_MISMATCH")
        _require(inp["operator_counts"] == history.op_n and inp["operator_rewards"] == history.op_sum, "PROPOSAL_PRIOR_MISMATCH")
        # Normal meta adoptions, if any, are only sourced from this ledger.
        strategy = dict(search.DEFAULT_STRATEGY)
        unlocked = set()
        for row in rows:
            payload = row["payload"]
            if row["event_type"] == "meta" and payload.get("adopted"):
                candidate = dict(payload["candidate"])
                candidate["version"] = strategy.get("version", 0) + 1
                strategy = candidate
            if row["event_type"] == "research_unlock":
                unlocked.add(tuple(payload["option"]))
        _require(inp["strategy"] == strategy and inp["rng_state"] == expected_rng and inp["unlocked"] == sorted(map(list, unlocked)),
                 "STRATEGY_RNG_OR_PRIOR_OVERRIDE")
        _require(trace["candidate_origin"] == "search" and trace["proposal_method"] == "gaia.search.Strategy.propose", "NON_SEARCH_PROPOSAL")
        local_rng = np.random.default_rng()
        local_rng.bit_generator.state = copy.deepcopy(inp["rng_state"])
        prior_unlocked = set(snippets.UNLOCKED)
        try:
            snippets.set_unlocked(inp["unlocked"])
            generated, ops, parent_hash, parent_cost = search.Strategy(strategy, local_rng).propose(history)
        finally:
            snippets.set_unlocked(prior_unlocked)
        _require(provenance.digest(generated) == trace["genome_hash"] == provenance.digest(trace["genome"]) and
                 G.render(generated) == G.render(trace["genome"]) and ops == trace["ops"] and parent_hash == trace["parent_hash"] and
                 parent_cost == trace["parent_cost"] and local_rng.bit_generator.state == trace["rng_after"], "PROPOSAL_REPLAY_MISMATCH")
        _require(hashlib.sha256(G.render(trace["genome"]).encode()).hexdigest() == trace["trainer_hash"], "PROPOSAL_TRAINER_EDITED")
        expected_rng = trace["rng_after"]
        matching = [(p, doc) for p, doc in gate_reports if doc.get("proposal_trace_hash") == trace["trace_hash"] and
                    doc["candidate_genome_hash"] == trace["genome_hash"]]
        starts = [r for r in chain["records"] if r["event_type"] == "experiment_started" and
                  r["payload"].get("proposal_trace_hash") == trace["trace_hash"]]
        if starts:
            _require(len(starts) == 1, "PROPOSAL_STARTED_MORE_THAN_ONCE")
            eid = starts[0]["payload"]["id"]
            artifact = manifest._state_path(eng.store.dir, f"experiments/{eid}/trainer.py")
            stored_genome = json.loads(manifest._state_path(eng.store.dir, f"experiments/{eid}/genome.json").read_bytes())
            _require(provenance.digest(stored_genome) == trace["genome_hash"] and manifest.file_hash(artifact) == trace["trainer_hash"] and
                     artifact.read_text() == G.render(stored_genome), "MANUAL_GENOME_OR_TRAINER_EDIT")
        completed = next((r["payload"] for r in chain["records"] if r["event_type"] in ("experiment_completed", "experiment_aborted") and
                          starts and r["payload"]["id"] == starts[0]["payload"]["id"]), None)
        summaries.append({"proposal_index": index, "proposal_trace_path": str(path.relative_to(eng.store.dir)), "trace_hash": trace["trace_hash"],
                          "candidate_origin": "search", "proposal_method": trace["proposal_method"], "ops": ops,
                          "parent_hash": parent_hash, "history_items": inp["history_items"], "history_hash": inp["history_hash"],
                          "genome_hash": trace["genome_hash"], "trainer_hash": trace["trainer_hash"], "description": G.describe(trace["genome"]),
                          "experiment_id": starts[0]["payload"]["id"] if starts else None,
                          "gate_report_path": str(matching[0][0].relative_to(eng.store.dir)) if matching else None,
                          "gates": matching[0][1]["overall"] if matching else "MISSING",
                          "result": completed["decision"] if completed else "GATES_BLOCKED", "reason": completed.get("reason") if completed else None,
                          "screening": {k: (completed.get("screen") or {}).get(k) for k in ("status", "reached", "cost_s", "final_acc", "peak_rss_mb")} if completed else None,
                          "confirmation": completed.get("confirm") if completed else None})
    return summaries


def failure_category(outcome, reason):
    if outcome == "budget" or "Meseta:" in reason:
        return "AUTONOMOUS_SEARCH_EXHAUSTED"
    if any(code in reason for code in ("OVERRIDE", "FORBIDDEN", "NON_SEARCH", "REPLAY_MISMATCH", "INVALID_CANDIDATE")):
        return "OTRO"
    return "INFRASTRUCTURE_FAILURE"


def completion_flags(search_promotion, loaded, rolled_back, final_integrity):
    passed = all((search_promotion, loaded, rolled_back, final_integrity))
    return {"autonomous_promotion_certified": bool(search_promotion), "autonomous_self_improvement_certified": passed,
            "overall_status": "PASS" if passed else "FAIL"}


def run(root, log=print):
    root = Path(root).resolve()
    cfg = new_configuration(root)
    eng = engine.Engine(root, cfg, log=log)
    budget = frozen_budget(cfg)
    report = {"schema": SCHEMA, **provenance.purpose_metadata(cfg), "started_at": manifest.timestamp(),
              "state": str(eng.store.dir), "budget": budget, "proposal_count": 0, "candidates": [],
              **completion_flags(False, False, False, False), "failure_type": None, "failure": None,
              "pipeline_certified": True, "pipeline_certification_scope": "prior pipeline certification, not autonomous search input",
              "normal_engine_run_calls": 0}
    phase = "baseline"
    search_promotion = False
    try:
        _require(not (root / "STOP").exists() and not (root / "NEEDS_HUMAN.md").exists(), "Existing STOP/NEEDS_HUMAN blocks normal run")
        log("PRUEBA B — ONE normal Engine.run(), no controlled proposal, no retries")
        log("B state: " + str(eng.store.dir))
        log("Frozen normal budget: " + json.dumps(budget, sort_keys=True))
        eng.init(initialize_mvp=True)
        eng._load()
        _require(eng.state["n_experiments"] == 0 and eng.state["strategy"] == search.DEFAULT_STRATEGY and len(eng.hist.items) == 1,
                 "B requires fresh normal history/strategy")
        baseline = manifest._document(eng.store.stable / "v0000/manifest.json")
        _require(eng.store.load_version("v0000") == (G.new_genome(), G.render(G.new_genome())), "BASELINE_OVERRIDE")
        validate_budget(cfg, budget, baseline)
        manifest.write_manifest(eng.store.dir / "autonomous-budget.json", budget)
        report["baseline"] = {"version": "v0000", "genome_hash": baseline["source"]["baseline_genome_sha256"],
                              "trainer_hash": baseline["source"]["baseline_trainer_sha256"], "manifest_hash": baseline["manifest_hash"],
                              "source_hash": baseline["source_hash"], "environment_hash": baseline["environment_hash"],
                              "benchmark": eng.bench["calibrated"], "genome": G.new_genome()}
        phase = "normal_campaign"
        report["normal_engine_run_calls"] = 1
        outcome = eng.run()  # EXACT production defaults; no proposal, seed, meta or budget argument.
        report["campaign_outcome"] = outcome
        chain = ledger.verify_ledger(eng.store)
        _require(chain["ok"], str(chain["errors"]))
        candidates = verify_proposals(eng, baseline, chain)
        report.update(candidates=candidates, proposal_count=len(candidates))
        validate_budget(cfg, budget, baseline)
        persisted_budget = json.loads((eng.store.dir / "autonomous-budget.json").read_bytes())
        _require(persisted_budget == budget, "BUDGET_FILE_CHANGED")
        _require(len(candidates) <= budget["max_proposals"] and eng.state["n_experiments"] <= budget["max_experiments"], "BUDGET_EXCEEDED")
        promoted = [r for r in chain["records"] if r["event_type"] == "version_promoted"]
        if not promoted:
            stop_path = root / "NEEDS_HUMAN.md"
            reason = stop_path.read_text() if stop_path.exists() else outcome
            report["normal_stop_reason"] = reason
            report["failure_type"] = failure_category(outcome, reason)
            raise ValueError("No autonomous promotion; normal campaign stopped: " + reason)
        _require(len(promoted) == 1, "Unexpected number of promotions")
        event = promoted[0]
        version = event["payload"]["version"]
        stable = manifest._document(eng.store.stable / version / "manifest.json")
        experiment = manifest._document(manifest._state_path(eng.store.dir, stable["experiment_manifest_path"]))
        selection = next((c for c in candidates if c["experiment_id"] == experiment["experiment_id"]), None)
        _require(experiment.get("candidate_origin") == "search" and not experiment.get("certification") and
                 selection is not None and selection["result"] == "accepted", "WINNER_NOT_NORMAL_SEARCH")
        parent = experiment["parent_version"]
        execution = manifest._execution_evidence(manifest._state_path(eng.store.dir, stable["experiment_evidence_path"]), experiment, baseline)
        confirmation = publication.confirmation(baseline, experiment, execution)
        checked = manifest.validate_manifest(eng, eng.store.stable / version / "manifest.json")
        _require(checked["ok"] and eng.store.current_version() == version, str(checked["errors"]))
        search_promotion = True
        report.update(autonomous_promotion_certified=True, promoted_version=version, parent_version=parent,
                      promotion_event_id=event["event_id"], current_after_promotion=version,
                      winner={"experiment_id": experiment["experiment_id"], "candidate_origin": "search", "genome_hash": experiment["candidate_genome_hash"],
                              "trainer_hash": experiment["candidate_trainer_hash"], "proposal_trace_hash": experiment["proposal_trace_hash"],
                              **{k: selection[k] for k in ("proposal_method", "ops", "parent_hash", "history_items", "history_hash")}},
                      screening={k: execution["screen"].get(k) for k in ("status", "reached", "cost_s", "final_acc", "peak_rss_mb", "sandbox_validation")}, confirmation=confirmation,
                      improvement_percent=round((1 - confirmation["ratio"]) * 100, 4))
        _require(outcome == "improved", "Promotion observed but normal campaign did not finish normally: " + outcome)
        phase = "post_promotion_verification"
        genome, trainer = eng.store.load_version()
        _require(provenance.digest(genome) == experiment["candidate_genome_hash"] and trainer == G.render(genome) and
                 hashlib.sha256(trainer.encode()).hexdigest() == experiment["candidate_trainer_hash"], "WINNER_ARTIFACT_EDITED")
        measured = eng.trial(trainer, eng.bench["tiers"]["screen"][0])
        _require(measured["status"] == "ok" and measured["reached"] is True and measured["sandbox_validation"] is True, "POST_PROMOTION_QUALITY_FAILED")
        manifest.write_manifest(eng.store.dir / "autonomous-post-verification.json", {"version": version, "trainer_hash": experiment["candidate_trainer_hash"], "result": measured})
        report["winner"]["genome"] = genome
        report["post_verification"] = {k: measured.get(k) for k in ("status", "reached", "cost_s", "final_acc", "peak_rss_mb", "sandbox_validation")}
        versions = (parent, version)
        before = {f"stable/{v}/{name}": manifest.file_hash(eng.store.stable / v / name) for v in versions for name in sorted(publication.ARTIFACTS)}
        phase = "verification_rollback"
        rolled = eng.rollback(parent, ROLLBACK_REASON)
        _require(rolled["status"] == "COMPLETED", str(rolled))
        report["rollback_event_id"] = rolled["event_id"]
        after = {path: manifest.file_hash(eng.store.dir / path) for path in before}
        _require(before == after and eng.store.current_version() == parent, "ROLLBACK_IMMUTABILITY_OR_CURRENT_FAILED")
        final = readiness.run_gates(eng)
        _require(final["status"] == "READY_FOR_CAMPAIGN", "FINAL_READINESS_FAILED")
        chain = ledger.verify_ledger(eng.store)
        _require(chain["ok"], str(chain["errors"]))
        report.update(completion_flags(True, True, True, True))
        report.update(final_current=eng.store.current_version(), ledger_head=chain["last_hash"], ledger_records=len(chain["records"]),
                      version_hashes_before_rollback=before, version_hashes_after_rollback=after,
                      final_gate_reference={k: final[k] for k in ("campaign_id", "gate_report_path", "gate_report_hash", "overall_gates_passed")},
                      no_intervention={k: True for k in ("no_candidate_injection", "no_manual_genome", "no_trainer_modification", "no_certification_candidate",
                           "no_threshold_override", "no_seed_override", "no_benchmark_override", "no_skip_gate", "no_force", "no_external_proposal")})
    except (Exception, KeyboardInterrupt) as exc:
        report.update(completion_flags(search_promotion, False, False, False))
        report["failure_type"] = report["failure_type"] or failure_category("error", str(exc))
        report["failure"] = {"phase": phase, "type": type(exc).__name__, "reason": str(exc)}
        if eng.bench is not None:
            try:
                chain = ledger.verify_ledger(eng.store)
                if chain["ok"]:
                    report.update(ledger_head=chain.get("last_hash"), ledger_records=len(chain["records"]))
                    # Verification only; preserve all failed proposals/gates too.
                    baseline = manifest._document(eng.store.stable / "v0000/manifest.json")
                    candidates = verify_proposals(eng, baseline, chain)
                    report.update(candidates=candidates, proposal_count=len(candidates))
            except (OSError, ValueError, RuntimeError, KeyError, TypeError) as diagnostic:
                report["evidence_diagnostic"] = str(diagnostic)
                files = sorted((eng.store.dir / "proposals").glob("p[0-9]*.json"))
                report["proposal_count"] = len(files)
                report["candidates"] = []
                for file in files:
                    try:
                        raw = json.loads(file.read_bytes())
                        report["candidates"].append({"proposal_index": raw.get("proposal_index"), "candidate_origin": raw.get("candidate_origin"),
                            "genome_hash": raw.get("genome_hash"), "ops": raw.get("ops"), "autonomy_verified": False,
                            "proposal_trace_path": str(file.relative_to(eng.store.dir)), "verification_error": str(diagnostic)})
                    except (OSError, ValueError):
                        pass
        try:
            report["final_current"] = eng.store.current_version()
        except (OSError, ValueError) as diagnostic:
            report["final_current"] = None
            report["current_diagnostic"] = str(diagnostic)
    report["finished_at"] = manifest.timestamp()
    path = eng.store.dir / "autonomous-mvp-report.json"
    report["report_path"] = str(path)
    report["report_hash"] = provenance.digest(report)
    manifest.write_manifest(path, report)
    with path.open("rb") as stream:
        os.fsync(stream.fileno())
    fsync_directory(path.parent)
    return report
