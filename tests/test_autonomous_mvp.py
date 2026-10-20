"""Verification-only tests. The ONE real B is executed explicitly, not by tests.

No successful autonomous campaign is manufactured here. Exhaustion/error paths
use an Engine.run double; the live invocation uses the unmodified real method.
"""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gaia import autonomous_mvp as B, config, engine, genome as G, ledger, manifest, provenance, readiness
from gaia.protected import benchmark

ROOT = Path(__file__).resolve().parents[1]


class AutonomousVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaia-b-verifier-unit-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "gaia", self.root / "gaia", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "gaia.py", self.root / "gaia.py")
        self.a = self.root / "state_certification_cpu_previous"
        self.a.mkdir()
        (self.a / "state.json").write_text('{"certification_only":true,"state_purpose":"pipeline_certification","n_experiments":9}')
        (self.a / "priors.json").write_text('{"not_available_to_B":true}')
        self.a_before = {p.name: p.read_bytes() for p in self.a.iterdir()}

    def baseline(self):
        cfg = B.new_configuration(self.root)
        eng = engine.Engine(self.root, cfg, log=lambda *args: None)
        bench = copy.deepcopy(benchmark.PROFILES[cfg["benchmark_profile"]])
        bench["calibrated"] = {task: {"target": 0.0, "ref_cost_s": 1.0, "cv": .01} for task in ("main", "audit")}
        with patch.object(benchmark, "calibrate", return_value=bench):
            eng.init(initialize_mvp=True)
        eng._load()
        return cfg, eng, manifest._document(eng.store.stable / "v0000/manifest.json")

    def test_b_state_is_independent_with_normal_configuration_and_budget(self):
        cfg = B.new_configuration(self.root)
        self.assertTrue(cfg["workload"]["state_dir"].startswith(B.PREFIX))
        self.assertNotEqual(cfg["workload"]["state_dir"], self.a.name)
        self.assertIs(cfg["certification"], False)
        self.assertIs(cfg["certification_only"], False)
        self.assertEqual(cfg["state_purpose"], "autonomous_mvp")
        for field in ("limits", "acceptance", "readiness", "meta", "research", "benchmark_profile"):
            self.assertEqual(cfg[field], config.DEFAULTS[field])
        self.assertEqual(self.a_before, {p.name: p.read_bytes() for p in self.a.iterdir()})

    def test_manual_candidate_injection_is_rejected_before_any_experiment(self):
        cfg = B.new_configuration(self.root)
        eng = engine.Engine(self.root, cfg, log=lambda *args: None)
        with self.assertRaisesRegex(engine.NeedsHuman, "EXTERNAL_PROPOSAL_FORBIDDEN"):
            eng.experiment(proposal=(G.new_genome(), [], None, None))
        self.assertFalse(eng.store.ledger.exists())
        with self.assertRaises(TypeError):
            B.run(self.root, candidate=G.new_genome())

    def test_certification_state_or_configuration_cannot_be_opened_as_b(self):
        cfg = B.new_configuration(self.root)
        cfg["workload"]["state_dir"] = self.a.name
        with self.assertRaises(ValueError):
            engine.Engine(self.root, cfg)
        (self.root / "gaia.json").write_text(json.dumps({"certification_only": True}))
        with self.assertRaises(ValueError):
            B.new_configuration(self.root)
        self.assertEqual(self.a_before, {p.name: p.read_bytes() for p in self.a.iterdir()})

    def test_frozen_budget_rejects_threshold_seed_and_budget_overrides(self):
        cfg, eng, baseline = self.baseline()
        frozen = B.frozen_budget(cfg)
        B.validate_budget(cfg, frozen, baseline)
        changed = copy.deepcopy(cfg)
        changed["acceptance"]["min_gain"] = .00001
        with self.assertRaises(ValueError):
            B.validate_budget(changed, frozen, baseline)
        changed = copy.deepcopy(baseline)
        changed["effective_config"]["benchmark"]["tiers"]["confirm"][0] = 99
        with self.assertRaises(ValueError):
            B.validate_budget(cfg, frozen, changed)
        changed_cfg = copy.deepcopy(cfg)
        changed_cfg["limits"]["max_total_minutes"] *= 2
        replacement = B.frozen_budget(changed_cfg)
        with self.assertRaises(ValueError):
            B.validate_budget(changed_cfg, replacement, baseline)
        self.assertEqual(frozen["minutes"], 60)
        self.assertEqual(frozen["max_experiments"], 100000)

    def test_skip_and_force_do_not_reach_normal_campaign(self):
        spec = importlib.util.spec_from_file_location("gaia_b_cli_unit", ROOT / "gaia.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        for skip, force in ((True, False), (False, True)):
            with patch.object(cli, "make") as make:
                self.assertEqual(cli.cmd_run(SimpleNamespace(skip_gate=skip, force=force)), 30)
                make.assert_not_called()

    def test_one_default_engine_run_and_exhaustion_is_not_infrastructure_failure(self):
        bench = copy.deepcopy(benchmark.PROFILES[config.DEFAULTS["benchmark_profile"]])
        bench["calibrated"] = {task: {"target": 0.0, "ref_cost_s": 1.0, "cv": .01} for task in ("main", "audit")}
        with patch.object(benchmark, "calibrate", return_value=bench), \
                patch.object(engine.Engine, "run", return_value="budget") as run:
            result = B.run(self.root, log=lambda *args: None)
        run.assert_called_once_with()
        self.assertEqual(result["overall_status"], "FAIL")
        self.assertEqual(result["failure_type"], "AUTONOMOUS_SEARCH_EXHAUSTED")
        self.assertFalse(result["autonomous_self_improvement_certified"])
        self.assertEqual(result["proposal_count"], 0)
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["normal_engine_run_calls"], 1)
        self.assertTrue(Path(result["report_path"]).exists())
        persisted = json.loads(Path(result["report_path"]).read_bytes())
        self.assertEqual(persisted["report_hash"], provenance.digest({k: v for k, v in persisted.items() if k != "report_hash"}))
        self.assertEqual(self.a_before, {p.name: p.read_bytes() for p in self.a.iterdir()})

    def test_certification_controlled_trace_cannot_be_certified_as_search(self):
        cfg, eng, baseline = self.baseline()
        chain = ledger.verify_ledger(eng.store)
        h = eng.hist
        before = {"items": h.items, "seen": sorted(h.seen), "op_n": h.op_n, "op_sum": h.op_sum,
                  "since_improve": h.since_improve, "best": h.best}
        trace = {"proposal_schema": "cpu_search_proposal_v1", **provenance.purpose_metadata(cfg), "proposal_index": 1,
                 "candidate_origin": "certification_controlled", "proposal_method": "certification_controlled",
                 "input": {"strategy": eng.state["strategy"], "rng_state": eng.rng.bit_generator.state,
                           "history_hash": provenance.digest(before), "history_items": 1, "unlocked": [],
                           "operator_counts": {}, "operator_rewards": {},
                           "ledger_sequence": len(chain["records"]), "ledger_head": chain["last_hash"]}}
        trace["trace_hash"] = provenance.digest(trace)
        manifest.write_manifest(eng.store.dir / "proposals/p000001.json", trace)
        with self.assertRaisesRegex(ValueError, "NON_SEARCH_PROPOSAL"):
            B.verify_proposals(eng, baseline, chain)

    def test_observational_trace_replays_normal_rng_without_submitting_any_candidate(self):
        cfg, eng, baseline = self.baseline()
        budget = B.frozen_budget(cfg)
        # This unit test stops at G0, before any experiment or benchmark. It
        # checks trace/replay only; it is not an execution/certification of B.
        with patch.object(readiness, "g0_runtime", return_value={"ok": False, "reason_codes": ["UNIT_STOP_BEFORE_EXPERIMENT"]}):
            for _ in range(3):
                with self.assertRaisesRegex(engine.NeedsHuman, "GATES_BLOCKED"):
                    eng.experiment()
        chain = ledger.verify_ledger(eng.store)
        summaries = B.verify_proposals(eng, baseline, chain)
        self.assertEqual(len(summaries), 3)
        self.assertTrue(all(row["candidate_origin"] == "search" and row["proposal_method"] == "gaia.search.Strategy.propose" for row in summaries))
        self.assertFalse(any(row["event_type"] == "experiment_started" for row in chain["records"]))
        B.validate_budget(cfg, budget, baseline)

    def test_promotion_flag_survives_rollback_but_missing_final_proof_never_passes(self):
        self.assertEqual(B.completion_flags(True, True, True, True), {
            "autonomous_promotion_certified": True, "autonomous_self_improvement_certified": True, "overall_status": "PASS"})
        failed = B.completion_flags(True, True, False, True)
        self.assertTrue(failed["autonomous_promotion_certified"])
        self.assertFalse(failed["autonomous_self_improvement_certified"])
        self.assertEqual(failed["overall_status"], "FAIL")
        self.assertEqual(B.failure_category("budget", "no promotion"), "AUTONOMOUS_SEARCH_EXHAUSTED")
        self.assertEqual(B.failure_category("needs_human", "SANDBOX_UNAVAILABLE"), "INFRASTRUCTURE_FAILURE")


if __name__ == "__main__":
    unittest.main()
