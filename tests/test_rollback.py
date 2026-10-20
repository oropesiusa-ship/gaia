"""Explicit CPU rollback transactions; storage fixtures are not MVP A/B proofs."""
import copy
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gaia import engine, genome as G, ledger, manifest, provenance, publication, readiness, rollback, stats
from gaia.protected import evaluator
import test_publication as fixtures


def _hash(source):
    return hashlib.sha256(source.encode()).hexdigest()


def _new_accepted(eng, number, lr):
    """Real sandbox/quality, controlled cost for storage and lineage tests only."""
    eng._load()
    parent_genome, parent = eng.store.load_version()
    candidate = G.new_genome(hp={"lr": lr})
    source = G.render(candidate)
    eid = f"e{number:05d}"
    context = eng.source_context()
    gates = readiness.run_gates(eng, genome=candidate, source=source)
    if gates["status"] != "READY_FOR_CAMPAIGN":
        raise AssertionError(gates)
    eng._campaign_context = {key: gates[key] for key in ("campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")}
    doc = manifest.build_experiment(eng, eid, context, candidate, source, parent_genome, parent)
    directory = eng.store.dir / "experiments" / eid
    manifest.write_manifest(directory / "manifest.json", doc)
    (directory / "genome.json").write_bytes(publication.genome_bytes(candidate))
    (directory / "trainer.py").write_text(source)
    for name in ("genome.json", "trainer.py"):
        (directory / name).chmod(0o444)
    trials, parents, candidates = [], [], []

    def trial(src, seed, cost):
        result = evaluator.run_trial(src, eng.bench, "main", seed, seed, 20, eng.lim, eng.store.tmp)
        if not result["reached"] or result["status"] != "ok" or not result["sandbox_validation"]:
            raise AssertionError(result)
        result["cost_s"] = cost
        trials.append({"trainer_hash": _hash(src), "task": "main", "data_seed": seed,
                       "campaign_id": doc["campaign_id"], "environment_hash": doc["environment_hash"],
                       "stable_version": doc["parent_version"], "source_sha": doc["candidate_trainer_hash"],
                       "init_seed": seed, "cap_s": 20, "result": result})
        return result

    screen = trial(source, 0, .5)
    for index, seed in enumerate(range(1000, 1005)):
        for who in (("candidate", "parent") if index % 2 else ("parent", "candidate")):
            result = trial(source if who == "candidate" else parent, seed, .5 if who == "candidate" else 1.0)
            (candidates if who == "candidate" else parents).append(result)
    decision = stats.decide(parents, candidates, eng.acc)
    decision.update(champ_costs=[r["cost_s"] for r in parents], cand_costs=[r["cost_s"] for r in candidates])
    evidence = {"type": "end", "id": eid, "genome": candidate, "ops": ["lr"], "confirm": decision,
                **eng._campaign_context,
                "screen": screen, "decision": "accepted", "reason": decision["reason"], **context,
                "baseline_manifest_hash": context["manifest_hash"], "candidate_genome_hash": manifest.digest(candidate),
                "candidate_trainer_hash": _hash(source), "experiment_manifest_hash": doc["manifest_hash"],
                "parent_version": doc["parent_version"], "trial_metrics": trials,
                "sandbox_evidence_hash": manifest.digest([t["result"]["sandbox_evidence"] for t in trials]),
                "started_at": doc["created_at"], "finished_at": manifest.timestamp(), "promotable": True,
                "evidence_path": f"experiments/{eid}/evidence.json"}
    evidence["evidence_hash"] = manifest.digest(evidence)
    manifest.write_manifest(directory / "evidence.json", evidence)
    eng.store.append({"type": "start", "id": eid, "genome": candidate, "ops": ["lr"],
                      **eng._campaign_context,
                      "stable_version": doc["parent_version"], "environment_hash": context["environment_hash"],
                      "experiment_manifest_hash": doc["manifest_hash"], "source_sha": _hash(source)})
    eng.store.append(evidence)
    provided = {"experiment": eid, **context, "baseline_manifest_hash": context["manifest_hash"],
                "experiment_manifest_path": f"experiments/{eid}/manifest.json", "experiment_manifest_hash": doc["manifest_hash"],
                "experiment_evidence_path": evidence["evidence_path"], "experiment_evidence_hash": evidence["evidence_hash"],
                "confirm": decision, "hypothesis": {"detail": G.describe(candidate)}, "provenance": "known",
                "diff_vs_champion": [list(row) for row in G.diff(parent_genome, candidate)]}
    provided.update(readiness.pre_promotion(eng, candidate, source, provided))
    return candidate, source, provided


