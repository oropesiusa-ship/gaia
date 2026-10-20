"""Prueba A isolation/failure contracts plus a REAL, unmocked CLI end-to-end run.

Failure-path doubles below never produce a successful certification. Only
RealCertificationTests executes the complete pipeline and may assert PASS.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gaia import bootstrap, certification, config, engine, genome as G, manifest, provenance, search, snippets

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(directory):
    return {p.relative_to(directory).as_posix(): manifest.file_hash(p) for p in directory.rglob("*") if p.is_file()}


class FailureEngine:
    """Unit double for error propagation only, with no successful pipeline path."""
    failure = "gates"

    def __init__(self, root, cfg, log=print):
        self.root, self.cfg = Path(root), cfg
        self.current = "v0000"
        self.directory = self.root / cfg["workload"]["state_dir"]
        self.stable = self.directory / "stable"
        self.store = SimpleNamespace(dir=self.directory, stable=self.stable,
            current_version=lambda: self.current, versions=lambda: sorted(p.name for p in self.stable.glob("v*")),
            load_version=lambda name=None: (certification.controlled_pair()[int((name or self.current)[1:])],
                                           G.render(certification.controlled_pair()[int((name or self.current)[1:])])))
        self.bench = {"calibrated": {"main": {"ref_cost_s": 1}}, "tiers": {"screen": [0]}}
        self.state = {"source_snapshot": {}, "baseline_manifest_hash": "unit-only"}

    def artifact(self, name, genome, extra=None):
        directory = self.stable / name
        directory.mkdir(parents=True)
        (directory / "trainer.py").write_text(G.render(genome))
        (directory / "genome.json").write_text(json.dumps(genome))
        doc = manifest.seal({"manifest_schema": manifest.MANIFEST_SCHEMA, "kind": "baseline" if name == "v0000" else "stable",
                             "pre_promotion_hash": "unit-only", "environment_hash": "unit-only", **(extra or {})})
        (directory / "manifest.json").write_bytes(provenance.canonical_json(doc))
        (directory / "evidence.json").write_text("{}")

    def init(self, initialize_mvp=False):
        self.artifact("v0000", certification.controlled_pair()[0])
        (self.directory / "state.json").write_text(json.dumps(provenance.certification_metadata(self.cfg)))
        return True

    def _load(self):
        pass

    def experiment(self, proposal=None):
        if self.failure == "gates":
            raise engine.NeedsHuman("GATES_BLOCKED: G2 BASELINE_DRIFT")
        if self.failure == "screening":
            return "rejected"
        if self.failure == "confirmation":
            return "deferred"
        if self.failure == "publication":
            raise RuntimeError("PUBLICATION_FAILED: test fault")
        self.current = "v0001"
        self.artifact("v0001", certification.controlled_pair()[1])
        directory = self.directory / "experiments/e00001"
        directory.mkdir(parents=True)
        (directory / "evidence.json").write_text(json.dumps({"screen": {"status": "ok", "reached": True},
            "confirm": {"decision": "accepted", "ratio": .5}}))
        manifest.write_manifest(directory / "manifest.json", manifest.seal({"manifest_schema": manifest.MANIFEST_SCHEMA,
            "gate_report_path": "campaigns/unit/gates.json", "gate_report_hash": "unit-only"}))
        gates = self.directory / "campaigns/unit"
        gates.mkdir(parents=True)
        (gates / "gates.json").write_text(json.dumps({"overall": "PASS", "gates": {"G0": {"status": "PASS"}}}))
        return "improved"

    def trial(self, *args, **kwargs):
        return {"status": "ok", "reached": True, "sandbox_validation": True}

    def rollback(self, *args):
        if self.failure == "rollback":
            return {"status": "BLOCKED", "reason": "test rollback failure"}
        self.current = "v0000"
        return {"status": "COMPLETED", "event_id": "unit-only"}


class CertificationUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaia-cert-unit-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        normal = self.root / "state_numpy_mlp_real"
        normal.mkdir()
        (normal / "state.json").write_text('{"n_experiments":42,"strategy":{"version":7}}')
        (normal / "priors.json").write_text('{"optimizer":0.75}')
        self.normal = normal
        self.normal_before = fingerprint(normal)

    def test_pair_is_real_existing_genomes_not_arbitrary_trainers(self):
        baseline, candidate = certification.controlled_pair()
        self.assertEqual(baseline, G.new_genome())
        self.assertEqual(candidate["slots"]["optimizer"], "adam")
        self.assertIn(candidate["hp"]["depth"], G.HP_CHOICES["depth"])
        self.assertEqual(candidate["lits"], {})
        self.assertEqual(candidate["drops"], [])
        for genome in (baseline, candidate):
            self.assertIsInstance(G.render(genome), str)

    def test_each_allocation_is_independent_and_preserves_defaults_and_productive_history(self):
        defaults = copy.deepcopy(config.DEFAULTS)
        first = certification.new_configuration(self.root)
        second = certification.new_configuration(self.root)
        self.assertNotEqual(first["workload"]["state_dir"], second["workload"]["state_dir"])
        self.assertTrue(first["certification_only"])
        self.assertEqual(first["state_purpose"], "pipeline_certification")
        self.assertEqual(first["candidate_origin"], "certification_controlled")
        self.assertFalse(first["autonomous_self_improvement_certified"])
        self.assertEqual(first["acceptance"], defaults["acceptance"])
        self.assertEqual(first["benchmark_profile"], defaults["benchmark_profile"])
        self.assertEqual(defaults, config.DEFAULTS)
        self.assertEqual(self.normal_before, fingerprint(self.normal))

    def test_productive_configuration_cannot_relax_certification_and_dispatch_never_provisions(self):
        (self.root / "gaia.json").write_text(json.dumps({"benchmark_profile": "easy", "acceptance": {"min_gain": .00001},
            "workload": {"state_dir": "state_numpy_mlp_real"}, "limits": {"max_ram_mb": 999999}}))
        cfg = certification.new_configuration(self.root)
        self.assertEqual(cfg["acceptance"], config.DEFAULTS["acceptance"])
        self.assertEqual(cfg["benchmark_profile"], config.DEFAULTS["benchmark_profile"])
        self.assertEqual(cfg["limits"], config.DEFAULTS["limits"])
        with patch.object(bootstrap, "provision", side_effect=AssertionError("certification must stay offline")) as provision:
            self.assertIsNone(bootstrap.dispatch(self.root, ["certify-pipeline"]))
            provision.assert_not_called()

    def test_normal_run_cannot_consume_certification_state_or_propose(self):
        cfg = certification.new_configuration(self.root)
        eng = engine.Engine(self.root, cfg, log=lambda *args: None)
        with patch.object(search.Strategy, "propose", side_effect=AssertionError("must never search")):
            self.assertEqual(eng.run(), "needs_human")
            with self.assertRaisesRegex(engine.NeedsHuman, "controlled genome"):
                eng.experiment()
            with self.assertRaisesRegex(engine.NeedsHuman, "controlled genome"):
                eng.experiment(proposal=(G.new_genome(), [], None, None))
        (eng.store.dir / "state.json").write_text(json.dumps(provenance.certification_metadata(cfg)))
        ordinary = copy.deepcopy(config.DEFAULTS)
        ordinary["workload"]["state_dir"] = cfg["workload"]["state_dir"]
        with self.assertRaisesRegex(ValueError, "cannot be opened"):
            engine.Engine(self.root, ordinary)
        self.assertEqual(self.normal_before, fingerprint(self.normal))

    def test_initialization_failure_reports_fail_and_second_run_uses_another_state(self):
        old = set(snippets.UNLOCKED)
        snippets.set_unlocked([("sampler", "shuffled_slices")])
        try:
            with patch.object(engine.Engine, "init", side_effect=RuntimeError("initialization fault")):
                first = certification.run(self.root, log=lambda *args: None)
                second = certification.run(self.root, log=lambda *args: None)
            self.assertNotEqual(first["state_id"], second["state_id"])
            for result in (first, second):
                self.assertFalse(result["pipeline_certified"])
                self.assertFalse(result["autonomous_self_improvement_certified"])
                self.assertEqual(result["overall_status"], "FAIL")
                self.assertTrue(Path(result["report_path"]).is_file())
            self.assertEqual(snippets.UNLOCKED, {("sampler", "shuffled_slices")})
        finally:
            snippets.set_unlocked(old)
        self.assertEqual(self.normal_before, fingerprint(self.normal))

    def test_gates_screening_confirmation_publication_and_rollback_failures_never_certify(self):
        for failure in ("gates", "screening", "confirmation", "publication", "rollback", "ledger"):
            with self.subTest(failure=failure):
                FailureEngine.failure = failure
                chain_results = [{"ok": True, "records": [{"event_type": "version_promoted", "event_id": "unit-only",
                                                           "payload": {"version": "v0001"}}]},
                                 {"ok": False, "errors": ["LEDGER_INVALID"]}]
                final = {"status": "READY_FOR_CAMPAIGN", "campaign_id": "unit", "gate_report_hash": "unit",
                         "gate_report_path": "campaigns/unit/gates.json", "overall_gates_passed": True}
                with patch.object(certification.engine, "Engine", FailureEngine), \
                        patch.object(certification.manifest, "validate_manifest", return_value={"ok": True, "errors": []}), \
                        patch.object(certification.ledger, "verify_ledger", side_effect=chain_results), \
                        patch.object(certification.readiness, "run_gates", return_value=final):
                    report = certification.run(self.root, log=lambda *args: None)
                self.assertFalse(report["pipeline_certified"])
                self.assertFalse(report["autonomous_self_improvement_certified"])
                self.assertEqual(report["overall_status"], "FAIL")
                self.assertIsNotNone(report["failure"])
                self.assertEqual(self.normal_before, fingerprint(self.normal))

    def test_report_can_never_claim_autonomous_true_even_if_rehashed(self):
        with patch.object(engine.Engine, "init", side_effect=RuntimeError("test-only failure")):
            report = certification.run(self.root, log=lambda *args: None)
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg["workload"]["state_dir"] = report["state_id"]
        cfg["certification_only"] = True
        eng = engine.Engine(self.root, cfg, log=lambda *args: None)
        report["autonomous_self_improvement_certified"] = True
        report["report_hash"] = provenance.digest({k: v for k, v in report.items() if k != "report_hash"})
        self.assertFalse(certification.validate_report(eng, report)["ok"])
        (eng.store.dir / "bad-report.json").write_text("null")
        self.assertFalse(certification.validate_report(eng, eng.store.dir / "bad-report.json")["ok"])


class RealCertificationTests(unittest.TestCase):
    def test_real_unmocked_cli_certifies_pipeline_only_and_preserves_normal_state(self):
        with tempfile.TemporaryDirectory(prefix="gaia-cert-real-e2e-") as temporary:
            root = Path(temporary)
            shutil.copytree(ROOT / "gaia", root / "gaia", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copyfile(ROOT / "gaia.py", root / "gaia.py")
            shutil.copyfile(ROOT / "requirements.txt", root / "requirements.txt")
            normal = root / "state"
            normal.mkdir()
            (normal / "state.json").write_text('{"n_experiments":123,"strategy":{"version":9}}')
            (normal / "priors.json").write_text('{"family":0.9}')
            before = fingerprint(normal)
            env = os.environ.copy()
            for key in ("GAIA_LOCAL_CONFIG", "GAIA_MANAGED", "GAIA_FP_TORCH"):
                env.pop(key, None)
            completed = subprocess.run([sys.executable, "-W", "error::ResourceWarning", str(root / "gaia.py"), "certify-pipeline"],
                                       cwd=root, env=env, text=True, capture_output=True, timeout=900)
            paths = list(root.glob("state_certification_cpu_*/certification-report.json"))
            self.assertEqual(len(paths), 1, completed.stderr)
            report = json.loads(paths[0].read_bytes())
            self.assertEqual(completed.returncode, 0, str(report.get("failure")) + completed.stderr[-4000:])
            self.assertEqual(report["overall_status"], "PASS", report.get("failure"))
            self.assertTrue(report["pipeline_certified"])
            self.assertFalse(report["autonomous_self_improvement_certified"])
            self.assertTrue(all(report["phases"].values()))
            self.assertEqual(report["current_after_promotion"], "v0001")
            self.assertEqual(report["final_current"], "v0000")
            self.assertEqual(before, fingerprint(normal))
            self.assertFalse((root / "REPORT.md").exists())
            for path in (paths[0].parent / "stable").glob("v*/manifest.json"):
                document = json.loads(path.read_bytes())
                self.assertTrue(document["certification"])
                self.assertEqual(document["candidate_origin"], "certification_controlled")
            cfg = copy.deepcopy(config.DEFAULTS)
            cfg["workload"]["state_dir"] = report["state_id"]
            cfg["certification_only"] = True
            cfg.update(provenance.certification_metadata(cfg))
            cfg["meta"]["enabled"] = cfg["research"]["enabled"] = False
            eng = engine.Engine(root, cfg, log=lambda *args: None)
            eng._load()
            checked = certification.validate_report(eng, paths[0])
            self.assertTrue(checked["ok"], checked)
            (eng.store.ledger).write_bytes(eng.store.ledger.read_bytes() + b"partial")
            self.assertFalse(certification.validate_report(eng, paths[0])["ok"])


if __name__ == "__main__":
    unittest.main()
