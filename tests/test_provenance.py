"""Local CPU provenance; no version-control tool is used by these tests."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gaia import config, engine, provenance, readiness, genome as G

ROOT = Path(__file__).resolve().parents[1]
GOOD_BWRAP = {"available": True, "verified": True, "binary": "/usr/bin/bwrap",
              "reason": None, "capabilities": ["user_namespace", "pid_namespace", "net_namespace"]}


class BwrapTests(unittest.TestCase):
    def test_absent(self):
        with patch.object(shutil, "which", return_value=None):
            result = provenance.bwrap_capability()
        self.assertFalse(result["available"])
        self.assertFalse(result["verified"])

    def test_failure_success_and_timeout(self):
        with patch.object(shutil, "which", return_value="/usr/bin/bwrap"), \
                patch.object(subprocess, "run") as run:
            run.return_value = SimpleNamespace(returncode=1, stderr="namespaces denied")
            self.assertFalse(provenance.bwrap_capability()["verified"])
            run.return_value = SimpleNamespace(returncode=0, stderr="")
            result = provenance.bwrap_capability()
            self.assertTrue(result["verified"])
            for flag in ("--unshare-user", "--unshare-pid", "--unshare-net"):
                self.assertIn(flag, run.call_args.args[0])
            self.assertEqual(len(result["capabilities"]), 3)
            run.side_effect = subprocess.TimeoutExpired("bwrap", 5)
            self.assertFalse(provenance.bwrap_capability()["verified"])


class LocalProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "gaia", self.root / "gaia", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "gaia.py", self.root / "gaia.py")
        (self.root / "requirements.txt").write_text("numpy>=1.24,<3\n")
        self.eng = engine.Engine(self.root, config.load(self.root), log=lambda *args: None)
        self.smoke = patch.object(provenance, "bwrap_capability", return_value=GOOD_BWRAP)
        self.smoke.start()
        self.addCleanup(self.smoke.stop)

    def initialize(self, eng=None):
        eng = eng or self.eng
        bench = json.loads(json.dumps(engine.benchmark.PROFILES["easy"]))
        for task in bench["tasks"].values():
            task.update(d=96, teacher_hidden=192, k=16, n_train=2000, n_val=1000, noise=.05)
        bench.update(eval_every=500, max_batches=1000)
        bench["calibrated"] = {"main": {"target": 0.0, "ref_cost_s": 1.0}, "audit": {"target": 0.0, "ref_cost_s": 1.0}}
        with patch.object(engine.benchmark, "calibrate", return_value=bench):
            self.assertTrue(eng.init(initialize_mvp=True))
        return eng.store.dir / "provenance/snapshots/src-000001"

    def mutate(self, path, content):
        path.chmod(0o644)
        path.write_text(content)

    def blocked(self):
        with patch.object(readiness, "run_gates") as gates:
            result = readiness.prepare(self.eng, refreeze=True)
            self.assertEqual(result["status"], "NOT_READY")
            self.assertTrue(result["requirements"]["reasons"])
            gates.assert_not_called()
        self.assertEqual(self.eng.run(), "needs_human")
        return result["requirements"]["source"]

    def test_new_requires_explicit_initialization(self):
        with patch.object(readiness, "run_gates") as gates:
            self.assertEqual(readiness.prepare(self.eng)["status"], "NOT_READY")
            gates.assert_not_called()
        self.assertEqual(self.eng.run(), "needs_human")
        self.assertEqual(list(self.eng.store.dir.iterdir()), [])
        with self.assertRaisesRegex(ValueError, "explicit"):
            self.eng.init()
        self.assertEqual(provenance.state_schema(self.eng.store.dir), "NEW")

    def test_new_creates_snapshot_required_sources_and_baseline_reference(self):
        directory = self.initialize()
        self.assertEqual(provenance.state_schema(self.eng.store.dir), "MVP_CPU_V1")
        for relative in provenance.source_paths(self.root):
            self.assertEqual((directory / relative).read_bytes(), (self.root / relative).read_bytes())
        self.assertTrue((directory / "effective-config.json").is_file())
        self.assertFalse((directory / "gaia/appliance_image.py").exists())
        self.assertFalse((directory / "gaia/gaia_transformer").exists())
        self.assertFalse(list(directory.rglob("__pycache__")))
        state = self.eng.store.load_state()
        evidence = json.loads((self.eng.store.stable / "v0000/evidence.json").read_text())
        self.assertEqual(evidence["source_snapshot"], state["source_snapshot"])
        self.assertTrue(evidence["execution_id"])
        self.assertEqual(self.eng.store.records()[0]["source_snapshot"], state["source_snapshot"])

    def test_manifest_and_canonical_hashes(self):
        directory = self.initialize()
        manifest = json.loads((directory / "manifest.json").read_text())
        for entry in manifest["files"]:
            self.assertEqual(hashlib.sha256((directory / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])
        self.assertEqual(manifest["aggregate_sha256"], provenance.aggregate_hash(manifest["files"], self.eng.cfg))
        self.assertEqual(manifest["aggregate_sha256"], provenance.aggregate_hash(list(reversed(manifest["files"])), self.eng.cfg))
        self.assertTrue(provenance.validate_snapshot(directory, self.eng.state["source_snapshot"])["ok"])
        self.assertTrue(provenance.prerequisites(self.eng)["ok"])

    def test_modified_snapshot_blocks(self):
        directory = self.initialize()
        self.mutate(directory / "gaia/stats.py", "# altered")
        self.assertIn("gaia/stats.py", self.blocked()["modified"])

    def test_deleted_snapshot_file_blocks(self):
        directory = self.initialize()
        (directory / "gaia/engine.py").unlink()
        self.assertIn("gaia/engine.py", self.blocked()["missing"])

    def test_extra_snapshot_file_blocks(self):
        directory = self.initialize()
        (directory / "gaia/protected/extra.py").write_text("# unexpected")
        self.assertFalse(provenance.validate_snapshot(directory)["ok"])
        self.blocked()

    def test_altered_manifest_blocks(self):
        directory = self.initialize()
        path = directory / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["created_at"] = "changed"
        self.mutate(path, json.dumps(manifest))
        self.assertFalse(self.blocked()["manifest"])

    def test_rehashed_manifest_still_rejected_by_baseline_anchor(self):
        directory = self.initialize()
        path = directory / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["created_at"] = "changed"
        del manifest["manifest_sha256"]
        manifest["manifest_sha256"] = provenance.digest(manifest)
        self.mutate(path, json.dumps(manifest))
        self.assertFalse(self.blocked()["manifest"])

    def test_missing_manifest_or_reference_blocks(self):
        directory = self.initialize()
        (directory / "manifest.json").unlink()
        self.blocked()

    def test_baseline_reference_mismatch_blocks(self):
        self.initialize()
        path = self.eng.store.stable / "v0000/evidence.json"
        evidence = json.loads(path.read_text())
        evidence["source_snapshot"]["aggregate_sha256"] = "0" * 64
        self.mutate(path, json.dumps(evidence))
        self.blocked()
        del self.eng.state["source_snapshot"]
        self.eng.store.save_state(self.eng.state)
        self.blocked()

    def test_development_change_preserves_old_snapshot_and_new_line_is_explicit(self):
        directory = self.initialize()
        before = {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
        path = self.root / "gaia/stats.py"
        path.write_text(path.read_text() + "\n# development change\n")
        self.assertIn("gaia/stats.py", self.blocked()["comparison"]["modified"])
        self.assertTrue(provenance.validate_snapshot(directory, self.eng.state["source_snapshot"])["ok"])
        cfg = config.load(self.root)
        cfg["workload"]["state_dir"] = "state_new_line"
        new_engine = engine.Engine(self.root, cfg, log=lambda *args: None)
        with self.assertRaisesRegex(ValueError, "explicit"):
            new_engine.init()
        new_directory = self.initialize(new_engine)
        self.assertNotEqual(self.eng.state["source_snapshot"]["aggregate_sha256"], new_engine.state["source_snapshot"]["aggregate_sha256"])
        self.assertTrue(provenance.prerequisites(new_engine)["ok"])
        self.assertTrue(provenance.validate_snapshot(new_directory)["ok"])
        self.assertEqual(before, {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()})

    def test_runtime_and_config_changes_block(self):
        self.initialize()
        self.eng.cfg["acceptance"]["min_gain"] = 0.01
        self.blocked()
        self.eng.cfg = config.load(self.root)
        actual = provenance.runtime_identity()
        with patch.object(provenance, "runtime_identity", return_value={**actual, "numpy": "changed"}):
            self.blocked()

    def test_comparison_reports_new_and_missing_relevant_sources(self):
        directory = self.initialize()
        (self.root / "gaia/protected/extra.py").write_text("# extra")
        (self.root / "gaia/search.py").unlink()
        result = provenance.compare_sources(self.root, directory, self.eng.cfg)
        self.assertIn("gaia/protected/extra.py", result["new"])
        self.assertIn("gaia/search.py", result["missing"])
        self.blocked()

    def test_legacy_unchanged(self):
        state = self.eng.store.dir / "state.json"
        state.write_text('{"n_experiments": 1}')
        before = state.read_bytes()
        for initialize in (True, False):
            result = readiness.prepare(self.eng, refreeze=True, initialize_mvp=initialize)
            self.assertEqual(result["requirements"]["state_schema"], "LEGACY_NON_CERTIFIABLE")
            self.assertEqual(result["status"], "NOT_READY")
        self.assertEqual(self.eng.run(), "needs_human")
        self.assertEqual(state.read_bytes(), before)
        self.assertEqual(list(self.eng.store.dir.iterdir()), [state])

    def test_bwrap_absent_or_invalid_blocks_new_and_existing(self):
        for initialized in (False, True):
            if initialized:
                self.initialize()
            for available in (False, True):
                failed = {**GOOD_BWRAP, "available": available, "verified": False, "reason": "smoke denied"}
                with patch.object(provenance, "bwrap_capability", return_value=failed):
                    result = readiness.prepare(self.eng, initialize_mvp=not initialized)
                    self.assertEqual(result["status"], "NOT_READY")
                    self.assertIn("smoke denied", result["requirements"]["reasons"])

    def test_ready_requires_all_gates_and_valid_local_snapshot(self):
        bench = json.loads(json.dumps(engine.benchmark.PROFILES["easy"]))
        bench["calibrated"] = {"main": {"target": 0.0, "ref_cost_s": 1.0}, "audit": {"target": 0.0, "ref_cost_s": 1.0}}
        passing = {"ok": True}
        with patch.object(engine.benchmark, "calibrate", return_value=bench), \
                patch.object(readiness, "g0_runtime", return_value=passing), \
                patch.object(readiness, "g1_correctness", return_value=passing), \
                patch.object(readiness, "g2_reliability", return_value=passing), \
                patch.object(readiness, "g3_integrity", return_value=passing), \
                patch.object(readiness, "g4_controls", return_value=passing), \
                patch.object(readiness, "g5_budget", return_value=passing):
            result = readiness.prepare(self.eng, initialize_mvp=True)
        self.assertEqual(result["status"], "READY_FOR_CAMPAIGN")
        self.assertTrue(result["requirements"]["source"]["integrity"])
        self.assertEqual(readiness.prepare(self.eng)["status"], "READY_FOR_CAMPAIGN")
        self.mutate(self.eng.store.dir / "provenance/snapshots/src-000001/gaia/stats.py", "# tampered")
        self.blocked()

    def test_experiment_records_snapshot_and_execution_identity(self):
        self.initialize()
        self.eng._load()
        self.eng.state["ref"] = {"cost": 1.0}
        self.eng.store.save_state(self.eng.state)
        proposal = (G.new_genome(hp={"lr": 0.08}), ["lr"], None, 1.0)
        self.eng.state["ref"] = {"cost": 0.000001}
        self.eng.store.save_state(self.eng.state)
        self.eng.experiment(proposal=proposal)
        events = [r for r in self.eng.store.records() if r["type"] in ("start", "end")]
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertEqual(event["source_snapshot"], self.eng.state["source_snapshot"])
            self.assertEqual(event["execution_id"], self.eng.execution_id)

    def test_development_change_during_experiment_prevents_promotion(self):
        self.initialize()
        self.eng._load()
        self.eng.state["ref"] = {"cost": 1.0}
        self.eng.store.save_state(self.eng.state)
        proposal = (G.new_genome(hp={"lr": 0.08}), ["lr"], None, 1.0)
        count = 0
        real_trial = self.eng.trial

        def trial(*args, **kwargs):
            nonlocal count
            if self.eng._active_record is None:
                return real_trial(*args, **kwargs)
            count += 1
            if count == 11:
                path = self.root / "gaia/stats.py"
                path.write_text(path.read_text() + "\n# changed during experiment\n")
            return {"status": "ok", "reached": True, "cost_s": 0.5,
                    "peak_rss_mb": 50, "final_acc": 0.8, "error": ""}

        with patch.object(self.eng, "trial", side_effect=trial), \
                patch.object(engine.stats, "decide", return_value={"decision": "accepted", "reason": "test"}), \
                patch.object(self.eng.store, "promote") as promote:
            with self.assertRaises(engine.NeedsHuman):
                self.eng.experiment(proposal=proposal)
            promote.assert_not_called()
        self.assertEqual(self.eng.store.current_version(), "v0000")


if __name__ == "__main__":
    unittest.main()
