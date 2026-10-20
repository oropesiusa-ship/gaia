"""Contextual learning from real Test B projections and labelled synthetic runs."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gaia import config, provenance
from gaia.learning.applicability import assess
from gaia.learning.engine import learn, settings
from gaia.learning.ingestion import load_source
from gaia.learning.query import query
from gaia.learning.schema import seal, seal_source, validate, validate_source
from gaia.learning.store import LearningStore

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "docs/learning_evidence/test-b-sources.json"


def fixture(outcome="ACCEPTED", *, run=1, variation=0.0, evidence=1, context_change=None):
    exp = copy.deepcopy(load_source(REAL)["experiments"][2])
    exp["experiment_id"] = f"e{evidence:05d}"
    exp["evidence_hash"] = provenance.digest({"synthetic_evidence": evidence, "run": run, "outcome": outcome, "variation": variation})
    exp["execution_hash"] = provenance.digest({"synthetic_execution": run})
    exp["manifest_hash"] = provenance.digest({"synthetic_manifest": evidence, "run": run})
    exp["promotion"] = outcome == "ACCEPTED"
    exp["rollback"] = "NONE"
    c = exp["confirmation"]
    c["trial_count"] = c["pairs"] = 5
    c["baseline_costs"] = [1, 1.1, 1, 1.1, 1]
    ratio = {"ACCEPTED": .7, "REJECTED": 1.2, "INCONCLUSIVE": .9}[outcome]
    ratio += variation
    c["candidate_costs"] = [x * ratio for x in c["baseline_costs"]]
    c["ratio"] = ratio
    c["upper95"] = ratio + (.02 if outcome == "ACCEPTED" else .09)
    c["candidate_reached"] = c["baseline_reached"] = 5
    c["decision"] = {"ACCEPTED": "accepted", "REJECTED": "rejected", "INCONCLUSIVE": "deferred"}[outcome]
    exp["screen"] = {"status": "ok", "reached": True, "cost_s": ratio, "baseline_cost_s": 1}
    exp["outcome"] = outcome
    if context_change:
        exp["context"].update(context_change)
    return exp


def source(*experiments):
    return seal_source({"schema": "gaia_learning_sources_v1", "provenance": {"kind": "SYNTHETIC", "archive_aggregate": "0" * 64,
                         "projection_version": "cpu_projection_v1"}, "experiments": list(experiments)})


def exact(run):
    return next(k for k in run["knowledge"] if k["claim"]["subject"] == "EXACT_CONFIGURATION")


class LearningTests(unittest.TestCase):
    def test_A_single_accepted_is_not_replicated_or_high(self):
        run = learn([source(fixture())])
        item = exact(run)
        self.assertEqual(item["claim_type"], "OBSERVED_EFFECT")
        self.assertEqual(item["confidence"], "MEDIUM")
        self.assertEqual(item["replication_status"], "REPEATED_WITHIN_EXPERIMENT")
        self.assertNotEqual(item["status"], "OPERATIONAL_KNOWLEDGE")

    def test_B_exact_evidence_duplicate_is_not_independent(self):
        exp = fixture()
        run = learn([source(exp, exp)])
        self.assertEqual(len(run["records"]), 1)
        self.assertEqual(run["duplicates"][0]["kind"], "EXACT_DUPLICATE")
        self.assertEqual(exact(run)["quality"]["independent_evidence_count"], 1)

    def test_relabeled_identical_measurements_not_replication(self):
        a, b = fixture(), fixture(run=2, evidence=2)
        run = learn([source(a, b)])
        self.assertEqual(exact(run)["quality"]["independent_evidence_count"], 1)
        self.assertEqual(run["experiment_comparisons"][0]["kind"], "EXACT_MEASUREMENT_DUPLICATE")
        self.assertNotEqual(exact(run)["claim_type"], "REPLICATED_EFFECT")

    def test_copied_confirmation_not_independent_despite_changed_screen(self):
        a, b = fixture(), fixture(run=2, evidence=2)
        b["screen"]["cost_s"] += .1
        item = exact(learn([source(a, b)]))
        self.assertEqual(item["quality"]["independent_evidence_count"], 1)
        self.assertNotEqual(item["confidence"], "HIGH")

    def test_C_independent_confirmations_create_operational_knowledge(self):
        run = learn([source(fixture(), fixture(run=2, evidence=2, variation=.01))])
        item = exact(run)
        self.assertEqual(item["claim_type"], "REPLICATED_EFFECT")
        self.assertEqual(item["replication_status"], "REPLICATED_INDEPENDENTLY")
        self.assertEqual(item["confidence"], "HIGH")
        self.assertEqual(item["status"], "OPERATIONAL_KNOWLEDGE")
        self.assertEqual(item["hierarchy"], "OPERATIONAL_KNOWLEDGE")

    def test_distinct_experiments_same_execution_are_not_independent(self):
        run = learn([source(fixture(), fixture(run=1, evidence=2, variation=.01))])
        self.assertEqual(exact(run)["quality"]["independent_evidence_count"], 1)
        self.assertNotEqual(exact(run)["confidence"], "HIGH")

    def test_D_accepted_then_contradicted_lowers_confidence(self):
        run = learn([source(fixture(), fixture("REJECTED", run=2, evidence=2))])
        item = exact(run)
        self.assertEqual(item["status"], "CONTRADICTED")
        self.assertEqual(item["replication_status"], "CONTRADICTED")
        self.assertEqual(item["confidence"], "LOW")
        self.assertTrue(item["contradictory_evidence"])

    def test_E_promising_inconclusive_is_not_success(self):
        run = learn([source(fixture("INCONCLUSIVE"))])
        item = run["records"][0]
        self.assertEqual(item["claim_type"], "PROMISING_DIRECTION")
        self.assertEqual(item["claim"]["outcome"], "INCONCLUSIVE")
        self.assertEqual(item["confidence"], "LOW")
        self.assertIn("interval_below_acceptance_threshold", item["supporting_evidence"][0]["missing_evidence"])

    def test_unpromising_inconclusive_retained_separately_from_rejection(self):
        exp = fixture("INCONCLUSIVE", variation=.08)
        item = learn([source(exp)])["records"][0]
        self.assertEqual(item["claim_type"], "INCONCLUSIVE_RESULT")
        self.assertEqual(item["claim"]["outcome"], "INCONCLUSIVE")

    def test_pareto_tradeoff_not_mislabeled_as_unresolved_cost_interval(self):
        exp = fixture()
        exp["outcome"] = "INCONCLUSIVE"
        exp["promotion"] = False
        exp["confirmation"]["decision"] = "pareto_alternative"
        item = learn([source(exp)])["records"][0]
        self.assertEqual(item["claim_type"], "INCONCLUSIVE_RESULT")
        self.assertEqual(item["claim"]["effect"], "RESOURCE_TRADEOFF_UNRESOLVED")
        self.assertIn("resource_tradeoff_resolution", item["supporting_evidence"][0]["missing_evidence"])
        self.assertNotIn("interval_below_acceptance_threshold", item["supporting_evidence"][0]["missing_evidence"])

    def test_F_negative_exact_configuration_not_regional_ban(self):
        item = exact(learn([source(fixture("REJECTED"))]))
        self.assertEqual(item["claim_type"], "REJECTED_DIRECTION")
        self.assertEqual(item["claim"]["negative_reuse_scope"], "EXACT_CANDIDATE_EQUIVALENT_CONTEXT_ONLY")
        self.assertEqual(len(item["claim"]["tested_configurations"]), 1)

    def test_single_screening_rejection_not_sufficient_for_avoidance(self):
        real = load_source(REAL)
        item = learn([source(real["experiments"][0])])["records"][0]
        self.assertEqual(item["claim_type"], "REJECTED_DIRECTION")
        self.assertEqual(item["claim"]["negative_reuse_scope"], "HISTORICAL_REJECTION_ONLY")

    def test_quality_guard_failure_is_informative_negative(self):
        exp = fixture("REJECTED")
        exp["confirmation"]["candidate_reached"] = 2
        exp["confirmation"]["pairs"] = 2
        for field in ("candidate_costs", "baseline_costs"):
            exp["confirmation"][field] = exp["confirmation"][field][:2]
        item = learn([source(exp)])["records"][0]
        self.assertEqual(item["claim"]["effect"], "QUALITY_GUARD_NOT_MET")

    def test_paired_cost_count_cannot_exceed_successful_quality_trials(self):
        exp = fixture("REJECTED")
        exp["confirmation"]["candidate_reached"] = 2
        with self.assertRaises(ValueError):
            source(exp)

    def test_failed_execution_does_not_claim_a_runtime_cause(self):
        exp = fixture("REJECTED")
        exp["confirmation"] = None
        exp["screen"] = {"status": "timeout", "reached": False, "cost_s": None, "baseline_cost_s": 1}
        item = learn([source(exp)])["records"][0]
        self.assertEqual(item["claim"]["effect"], "EXECUTION_NOT_SUCCESSFUL")

    def test_G_different_runtime_does_not_consolidate_as_replication(self):
        a, b = fixture(), fixture(run=2, evidence=2, variation=.01, context_change={"runtime_hash": "f" * 64})
        run = learn([source(a, b)])
        self.assertTrue(all(k["confidence"] != "HIGH" for k in run["knowledge"]))
        self.assertEqual(len([k for k in run["knowledge"] if k["claim"]["subject"] == "EXACT_CONFIGURATION"]), 2)

    def test_verification_rollback_does_not_refute_promotion(self):
        real = load_source(REAL)
        accepted = next(r for r in learn([real])["records"] if r["claim"]["outcome"] == "ACCEPTED")
        self.assertEqual(accepted["supporting_evidence"][0]["rollback"], "VERIFICATION")
        self.assertFalse(accepted["contradictory_evidence"])

    def test_adverse_or_unknown_rollback_is_explicit_counterevidence(self):
        for rollback in ("ADVERSE", "UNKNOWN"):
            exp = fixture()
            exp["rollback"] = rollback
            result = learn([source(exp)])
            self.assertEqual(result["records"][0]["status"], "CONTRADICTED")
            self.assertNotEqual(exact(result)["confidence"], "HIGH")

    def test_test_b_three_records_and_cautious_direction_synthesis(self):
        run = learn([load_source(REAL)])
        by_exp = {r["source_experiments"][0]: r for r in run["records"]}
        self.assertEqual(by_exp["e00001"]["claim_type"], "REJECTED_DIRECTION")
        self.assertEqual(by_exp["e00002"]["claim_type"], "PROMISING_DIRECTION")
        self.assertEqual(by_exp["e00003"]["claim_type"], "OBSERVED_EFFECT")
        region = next(k for k in run["knowledge"] if k["claim"]["subject"] == "HIGHER_LR_REGION")
        self.assertEqual(region["claim_type"], "CONTEXT_DEPENDENT_EFFECT")
        self.assertEqual(region["confidence"], "MEDIUM")
        self.assertEqual(region["quality"]["independent_evidence_count"], 1)
        self.assertEqual(region["claim"]["tested_lr_values"], [.0763])
        self.assertEqual(region["claim"]["tested_wd_values"], [0, .003888])
        self.assertFalse(any(k["status"] == "OPERATIONAL_KNOWLEDGE" for k in run["knowledge"]))

    def test_no_recollection_or_new_candidate_execution(self):
        with patch("gaia.observation.collector.collect", side_effect=AssertionError("forbidden")), patch("gaia.diagnosis.engine.diagnose", side_effect=AssertionError("forbidden")):
            learn([load_source(REAL)])


class SourceSchemaTests(unittest.TestCase):
    def test_source_and_learning_canonical_hashes(self):
        s = source(fixture())
        self.assertEqual(validate_source(s), s)
        item = learn([s])["records"][0]
        self.assertEqual(validate(item), item)
        self.assertEqual(provenance.canonical_json(item), provenance.canonical_json(dict(reversed(list(item.items())))))
        for key in item:
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                validate({k: v for k, v in item.items() if k != key})

    def test_corrupt_source_and_future_schema_rejected(self):
        s = source(fixture())
        s["experiments"][0]["outcome"] = "REJECTED"
        with self.assertRaises(ValueError):
            validate_source(s)
        with self.assertRaises(ValueError):
            seal_source({**source(fixture()), "schema": "future"})

    def test_acceptance_requires_confirmation(self):
        exp = fixture()
        exp["confirmation"] = None
        with self.assertRaises(ValueError):
            source(exp)
        exp = fixture()
        exp["confirmation"]["upper95"] = 1.1
        with self.assertRaises(ValueError):
            source(exp)

    def test_resealed_false_cost_ratio_rejected(self):
        exp = fixture()
        exp["confirmation"]["ratio"] = .1
        with self.assertRaises(ValueError):
            source(exp)

    def test_private_extensions_and_paths_in_projection_rejected(self):
        exp = fixture()
        exp["username"] = "PRIVATE_CANARY_05"
        with self.assertRaises(ValueError):
            source(exp)
        exp = fixture()
        exp["artifacts"][0]["path"] = "../secret.json"
        with self.assertRaises(ValueError):
            source(exp)

    def test_unsupported_slots_not_echoed(self):
        exp = fixture()
        exp["candidate"]["slots"]["optimizer"] = "PRIVATE_CANARY_05"
        with self.assertRaises(ValueError):
            source(exp)

    def test_false_upper_interval_or_promotion_not_accepted(self):
        exp = fixture()
        exp["confirmation"]["upper95"] = .1
        with self.assertRaises(ValueError):
            source(exp)
        exp = fixture("INCONCLUSIVE")
        exp["promotion"] = True
        with self.assertRaises(ValueError):
            source(exp)

    def test_noncanonical_source_file_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.json"
            path.write_text(json.dumps(source(fixture()), indent=2))
            with self.assertRaises(ValueError):
                load_source(path)

    def test_hierarchy_cannot_upgrade_single_experiment(self):
        item = learn([source(fixture())])["records"][0]
        for changes in ({"claim_type": "REPLICATED_EFFECT"}, {"confidence": "HIGH"}, {"hierarchy": "OPERATIONAL_KNOWLEDGE"}):
            with self.assertRaises(ValueError):
                seal({**item, **changes})

    def test_forged_counts_cannot_make_one_experiment_independent(self):
        item = exact(learn([source(fixture())]))
        item["quality"]["evidence_count"] = 2
        item["quality"]["independent_evidence_count"] = 2
        item["quality"]["independent_positive_count"] = 2
        item["claim_type"] = "REPLICATED_EFFECT"
        item["replication_status"] = "REPLICATED_INDEPENDENTLY"
        with self.assertRaises(ValueError):
            seal(item)

    def test_experimental_claim_has_explicit_hierarchy(self):
        run = learn([source(fixture())])
        self.assertEqual(run["evidence_hierarchy"], ["OBSERVATION", "HYPOTHESIS", "EXPERIMENTAL_EVIDENCE", "REPLICATED_EVIDENCE", "OPERATIONAL_KNOWLEDGE"])
        with self.assertRaises(ValueError):
            seal({**run["records"][0], "hierarchy": "OBSERVATION"})

    def test_same_evidence_hash_different_projection_rejected(self):
        a, b = fixture(), fixture("REJECTED", evidence=2)
        b["evidence_hash"] = a["evidence_hash"]
        with self.assertRaises(ValueError):
            learn([source(a, b)])

    def test_learning_configuration_is_separate_and_safe(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        before = provenance.experimental_config(cfg)
        cfg["learning"]["minimum_independent_replications"] = 3
        self.assertEqual(before, provenance.experimental_config(cfg))
        self.assertEqual(settings(cfg)["minimum_independent_replications"], 3)
        for values in ({"minimum_independent_replications": 1}, {"contradiction_confidence_penalty": 0}, {"unknown": 1}):
            with self.assertRaises(ValueError):
                settings({"learning": values})


class ApplicabilityTests(unittest.TestCase):
    def setUp(self):
        self.context = fixture()["context"]

    def test_exact_context_requires_explicit_full_identity(self):
        self.assertEqual(assess(self.context, self.context)["transferability"], "EXACT_CONTEXT")
        self.assertEqual(assess(self.context)["transferability"], "UNKNOWN_TRANSFER")
        self.assertEqual(assess(self.context, {"workload": "numpy_mlp"})["transferability"], "SAME_WORKLOAD")

    def test_runtime_and_hardware_changes_are_stale(self):
        for key in ("environment_hash", "runtime_hash", "host_hash", "benchmark_hash", "source_hash", "gaia_version"):
            changed = {**self.context, key: "gaia-v0.5" if key == "gaia_version" else "b" * 64}
            self.assertEqual(assess(self.context, changed)["status"], "STALE")

    def test_llm_or_gpu_transfer_never_assumed(self):
        self.assertEqual(assess(self.context, {"workload": "llm"})["transferability"], "NOT_TRANSFERABLE")
        self.assertEqual(assess(self.context, {"trainer_family": "gpu"})["transferability"], "NOT_TRANSFERABLE")

    def test_staleness_policy_does_not_make_changed_context_exact(self):
        changed = {**self.context, "runtime_hash": "a" * 64}
        view = assess(self.context, changed, {"stale_on_runtime_change": False})
        self.assertEqual(view["status"], "LIMITED")
        self.assertEqual(view["transferability"], "SAME_WORKLOAD")


class StoreQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = LearningStore(self.tmp.name)

    def test_immutable_files_idempotent_ingestion_and_query(self):
        s = source(fixture())
        first = self.store.ingest([s])
        self.assertEqual(self.store.ingest([s]), first)
        self.assertEqual(len(self.store.batches()), 1)
        item = self.store.items("records")[0]
        self.assertEqual(self.store.read(item["learning_id"]), item)
        path = self.store._path("records", item["learning_id"])
        self.assertEqual(path.stat().st_mode & 0o222, 0)
        with self.assertRaises(ValueError):
            self.store._write("records", item["learning_id"], {**item, "confidence": "HIGH"})

    def test_H_supersession_keeps_old_bytes_and_adds_bidirectional_relations(self):
        first = self.store.ingest([source(fixture())])
        old = exact(first["run"])
        raw = self.store._path("knowledge", old["learning_id"]).read_bytes()
        second = self.store.ingest([source(fixture(run=2, evidence=2, variation=.01))])
        new = exact(second["run"])
        self.assertIn(old["learning_id"], new["supersedes"])
        self.assertEqual(raw, self.store._path("knowledge", old["learning_id"]).read_bytes())
        all_views = query(self.store, component="cpu_evolution", include_superseded=True)
        old_view = next(v for v in all_views if v["item"]["learning_id"] == old["learning_id"])
        self.assertEqual(old_view["effective_status"], "SUPERSEDED")
        self.assertIn(new["learning_id"], old_view["effective_superseded_by"])

    def test_new_contradiction_cannot_leave_old_high_operational(self):
        self.store.ingest([source(fixture(), fixture(run=2, evidence=2, variation=.01))])
        context = fixture()["context"]
        before = query(self.store, component="cpu_evolution", context=context)
        self.assertTrue(any(v["usable_as_operational_knowledge"] for v in before))
        self.store.ingest([source(fixture("REJECTED", run=3, evidence=3))])
        after = query(self.store, component="cpu_evolution", context=context)
        self.assertFalse(any(v["usable_as_operational_knowledge"] for v in after))
        self.assertTrue(any(v["weakened_by"] for v in after))
        self.assertFalse(query(self.store, component="cpu_evolution", replicated_only=True))

    def test_weak_screening_counterevidence_is_weakens_not_confirmed_refutation(self):
        self.store.ingest([source(fixture())])
        exp = fixture("REJECTED", run=2, evidence=2)
        exp["confirmation"] = None
        batch = self.store.ingest([source(exp)])
        self.assertTrue(any(r["relation"] == "weakens" for r in batch["run"]["relations"]))

    def test_query_filters_and_no_unqualified_dump(self):
        self.store.ingest([load_source(REAL)])
        with self.assertRaises(ValueError):
            query(self.store)
        rejected = query(self.store, workload="numpy_mlp", claim_type="REJECTED_DIRECTION")
        self.assertEqual(len(rejected), 1)
        self.assertEqual(query(self.store, workload="llm"), [])
        self.assertEqual(query(self.store, component="gpu"), [])
        self.assertEqual(query(self.store, environment="f" * 64), [])
        self.assertEqual(query(self.store, workload="numpy_mlp", minimum_confidence="HIGH"), [])

    def test_stale_view_does_not_rewrite_knowledge(self):
        self.store.ingest([source(fixture())])
        context = {**fixture()["context"], "runtime_hash": "a" * 64}
        self.assertEqual(query(self.store, component="cpu_evolution", context=context), [])
        stale = query(self.store, component="cpu_evolution", context=context, include_stale=True)
        self.assertTrue(stale)
        self.assertTrue(all(v["applicability_assessment"]["status"] == "STALE" for v in stale))
        self.assertTrue(all(v["status"] != "STALE" for v in self.store.items("knowledge")))

    def test_atomic_failure_no_visible_batch(self):
        with patch("gaia.learning.store.os.link", side_effect=OSError("fault")):
            with self.assertRaises(OSError):
                self.store.ingest([source(fixture())])
        self.assertEqual(self.store.batches(), [])
        self.assertFalse(list(self.store.directory.glob("**/.pending-*")))

    def test_failure_at_commit_does_not_expose_uncommitted_items(self):
        original = self.store._write
        def failure(category, identifier, document):
            if category == "batches":
                raise OSError("commit fault")
            return original(category, identifier, document)
        with patch.object(self.store, "_write", side_effect=failure):
            with self.assertRaises(OSError):
                self.store.ingest([source(fixture())])
        self.assertEqual(self.store.items("records"), [])
        self.assertEqual(self.store.items("knowledge"), [])
        self.store.ingest([source(fixture())])
        self.assertTrue(self.store.items("records"))

    def test_concurrent_identical_ingestion_commits_once(self):
        from concurrent.futures import ThreadPoolExecutor
        s = source(fixture())
        with ThreadPoolExecutor(max_workers=4) as pool:
            batches = list(pool.map(lambda _: self.store.ingest([s]), range(4)))
        self.assertEqual(len({b["batch_hash"] for b in batches}), 1)
        self.assertEqual(len(self.store.batches()), 1)

    def test_store_policy_cannot_change_silently(self):
        self.store.ingest([source(fixture())])
        with self.assertRaises(ValueError):
            self.store.ingest([source(fixture(run=2, evidence=2, variation=.01))], {"learning": {"minimum_independent_replications": 3}})

    def test_path_symlink_and_corruption_rejected(self):
        with self.assertRaises(ValueError):
            self.store._path("records", "../../secret")
        self.store.ingest([source(fixture())])
        item = self.store.items("records")[0]
        path = self.store._path("records", item["learning_id"])
        path.chmod(0o644); path.write_text("{}")
        with self.assertRaises(ValueError):
            self.store.batches()


class AuditCLITests(unittest.TestCase):
    def test_audit_reproduces_and_rejects_added_solution(self):
        from tools.audit_learning import audit_run, source_policy
        s = source(fixture())
        run = learn([s])
        from gaia.learning.contradictions import with_history
        run = with_history(run)
        self.assertEqual(audit_run(run, [s])["status"], "PASS")
        self.assertTrue(source_policy()["no_execution_authority"])
        item = run["records"][0]
        item["limitations"].append("PRIVATE_CANARY_05: next experiment lr .08")
        run["records"][0] = seal(item)
        run["run_hash"] = provenance.digest({k: v for k, v in run.items() if k != "run_hash"})
        with self.assertRaises(ValueError):
            audit_run(run, [s])

    def test_store_audit_checks_supersession_and_contradiction_history(self):
        from tools.audit_learning import audit_store
        with tempfile.TemporaryDirectory() as tmp:
            store = LearningStore(tmp)
            store.ingest([source(fixture())])
            store.ingest([source(fixture(run=2, evidence=2, variation=.01))])
            store.ingest([source(fixture("REJECTED", run=3, evidence=3))])
            self.assertEqual(len(audit_store(tmp)), 3)

    def test_audit_cli_reproduces_exported_sequential_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = LearningStore(root / "state")
            args = []
            for i, exp in enumerate((fixture(), fixture(run=2, evidence=2, variation=.01), fixture("REJECTED", run=3, evidence=3)), 1):
                s = source(exp)
                source_path, run_path = root / f"source-{i}.json", root / f"run-{i}.json"
                source_path.write_bytes(provenance.canonical_json(s))
                run_path.write_bytes(provenance.canonical_json(store.ingest([s])["run"]))
                args += ["--source", str(source_path), "--run", str(run_path)]
            proc = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", str(ROOT / "tools/audit_learning.py"), *args],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(len(json.loads(proc.stdout)["runs"]), 3)

    def test_cli_real_test_b_records_queries_show_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            def cli(*args, expected=0):
                proc = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", str(ROOT / "gaia.py"), *args,
                                       "--state-dir", tmp, "--json"], capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
                return json.loads(proc.stdout) if expected == 0 else proc.stdout
            batch = cli("learn-experiments", str(REAL))
            records = cli("learning-records")
            self.assertEqual(len(records), 3)
            self.assertEqual(cli("learning-record", records[0]["learning_id"]), records[0])
            self.assertEqual(len(cli("knowledge")), 4)
            self.assertEqual(cli("knowledge-item", "latest")["kind"], "knowledge")
            self.assertEqual(len(cli("query-knowledge", "--workload", "numpy_mlp", "--component", "cpu_evolution")), 4)
            self.assertEqual(len(cli("query-knowledge", "--claim-type", "REJECTED_DIRECTION")), 1)
            self.assertIn("INVALID_SOURCE", cli("query-knowledge", expected=2))
            self.assertIn("INVALID_SOURCE", cli("knowledge-item", "missing", expected=2))
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["learning"])


if __name__ == "__main__":
    unittest.main()
