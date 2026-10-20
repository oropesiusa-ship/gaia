import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia import bootstrap
from gaia.gaia_transformer import genome as G, profiling as P


def observation():
    plain = {"train_s": 1., "signature": {"state": "same"}}
    phases = {key: {"wall_s": 1 / len(P.PHASES), "cuda_stream_ms": .1, "count": 100} for key in P.PHASES}
    return {"plain_runs": [copy.deepcopy(plain) for _ in range(3)], "parity": True, "steps": 100,
            "instrumented": {"train_s": 2., "signature": plain["signature"], "phases": phases}}


class TestGaiaTransformerProfiling(unittest.TestCase):
    def test_instrumentation_wraps_known_step_and_preserves_source(self):
        source = G.render(G.BASE)
        wrapped = P.instrument(source)
        self.assertNotIn("gaia_observe_phase", source)
        tree = ast.parse(wrapped)
        step = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "step")
        self.assertEqual([n.items[0].context_expr.args[0].value for n in step.body if isinstance(n, ast.With)], list(P.PHASES))
        self.assertIsInstance(step.body[-1], ast.Return)

    def test_all_exposed_components_are_instrumentable(self):
        for key, values in G.SPACE.items():
            for value in values:
                with self.subTest(component=key, value=value):
                    ast.parse(P.instrument(G.render({**G.BASE, key: value})))
        for key in G.RESEARCH_SPACE:
            ast.parse(P.instrument(G.render({**G.BASE, key: "foreach"})))

    def test_unknown_step_structure_fails_instead_of_mislabeling(self):
        changed = G.render(G.BASE).replace("loss.backward()", "loss.backward(); self.optimizer.step()")
        with self.assertRaises(ValueError):
            P.instrument(changed)

    def test_numeric_parity_is_mandatory(self):
        result = observation()
        P.validate_observation(result)
        for key, value in (("parity", False), ("plain_runs", [result["plain_runs"][0]])):
            invalid = copy.deepcopy(result)
            invalid[key] = value
            with self.assertRaises(ValueError):
                P.validate_observation(invalid)
        result["instrumented"]["signature"] = {"state": "changed"}
        with self.assertRaises(ValueError):
            P.validate_observation(result)

    def test_nonfinite_counts_and_overlapping_time_are_rejected(self):
        for field, value in (("wall_s", float("nan")), ("count", 99), ("cuda_stream_ms", -1), ("wall_s", 10)):
            result = observation()
            result["instrumented"]["phases"][P.PHASES[0]][field] = value
            with self.assertRaises(ValueError):
                P.validate_observation(result)

    def test_history_distinguishes_aborts_regions_and_measured_comparisons(self):
        records = []
        for index, (decision, stage) in enumerate((("rejected", "confirmation"), ("aborted", None), ("rejected", "screen"))):
            ident = str(index)
            records += [{"type": "start", "id": ident, "genome": G.BASE, "operator": "lr"},
                        {"type": "end", "id": ident, "decision": decision, "stage": stage}]
        result = P.history_metrics(records)
        self.assertEqual(result["completed"], 2)
        self.assertEqual(result["aborted"], 1)
        self.assertEqual(result["confirmation_fraction"], .5)
        self.assertEqual(result["region_repeat_fraction"], .5)

    def test_diagnosis_labels_instrumentation_overhead_and_amdahl_as_estimates(self):
        trial = {"cost_s": 4., "t_train_s": 1., "t_init_s": 2., "t_eval_s": .9, "t_metric_s": .1,
                 "spec": {"target_loss": .3, "eval_every": 25}, "steps": 125,
                 "curve": [{"step": 0, "loss": 5}, {"step": 100, "loss": .2}, {"step": 125, "loss": .1}]}
        result = P.diagnose(observation(), trial, [])
        self.assertFalse(result["promotion_evidence"])
        self.assertEqual(result["instrumentation_overhead_ratio"], 2)
        self.assertAlmostEqual(sum(result["instrumented_phase_fractions"].values()), 1)
        self.assertAlmostEqual(sum(result["estimated_cost_phase_shares"].values()), .25)
        self.assertFalse(result["claims"][-1]["enough_history"])

    def test_cli_does_not_claim_ready_when_observation_rejected(self):
        for status, code in (("GPU_OBSERVATION_READY", 0), ("FAILED", 40)):
            with tempfile.TemporaryDirectory() as tmp:
                def provision(session, requested, **kwargs):
                    self.assertEqual(requested, "gaia-transformer-cuda-pascal")
                    self.assertFalse(kwargs["prepare"])
                    return Path("/managed/python"), {"GAIA_LOCAL_CONFIG": "/managed/config.json"}

                def command(session, stage, *args, **kwargs):
                    return json.dumps({"status": status})

                with patch.object(bootstrap, "provision", side_effect=provision), patch.object(bootstrap.Session, "command", new=command):
                    self.assertEqual(bootstrap.dispatch(Path(tmp), ["gaia-transformer-observe"]), code)

    def test_campaign_noise_is_kept_separate_from_warm_training_noise(self):
        trial = {"cost_s": 4., "t_train_s": 1., "t_init_s": 2., "t_eval_s": .9, "t_metric_s": .1,
                 "spec": {"target_loss": .3, "eval_every": 25}, "steps": 125,
                 "curve": [{"step": 0, "loss": 5}, {"step": 100, "loss": .2}]}
        result = P.diagnose(observation(), trial, [], campaign_noise={"cv": .1, "historical": True})
        claims = {c["id"]: c for c in result["claims"]}
        self.assertFalse(claims["noise_vs_gain"]["comparable"])
        self.assertTrue(claims["campaign_noise_vs_gain"]["comparable"])

    def test_reference_parity_compares_only_identical_update_counts(self):
        sample = observation()
        sample["warmup"] = 25
        sample["instrumented"]["signature"]["logits"] = "hash"
        trial = {"steps": 125, "curve": [{"logits_sha256": "hash"}]}
        self.assertTrue(P.reference_parity(sample, trial))
        trial["steps"] = 150
        self.assertIsNone(P.reference_parity(sample, trial))
        trial["steps"] = 125
        trial["curve"][0]["logits_sha256"] = "changed"
        with self.assertRaises(ValueError):
            P.reference_parity(sample, trial)


if __name__ == "__main__":
    unittest.main()
