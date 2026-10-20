import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gaia import bootstrap
from gaia.gaia_transformer import genome as G, meta_tasks as T, metastudy as M, search_strategy as S
from gaia.gaia_transformer.lab import benchmark, evaluator


def landscape():
    return [{**entry, "fitness": 4. if index == 0 else 2.8 if entry["operator"] in ("dim", "layers") else 5.,
             "resource_s": 12., "all_quality": True} for index, entry in enumerate(M.catalog())]


class TestGpuMetaTasks(unittest.TestCase):
    def test_task_digests_and_distinct_continuation_rules(self):
        frozen = json.loads(Path(T.__file__).with_name("meta_tasks_v1.json").read_text())
        for task in T.TASKS:
            self.assertEqual(T.manifest(task), frozen[task])
        self.assertNotEqual(T.generate(*("periodic_tune", "train")), T.generate("counter_holdout", "train"))
        rows = T.data.records(T.generate("counter_holdout", "validation"))
        indices = {value: index for index, value in enumerate(T.data.ALPHABET)}
        for row in rows:
            values = [indices[int(value)] for value in row[10:]]
            increments = {(b - a) % 16 for a, b in zip(values, values[1:])}
            self.assertEqual(len(increments), 1)
            self.assertIn(next(iter(increments)), (1, 3, 5, 7))

    def test_private_targets_and_production_evaluator_are_not_modified(self):
        original = evaluator.run_trial.__globals__["benchmark"]
        runner = T.evaluator_for("counter_holdout")
        self.assertIs(runner.__code__, evaluator.run_trial.__code__)
        self.assertIsNot(runner.__globals__, evaluator.run_trial.__globals__)
        self.assertIs(evaluator.run_trial.__globals__["benchmark"], original)
        a, x, y, digest = runner.__globals__["benchmark"].private_data(benchmark.TrialSpec())
        self.assertEqual(a.shape, (4096, 65))
        self.assertEqual(x.shape, (256, 64))
        self.assertEqual(y.shape, (256,))
        self.assertEqual(digest, T.manifest("counter_holdout")["sha256"])
        with self.assertRaises(ValueError):
            runner.__globals__["benchmark"].private_data(benchmark.TrialSpec(split="audit"))


