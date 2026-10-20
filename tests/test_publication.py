"""Storage-only acceptance fixtures and crash/concurrency tests, not A/B certification.

Sandbox/quality trials are real. Costs are deliberately controlled in this
test fixture to exercise statistical evidence validation, never to claim an
autonomous improvement. No production CLI accepts this fixture.
"""
import copy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gaia import atomic_publish, config, engine, genome as G, manifest, publication, readiness, stats
from gaia.protected import benchmark, evaluator

ROOT = Path(__file__).resolve().parents[1]


def _source_hash(source):
    return hashlib.sha256(source.encode()).hexdigest()


def _make_template(root):
    shutil.copytree(ROOT / "gaia", root / "gaia", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(ROOT / "gaia.py", root / "gaia.py")
    cfg = config.load(root)
    cfg["benchmark_profile"] = "easy"
    cfg["meta"]["enabled"] = False
    cfg["research"]["enabled"] = False
    eng = engine.Engine(root, cfg, log=lambda *args: None)
    bench = copy.deepcopy(benchmark.DEFAULT_SPEC)
    # Keep the real MLP dimensions representative: a 6-column toy makes the
    # existing six-matmul slow control too small to resolve above IPC noise.
    # This is test data only; production benchmark/seeds/tolerances are untouched.
    bench["tasks"]["main"].update(d=96, teacher_hidden=192, k=16, n_train=2000, n_val=1000, noise=.05)
    # Measured work must dominate IPC/scheduling noise for real G2/G4 checks.
    # This fixture freezes a longer batch interval, not looser acceptance gates.
    bench["max_batches"], bench["eval_every"] = 1000, 500
    bench["calibrated"] = {task: {"target": 0.0, "ref_cost_s": 1.0, "cv": 0.01,
                                  "q_ref": 0.1, "ref_costs": [1.0] * 5} for task in ("main", "audit")}
    with patch.object(benchmark, "calibrate", return_value=bench):
        eng.init(initialize_mvp=True)
    eng._load()
    parent_genome, parent = eng.store.load_version()
    candidate = G.new_genome(hp={"lr": 0.08})
    source = G.render(candidate)
    context = eng.source_context()
    gates = readiness.run_gates(eng, genome=candidate, source=source)
    if gates["status"] != "READY_FOR_CAMPAIGN":
        raise AssertionError(gates)
    eng._campaign_context = {key: gates[key] for key in ("campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")}
    doc = manifest.build_experiment(eng, "e00001", context, candidate, source, parent_genome, parent)
    directory = eng.store.dir / "experiments/e00001"
    manifest.write_manifest(directory / "manifest.json", doc)
    (directory / "genome.json").write_bytes(publication.genome_bytes(candidate))
    (directory / "genome.json").chmod(0o444)
    (directory / "trainer.py").write_text(source)
    (directory / "trainer.py").chmod(0o444)
    trials, parent_results, candidate_results = [], [], []

    def trial(src, seed, cost):
        result = evaluator.run_trial(src, bench, "main", seed, seed, 20, cfg["limits"], eng.store.tmp)
        if result["status"] != "ok" or not result["reached"] or not result["sandbox_validation"]:
            raise AssertionError(result)
        result["cost_s"] = cost  # Storage-only synthetic cost, explicitly not MVP evidence.
        trials.append({"trainer_hash": _source_hash(src), "task": "main", "data_seed": seed,
                       "campaign_id": doc["campaign_id"], "environment_hash": doc["environment_hash"],
                       "stable_version": doc["parent_version"], "source_sha": doc["candidate_trainer_hash"],
                       "init_seed": seed, "cap_s": 20, "result": result})
        return result

    screen = trial(source, 0, .5)
    for index, seed in enumerate(range(1000, 1005)):
        for who in (("candidate", "parent") if index % 2 else ("parent", "candidate")):
            result = trial(source if who == "candidate" else parent, seed, .5 if who == "candidate" else 1.0)
            (candidate_results if who == "candidate" else parent_results).append(result)
    decision = stats.decide(parent_results, candidate_results, cfg["acceptance"])
    decision.update(champ_costs=[r["cost_s"] for r in parent_results], cand_costs=[r["cost_s"] for r in candidate_results])
    if decision["decision"] != "accepted":
        raise AssertionError(decision)
    execution = {"type": "end", "id": "e00001", "genome": candidate, "ops": ["lr"],
                 **eng._campaign_context,
                 "screen": screen, "confirm": decision, "decision": "accepted", "reason": decision["reason"],
                 **context, "baseline_manifest_hash": context["manifest_hash"],
                 "candidate_genome_hash": manifest.digest(candidate), "candidate_trainer_hash": _source_hash(source),
                 "experiment_manifest_hash": doc["manifest_hash"], "parent_version": "v0000",
                 "trial_metrics": trials, "sandbox_evidence_hash": manifest.digest([r["result"]["sandbox_evidence"] for r in trials]),
                 "started_at": doc["created_at"], "finished_at": manifest.timestamp(), "promotable": True,
                 "evidence_path": "experiments/e00001/evidence.json"}
    execution["evidence_hash"] = manifest.digest(execution)
    manifest.write_manifest(directory / "evidence.json", execution)
    provided = {"experiment": "e00001", **context, "baseline_manifest_hash": context["manifest_hash"],
                "experiment_manifest_path": "experiments/e00001/manifest.json", "experiment_manifest_hash": doc["manifest_hash"],
                "experiment_evidence_path": execution["evidence_path"], "experiment_evidence_hash": execution["evidence_hash"],
                "confirm": decision, "hypothesis": {"detail": G.describe(candidate)}, "provenance": "known",
                "diff_vs_champion": [list(row) for row in G.diff(parent_genome, candidate)]}
    eng.store.append({"type": "start", "id": "e00001", "genome": candidate, "ops": ["lr"],
                      **eng._campaign_context,
                      "stable_version": "v0000", "environment_hash": context["environment_hash"],
                      "manifest_hash": context["manifest_hash"], "experiment_manifest_hash": doc["manifest_hash"],
                      "source_sha": _source_hash(source),
                      "hypothesis": {"accept_rule": "storage-only fixture"}})
    eng.store.append(execution)
    provided.update(readiness.pre_promotion(eng, candidate, source, provided))
    return cfg, candidate, source, provided


def _publish_child(root, cfg, genome, source, provided, barrier, results, fault=None):
    eng = engine.Engine(root, cfg, log=lambda *args: None)
    eng._load()
    if barrier is not None:
        barrier.wait(timeout=15)
    try:
        def crash(phase, path):
            if phase == fault:
                os._exit(71)
        version = eng.store.promote(genome, source, provided, context=eng, _test_fault=crash if fault else None)
        if results is not None:
            results.put((True, version))
    except Exception as exc:
        if results is not None:
            results.put((False, str(exc)))


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory(prefix="gaia-publish-template-")
        cls.addClassCleanup(cls.template.cleanup)
        cls.cfg, cls.genome, cls.source, cls.provided = _make_template(Path(cls.template.name))

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gaia-publish-case-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        shutil.copytree(self.template.name, self.root)
        self.eng = engine.Engine(self.root, copy.deepcopy(self.cfg), log=lambda *args: None)
        self.eng._load()
        self.evidence = copy.deepcopy(self.provided)

    def promote(self, **kwargs):
        # Exercise the required final Engine-side validation; direct Store is
        # separately tested to reject missing pre-promotion evidence.
        self.evidence.update(readiness.pre_promotion(self.eng, self.genome, self.source, self.evidence))
        return self.eng.store.promote(self.genome, self.source, self.evidence, context=self.eng, **kwargs)

    def mutate(self, path, value):
        path.chmod(0o644)
        path.write_bytes(manifest.canonical_json(value) if not isinstance(value, bytes) else value)

    def reject(self):
        with self.assertRaises((ValueError, RuntimeError)):
            self.promote()
        self.assertEqual(self.eng.store.current_version(), "v0000")
        self.assertFalse((self.eng.store.stable / "v0001").exists())

    def reseal_execution(self, change):
        path = self.eng.store.dir / self.evidence["experiment_evidence_path"]
        doc = json.loads(path.read_bytes())
        change(doc)
        doc["sandbox_evidence_hash"] = manifest.digest([r["result"]["sandbox_evidence"] for r in doc["trial_metrics"]])
        doc.pop("evidence_hash")
        doc["evidence_hash"] = manifest.digest(doc)
        self.mutate(path, doc)
        self.evidence["experiment_evidence_hash"] = doc["evidence_hash"]

    def test_valid_publication_is_complete_reloadable_and_keeps_experiment_immutable(self):
        original = (self.eng.store.dir / self.evidence["experiment_manifest_path"]).read_bytes()
        self.assertEqual(self.promote(), "v0001")
        directory = self.eng.store.stable / "v0001"
        self.assertEqual({p.name for p in directory.iterdir()}, publication.ARTIFACTS)
        checked = manifest.validate_manifest(self.eng, directory / "manifest.json")
        self.assertTrue(checked["ok"], checked)
        self.assertEqual(checked["stable"]["kind"], "stable")
        self.assertEqual(checked["stable"]["parent_version"], "v0000")
        self.assertEqual(self.eng.store.load_version(), (self.genome, self.source))
        self.assertEqual(original, (self.eng.store.dir / self.evidence["experiment_manifest_path"]).read_bytes())
        self.assertEqual(self.eng.store.records()[-1]["result"], "committed")
        rolled_back = self.eng.rollback("v0000", "publication regression rollback")
        self.assertEqual(rolled_back["status"], "COMPLETED", rolled_back)
        self.assertEqual(self.eng.store.current_version(), "v0000")

    def test_initial_baseline_uses_the_same_four_artifact_transaction(self):
        root = Path(self.tmp.name) / "initialization"
        root.mkdir()
        shutil.copytree(self.root / "gaia", root / "gaia")
        shutil.copyfile(self.root / "gaia.py", root / "gaia.py")
        eng = engine.Engine(root, copy.deepcopy(self.cfg), log=lambda *args: None)
        original = atomic_publish.publish
        observations = []

        def inspect(phase, path):
            if phase == "before_current_replace":
                self.assertIsNone(eng.store.current_version())
                self.assertEqual({p.name for p in path.iterdir()}, publication.ARTIFACTS)
                checked = manifest.validate_manifest(eng, _current_version="v0000")
                self.assertTrue(checked["ok"], checked)
                observations.append(phase)

        def publish(*args, **kwargs):
            return original(*args, **{**kwargs, "_test_fault": inspect})

        with patch.object(benchmark, "calibrate", return_value=copy.deepcopy(self.eng.bench)), \
                patch.object(atomic_publish, "publish", side_effect=publish):
            eng.init(initialize_mvp=True)
        self.assertTrue(observations)
        self.assertEqual(eng.store.current_version(), "v0000")

    def test_failed_initial_baseline_preserves_staging_and_blocks_readiness(self):
        root = Path(self.tmp.name) / "failed-initialization"
        root.mkdir()
        shutil.copytree(self.root / "gaia", root / "gaia")
        shutil.copyfile(self.root / "gaia.py", root / "gaia.py")
        eng = engine.Engine(root, copy.deepcopy(self.cfg), log=lambda *args: None)
        original = atomic_publish.publish

        def publish(*args, **kwargs):
            return original(*args, **{**kwargs, "_test_fault": "before_write:manifest.json"})

        with patch.object(benchmark, "calibrate", return_value=copy.deepcopy(self.eng.bench)), \
                patch.object(atomic_publish, "publish", side_effect=publish):
            with self.assertRaises(atomic_publish.InjectedFailure):
                eng.init(initialize_mvp=True)
        self.assertIsNone(eng.store.current_version())
        self.assertFalse((eng.store.stable / "v0000").exists())
        report = eng.store.recover_publications(eng)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(len(report["staging"]), 1)
        self.assertEqual(readiness.prepare(eng)["status"], "NOT_READY")

    def test_current_stays_old_until_the_final_version_is_complete(self):
        phases = []

        def inspect(phase, path):
            phases.append(phase)
            if phase in ("after_version_rename", "before_current_replace"):
                self.assertEqual(self.eng.store.current_version(), "v0000")
                self.assertEqual({p.name for p in path.iterdir()}, publication.ARTIFACTS)
                self.assertTrue(manifest.validate_manifest(self.eng, path / "manifest.json")["ok"])
            if phase == "after_current_replace":
                self.assertEqual(self.eng.store.current_version(), "v0001")
                self.assertTrue(manifest.validate_manifest(self.eng)["ok"])

        self.promote(_test_fault=inspect)
        self.assertIn("before_current_replace", phases)

    def test_fsync_order_covers_staging_version_and_pointer(self):
        operations = []
        fsync = os.fsync

        def synchronize(fd):
            operations.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
            return fsync(fd)

        def checkpoint(phase, path):
            operations.append((phase, str(path)))

        with patch.object(os, "fsync", side_effect=synchronize):
            self.promote(_test_fault=checkpoint)
        before_rename = next(i for i, row in enumerate(operations) if row[0] == "before_version_rename")
        before_current = next(i for i, row in enumerate(operations) if row[0] == "before_current_replace")
        for name in publication.ARTIFACTS:
            self.assertTrue(any(kind == "fsync" and ".staging-v0001-" in path and path.endswith("/" + name)
                                for kind, path in operations[:before_rename]))
        self.assertTrue(any(kind == "fsync" and ".staging-v0001-" in path and Path(path).name.startswith(".staging-")
                            for kind, path in operations[:before_rename]))
        self.assertIn(("fsync", str(self.eng.store.stable / "v0001")), operations[before_rename:before_current])
        self.assertTrue(any(kind == "fsync" and "/.CURRENT-" in path for kind, path in operations[:before_current]))
        self.assertIn(("fsync", str(self.eng.store.stable / "CURRENT")), operations[before_current:])
        self.assertIn(("fsync", str(self.eng.store.stable)), operations[before_current:])

    def test_wrong_trainer_or_genome_rejected(self):
        with self.assertRaises(ValueError):
            self.eng.store.promote(self.genome, self.source + "\n", self.evidence, context=self.eng)
        altered = G.new_genome(hp={"lr": .04})
        with self.assertRaises(ValueError):
            self.eng.store.promote(altered, G.render(altered), self.evidence, context=self.eng)
        self.assertEqual(self.eng.store.current_version(), "v0000")

    def test_invalid_experiment_manifest_rejected(self):
        self.mutate(self.eng.store.dir / self.evidence["experiment_manifest_path"], b"{")
        self.reject()

    def test_invalid_baseline_manifest_rejected(self):
        self.mutate(self.eng.store.stable / "v0000/manifest.json", b"{}")
        self.reject()

    def test_invalid_evidence_rejected(self):
        self.mutate(self.eng.store.dir / self.evidence["experiment_evidence_path"], b"{}")
        self.reject()

    def test_each_environment_reference_is_revalidated(self):
        for field in ("environment_hash", "host_hash", "runtime_hash", "source_hash", "config_hash", "sandbox_policy_hash"):
            with self.subTest(field=field):
                old = self.evidence[field]
                self.evidence[field] = "0" * 64
                self.reject()
                self.evidence[field] = old

    def test_actual_environment_mismatch_rejected(self):
        self.eng.acc["min_gain"] = .01
        self.reject()

    def test_invalid_sandbox_even_with_resealed_evidence_is_rejected(self):
        self.reseal_execution(lambda doc: doc["trial_metrics"][2]["result"].update(sandbox=False))
        self.reject()

    def test_quality_failure_even_with_resealed_evidence_is_rejected(self):
        self.reseal_execution(lambda doc: doc["trial_metrics"][2]["result"].update(reached=False))
        self.reject()

    def test_rejected_statistical_decision_is_rejected(self):
        self.reseal_execution(lambda doc: doc.update(decision="rejected", promotable=False))
        self.reject()

    def test_fabricated_acceptance_is_recomputed_not_trusted(self):
        def slower(doc):
            for trial in doc["trial_metrics"]:
                if trial["trainer_hash"] == _source_hash(self.source):
                    trial["result"]["cost_s"] = 2.0
        self.reseal_execution(slower)
        self.reject()

    def test_wrong_confirmation_order_is_rejected(self):
        def reorder(doc):
            doc["trial_metrics"][1], doc["trial_metrics"][2] = doc["trial_metrics"][2], doc["trial_metrics"][1]
        self.reseal_execution(reorder)
        self.reject()

    def test_stale_parent_is_rechecked_under_lock(self):
        self.promote()
        with self.assertRaises(ValueError):
            self.promote()
        self.assertEqual(self.eng.store.current_version(), "v0001")
        self.assertFalse((self.eng.store.stable / "v0002").exists())

    def test_staging_write_fsync_and_pre_rename_failures_leave_current_intact(self):
        for phase in ("before_write:trainer.py", "before_write:manifest.json", "before_write:evidence.json",
                      "before_file_fsync", "before_staging_fsync", "before_version_rename"):
            with self.subTest(phase=phase):
                # Independent crash scenarios. Step 7's final barrier now
                # refuses another promotion while an earlier staging remains;
                # preserve/check it, then use a fresh test state for the next
                # injected fault instead of bypassing that barrier.
                shutil.rmtree(self.eng.store.dir)
                shutil.copytree(Path(self.template.name) / "state", self.eng.store.dir)
                with self.assertRaises(atomic_publish.InjectedFailure):
                    self.promote(_test_fault=phase)
                self.assertEqual(self.eng.store.current_version(), "v0000")
                self.assertFalse((self.eng.store.stable / "v0001").exists())
                report = self.eng.store.recover_publications(self.eng)
                self.assertEqual(len(report["staging"]), 1)
                self.assertTrue(report["staging"][0]["never_published"])
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "READY", report)
        self.assertEqual(len(report["staging"]), 1)
        self.assertTrue(all(row["never_published"] for row in report["staging"]))

    def test_failure_after_rename_preserves_valid_non_current_version(self):
        with self.assertRaises(atomic_publish.InjectedFailure):
            self.promote(_test_fault="after_version_rename")
        self.assertEqual(self.eng.store.current_version(), "v0000")
        self.assertTrue(manifest.validate_manifest(self.eng, self.eng.store.stable / "v0001/manifest.json")["ok"])
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "READY", report)
        self.assertIn("v0001", report["non_current_versions"])
        self.assertEqual(self.eng.store.current_version(), "v0000")
        self.assertEqual(self.promote(), "v0002")

    def test_current_replace_failure_preserves_complete_final_and_old_pointer(self):
        replace = os.replace

        def fail_current(src, dst):
            if Path(dst).name == "CURRENT":
                raise OSError("simulated pointer replace failure")
            return replace(src, dst)

        with patch.object(os, "replace", side_effect=fail_current), self.assertRaises(OSError):
            self.promote()
        self.assertEqual(self.eng.store.current_version(), "v0000")
        self.assertTrue(manifest.validate_manifest(self.eng, self.eng.store.stable / "v0001/manifest.json")["ok"])
        self.assertTrue(self.eng.store.recover_publications(self.eng)["pointer_temporaries"])

    def test_corrupt_current_or_version_blocks_readiness(self):
        self.promote()
        self.mutate(self.eng.store.stable / "v0001/trainer.py", b"changed")
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")
        self.assertEqual(readiness.prepare(self.eng)["status"], "NOT_READY")
        (self.eng.store.stable / "CURRENT").write_text("v0099\n")
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("nonexistent", str(report["errors"]))

    def test_non_current_corrupt_version_is_not_ignored_or_overwritten(self):
        with self.assertRaises(atomic_publish.InjectedFailure):
            self.promote(_test_fault="after_version_rename")
        self.mutate(self.eng.store.stable / "v0001/evidence.json", b"{}")
        with self.assertRaises(ValueError):
            self.promote()
        self.assertEqual((self.eng.store.stable / "v0001/evidence.json").read_bytes(), b"{}")
        self.assertEqual(self.eng.store.current_version(), "v0000")

    def test_kernel_lock_excludes_second_store_and_is_reentrant_for_owner(self):
        from gaia.store import Store
        with self.eng.store.exclusive():
            other = Store(self.root)
            with self.assertRaises(RuntimeError):
                other.lock()
            self.assertEqual(self.promote(), "v0001")

    def test_concurrent_processes_publish_only_once(self):
        ctx = multiprocessing.get_context("fork")
        barrier, results = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=_publish_child, args=(self.root, self.cfg, self.genome, self.source,
                                                              self.evidence, barrier, results)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(30)
                self.assertEqual(process.exitcode, 0)
            outcomes = [results.get(timeout=5) for _ in processes]
            self.assertEqual(sum(ok for ok, detail in outcomes), 1, outcomes)
            self.assertEqual(self.eng.store.current_version(), "v0001")
            self.assertFalse((self.eng.store.stable / "v0002").exists())
        finally:
            for process in processes:
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            results.close()
            results.join_thread()

    def test_process_death_releases_lock_and_preserves_non_current_version(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_publish_child, args=(self.root, self.cfg, self.genome, self.source,
                                                          self.evidence, None, None, "after_version_rename"))
        process.start()
        process.join(30)
        self.assertEqual(process.exitcode, 71)
        process.close()
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "READY", report)
        self.assertEqual(self.eng.store.current_version(), "v0000")
        self.assertIn("v0001", report["non_current_versions"])

    def test_process_death_after_current_does_not_recover_accepted_as_aborted(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_publish_child, args=(self.root, self.cfg, self.genome, self.source,
                                                          self.evidence, None, None, "after_current_commit"))
        process.start()
        process.join(30)
        self.assertEqual(process.exitcode, 71)
        process.close()
        self.assertEqual(self.eng.store.current_version(), "v0001")
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "READY")
        self.eng._recover()
        end = [r for r in self.eng.store.records() if r.get("type") == "end"][-1]
        self.assertEqual(end["decision"], "accepted")
        self.assertEqual(end["promoted_to"], "v0001")
        self.assertEqual(end["decision"], "accepted")
        self.assertIn(G.genome_hash(self.genome), self.eng.hist.seen)

    def test_post_commit_failure_is_critical_and_never_rolls_back_automatically(self):
        with self.assertRaisesRegex(RuntimeError, "CRITICAL_PUBLICATION_ERROR"):
            self.promote(_test_fault="after_current_replace")
        self.assertEqual(self.eng.store.current_version(), "v0001")
        self.assertTrue(manifest.validate_manifest(self.eng)["ok"])
        self.assertTrue(self.eng.store.records()[-1]["critical"])
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")

    def test_post_commit_disk_verification_failure_is_diagnosed(self):
        def corrupt_after_commit(phase, path):
            if phase == "after_current_commit":
                self.mutate(path / "manifest.json", b"{}")

        with self.assertRaisesRegex(RuntimeError, "CRITICAL_PUBLICATION_ERROR"):
            self.promote(_test_fault=corrupt_after_commit)
        self.assertEqual(self.eng.store.current_version(), "v0001")
        self.assertTrue(self.eng.store.records()[-1]["critical"])
        self.assertEqual(self.eng.store.recover_publications(self.eng)["status"], "BLOCKED")

    def test_late_environment_change_before_pointer_replace_does_not_commit(self):
        def changed(phase, path):
            if phase == "before_current_replace":
                self.eng.acc["min_gain"] = .01

        with self.assertRaises(ValueError):
            self.promote(_test_fault=changed)
        self.assertEqual(self.eng.store.current_version(), "v0000")

    def test_real_process_death_with_partial_staging_preserves_it(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_publish_child, args=(self.root, self.cfg, self.genome, self.source,
                                                          self.evidence, None, None, "before_write:manifest.json"))
        process.start()
        process.join(30)
        self.assertEqual(process.exitcode, 71)
        process.close()
        report = self.eng.store.recover_publications(self.eng)
        self.assertEqual(report["status"], "READY", report)
        self.assertEqual(len(report["staging"]), 1)
        self.assertFalse((self.eng.store.stable / "v0001").exists())
        self.assertEqual(self.eng.store.current_version(), "v0000")

    def test_truncated_ledger_does_not_swallow_publication_event(self):
        with self.eng.store.ledger.open("ab") as stream:
            stream.write(b'{"type":"incomplete","text":"\xc3')
        with self.assertRaises((ValueError, RuntimeError)):
            self.promote()
        from gaia.ledger import verify_ledger
        self.assertEqual(verify_ledger(self.eng.store)["code"], "LEDGER_TRUNCATED_OR_PARTIAL")
        self.assertEqual(self.eng.store.current_version(), "v0000")

    def test_atomic_primitive_never_overwrites_even_an_empty_destination(self):
        stable = self.root / "empty-stable"
        stable.mkdir()
        (stable / "v0000").mkdir()
        with self.assertRaises(FileExistsError):
            atomic_publish.publish(stable, "v0000", {"x": b"new"}, lambda p: None, None)
        self.assertEqual(list((stable / "v0000").iterdir()), [])

    def test_destination_created_during_staging_is_not_overwritten(self):
        stable = self.root / "race-stable"
        stable.mkdir()

        def race(phase, path):
            if phase == "before_version_rename":
                (stable / "v0000").mkdir()

        with self.assertRaises(FileExistsError):
            atomic_publish.publish(stable, "v0000", {"x": b"new"}, lambda p: None, None, _test_fault=race)
        self.assertEqual(list((stable / "v0000").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
