"""CPU manifest identities: real source snapshots and real sandbox verification."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from gaia import engine, genome as G, manifest, provenance, readiness
from gaia.protected import evaluator, sandbox
import test_provenance as fixtures


class ManifestTests(unittest.TestCase):
    setUp = fixtures.LocalProvenanceTests.setUp
    initialize = fixtures.LocalProvenanceTests.initialize
    mutate = fixtures.LocalProvenanceTests.mutate

    def baseline(self):
        self.initialize()
        self.path = self.eng.store.stable / "v0000/manifest.json"
        return json.loads(self.path.read_bytes())

    def assertBlocked(self):
        checked = manifest.validate_manifest(self.eng)
        self.assertFalse(checked["ok"], checked)
        self.assertEqual(checked["code"], "ENVIRONMENT_MISMATCH")
        self.assertTrue(all("ENVIRONMENT_MISMATCH" in error for error in checked["errors"]))
        self.assertEqual(readiness.prepare(self.eng, refreeze=True)["status"], "NOT_READY")
        return checked

    def test_baseline_schema_canonical_hash_and_evidence_references(self):
        doc = self.baseline()
        self.assertEqual(doc["manifest_schema"], "mvp_cpu_manifest_v1")
        self.assertEqual(doc["kind"], "baseline")
        self.assertEqual(doc["manifest_hash"], provenance.digest({k: v for k, v in doc.items() if k != "manifest_hash"}))
        self.assertEqual(provenance.digest(doc), provenance.digest(dict(reversed(list(doc.items())))))
        self.assertTrue(manifest.validate_manifest(self.eng)["ok"])
        evidence = json.loads(self.path.with_name("evidence.json").read_bytes())
        for key, value in manifest.reference(doc).items():
            self.assertEqual(evidence[key], value)
        self.assertEqual(evidence["trainer_hash"], hashlib.sha256(self.path.with_name("trainer.py").read_bytes()).hexdigest())
        self.assertEqual(evidence["genome_hash"], provenance.digest(json.loads(self.path.with_name("genome.json").read_bytes())))
        self.assertTrue(evidence["timestamp"])
        self.assertTrue(evidence["benchmark_summary"])
        self.assertEqual(evidence["sandbox_verification"]["validated"], True)

    def test_same_certified_environment_has_same_environment_hash(self):
        doc = self.baseline()
        g, src = self.eng.store.load_version("v0000")
        ev = json.loads(self.path.with_name("evidence.json").read_bytes())
        probe = {"status": "ok", "sandbox_validation": True, "sandbox_evidence": ev["sandbox_verification"]}
        again = manifest.build_baseline(self.eng, self.eng.state["source_snapshot"], g, src, probe)
        self.assertEqual(doc["environment_hash"], again["environment_hash"])
        self.assertEqual(doc["environment_hash"], provenance.digest({key: doc[key] for key in manifest.HASHES}))

    def test_snapshot_reference_change_blocks(self):
        self.baseline()
        self.eng.state["source_snapshot"]["aggregate_sha256"] = "0" * 64
        self.eng.store.save_state(self.eng.state)
        self.assertBlocked()

    def test_protected_and_worker_changes_block(self):
        self.baseline()
        for filename in ("evaluator.py", "worker.py"):
            path = self.root / "gaia/protected" / filename
            original = path.read_text()
            path.write_text(original + "\n# changed\n")
            self.assertBlocked()
            path.write_text(original)
        self.assertTrue(manifest.validate_manifest(self.eng)["ok"])

    def test_benchmark_change_on_disk_or_in_memory_blocks(self):
        self.baseline()
        self.eng.bench["tiers"]["screen"] = [999]
        self.assertBlocked()
        self.eng.bench = json.loads((self.eng.store.dir / "benchmark.json").read_bytes())
        path = self.eng.store.dir / "benchmark.json"
        changed = json.loads(path.read_bytes())
        changed["hits_needed"] += 1
        path.write_text(json.dumps(changed))
        self.assertBlocked()

    def test_numpy_python_and_interpreter_changes_block(self):
        self.baseline()
        actual = manifest.runtime_identity(self.root, self.eng.cfg)
        variants = []
        for field, value in (("python", "different"), ("implementation", "different")):
            variants.append({**actual, field: value})
        variants.append({**actual, "numpy": {**actual["numpy"], "version": "different"}})
        variants.append({**actual, "interpreter": {**actual["interpreter"], "sha256": "0" * 64}})
        for changed in variants:
            with self.subTest(runtime=changed), patch.object(manifest, "runtime_identity", return_value=changed):
                self.assertBlocked()

    def test_configuration_seed_threshold_and_flags_are_critical(self):
        doc = self.baseline()
        self.assertIn("actual_confirmation_seeds", doc["effective_config"])
        self.assertIn("acceptance", doc["effective_config"])
        self.assertIn("readiness", doc["effective_config"])
        self.eng.acc["min_gain"] = 0.01
        self.assertBlocked()

    def test_sandbox_policy_change_blocks(self):
        self.baseline()
        with patch.object(sandbox, "POLICY_SCHEMA", "different-policy"):
            checked = self.assertBlocked()
            self.assertFalse(checked["checks"]["sandbox_policy"])

    def test_informational_disk_kernel_and_ui_changes_do_not_block(self):
        doc = self.baseline()
        host = manifest.host_identity(self.root, self.eng.store.dir)
        host["information"].update(workspace_free_mb=1, state_free_mb=2, kernel="informational kernel")
        self.eng.cfg["ui"] = {"color": "changed"}
        with patch.object(manifest, "host_identity", return_value=host):
            checked = manifest.validate_manifest(self.eng)
            self.assertTrue(checked["ok"], checked)
            self.assertTrue(provenance.prerequisites(self.eng)["ok"])
        self.assertEqual(doc, json.loads(self.path.read_bytes()))

    def test_cpu_architecture_and_insufficient_ram_block(self):
        self.baseline()
        host = manifest.host_identity(self.root, self.eng.store.dir)
        for key in ("cpu_model", "architecture"):
            changed = copy.deepcopy(host)
            changed["identity"][key] = "different"
            with patch.object(manifest, "host_identity", return_value=changed):
                self.assertBlocked()
        changed = copy.deepcopy(host)
        changed["capabilities"]["available_ram_mb"] = 1
        with patch.object(manifest, "host_identity", return_value=changed):
            self.assertIn("CAPABILITY_CRITICAL", str(self.assertBlocked()["errors"]))

    def test_corrupt_wrong_schema_and_missing_manifest_block(self):
        original = self.baseline()
        self.mutate(self.path, "{")
        self.assertBlocked()
        self.mutate(self.path, json.dumps({**original, "manifest_schema": "wrong"}))
        self.assertBlocked()
        self.mutate(self.path, json.dumps({**original, "created_at": "changed"}))
        self.assertBlocked()
        self.path.unlink()
        self.assertBlocked()

    def test_resealed_manifest_is_rejected_by_external_anchor(self):
        original = self.baseline()
        original["created_at"] = "changed"
        self.mutate(self.path, json.dumps(manifest.seal(original)))
        self.assertBlocked()

    def test_baseline_critical_artifacts_and_evidence_references_block(self):
        self.baseline()
        path = self.path.with_name("evidence.json")
        ev = json.loads(path.read_bytes())
        for key in ("environment_hash", "source_hash", "config_hash", "sandbox_policy_hash", "trainer_hash", "genome_hash"):
            changed = {**ev, key: "0" * 64}
            self.mutate(path, json.dumps(changed))
            self.assertBlocked()
        self.mutate(path, json.dumps(ev))
        self.mutate(self.path.with_name("trainer.py"), "# altered baseline")
        self.assertBlocked()

    def test_missing_baseline_execution_references_block(self):
        self.baseline()
        path = self.path.with_name("evidence.json")
        ev = json.loads(path.read_bytes())
        for key in ("timestamp", "execution_id", "benchmark_summary", "sandbox_verification", "source_snapshot"):
            changed = {k: value for k, value in ev.items() if k != key}
            self.mutate(path, json.dumps(changed))
            self.assertBlocked()

    def test_uncertified_current_parent_cannot_be_used(self):
        self.baseline()
        import shutil
        shutil.copytree(self.eng.store.stable / "v0000", self.eng.store.stable / "v0001")
        (self.eng.store.stable / "CURRENT").write_text("v0001\n")
        self.assertBlocked()

    def experiment(self):
        self.baseline()
        self.eng._load()
        self.eng.state["ref"] = {"cost": 0.000001}
        self.eng.store.save_state(self.eng.state)
        proposal = (G.new_genome(hp={"lr": 0.08}), ["lr"], None, 1.0)
        self.eng.experiment(proposal=proposal)
        directory = self.eng.store.dir / "experiments/e00001"
        return directory, json.loads((directory / "manifest.json").read_bytes()), json.loads((directory / "evidence.json").read_bytes())

    def test_experiment_delta_and_evidence_have_verifiable_references(self):
        directory, doc, ev = self.experiment()
        self.assertTrue(manifest.validate_manifest(self.eng, directory / "manifest.json")["ok"])
        base = json.loads(self.path.read_bytes())
        self.assertEqual(doc["baseline_manifest_hash"], base["manifest_hash"])
        self.assertEqual(doc["environment_hash"], base["environment_hash"])
        self.assertEqual(doc["candidate_trainer_hash"], manifest.file_hash(directory / "trainer.py"))
        self.assertEqual(doc["candidate_genome_hash"], provenance.digest(json.loads((directory / "genome.json").read_bytes())))
        self.assertNotIn("effective_config", doc)
        self.assertNotIn("host", doc)
        self.assertEqual(ev["experiment_manifest_hash"], doc["manifest_hash"])
        self.assertEqual(ev["baseline_manifest_hash"], base["manifest_hash"])
        self.assertTrue(ev["trial_metrics"])
        self.assertEqual(ev["sandbox_evidence_hash"], provenance.digest([r["result"]["sandbox_evidence"] for r in ev["trial_metrics"]]))
        self.assertFalse(ev["promotable"])
        self.assertEqual(ev["evidence_hash"], provenance.digest({k: v for k, v in ev.items() if k != "evidence_hash"}))
        for event in self.eng.store.records():
            if event["type"] in ("start", "end"):
                self.assertEqual(event["experiment_manifest_hash"], doc["manifest_hash"])

    def test_candidate_artifact_or_evidence_tampering_blocks(self):
        directory, _, _ = self.experiment()
        path = directory / "evidence.json"
        self.mutate(path, "{}")
        self.assertFalse(manifest.validate_manifest(self.eng, directory / "manifest.json")["ok"])
        self.mutate(directory / "trainer.py", "# changed")
        self.assertFalse(manifest.validate_manifest(self.eng, directory / "manifest.json")["ok"])

    def test_environment_change_during_execution_records_invalid_and_stops(self):
        self.baseline()
        self.eng._load()
        self.eng.state["ref"] = {"cost": 0.05}
        self.eng.store.save_state(self.eng.state)
        real_trial = evaluator.run_trial

        def changed_during_trial(*args, **kwargs):
            result = real_trial(*args, **kwargs)
            if self.eng._active_record is not None:
                path = self.root / "gaia/stats.py"
                path.write_text(path.read_text() + "\n# changed during execution\n")
            return result

        with patch.object(evaluator, "run_trial", side_effect=changed_during_trial), \
                patch.object(self.eng.store, "promote") as promote:
            with self.assertRaises(engine.NeedsHuman):
                self.eng.experiment(proposal=(G.new_genome(hp={"lr": 0.08}), ["lr"], None, 1.0))
            promote.assert_not_called()
        self.assertEqual(self.eng.store.current_version(), "v0000")
        ev = json.loads((self.eng.store.dir / "experiments/e00001/evidence.json").read_bytes())
        self.assertEqual(ev["decision"], "invalid")
        self.assertFalse(ev["promotable"])
        self.assertTrue(ev["trial_metrics"])
        self.assertIn("ENVIRONMENT_MISMATCH", ev["reason"])

    def test_old_state_without_manifest_is_not_migrated(self):
        self.baseline()
        self.path.unlink()
        before = self.eng.store.load_state()
        self.assertBlocked()
        self.assertEqual(before, self.eng.store.load_state())
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