class TestGpuMetaSearch(unittest.TestCase):
    def test_budgets_equal_and_simulation_reproducible(self):
        data = landscape()
        for strategy in [S.DEFAULT, *M.strategies(S.DEFAULT)]:
            a = M.simulate(strategy, data, 123)
            self.assertEqual(a, M.simulate(strategy, data, 123))
            self.assertEqual(a["queries"], M.PROTOCOL["query_budget"])
            self.assertLessEqual(a["resource_s"], M.PROTOCOL["wall_budget_s"])
        self.assertEqual(data, landscape())

    def test_expensive_candidate_does_not_reveal_fitness_after_deadline(self):
        data = landscape()
        for entry in data[1:]:
            entry.update(resource_s=1000, fitness=.1)
        self.assertEqual(M.simulate(S.DEFAULT, data, 1)["auc"], 0)

    def test_paired_evidence_requires_practical_gain_and_complete_seeds(self):
        self.assertTrue(S.paired_bound([0.] * 40, [-.1] * 40, 2.023)["supported"])
        self.assertFalse(S.paired_bound([0.] * 40, [-.001] * 40, 2.023)["supported"])
        self.assertFalse(S.paired_bound([0.] * 40, [0.] * 40, 2.023)["supported"])
        with self.assertRaises(ValueError):
            S.paired_bound([0.] * 20, [0.] * 19, 3.)

    def test_pre_registered_sets_and_catalog_exclude_research_options(self):
        self.assertFalse(set(M.PROTOCOL["tuning_search_seeds"]) & set(M.PROTOCOL["transfer_search_seeds"]))
        self.assertFalse(set(M.PROTOCOL["tune_model_seeds"]) & set(M.PROTOCOL["holdout_model_seeds"]))
        self.assertEqual(len(M.catalog()), 9)
        self.assertEqual(len({G.digest(entry["genome"]) for entry in M.catalog()}), 9)
        self.assertEqual(len(M.strategies(S.DEFAULT)), 4)
        for entry in M.catalog():
            self.assertFalse(set(entry["genome"]) & set(G.RESEARCH_SPACE))

    def test_load_recomputes_adjustment_and_transfer_instead_of_trusting_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            strategy = M.strategies(S.DEFAULT)[0]
            result = {"status": "GPU_META_COMPLETE", "adopted": True, "selected": strategy,
                      "production_benchmark": {"frozen": "benchmark"}, "protocol_digest": M.protocol_digest(),
                      "transfer_scores": {"selected": [-.1] * 40, "previous": [0.] * 40, "random": [0.] * 40},
                      "tuning_previous_scores": [0.] * 20,
                      "tuning_candidates": [{"strategy": strategy, "scores": [-.1] * 20}]}
            path = root / "evidence.json"
            path.write_text(json.dumps(result))
            (root / "strategy_gpu.json").write_text(json.dumps({"strategy": strategy, "evidence": str(path)}))
            self.assertEqual(S.load(root, {"frozen": "benchmark"}), strategy)
            result["transfer_scores"]["selected"] = [0.] * 40
            path.write_text(json.dumps(result))
            with self.assertRaises(RuntimeError):
                S.load(root, {"frozen": "benchmark"})

    def test_default_strategy_when_no_validated_adoption(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(S.load(tmp, {}), S.DEFAULT)
        with self.assertRaises(ValueError):
            S.validate({**S.DEFAULT, "ucb_c": float("nan")})

    def test_selection_precedes_holdout_and_interrupted_transfer_cannot_retune(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(M.tempfile, "tempdir", tempfile.gettempdir()):
            root = Path(tmp)
            cfg = root / "config.json"
            cfg.write_text(json.dumps({"workload": {"state_dir": "state_gpu"}}))
            runtime = root / "bootstrap.json"
            runtime.write_text(json.dumps({"cuda_probes": [{"runtime": {"python": "test"}}]}))
            calls = []
            fail_holdout = [True]
            class Builder:
                def __init__(self, task, *args):
                    self.task = task
                def build(self, seeds):
                    calls.append(self.task)
                    if self.task == M.PROTOCOL["holdout_task"]:
                        committed = json.loads((root / "state_gpu/meta_gpu_v1/selection.json").read_text())
                        self_selected = committed["report"]["selected"]
                        S.validate(self_selected)
                        if fail_holdout[0]:
                            fail_holdout[0] = False
                            raise RuntimeError("deliberate interruption after selection")
                    data = landscape()
                    for entry in data[1:]:
                        entry["fitness"] = 5.
                    return {"landscape": data}
            out = root / "first"
            out.mkdir()
            args = SimpleNamespace(config=cfg, bootstrap_report=runtime, output=out)
            with patch.object(M, "ROOT", root), patch.object(M, "Builder", Builder), \
                    patch.object(M, "protocol_digest", return_value="protocol"), \
                    patch.object(M.benchmark_state, "load", return_value=({}, "baseline")):
                with self.assertRaisesRegex(RuntimeError, "deliberate interruption"):
                    M.run(args, {})
                args.output = root / "resumed"
                args.output.mkdir()
                result = {}
                M.run(args, result)
                self.assertEqual(result["status"], "GPU_META_COMPLETE")
                self.assertFalse(result["adopted"])
                self.assertEqual(calls.count(M.PROTOCOL["tune_task"]), 1)
                self.assertEqual(calls.count(M.PROTOCOL["holdout_task"]), 2)
                with self.assertRaisesRegex(RuntimeError, "Holdout v1 ya consumido"):
                    M.run(args, {})

    def test_cli_accepts_inconclusive_scientific_result_but_not_failed_study(self):
        for status, code in (("GPU_META_COMPLETE", 0), ("FAILED", 40)):
            with tempfile.TemporaryDirectory() as tmp:
                def provision(session, requested, **kwargs):
                    self.assertEqual(requested, "gaia-transformer-cuda-pascal")
                    self.assertFalse(kwargs["prepare"])
                    return Path("/managed/python"), {"GAIA_LOCAL_CONFIG": "/managed/config.json"}
                def command(session, stage, *args, **kwargs):
                    return json.dumps({"status": status, "adopted": False})
                with patch.object(bootstrap, "provision", side_effect=provision), patch.object(bootstrap.Session, "command", new=command):
                    self.assertEqual(bootstrap.dispatch(Path(tmp), ["gaia-transformer-meta"]), code)


if __name__ == "__main__":
    unittest.main()
