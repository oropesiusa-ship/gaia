import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia.gaia_transformer.lab.calibration import SPEC, decide, reliability, slow_source
from gaia.gaia_transformer.lab.candidate import baseline_source
from gaia.gaia_transformer.lab.guard import check_source
from gaia.gaia_transformer import benchmark_state


def trials(ratio=1.0):
    return [{"status": "ok", "valid": True, "reached": True, "cost_s": 4.0 * ratio,
             "peak_rss_mb": 1500, "peak_vram_nvml_mb": 238, "spec": {"seed": seed}}
            for seed in SPEC["confirm_seeds"]]


class TestGpuCalibration(unittest.TestCase):
    def test_null_rejected_and_real_gain_accepted(self):
        self.assertEqual(decide(trials(), trials(), SPEC["confirm_seeds"])["decision"], "rejected")
        self.assertEqual(decide(trials(), trials(.8), SPEC["confirm_seeds"])["decision"], "accepted")

    def test_all_pairs_must_reach_quality_and_be_valid(self):
        for key, value in (("status", "error"), ("valid", False), ("reached", False), ("cost_s", float("nan"))):
            candidate = trials(.8)
            candidate[0][key] = value
            self.assertEqual(decide(trials(), candidate, SPEC["confirm_seeds"])["decision"], "rejected")

    def test_seed_alignment_and_complete_pairs_required(self):
        candidate = trials(.8)
        candidate.reverse()
        self.assertEqual(decide(trials(), candidate, SPEC["confirm_seeds"])["decision"], "rejected")
        self.assertEqual(decide(trials()[:4], trials(.8), SPEC["confirm_seeds"])["decision"], "rejected")

    def test_vram_regression_is_pareto_not_promotion(self):
        candidate = trials(.8)
        for t in candidate:
            t["peak_vram_nvml_mb"] *= 2
        self.assertEqual(decide(trials(), candidate, SPEC["confirm_seeds"])["decision"], "pareto_alternative")

    def test_reliability_rejects_noise_drift_and_saturation(self):
        self.assertTrue(reliability(trials())["ok"])
        for costs in ([.01] * 5, [10, 4, 4, 4, 4], [1, 1, 3, 3, 3]):
            group = trials()
            for t, cost in zip(group, costs):
                t["cost_s"] = cost
            self.assertFalse(reliability(group)["ok"])

    def test_seed_sets_are_reserved_and_disjoint(self):
        groups = [set(SPEC[k]) for k in ("calibration_seeds", "confirm_seeds", "audit_seeds", "control_seeds")]
        self.assertEqual(sum(map(len, groups)), len(set.union(*groups)))
        self.assertNotIn(SPEC["screen_seed"], set.union(*groups))

    def test_slow_control_is_allowed_source(self):
        check_source(slow_source(baseline_source()))

    def test_frozen_state_rejects_runtime_config_integrity_and_baseline_changes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(benchmark_state.benchmark, "identity", return_value={"file": "hash"}):
            root = Path(tmp)
            state = root / "state_gpu"
            state.mkdir()
            cfg = {"workload": {"state_dir": "state_gpu"}}
            baseline = {"source": "baseline", "sha256": hashlib.sha256(b"baseline").hexdigest()}
            frozen = {"spec": SPEC, "config": cfg, "runtime": {"python": "test"},
                      "identity": {"file": "hash"}, "baseline_sha256": baseline["sha256"]}
            (state / "baseline.json").write_text(json.dumps(baseline))
            (state / "benchmark.json").write_text(json.dumps(frozen))
            self.assertEqual(benchmark_state.load(root, cfg, frozen["runtime"])[1], "baseline")
            with self.assertRaises(RuntimeError):
                benchmark_state.load(root, cfg, {"python": "other"})
            altered = copy.deepcopy(cfg)
            altered["limits"] = {"seconds": 999}
            with self.assertRaises(RuntimeError):
                benchmark_state.load(root, altered, frozen["runtime"])
            (state / "baseline.json").write_text(json.dumps({**baseline, "source": "changed"}))
            with self.assertRaises(RuntimeError):
                benchmark_state.load(root, cfg, frozen["runtime"])


if __name__ == "__main__":
    unittest.main()
