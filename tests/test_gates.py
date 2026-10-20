"""G0-G5 coordinator and the pre-promotion invariant. No certification A/B."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gaia import engine, genome as G, manifest, provenance, readiness
from gaia.protected import evaluator
import test_publication as fixtures


class GatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory(prefix="gaia-gates-template-")
        cls.addClassCleanup(cls.template.cleanup)
        cls.cfg, cls.genome, cls.source, cls.provided = fixtures._make_template(Path(cls.template.name))

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaia-gates-case-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        shutil.copytree(self.template.name, self.root)
        self.eng = engine.Engine(self.root, copy.deepcopy(self.cfg), log=lambda *args: None)
        self.eng._load()
        self.parent_g, self.parent = self.eng.store.load_version()

    def test_g0_valid_identity_and_real_sandbox(self):
        result = readiness.g0_runtime(self.eng, self.parent)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["cpu_sandbox_status"], "CPU_SANDBOX_VERIFIED")

    def test_g0_snapshot_failure_never_runs_benchmark(self):
        path = self.eng.store.dir / "provenance/snapshots/src-000001/gaia/stats.py"
        path.chmod(0o644)
        path.write_text("changed")
        with patch.object(self.eng, "trial") as trial, patch.object(evaluator, "check_correctness") as probe:
            result = readiness.g0_runtime(self.eng, self.parent)
        self.assertFalse(result["ok"])
        self.assertIn("SOURCE_INTEGRITY_FAILED", result["reason_codes"])
        trial.assert_not_called()
        probe.assert_not_called()

    def test_g0_real_sandbox_failure_blocks(self):
        with patch.object(evaluator, "check_correctness", side_effect=RuntimeError("SANDBOX_UNAVAILABLE")):
            result = readiness.g0_runtime(self.eng, self.parent)
        self.assertFalse(result["ok"])
        self.assertIn("SANDBOX_UNAVAILABLE", result["reason_codes"])

    def test_g0_ambiguous_recovery_blocks(self):
        (self.eng.store.dir / ".rollback-intent-bad.json").write_text("{}")
        result = readiness.g0_runtime(self.eng, self.parent)
        self.assertFalse(result["ok"])
        self.assertIn("RECOVERY_REQUIRED", result["reason_codes"])

    def test_g1_render_mismatch_invalid_genome_and_guard(self):
        self.assertIn("SOURCE_RENDER_MISMATCH", readiness.g1_candidate(self.eng, self.genome, self.source + "\n")["reason_codes"])
        self.assertIn("INVALID_GENOME", readiness.g1_candidate(self.eng, {}, "")["reason_codes"])
        with patch.object(G, "render", return_value="import os\n"):
            result = readiness.g1_candidate(self.eng, self.genome, "import os\n")
        self.assertIn("GUARD_REJECTED", result["reason_codes"])

    def test_g1_candidate_load_failure(self):
        with patch.object(evaluator, "check_correctness", side_effect=RuntimeError("worker cannot load")):
            result = readiness.g1_candidate(self.eng, self.genome, self.source)
        self.assertFalse(result["ok"])
        self.assertIn("CANDIDATE_LOAD_FAILED", result["reason_codes"])

    def healthy(self, cost=1.0):
        return {"status": "ok", "reached": True, "cost_s": cost, "peak_rss_mb": 50,
                "sandbox_validation": True, "promotable": True}

    def test_g2_quality_variability_and_drift_failures(self):
        cases = [([self.healthy() | {"reached": False, "cost_s": None}] * 5, "BASELINE_QUALITY_FAILED"),
                 ([self.healthy(c) for c in (1, .1, 2, .1, 3)], "BASELINE_UNSTABLE"),
                 ([self.healthy(c) for c in (1, 1, 2, 2, 2)], "BASELINE_DRIFT")]
        for trials, code in cases:
            with self.subTest(code=code), patch.object(self.eng, "trial", side_effect=trials) as run:
                result = readiness.g2_reliability(self.eng, self.parent)
                self.assertFalse(result["ok"])
                self.assertIn(code, result["reason_codes"])
                self.assertEqual(run.call_count, 5)

    def test_g3_ledger_corruption(self):
        with self.eng.store.ledger.open("ab") as stream:
            stream.write(b"partial")
        result = readiness.g3_integrity(self.eng)
        self.assertFalse(result["ok"])
        self.assertIn("LEDGER_INVALID", result["reason_codes"])

    def test_g3_manifest_corruption(self):
        path = self.eng.store.stable / "v0000/manifest.json"
        path.chmod(0o644)
        path.write_text("{}")
        result = readiness.g3_integrity(self.eng)
        self.assertFalse(result["ok"])
        self.assertIn("MANIFEST_INVALID", result["reason_codes"])

    def test_g3_current_lineage_mismatch(self):
        (self.eng.store.stable / "CURRENT").write_text("v9999\n")
        result = readiness.g3_integrity(self.eng)
        self.assertFalse(result["ok"])
        self.assertIn("LINEAGE_INVALID", result["reason_codes"])

    def test_g4_faulty_null_and_insensitive_benchmark(self):
        with patch.object(self.eng, "trial", return_value=self.healthy()), \
                patch.object(readiness.stats, "decide", return_value={"decision": "accepted", "ratio": .5}):
            result = readiness.g4_controls(self.eng, self.parent)
        self.assertFalse(result["ok"])
        self.assertIn("EVALUATOR_CONTROL_FAILED", result["reason_codes"])
        with patch.object(self.eng, "trial", return_value=self.healthy()):
            result = readiness.g4_controls(self.eng, self.parent)
        self.assertFalse(result["ok"])
        self.assertIn("BENCHMARK_DISCRIMINATION_FAILED", result["reason_codes"])

    def test_g5_invalid_budget_ram_disk_and_cli_overrides(self):
        self.eng.invocation = {"minutes": self.eng.lim["max_total_minutes"] + 1}
        self.assertIn("BUDGET_INVALID", readiness.g5_budget(self.eng)["reason_codes"])
        self.eng.invocation = {}
        self.eng.lim["max_experiments"] = 0
        self.assertIn("BUDGET_INVALID", readiness.g5_budget(self.eng)["reason_codes"])
        self.eng.lim["max_experiments"] = self.cfg["limits"]["max_experiments"]
        host = manifest.host_identity(self.root, self.eng.store.dir)
        host["capabilities"]["available_ram_mb"] = 1
        with patch.object(manifest, "host_identity", return_value=host):
            self.assertIn("RESOURCE_BUDGET_FAILED", readiness.g5_budget(self.eng)["reason_codes"])
        host = manifest.host_identity(self.root, self.eng.store.dir)
        host["information"]["state_free_mb"] = 0
        with patch.object(manifest, "host_identity", return_value=host):
            self.assertIn("DISK_BUDGET_FAILED", readiness.g5_budget(self.eng)["reason_codes"])

    def test_real_gate_report_is_uniform_hashed_and_not_a_handshake_dump(self):
        experiment = manifest._document(self.eng.store.dir / self.provided["experiment_manifest_path"])
        checked = readiness.validate_report(self.eng, experiment)
        self.assertTrue(checked["ok"], checked)
        report = checked["report"]
        self.assertEqual(report["overall"], "PASS")
        self.assertEqual(set(report["gates"]), set(readiness.GATE_NAMES))
        for name in readiness.GATE_NAMES:
            gate = report["gates"][name]
            self.assertEqual(gate["status"], "PASS")
            self.assertTrue(gate["started_at"])
            self.assertTrue(gate["finished_at"])
            self.assertNotIn("sandbox_evidence", gate["details"])
            self.assertEqual(gate["evidence_hash"], provenance.digest({k: v for k, v in gate.items() if k != "evidence_hash"}))

    def test_gates_do_not_reset_search_rng_history_or_experiment_counter(self):
        self.eng.rng.random(7)
        rng_before = copy.deepcopy(self.eng.rng.bit_generator.state)
        history_before, state_before = self.eng.hist, self.eng.state
        count_before = self.eng.state["n_experiments"]
        report = readiness.run_gates(self.eng, genome=self.genome, source=self.source)
        self.assertEqual(report["status"], "READY_FOR_CAMPAIGN", report)
        self.assertEqual(rng_before, self.eng.rng.bit_generator.state)
        self.assertIs(history_before, self.eng.hist)
        self.assertIs(state_before, self.eng.state)
        self.assertEqual(count_before, self.eng.state["n_experiments"])

    def test_each_single_gate_failure_stops_before_start_or_promotion(self):
        functions = ("g0_runtime", "g1_candidate", "g2_reliability", "g3_integrity", "g4_controls", "g5_budget")
        before = self.eng.store.ledger.read_bytes()
        for function in functions:
            with self.subTest(gate=function), patch.object(readiness, function, return_value={"ok": False, "reason_codes": ["INJECTED_GATE_FAILURE"]}), \
                    patch.object(self.eng.store, "promote") as promote:
                with self.assertRaisesRegex(engine.NeedsHuman, "GATES_BLOCKED"):
                    self.eng.experiment(proposal=(G.new_genome(hp={"lr": .09}), ["lr"], None, 1.0))
                promote.assert_not_called()
                self.assertEqual(before, self.eng.store.ledger.read_bytes())

    def test_all_gates_pass_then_screening_reject_is_not_gate_failure(self):
        self.eng.state.update(n_experiments=1, ref={"cost": .000001})
        self.eng.store.save_state(self.eng.state)
        result = self.eng.experiment(proposal=(G.new_genome(hp={"lr": .09}), ["lr"], None, 1.0))
        self.assertEqual(result, "rejected")
        evidence = json.loads((self.eng.store.dir / "experiments/e00002/evidence.json").read_bytes())
        self.assertEqual(evidence["result_code"], "CANDIDATE_REJECTED")
        self.assertTrue(evidence["overall_gates_passed"])
        self.assertTrue(evidence["campaign_id"])

    def test_inconclusive_confirmation_is_not_a_gate_failure(self):
        self.eng.state.update(n_experiments=1, ref={"cost": 1.0})
        self.eng.store.save_state(self.eng.state)
        candidate = G.new_genome(hp={"lr": .09})
        source = G.render(candidate)
        real = evaluator.run_trial
        candidate_count = 0

        def measured(*args, **kwargs):
            nonlocal candidate_count
            result = real(*args, **kwargs)
            if self.eng._active_record is not None:
                if args[0] == source:
                    result["cost_s"] = .8 if candidate_count == 0 else (.8, .99, .99, .98, .94)[(candidate_count - 1) % 5]
                    candidate_count += 1
                else:
                    result["cost_s"] = 1.0
            return result

        # Control costs only to exercise the unchanged inconclusive branch;
        # all gates/sandbox/quality run normally, no promotion is requested.
        with patch.object(evaluator, "run_trial", side_effect=measured), patch.object(self.eng.store, "promote") as promote:
            result = self.eng.experiment(proposal=(candidate, ["lr"], None, 1.0))
            promote.assert_not_called()
        self.assertEqual(result, "deferred")
        evidence = json.loads((self.eng.store.dir / "experiments/e00002/evidence.json").read_bytes())
        self.assertEqual(evidence["result_code"], "INCONCLUSIVE")
        self.assertTrue(evidence["overall_gates_passed"])

    def test_start_without_a_gate_report_cannot_be_created(self):
        self.eng._campaign_context = None
        with self.assertRaisesRegex(ValueError, "G0-G5"):
            manifest.build_experiment(self.eng, "e00002", self.eng.source_context(), self.genome, self.source, self.parent_g, self.parent)

    def test_gate_report_tampering_blocks_pre_promotion(self):
        doc = manifest._document(self.eng.store.dir / self.provided["experiment_manifest_path"])
        path = self.eng.store.dir / doc["gate_report_path"]
        path.chmod(0o644)
        path.write_text("{}")
        with self.assertRaises((ValueError, RuntimeError)):
            readiness.pre_promotion(self.eng, self.genome, self.source, self.provided)

    def test_staging_appearing_after_gates_blocks_pre_promotion(self):
        (self.eng.store.stable / (".staging-v0001-" + "a" * 32)).mkdir()
        with self.assertRaisesRegex(ValueError, "pending staging"):
            readiness.pre_promotion(self.eng, self.genome, self.source, self.provided)

    def test_environment_or_current_change_blocks_pre_promotion(self):
        self.eng.acc["min_gain"] = .01
        with self.assertRaises(ValueError):
            readiness.pre_promotion(self.eng, self.genome, self.source, self.provided)
        self.eng.acc["min_gain"] = self.cfg["acceptance"]["min_gain"]
        (self.eng.store.stable / "CURRENT").write_text("v9999\n")
        with self.assertRaises(ValueError):
            readiness.pre_promotion(self.eng, self.genome, self.source, self.provided)

    def test_store_rejects_missing_pre_promotion_and_changed_ledger_tip(self):
        missing = {k: v for k, v in self.provided.items() if not k.startswith("pre_promotion")}
        with self.assertRaises((ValueError, KeyError)):
            self.eng.store.promote(self.genome, self.source, missing, context=self.eng)
        self.eng.store.append_ledger_event("identity", {"type": "identity", "after_final_validation": True})
        with self.assertRaises(ValueError):
            self.eng.store.promote(self.genome, self.source, self.provided, context=self.eng)

    def test_skip_gate_and_force_are_rejected_before_engine_run(self):
        spec = importlib.util.spec_from_file_location("gaia_gates_cli", Path(__file__).resolve().parents[1] / "gaia.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        for skip, force in ((True, False), (False, True)):
            with patch.object(cli, "make") as make:
                self.assertEqual(cli.cmd_run(SimpleNamespace(skip_gate=skip, force=force)), 30)
                make.assert_not_called()

    def test_cli_new_state_is_blocked_without_attempting_a_historical_report(self):
        spec = importlib.util.spec_from_file_location("gaia_new_state_cli", Path(__file__).resolve().parents[1] / "gaia.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        cfg = copy.deepcopy(self.cfg)
        cfg["workload"]["state_dir"] = "new_explicit_baseline_required"
        new = engine.Engine(self.root, cfg, log=lambda *args: None)
        cli.engine = engine
        cli.ROOT = self.root
        cli.report = SimpleNamespace(write=lambda eng: self.fail("No report should be read from an uninitialized state"))
        args = SimpleNamespace(skip_gate=False, force=False, keep_going=False, minutes=None, max_experiments=None, no_meta=False)
        with patch.object(cli, "make", return_value=new):
            self.assertEqual(cli.cmd_run(args), engine.EXIT["needs_human"])
        self.assertEqual(provenance.state_schema(new.store.dir), "NEW")


if __name__ == "__main__":
    unittest.main()