def _rollback_child(root, cfg, target, barrier=None, queue=None, fault=None):
    eng = engine.Engine(root, cfg, log=lambda *args: None)
    if barrier:
        barrier.wait(15)

    def die(phase, path):
        if phase == fault:
            os._exit(73)

    result = eng.rollback(target, "explicit subprocess verification", _test_fault=die if fault else None)
    if queue:
        queue.put(result)


class RollbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory(prefix="gaia-rollback-template-")
        cls.addClassCleanup(cls.template.cleanup)
        root = Path(cls.template.name)
        cls.cfg, genome, source, evidence = fixtures._make_template(root)
        eng = engine.Engine(root, cls.cfg, log=lambda *args: None)
        eng._load()
        eng.store.promote(genome, source, evidence, context=eng)

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaia-rollback-case-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        shutil.copytree(self.template.name, self.root)
        self.eng = engine.Engine(self.root, copy.deepcopy(self.cfg), log=lambda *args: None)
        self.eng._load()

    def hashes(self):
        return {p.relative_to(self.eng.store.stable).as_posix(): manifest.file_hash(p)
                for version in self.eng.store.versions() for p in (self.eng.store.stable / version).iterdir()}

    def rollback(self, to="v0000", reason="manual rollback verification", **kwargs):
        return self.eng.rollback(to, reason, **kwargs)

    def test_valid_rollback_is_chained_explicit_and_immutable(self):
        before = self.hashes()
        result = self.rollback()
        self.assertEqual(result["status"], "COMPLETED", result)
        self.assertEqual(result["previous_current"], "v0001")
        self.assertEqual(result["resulting_current"], "v0000")
        self.assertEqual(self.eng.store.current_version(), "v0000")
        checked = ledger.verify_ledger(self.eng.store)
        self.assertTrue(checked["ok"], checked)
        event = checked["records"][-1]
        self.assertEqual(event["event_type"], "rollback")
        self.assertEqual(event["event_id"], result["event_id"])
        self.assertEqual(event["payload"]["from_version"], "v0001")
        self.assertEqual(event["payload"]["to_version"], "v0000")
        self.assertTrue(event["payload"]["operator_initiated"])
        self.assertEqual(event["evidence_ref"], "stable/v0000/evidence.json")
        self.assertEqual(event["manifest_hash"], event["payload"]["to_manifest_hash"])
        self.assertFalse(event["payload"]["recovered_after_crash"])
        self.assertEqual(before, self.hashes())
        self.assertFalse(list(self.eng.store.dir.glob(".rollback-intent-*")))
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "READY")
        gate = readiness.g3_integrity(self.eng)
        self.assertTrue(gate["ok"], gate)
        self.assertTrue(provenance.prerequisites(self.eng)["ok"])

    def test_reason_is_required(self):
        for reason in ("", "   ", None):
            result = self.rollback(reason=reason)
            self.assertEqual(result["code"], "INVALID_REASON")
        self.assertEqual(self.eng.store.current_version(), "v0001")

    def test_invalid_destination_and_path_traversal_are_rejected(self):
        for destination in ("latest", "../v0000", "/v0000", ".staging-v0000-test", "v0000/../v0001", "v１２３４", "v1"):
            with self.subTest(destination=destination):
                self.assertEqual(self.rollback(to=destination)["code"], "INVALID_DESTINATION")
        self.assertEqual(self.eng.store.current_version(), "v0001")

    def test_equal_missing_and_forward_targets_are_rejected(self):
        for target in ("v0001", "v9999"):
            self.assertEqual(self.rollback(to=target)["status"], "BLOCKED")
        self.assertEqual(self.rollback()["status"], "COMPLETED")
        self.assertEqual(self.rollback(to="v0001")["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0000")

    def test_destination_corrupt_blocks_without_touching_current(self):
        path = self.eng.store.stable / "v0000/trainer.py"
        path.chmod(0o644)
        path.write_text("changed")
        self.assertEqual(self.rollback()["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0001")

    def test_legacy_or_copied_version_cannot_be_a_destination(self):
        copied = self.eng.store.stable / "v0099"
        copied.mkdir()
        (copied / "trainer.py").write_text("legacy")
        self.assertEqual(self.rollback(to="v0099")["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0001")

    def test_legacy_whole_state_is_preserved_and_blocked(self):
        state = self.eng.store.load_state()
        del state["ledger_schema"]
        self.eng.store.save_state(state)
        before = self.eng.store.ledger.read_bytes()
        self.assertEqual(self.rollback()["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0001")
        self.assertEqual(before, self.eng.store.ledger.read_bytes())

    def test_origin_or_ledger_corrupt_blocks(self):
        path = self.eng.store.stable / "v0001/manifest.json"
        original = path.read_bytes()
        path.chmod(0o644)
        path.write_text("{}")
        self.assertEqual(self.rollback()["status"], "BLOCKED")
        path.write_bytes(original)
        with self.eng.store.ledger.open("ab") as stream:
            stream.write(b"partial")
        self.assertEqual(self.rollback()["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0001")

    def test_campaign_lock_including_same_engine_is_busy(self):
        self.eng.store.lock()
        try:
            self.assertEqual(self.rollback()["code"], "STATE_BUSY")
            other = engine.Engine(self.root, self.cfg, log=lambda *args: None)
            self.assertEqual(other.rollback("v0000", "other operator")["code"], "STATE_BUSY")
        finally:
            self.eng.store.unlock()

    def test_store_api_cannot_bypass_engine(self):
        with self.assertRaisesRegex(RuntimeError, "Engine.rollback"):
            self.eng.store.rollback()
        with self.assertRaises(rollback.RollbackError):
            rollback.perform(self.eng, "v0000", "bypass")

    def test_staging_or_uncommitted_publication_blocks(self):
        staging = self.eng.store.stable / (".staging-v0002-" + "a" * 32)
        staging.mkdir()
        self.assertEqual(self.rollback()["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0001")

    def test_pre_switch_faults_keep_current_and_do_not_log_success(self):
        for fault in ("after_intent_created", "before_current_change"):
            result = self.rollback(_test_fault=fault)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(self.eng.store.current_version(), "v0001")
            before = self.eng.store.ledger.read_bytes()
            report = self.eng.store.recover_publications(self.eng)
            self.assertEqual(report["status"], "READY", report)
            self.assertEqual(report["rollback_recovery"]["action"], "not_committed_intent_removed")
            self.assertEqual(before, self.eng.store.ledger.read_bytes())

    def test_rollback_event_cannot_precede_current_switch(self):
        self.rollback(_test_fault="after_intent_created")
        intent = json.loads(next(self.eng.store.dir.glob(".rollback-intent-*.json")).read_bytes())
        before = self.eng.store.ledger.read_bytes()
        with self.assertRaisesRegex(ValueError, "before CURRENT"):
            self.eng.store.append_ledger_event("rollback", {**intent["payload"], "intent_hash": intent["intent_hash"]})
        self.assertEqual(before, self.eng.store.ledger.read_bytes())

    def test_post_switch_fault_recovers_only_event_and_preserves_versions(self):
        before_hashes = self.hashes()
        before = ledger.verify_ledger(self.eng.store)["records"]
        result = self.rollback(_test_fault="before_rollback_append")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0000")
        self.assertEqual(len(ledger.verify_ledger(self.eng.store)["records"]), len(before))
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "READY", report)
        after = ledger.verify_ledger(self.eng.store)["records"]
        self.assertEqual(after[:-1], before)
        self.assertTrue(after[-1]["payload"]["recovered_after_crash"])
        self.assertEqual(before_hashes, self.hashes())
        self.eng.store.recover_publications(self.eng)
        self.assertEqual(after, ledger.verify_ledger(self.eng.store)["records"])

    def test_each_post_switch_boundary_recovers_idempotently(self):
        original_state = Path(self.template.name) / "state"
        for fault in ("after_current_replace", "after_current_verified", "after_rollback_append", "before_intent_remove"):
            with self.subTest(fault=fault):
                shutil.rmtree(self.eng.store.dir)
                shutil.copytree(original_state, self.eng.store.dir)
                result = self.rollback(_test_fault=fault)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(self.eng.store.current_version(), "v0000")
                report = self.eng.store.recover_publications(self.eng)
                self.assertEqual(report["status"], "READY", report)
                records = ledger.verify_ledger(self.eng.store)["records"]
                self.assertEqual(sum(r["event_type"] == "rollback" for r in records), 1)
                self.assertFalse(list(self.eng.store.dir.glob(".rollback-intent-*")))

    def test_bad_intent_or_ambiguous_current_is_blocked_without_repair(self):
        self.rollback(_test_fault="after_intent_created")
        path = next(self.eng.store.dir.glob(".rollback-intent-*.json"))
        raw = path.read_bytes()
        path.write_text("{}")
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")
        self.assertTrue(path.exists())
        path.write_bytes(raw)
        (self.eng.store.stable / "CURRENT").write_text("v9999\n")
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")
        self.assertTrue(path.exists())

    def test_unexpected_ledger_change_with_intent_is_ambiguous(self):
        self.rollback(_test_fault="after_intent_created")
        self.eng.store.append_ledger_event("identity", {"type": "identity", "unexpected": True})
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")
        self.assertTrue(list(self.eng.store.dir.glob(".rollback-intent-*")))
        self.assertEqual(self.eng.store.current_version(), "v0001")

    def test_corrupted_destination_after_switch_blocks_reconstruction(self):
        self.rollback(_test_fault="before_rollback_append")
        path = self.eng.store.stable / "v0000/evidence.json"
        path.chmod(0o644)
        path.write_text("{}")
        before = self.eng.store.ledger.read_bytes()
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")
        self.assertEqual(before, self.eng.store.ledger.read_bytes())

    def test_partial_rollback_ledger_write_blocks_without_repair(self):
        append = self.eng.store.append_ledger_event

        def partial(event_type, payload, **kwargs):
            return append(event_type, payload, _test_fault="during_write" if event_type == "rollback" else None)

        with patch.object(self.eng.store, "append_ledger_event", side_effect=partial):
            self.assertEqual(self.rollback()["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0000")
        before = self.eng.store.ledger.read_bytes()
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")
        self.assertEqual(before, self.eng.store.ledger.read_bytes())
        self.assertTrue(list(self.eng.store.dir.glob(".rollback-intent-*")))

    def test_late_artifact_change_before_pointer_replace_keeps_original_current(self):
        def change(phase, path):
            if phase == "before_current_change":
                candidate = self.eng.store.stable / "v0000/trainer.py"
                candidate.chmod(0o644)
                candidate.write_text("late corruption")

        self.assertEqual(self.rollback(_test_fault=change)["status"], "BLOCKED")
        self.assertEqual(self.eng.store.current_version(), "v0001")

    def test_unjournaled_current_change_is_not_treated_as_a_rollback(self):
        (self.eng.store.stable / "CURRENT").write_text("v0000\n")
        self.assertFalse(readiness.g3_integrity(self.eng)["ok"])
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")
        self.assertFalse(any(r["event_type"] == "rollback" for r in ledger.verify_ledger(self.eng.store)["records"]))

    def test_real_process_death_after_replace_is_recovered(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_rollback_child, args=(self.root, self.cfg, "v0000", None, None, "after_current_replace"))
        process.start()
        process.join(30)
        self.assertEqual(process.exitcode, 73)
        process.close()
        self.assertEqual(self.eng.store.current_version(), "v0000")
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "READY", report)
        last = ledger.verify_ledger(self.eng.store)["records"][-1]
        self.assertTrue(last["payload"]["recovered_after_crash"])

    def test_concurrent_rollbacks_only_one_proceeds(self):
        ctx = multiprocessing.get_context("fork")
        barrier, queue = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=_rollback_child, args=(self.root, self.cfg, "v0000", barrier, queue)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(30)
                self.assertEqual(process.exitcode, 0)
            results = [queue.get(timeout=5) for _ in processes]
            self.assertEqual(sum(r["status"] == "COMPLETED" for r in results), 1, results)
            self.assertEqual(self.eng.store.current_version(), "v0000")
        finally:
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            queue.close()
            queue.join_thread()

    def test_non_immediate_ancestor_and_new_branch_numbering(self):
        for number, lr in ((2, .06), (3, .04)):
            genome, source, evidence = _new_accepted(self.eng, number, lr)
            self.assertEqual(self.eng.store.promote(genome, source, evidence, context=self.eng), f"v{number:04d}")
        before = self.hashes()
        result = self.rollback(to="v0001")
        self.assertEqual(result["status"], "COMPLETED", result)
        self.assertEqual(before, self.hashes())
        self.assertEqual(self.eng.store.current_version(), "v0001")
        genome, source, evidence = _new_accepted(self.eng, 4, .07)
        document = manifest._document(self.eng.store.dir / "experiments/e00004/manifest.json")
        self.assertEqual(document["parent_version"], "v0001")
        self.assertEqual(self.eng.store.promote(genome, source, evidence, context=self.eng), "v0004")

    def test_after_rollback_new_parent_is_current_and_next_promotion_v0002(self):
        self.assertEqual(self.rollback()["status"], "COMPLETED")
        genome, source, evidence = _new_accepted(self.eng, 2, .09)
        document = manifest._document(self.eng.store.dir / "experiments/e00002/manifest.json")
        self.assertEqual(document["parent_version"], "v0000")
        self.assertEqual(self.eng.store.promote(genome, source, evidence, context=self.eng), "v0002")
        self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])
        self.assertEqual(self.rollback(to="v0001")["status"], "BLOCKED")  # older number, but another branch.

    def test_cli_calls_engine_with_explicit_destination_and_reason(self):
        spec = importlib.util.spec_from_file_location("gaia_cpu_cli_test", Path(__file__).resolve().parents[1] / "gaia.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        from types import SimpleNamespace
        with patch.object(cli, "make", return_value=self.eng):
            self.assertEqual(cli.cmd_rollback(SimpleNamespace(to="v0000", reason="CLI verification")), 0)
        self.assertEqual(self.eng.store.current_version(), "v0000")


if __name__ == "__main__":
    unittest.main()
