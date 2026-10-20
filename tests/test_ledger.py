"""CPU canonical ledger: tamper detection, explicit crash boundaries, local refs."""
import copy
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from gaia import config, engine, genome as G, ledger, manifest, provenance, readiness
from gaia.store import Store
from gaia.protected import evaluator
import test_publication as fixtures


def writer(root, cfg, barrier, queue):
    eng = engine.Engine(root, cfg, log=lambda *args: None)
    barrier.wait(15)
    try:
        for index in range(3):
            for attempt in range(100):
                try:
                    eng.store.append_ledger_event("identity", {"type": "identity", "writer": os.getpid(), "index": index})
                    break
                except RuntimeError as exc:
                    if "lock" not in str(exc):
                        raise
                    time.sleep(.02)
            else:
                raise RuntimeError("writer lock deadline")
        queue.put(True)
    except Exception as exc:
        queue.put(str(exc))


class LedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory(prefix="gaia-ledger-template-")
        cls.addClassCleanup(cls.template.cleanup)
        cls.cfg, cls.genome, cls.source, cls.provided = fixtures._make_template(Path(cls.template.name))

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaia-ledger-case-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        shutil.copytree(self.template.name, self.root)
        self.eng = engine.Engine(self.root, copy.deepcopy(self.cfg), log=lambda *args: None)
        self.eng._load()

    def rows(self):
        return [json.loads(line) for line in self.eng.store.ledger.read_bytes().splitlines()]

    def write_rows(self, rows):
        self.eng.store.ledger.write_bytes(b"".join(provenance.canonical_json(row) + b"\n" for row in rows))

    def blocked(self):
        report = ledger.verify_ledger(self.eng.store)
        self.assertFalse(report["ok"], report)
        self.assertEqual(readiness.prepare(self.eng)["status"], "NOT_READY")
        with self.assertRaises((RuntimeError, ValueError)):
            self.eng.store.append_ledger_event("identity", {"type": "identity"})
        return report

    def test_genesis_and_chain_canonical_identity(self):
        rows = self.rows()
        self.assertEqual(rows[0]["event_type"], "baseline_initialized")
        self.assertEqual(rows[0]["sequence"], 1)
        self.assertIsNone(rows[0]["previous_hash"])
        self.assertEqual(rows[1]["previous_hash"], rows[0]["record_hash"])
        self.assertEqual([r["sequence"] for r in rows], list(range(1, len(rows) + 1)))
        for row in rows:
            payload = {k: v for k, v in row.items() if k != "record_hash"}
            self.assertEqual(row["record_hash"], provenance.digest(dict(reversed(list(payload.items())))))
        self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])
        self.assertTrue(readiness.g3_integrity(self.eng)["ok"])

    def test_all_hash_and_sequence_mutations_block(self):
        original = self.rows()
        mutations = (("payload", {"type": "init", "altered": True}), ("previous_hash", "0" * 64),
                     ("record_hash", "0" * 64), ("sequence", 0), ("sequence", -1),
                     ("sequence", 1), ("sequence", 99), ("ledger_schema", "other"),
                     ("event_id", "bad"), ("event_id", original[0]["event_id"]))
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                rows = copy.deepcopy(original)
                rows[1][field] = value
                self.write_rows(rows)
                self.blocked()
        self.write_rows(original)
        self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])

    def test_delete_reorder_duplicate_and_insert_are_detected(self):
        rows = self.rows()
        for changed in (rows[:1] + rows[2:], [rows[1], rows[0], *rows[2:]],
                        rows[:2] + [rows[1]] + rows[2:], rows[:1] + [rows[2]] + rows[1:]):
            self.write_rows(changed)
            self.blocked()

    def test_missing_ledger_or_genesis_blocks_without_recreation(self):
        rows = self.rows()
        self.write_rows(rows[1:])
        self.blocked()
        self.eng.store.ledger.unlink()
        self.blocked()
        self.assertFalse(self.eng.store.ledger.exists())

    def test_corrupt_json_and_partial_line_block_without_truncation(self):
        original = self.eng.store.ledger.read_bytes()
        for suffix in (b"{\n", b'{"sequence":', b"\xc3"):
            value = original + suffix
            self.eng.store.ledger.write_bytes(value)
            report = self.blocked()
            if not suffix.endswith(b"\n"):
                self.assertEqual(report["code"], "LEDGER_TRUNCATED_OR_PARTIAL")
            self.assertEqual(self.eng.store.ledger.read_bytes(), value)

    def test_missing_and_altered_evidence_block(self):
        path = self.eng.store.dir / self.provided["experiment_evidence_path"]
        original = path.read_bytes()
        path.unlink()
        self.blocked()
        path.write_bytes(original + b" ")
        self.blocked()

    def test_altered_manifest_and_artifacts_block(self):
        for name in ("manifest.json", "trainer.py", "genome.json"):
            path = self.eng.store.dir / "experiments/e00001" / name
            data = path.read_bytes()
            path.chmod(0o644)
            path.write_bytes(data + b" ")
            self.blocked()
            path.write_bytes(data)

    def test_valid_start_complete_accept_sequence(self):
        types = [r["event_type"] for r in self.rows()]
        self.assertEqual(types, ["baseline_initialized", "experiment_started", "experiment_completed", "candidate_accepted"])
        self.assertNotIn("trial_metrics", self.rows()[2]["payload"])
        self.assertTrue(self.rows()[2]["evidence_ref"])

    def new_start(self, eid="e00002"):
        g, src = self.eng.store.load_version()
        report = readiness.run_gates(self.eng, genome=g, source=src)
        self.assertEqual(report["status"], "READY_FOR_CAMPAIGN", report)
        self.eng._campaign_context = {key: report[key] for key in ("campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")}
        doc = manifest.build_experiment(self.eng, eid, self.eng.source_context(), g, src, g, src)
        directory = self.eng.store.dir / "experiments" / eid
        manifest.write_manifest(directory / "manifest.json", doc)
        manifest.write_manifest(directory / "genome.json", g)
        (directory / "trainer.py").write_text(src)
        payload = {"type": "start", "id": eid, "genome": g, "source_sha": doc["candidate_trainer_hash"],
                   **self.eng._campaign_context,
                   "experiment_manifest_hash": doc["manifest_hash"], "environment_hash": doc["environment_hash"],
                   "stable_version": "v0000"}
        self.eng.store.append(payload)
        return doc

    def test_explicit_abort_records_reason_and_does_not_accept(self):
        self.new_start()
        self.eng.store.append({"type": "end", "id": "e00002", "decision": "aborted", "reason": "STOP requested"})
        self.assertEqual(self.rows()[-1]["event_type"], "experiment_aborted")
        self.assertTrue(self.rows()[-1]["payload"]["reason_code"])
        self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])

    def test_orphan_is_not_repaired_or_truncated_automatically(self):
        self.new_start()
        before = self.eng.store.ledger.read_bytes()
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")
        self.assertEqual(self.eng.store.close_orphans(context=self.eng), 0)
        self.assertEqual(self.eng.store.close_orphans(), 0)
        self.assertEqual(before, self.eng.store.ledger.read_bytes())

    def test_missing_candidate_action_is_blocked_and_not_rebuilt(self):
        rows = self.rows()[:-1]
        self.write_rows(rows)
        self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])  # Valid append prefix, incomplete lifecycle.
        before = self.eng.store.ledger.read_bytes()
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(before, self.eng.store.ledger.read_bytes())

    def test_unexpected_valid_append_during_experiment_stops_execution(self):
        self.eng.state["n_experiments"] = 1
        self.eng.state["ref"] = {"cost": 0.05}
        self.eng.store.save_state(self.eng.state)
        original = evaluator.run_trial

        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            if self.eng._active_record is not None:
                self.eng.store.append_ledger_event("identity", {"type": "identity", "unexpected": True})
            return result

        with patch.object(evaluator, "run_trial", side_effect=changed):
            with self.assertRaisesRegex(engine.NeedsHuman, "LEDGER_UNEXPECTED_CHANGE"):
                self.eng.experiment(proposal=(G.new_genome(hp={"lr": 0.09}), ["lr"], None, 1.0))
        self.assertEqual(self.rows()[-1]["event_type"], "experiment_aborted")
        self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])
        self.assertEqual(self.eng.store.current_version(), "v0000")

    def test_rejection_has_distinct_result_and_action(self):
        # Build a fresh rejected result for an explicitly started real artifact.
        doc = self.new_start()
        directory = self.eng.store.dir / "experiments/e00002"
        evidence = {"type": "end", "id": "e00002", "decision": "rejected", "promotable": False,
                    **self.eng._campaign_context,
                    "experiment_manifest_hash": doc["manifest_hash"], "baseline_manifest_hash": doc["baseline_manifest_hash"],
                    "environment_hash": doc["environment_hash"], "candidate_genome_hash": doc["candidate_genome_hash"],
                    "candidate_trainer_hash": doc["candidate_trainer_hash"], "execution_id": doc["execution_id"],
                    "parent_version": doc["parent_version"], "started_at": doc["created_at"], "finished_at": manifest.timestamp(),
                    "trial_metrics": [], "sandbox_evidence_hash": provenance.digest([]), "reason": "did not improve"}
        evidence["evidence_hash"] = provenance.digest(evidence)
        manifest.write_manifest(directory / "evidence.json", evidence)
        self.eng.store.append(evidence)
        self.assertEqual([r["event_type"] for r in self.rows()[-2:]], ["experiment_completed", "candidate_rejected"])
        self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])

    def test_promote_and_cross_reference_version(self):
        self.eng.store.promote(self.genome, self.source, copy.deepcopy(self.provided), context=self.eng)
        row = self.rows()[-1]
        self.assertEqual(row["event_type"], "version_promoted")
        self.assertEqual(row["version"], "v0001")
        self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])
        path = self.eng.store.stable / "v0001/evidence.json"
        path.chmod(0o644)
        ev = json.loads(path.read_bytes())
        ev["promoted_from"] = "other"
        path.write_text(json.dumps(ev))
        self.blocked()

    def test_promote_without_acceptance_or_missing_version_blocks(self):
        self.eng.store.promote(self.genome, self.source, copy.deepcopy(self.provided), context=self.eng)
        rows = self.rows()
        bad = [r for r in rows if r["event_type"] != "candidate_accepted"]
        # Even a self-consistently rehashed malformed history fails semantics.
        previous = None
        for i, row in enumerate(bad, 1):
            row["sequence"], row["previous_hash"] = i, previous
            row["record_hash"] = provenance.digest({k: v for k, v in row.items() if k != "record_hash"})
            previous = row["record_hash"]
        self.write_rows(bad)
        self.assertIn("without acceptance", str(self.blocked()["errors"]))
        self.write_rows(rows)
        shutil.rmtree(self.eng.store.stable / "v0001")
        self.blocked()

    def test_fault_boundaries_never_auto_repair(self):
        original = self.eng.store.ledger.read_bytes()
        for fault in ("before_append", "during_write", "after_write_before_fsync", "after_fsync"):
            self.eng.store.ledger.write_bytes(original)
            with self.assertRaises(RuntimeError):
                self.eng.store.append_ledger_event("identity", {"type": "identity"}, _test_fault=fault)
            checked = ledger.verify_ledger(self.eng.store)
            if fault == "during_write":
                self.assertFalse(checked["ok"])
                self.assertEqual(checked["code"], "LEDGER_TRUNCATED_OR_PARTIAL")
            else:
                self.assertTrue(checked["ok"], checked)
                self.assertEqual(len(checked["records"]), 4 if fault == "before_append" else 5)

    def test_crash_after_publication_recovers_only_missing_promotion_once(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=fixtures._publish_child, args=(self.root, self.cfg, self.genome, self.source,
                              self.provided, None, None, "after_publication_before_ledger"))
        before = self.rows()
        process.start()
        process.join(30)
        self.assertEqual(process.exitcode, 71)
        process.close()
        self.assertEqual(self.eng.store.current_version(), "v0001")
        self.assertEqual(len(self.rows()), len(before))
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "READY", report)
        after = self.rows()
        self.assertEqual(after[:-1], before)
        self.assertEqual(after[-1]["event_type"], "version_promoted")
        self.assertTrue(after[-1]["payload"]["recovered_after_crash"])
        self.eng.store.recover_publications(self.eng)
        self.assertEqual(after, self.rows())
        self.assertFalse((self.eng.store.stable / "v0002").exists())

    def test_concurrent_writers_assign_unique_sequences(self):
        ctx = multiprocessing.get_context("fork")
        barrier, queue = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=writer, args=(self.root, self.cfg, barrier, queue)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(30)
                self.assertEqual(process.exitcode, 0)
            self.assertEqual([queue.get(timeout=5) for _ in processes], [True, True])
            rows = self.rows()
            self.assertEqual([r["sequence"] for r in rows], list(range(1, 11)))
            self.assertTrue(ledger.verify_ledger(self.eng.store)["ok"])
        finally:
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            queue.close()
            queue.join_thread()

    def test_previous_mvp_without_ledger_schema_is_legacy_and_untouched(self):
        state = self.eng.store.load_state()
        del state["ledger_schema"]
        self.eng.store.save_state(state)
        before = self.eng.store.ledger.read_bytes()
        self.assertEqual(provenance.state_schema(self.eng.store.dir), "LEGACY_NON_CERTIFIABLE")
        self.assertEqual(readiness.prepare(self.eng)["status"], "NOT_READY")
        self.assertEqual(before, self.eng.store.ledger.read_bytes())


if __name__ == "__main__":
    unittest.main()
