"""Shadow strategies from real saved knowledge and explicitly controlled targets."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gaia import config, provenance
from gaia.diagnosis.engine import diagnose
from gaia.learning.contradictions import with_history
from gaia.learning.engine import learn
from gaia.prioritization.engine import prioritize
from gaia.prioritization.policy import ordering
from gaia.prioritization.schema import seal as seal_priority
from gaia.experiment_strategy.engine import plan_experiments
from gaia.experiment_strategy.model import finish_plan
from gaia.experiment_strategy.policy import rank, score, settings
from gaia.experiment_strategy.schema import seal, validate
from gaia.experiment_strategy.query import query
from gaia.experiment_strategy.store import StrategyStore
from test_diagnosis import fixture as observation, metric, reseal
from test_learning import fixture as experiment, source

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "docs/learning_evidence/test-b-run.json"
REAL_NOISY = ROOT / "docs/prioritization_evidence/real-noisy.json"
REAL_NO_ISSUE = ROOT / "docs/prioritization_evidence/real-no-issue.json"


def target(*, noisy=False, cls="CPU_RUNTIME_EFFICIENCY"):
    obs = observation()
    metric(obs, "resources", "system_cpu_utilization_percent", [98] * 5)
    if noisy:
        metric(obs, "workload", "wall_s", [1, 2, 1, 2, 1])
    d = diagnose(reseal(obs))
    p = prioritize([d])
    if not noisy:
        p["candidate_targets"] = [t for t in p["candidate_targets"] if t["target_class"] == cls]
        p["ordering"] = [t["target_id"] for t in ordering(p["candidate_targets"])]
        p["blockers"] = {t["target_id"]: t["blocked_by"] for t in p["candidate_targets"] if t["blocked_by"]}
        p = seal_priority(p)
    return p, d


def knowledge(*experiments):
    return with_history(learn([source(*experiments)]))


def plan(p=None, runs=(), context=None, **kwargs):
    p = p if p is not None else target()[0]
    return plan_experiments(p, runs, context=context if context is not None else experiment()["context"], analysis_mode="HISTORICAL_ANALYSIS", **kwargs)


def first(document):
    return next(p for p in document["candidate_plans"] if p["plan_id"] == document["ranking"][0])


class StrategyCases(unittest.TestCase):
    def test_A_accepted_unreplicated_favors_replication(self):
        result = plan(runs=[knowledge(experiment())])
        p = first(result)
        self.assertEqual(p["class"], "REPLICATION")
        self.assertEqual(p["mode"], "VERIFY")
        self.assertEqual(p["novelty"], "EXACT_REPEAT")
        self.assertTrue(p["duplication"]["intentional"])
        self.assertEqual(p["utility"]["components"]["duplication"], 0)

    def test_B_promising_inconclusive_favors_discrimination_verify(self):
        result = plan(runs=[knowledge(experiment("INCONCLUSIVE"))])
        self.assertEqual(first(result)["class"], "DISCRIMINATION")
        self.assertEqual(first(result)["mode"], "VERIFY")
        self.assertEqual(first(result)["design"], "PAIRED_DISCRIMINATION")
        self.assertEqual(first(result)["variables"], ["independent_paired_evidence"])
        self.assertEqual(first(result)["candidate_variation"]["kind"], "REPEAT_REFERENCE_CONFIGURATION")
        self.assertFalse(any(p["mode"] == "EXPLOIT" for p in result["candidate_plans"]))

    def test_C_strong_exact_rejection_blocks_accidental_repeat_not_region(self):
        result = plan(runs=[knowledge(experiment("REJECTED"))])
        negative = next(p for p in result["candidate_plans"] if "META_NEGATIVE_001" in p["rule_ids"])
        self.assertIn("EXACT_REJECTED_CONFIGURATION", negative["blocked_by"])
        self.assertNotIn(negative["plan_id"], result["ranking"])
        self.assertLess(negative["utility"]["components"]["duplication"], 0)
        self.assertTrue(result["ranking"])

    def test_D_noisy_blocker_favors_measurement_refinement(self):
        p, _ = target(noisy=True)
        result = plan(p)
        self.assertEqual(first(result)["class"], "MEASUREMENT_REFINEMENT")
        self.assertTrue(any(e["reason"] == "TARGET_DEFERRED_OR_BLOCKED" for e in result["exclusions"]))
        self.assertFalse(any(q["target_ref"]["priority"] == "DEFER" for q in result["candidate_plans"]))

    def test_E_contradicted_knowledge_is_discriminated_not_exploited(self):
        result = plan(runs=[knowledge(experiment(), experiment("REJECTED", run=2, evidence=2))])
        self.assertEqual(first(result)["class"], "DISCRIMINATION")
        self.assertFalse(any(p["mode"] == "EXPLOIT" for p in result["candidate_plans"]))

    def test_F_stale_knowledge_requires_validation_before_reuse(self):
        context = {**experiment()["context"], "runtime_hash": "a" * 64}
        result = plan(runs=[knowledge(experiment())], context=context)
        self.assertEqual(first(result)["class"], "KNOWLEDGE_VALIDATION")
        self.assertTrue(any(k["stale"] for p in result["candidate_plans"] for k in p["knowledge_refs"]))
        self.assertFalse(any(p["mode"] == "EXPLOIT" for p in result["candidate_plans"]))

    def test_G_cheap_high_information_control_can_precede_local_search(self):
        result = plan(runs=[knowledge(experiment())])
        candidates = [p for p in result["candidate_plans"] if p["class"] in ("CONTROL_EXPERIMENT", "PARAMETER_LOCAL_SEARCH")]
        self.assertEqual(rank(candidates)[0]["class"], "CONTROL_EXPERIMENT")
        self.assertEqual(rank(candidates)[0]["estimates"]["improvement_potential"], "LOW")

    def test_H_no_knowledge_has_controlled_exploration(self):
        result = plan()
        self.assertTrue(any(p["mode"] == "EXPLORE" for p in result["candidate_plans"]))
        self.assertTrue(all(p["controlled_variables"] and p["stopping_rules"] for p in result["candidate_plans"]))

    def test_unknown_target_prefers_discrimination_before_optimization(self):
        from test_prioritization import diagnosis
        p = prioritize([diagnosis("unknown")])
        result = plan(p)
        self.assertEqual(first(result)["class"], "DISCRIMINATION")
        self.assertIn("COMPUTE_PRESSURE", first(result)["discriminates"])
        self.assertTrue(any(p["mode"] == "EXPLORE" for p in result["candidate_plans"]))

    def test_replicated_operational_knowledge_allows_exploitation(self):
        run = knowledge(experiment(), experiment(run=2, evidence=2, variation=.01))
        result = plan(runs=[run])
        self.assertTrue(any(p["class"] == "EXPLOITATION" and p["mode"] == "EXPLOIT" for p in result["candidate_plans"]))

    def test_superseded_or_newly_contradicted_old_high_not_exploited(self):
        a = knowledge(experiment())
        b = with_history(learn([source(experiment(), experiment(run=2, evidence=2, variation=.01))]), a["knowledge"])
        c = with_history(learn([source(experiment(), experiment(run=2, evidence=2, variation=.01), experiment("REJECTED", run=3, evidence=3))]), a["knowledge"] + b["knowledge"])
        result = plan(runs=[a, b, c])
        self.assertFalse(any(p["mode"] == "EXPLOIT" for p in result["candidate_plans"]))

    def test_incomplete_relationship_history_rejected(self):
        a = knowledge(experiment())
        b = with_history(learn([source(experiment(), experiment(run=2, evidence=2, variation=.01))]), a["knowledge"])
        with self.assertRaises(ValueError):
            plan(runs=[b])

    def test_real_test_b_replication_and_screening_repeat_penalty(self):
        run = json.loads(REAL.read_bytes())
        result = plan(runs=[run])
        self.assertEqual(first(result)["class"], "REPLICATION")
        negative = next(p for p in result["candidate_plans"] if "META_NEGATIVE_001" in p["rule_ids"])
        self.assertFalse(negative["blocked_by"])
        self.assertLess(negative["utility"]["ordinal_total"], first(result)["utility"]["ordinal_total"])
        self.assertEqual(negative["duplication"]["negative_reuse_scope"], "HISTORICAL_REJECTION_ONLY")

    def test_test_b_factorial_plan_is_controlled_confounding_test_not_proven_interaction(self):
        result = plan(runs=[json.loads(REAL.read_bytes())])
        factorial = next(p for p in result["candidate_plans"] if p["design"] == "CONTROLLED_FACTORIAL")
        self.assertEqual(factorial["variables"], ["learning_rate", "weight_decay"])
        self.assertEqual(factorial["candidate_variation"]["numeric_values"], None)
        self.assertIn("CO_CHANGED_LR_WD_ARE_CONFOUNDING_NOT_ESTABLISHED_INTERACTION", factorial["rationale"])

    def test_no_significant_priority_produces_no_plan(self):
        result = plan(json.loads((ROOT / "docs/prioritization_evidence/real-no-issue.json").read_bytes()))
        self.assertEqual(result["candidate_plans"], [])
        self.assertEqual(result["ranking"], [])

    def test_frozen_target_never_receives_plan(self):
        from test_prioritization import diagnosis
        priority = prioritize([diagnosis("gpu")])
        result = plan(priority)
        self.assertEqual(result["candidate_plans"], [])
        self.assertEqual(result["exclusions"][0]["reason"], "FROZEN_COMPONENT")

    def test_current_context_cannot_be_bound_to_unrelated_historical_host(self):
        with self.assertRaises(ValueError):
            plan_experiments(target()[0], [knowledge(experiment())], context=experiment()["context"])

    def test_no_context_does_not_assume_exact_transfer(self):
        result = plan_experiments(target()[0], [knowledge(experiment())])
        knowledge_plans = [p for p in result["candidate_plans"] if p["knowledge_refs"]]
        self.assertTrue(knowledge_plans)
        self.assertTrue(all("CONTEXT_NOT_BOUND" in p["blocked_by"] for p in knowledge_plans))
        self.assertFalse(any(p["mode"] == "EXPLOIT" for p in knowledge_plans))


class PolicyAndDimensionsTests(unittest.TestCase):
    def setUp(self):
        self.doc = plan(runs=[knowledge(experiment())])
        self.p = copy.deepcopy(first(self.doc))
        self.cfg = settings()

    def test_information_and_improvement_are_distinct(self):
        self.assertEqual(self.p["estimates"]["information_value"], "HIGH")
        self.assertEqual(self.p["estimates"]["improvement_potential"], "LOW")

    def test_cost_risk_reversibility_each_influence_utility(self):
        original = sum(score(self.p, self.cfg).values())
        for field, value in (("cost", "HIGH"), ("risk", "HIGH"), ("reversibility", "DIFFICULT")):
            p = copy.deepcopy(self.p)
            p["estimates"][field] = value
            self.assertLess(sum(score(p, self.cfg).values()), original)

    def test_novelty_alone_has_no_bonus(self):
        base = score(self.p, self.cfg)
        self.p["novelty"] = "NEW_REGION"
        self.assertEqual(score(self.p, self.cfg), base)

    def test_duplicate_penalty_not_applied_to_intentional_replication(self):
        self.p["duplication"]["risk"] = "HIGH"
        self.assertEqual(score(self.p, self.cfg)["duplication"], 0)
        self.p["duplication"]["intentional"] = False
        self.assertEqual(score(self.p, self.cfg)["duplication"], -self.cfg["exact_repeat_penalty"])

    def test_stopping_conditions_and_finite_budget_present(self):
        for p in self.doc["candidate_plans"]:
            self.assertTrue(p["stopping_rules"]["success_condition"])
            self.assertTrue(p["stopping_rules"]["rejection_condition"])
            self.assertTrue(p["stopping_rules"]["inconclusive_condition"])
            self.assertLessEqual(p["stopping_rules"]["max_evidence_budget"], self.cfg["max_trials_per_plan"])
            self.assertFalse(p["stopping_rules"]["automatic_extension"])

    def test_historical_cost_not_invented_future_seconds(self):
        self.assertIsNotNone(self.p["estimates"]["historical_candidate_cost_median_s"])
        self.assertIsNone(self.p["estimates"]["future_seconds_estimate"])

    def test_candidate_cap_and_exploration_floor(self):
        result = plan(configuration={"meta_strategy": {"max_candidate_plans": 1}})
        self.assertEqual(len(result["candidate_plans"]), 1)
        self.assertEqual(first(result)["mode"], "EXPLORE")
        self.assertTrue(result["exclusions"])

    def test_factorial_blocked_when_budget_cannot_cover_design(self):
        result = plan(runs=[json.loads(REAL.read_bytes())], configuration={"meta_strategy": {"max_trials_per_plan": 5}})
        factorial = next(p for p in result["candidate_plans"] if p["design"] == "CONTROLLED_FACTORIAL")
        self.assertIn("INSUFFICIENT_CONCEPTUAL_EVIDENCE_BUDGET", factorial["blocked_by"])
        self.assertNotIn(factorial["plan_id"], result["ranking"])

    def test_settings_reject_unknown_and_unbounded_values(self):
        for values in ({"max_candidate_plans": 0}, {"max_trials_per_plan": 0}, {"unknown": 1}, {"exploration_floor": 2, "max_candidate_plans": 1}):
            with self.assertRaises(ValueError):
                settings({"meta_strategy": values})

    def test_sensitive_risk_blocks_all_plans_without_easing_target_policy(self):
        p = target()[0]
        from gaia.prioritization.policy import decide
        for t in p["candidate_targets"]:
            t["dimensions"]["risk"] = "HIGH"
            t["priority"], t["rule_ids"], t["reasons"] = decide(t["dimensions"], t["blocked_by"], p["policy"]["settings"])
        p["ordering"] = [t["target_id"] for t in ordering(p["candidate_targets"])]
        result = plan(seal_priority(p))
        self.assertEqual(result["ranking"], [])
        self.assertTrue(all("SENSITIVE_OR_UNBOUNDED_INVESTIGATION" in p["blocked_by"] for p in result["candidate_plans"]))

    def test_evolution_and_previous_defaults_unchanged_by_meta_settings(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        before = provenance.experimental_config(cfg)
        cfg["meta_strategy"]["replication_bonus"] = 5
        self.assertEqual(before, provenance.experimental_config(cfg))


class SchemaHistoryAuditTests(unittest.TestCase):
    def test_schema_hashes_required_fields_and_canonical(self):
        result = plan()
        self.assertEqual(validate(result), result)
        self.assertEqual(provenance.canonical_json(result), provenance.canonical_json(dict(reversed(list(result.items())))))
        for key in result:
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                validate({k: v for k, v in result.items() if k != key})
        with self.assertRaises(ValueError):
            seal({**result, "schema": "future"})

    def test_corrupt_priority_or_learning_input_rejected(self):
        p = target()[0]
        p["prioritization_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            plan(p)
        run = knowledge(experiment())
        run["run_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            plan(runs=[run])

    def test_forged_history_comparison_reference_rejected(self):
        run = knowledge(experiment())
        run["experiment_comparisons"].append({"a": "0" * 64, "b": "1" * 64, "kind": "INDEPENDENT_REPLICATION", "counted_independently": True})
        run["run_hash"] = provenance.digest({k: v for k, v in run.items() if k != "run_hash"})
        with self.assertRaises(ValueError):
            plan(runs=[run])

    def test_immutable_known_source_ids_not_free_text_channels(self):
        p = target()[0]
        p["candidate_targets"][0]["source_refs"][0]["evidence_refs"] = ["PRIVATE_CANARY_06"]
        p = seal_priority(p)
        with self.assertRaises(ValueError):
            plan(p)

    def test_forged_ranking_or_future_execution_not_accepted(self):
        doc = plan()
        doc["ranking"] = list(reversed(doc["ranking"]))
        with self.assertRaises(ValueError):
            seal(doc)
        doc = plan()
        doc["history"]["proposed_plans"][0]["eventual_execution"] = "EXECUTED"
        doc["history"]["history_hash"] = provenance.digest({k: v for k, v in doc["history"].items() if k != "history_hash"})
        with self.assertRaises(ValueError):
            seal(doc)

    def test_no_execution_mutation_or_hidden_code_fields(self):
        result = plan()
        p = result["candidate_plans"][0]
        p["execution"]["executed"] = True
        result["candidate_plans"][0] = finish_plan(p)
        with self.assertRaises(ValueError):
            seal(result)
        result = plan()
        p = result["candidate_plans"][0]
        p["command"] = "execute trainer"
        result["candidate_plans"][0] = finish_plan(p)
        with self.assertRaises(ValueError):
            seal(result)

    def test_generated_numeric_variation_not_allowed(self):
        result = plan()
        p = result["candidate_plans"][0]
        p["candidate_variation"]["numeric_values"] = [.08]
        result["candidate_plans"][0] = finish_plan(p)
        with self.assertRaises(ValueError):
            seal(result)

    def test_priorities_and_inputs_are_not_modified(self):
        p, d = target()
        run = knowledge(experiment())
        before = copy.deepcopy((p, d, run))
        plan(p, [run], diagnoses=[d])
        self.assertEqual((p, d, run), before)

    def test_exact_diagnosis_binding_checked(self):
        p, d = target()
        result = plan(p, diagnoses=[d])
        self.assertEqual(result["diagnosis_binding"], "EXACT_SOURCES_CHECKED")
        other = diagnose(observation())
        with self.assertRaises(ValueError):
            plan(p, diagnoses=[other])

    def test_no_engine_search_worker_or_collection_calls(self):
        p, run = target()[0], knowledge(experiment())
        with patch("gaia.protected.evaluator.run_trial", side_effect=AssertionError("no worker")), patch("gaia.engine.Engine.run", side_effect=AssertionError("no campaign")), patch("gaia.learning.engine.learn", side_effect=AssertionError("no learning mutation")):
            plan(p, [run])

    def test_real_test_b_meta_metrics_are_descriptive_small_sample(self):
        result = plan(runs=[json.loads(REAL.read_bytes())])
        m = result["meta_metrics"]
        self.assertEqual((m["experiments"], m["accepted"], m["rejected"], m["inconclusive"]), (3, 1, 1, 1))
        self.assertEqual(m["accepted_improvement_rate"], 1 / 3)
        self.assertEqual(m["experiments_per_accepted_improvement"], 3)
        self.assertTrue(m["small_sample"])
        self.assertIsNone(m["cost_per_useful_experiment_s"])
        self.assertFalse(m["strategy_utility_improvement_demonstrated"])
        self.assertEqual(result["history"]["inferred_strategy_episodes"], [])
        self.assertTrue(all(p["eventual_execution"] == "UNKNOWN_UNLINKED" for p in result["history"]["proposed_plans"]))

    def test_duplicate_learning_snapshots_do_not_inflate_metric_denominator(self):
        run = json.loads(REAL.read_bytes())
        result = plan(runs=[run, run])
        self.assertEqual(result["meta_metrics"]["experiments"], 3)

    def test_safe_retrospective_replication_inference_on_synthetic_history(self):
        run = knowledge(experiment(), experiment(run=2, evidence=2, variation=.01))
        result = plan(runs=[run])
        self.assertTrue(result["history"]["inferred_strategy_episodes"])
        episode = result["history"]["inferred_strategy_episodes"][0]
        self.assertEqual(episode["class"], "REPLICATION")
        self.assertIsNone(episode["proposed_plan_link"])

    def test_rank_determinism_excluding_clock_and_cost(self):
        run = json.loads(REAL.read_bytes())
        p = target()[0]
        a, b = plan(p, [run]), plan(p, [run])
        ignored = {"timestamp", "cost", "output_hash"}
        self.assertEqual({k: v for k, v in a.items() if k not in ignored}, {k: v for k, v in b.items() if k not in ignored})

    def test_private_free_text_not_copied_from_inputs(self):
        p = target()[0]
        p["rationale"] = "PRIVATE_CANARY_06"
        p = seal_priority(p)
        result = plan(p)
        self.assertNotIn("PRIVATE_CANARY_06", provenance.canonical_json(result).decode())

    def test_audit_reproduces_and_rejects_added_instructions(self):
        from tools.audit_meta_strategy import audit_document, source_policy
        p = target()[0]
        run = json.loads(REAL.read_bytes())
        result = plan(p, [run])
        self.assertEqual(audit_document(result, [p], [run])["status"], "PASS")
        self.assertTrue(source_policy()["no_plan_execution"])
        result["limitations"].append("PRIVATE_CANARY_06: execute next")
        with self.assertRaises(ValueError):
            audit_document(seal(result), [p], [run])


class StoreCLIQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = StrategyStore(self.tmp.name)
        self.doc = plan(runs=[json.loads(REAL.read_bytes())])

    def test_store_immutable_list_latest_and_separate_artifacts(self):
        a, b = self.store.save(self.doc), self.store.save(self.doc)
        self.assertEqual(self.store.ids(), ["s000001", "s000002"])
        self.assertEqual(self.store.latest(), b)
        self.assertEqual(self.store.read("s000001"), a)
        with self.assertRaises(FileExistsError):
            self.store.save(self.doc, strategy_id="s000001")
        self.assertEqual(self.store.path("decisions", "s000001").stat().st_mode & 0o222, 0)
        self.assertEqual(sorted(p.name for p in Path(self.tmp.name).iterdir()), ["experiment-strategies"])

    def test_failure_before_commit_not_visible_and_ids_not_reused(self):
        original = self.store._put
        def fail(category, identifier, value, **kwargs):
            if category == "decisions":
                raise OSError("fault")
            return original(category, identifier, value, **kwargs)
        with patch.object(self.store, "_put", side_effect=fail):
            with self.assertRaises(OSError):
                self.store.save(self.doc)
        self.assertEqual(self.store.ids(), [])
        saved = self.store.save(plan())
        self.assertEqual(saved["strategy_id"], "s000002")

    def test_atomic_link_failure_leaves_no_pending_or_decision(self):
        with patch("gaia.experiment_strategy.store.os.link", side_effect=OSError("fault")):
            with self.assertRaises(OSError):
                self.store.save(self.doc)
        self.assertEqual(self.store.ids(), [])
        self.assertFalse(list(self.store.directory.glob("**/.pending-*")))

    def test_concurrent_writers_unique_decisions(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            docs = list(pool.map(lambda _: self.store.save(self.doc), range(4)))
        self.assertEqual(len({d["strategy_id"] for d in docs}), 4)

    def test_traversal_symlink_and_sidecar_corruption_rejected(self):
        with self.assertRaises(ValueError):
            self.store.read("../escape")
        self.store.save(self.doc)
        path = self.store.path("metrics", "s000001")
        path.chmod(0o644); path.write_text("{}")
        with self.assertRaises(ValueError):
            self.store.read("s000001")

    def test_queries_class_target_knowledge_duplicates_and_highest(self):
        self.store.save(self.doc)
        top = query(self.store, highest=True)[0]
        self.assertEqual(top["plan"]["class"], "REPLICATION")
        self.assertTrue(query(self.store, strategy_class="DISCRIMINATION"))
        self.assertTrue(query(self.store, target=top["plan"]["target_ref"]["target_id"]))
        self.assertTrue(query(self.store, knowledge=top["plan"]["knowledge_refs"][0]["learning_id"]))
        self.assertTrue(query(self.store, duplicates=True))

    def test_cli_real_no_issue_noisy_read_list_metrics_and_failure(self):
        def cli(*args, expected=0):
            p = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", str(ROOT / "gaia.py"), *args,
                                "--state-dir", self.tmp.name, "--json"], capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
            return json.loads(p.stdout) if expected == 0 else p.stdout
        empty = cli("plan-experiments", str(REAL_NO_ISSUE))
        self.assertEqual(empty["ranking"], [])
        noisy = cli("plan-experiments", str(REAL_NOISY))
        self.assertEqual(first(noisy)["class"], "MEASUREMENT_REFINEMENT")
        self.assertEqual(cli("experiment-strategy", "latest"), noisy)
        self.assertEqual(len(cli("experiment-strategies")), 2)
        self.assertEqual(cli("experiment-strategies", "--highest")[0]["plan"]["class"], "MEASUREMENT_REFINEMENT")
        self.assertEqual(cli("strategy-metrics")["metrics"]["experiments"], 0)
        self.assertIn("INVALID_INPUT", cli("plan-experiments", "missing", expected=2))


if __name__ == "__main__":
    unittest.main()
