"""Corpus y evaluación privada: se ejecutan también en el entorno NumPy/CPU."""
from dataclasses import replace
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from gaia.gaia_transformer import data
from gaia.gaia_transformer import phase1
from gaia import bootstrap


class TestGaiaTransformerData(unittest.TestCase):
    def test_frozen_corpus_digest_and_shape(self):
        frozen = json.loads((Path(data.__file__).with_name("corpus_v1.json")).read_text())
        self.assertEqual(data.manifest(), frozen)
        for split in data.DOMAINS:
            rows = data.records(data.generate_split(data.DEFAULT_SPEC, split))
            self.assertEqual(rows.shape, (getattr(data.DEFAULT_SPEC, split + "_records"), 65))
            self.assertEqual(rows.dtype, np.uint8)

    def test_splits_and_contexts_do_not_share_records(self):
        sets = []
        for split in data.DOMAINS:
            rows = data.records(data.generate_split(data.DEFAULT_SPEC, split))
            values = {row.tobytes() for row in rows}
            self.assertEqual(len(values), len(rows))
            sets.append(values)
        self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])

    def test_manifest_reproduces_in_isolated_process(self):
        script = ("import sys,json;sys.path.insert(0,sys.argv[1]);"
                  "from gaia.gaia_transformer.data import manifest;print(json.dumps(manifest()))")
        result = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(Path(data.__file__).parents[2])],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), data.manifest())

    def test_seed_domains_are_independent_and_do_not_consume_global_rng(self):
        random.seed(9)
        np.random.seed(9)
        python_state = random.getstate()
        numpy_state = np.random.get_state()
        altered = replace(data.DEFAULT_SPEC, train_seed=1702)
        self.assertNotEqual(data.generate_split(data.DEFAULT_SPEC, "train"), data.generate_split(altered, "train"))
        self.assertEqual(data.generate_split(data.DEFAULT_SPEC, "validation"), data.generate_split(altered, "validation"))
        self.assertEqual(random.getstate(), python_state)
        np.testing.assert_array_equal(np.random.get_state()[1], numpy_state[1])

    def test_validation_target_column_is_not_serialized(self):
        raw = data.generate_split(data.DEFAULT_SPEC, "validation")
        contexts, targets = data.private_validation(raw)
        rows = data.records(raw)
        np.testing.assert_array_equal(contexts, rows[:, :64])
        np.testing.assert_array_equal(targets, rows[:, 64])
        self.assertFalse(np.shares_memory(contexts, targets))
        train = data.records(data.generate_split(data.DEFAULT_SPEC, "train"))
        with tempfile.TemporaryDirectory() as tmp:
            phase1.write_inputs(Path(tmp), train, contexts)
            with np.load(Path(tmp) / "inputs.npz", allow_pickle=False) as inputs:
                self.assertEqual(set(inputs.files), {"train", "contexts"})
                self.assertEqual(inputs["contexts"].shape, (256, 64))
                self.assertEqual(inputs["contexts"].nbytes, 256 * 64)
        contexts[0, 0] ^= 1
        np.testing.assert_array_equal(targets, rows[:, 64])

    def test_invalid_corpus_and_serialization_rejected(self):
        with self.assertRaises(ValueError):
            data.CorpusSpec(train_seed=2903)
        with self.assertRaises(ValueError):
            data.records(b"truncated")
        with self.assertRaises(ValueError):
            data.generate_split(data.DEFAULT_SPEC, "unknown")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                phase1.write_inputs(Path(tmp), np.zeros((4, 65)), np.zeros((4, 65)))

    def test_private_cross_entropy_is_stable_and_rejects_bad_predictions(self):
        logits = np.zeros((3, 256), dtype=np.float32)
        targets = np.array([0, 1, 2], dtype=np.uint8)
        self.assertAlmostEqual(phase1.cross_entropy(logits, targets), np.log(256))
        logits[np.arange(3), targets] = 1000
        self.assertAlmostEqual(phase1.cross_entropy(logits, targets), 0.0)
        logits[0, 0] = np.nan
        with self.assertRaises(ValueError):
            phase1.cross_entropy(logits, targets)
        with self.assertRaises(ValueError):
            phase1.cross_entropy(np.zeros((3, 255), dtype=np.float32), targets)
        with self.assertRaises(ValueError):
            phase1.cross_entropy(np.zeros((0, 256), dtype=np.float32), np.array([], dtype=np.uint8))

    def test_loss_reduction_and_reproducibility_fail_closed(self):
        worker = {"train_losses": [5.0, 4.0, 3.0, 2.0]}
        self.assertLess(phase1.check_training(worker, [{"loss": 5.0}, {"loss": 3.0}])["train_last_mean"], 5.0)
        with self.assertRaises(RuntimeError):
            phase1.check_training(worker, [{"loss": 5.0}, {"loss": 6.0}])
        with self.assertRaises(RuntimeError):
            phase1.check_training(worker, [{"loss": 5.0}, {"loss": float("nan")}])
        trial = {"runtime": "same", "gpu": "same", "policy": "same", "configuration": {},
                 "deterministic_result": {"final_state_sha256": "first"}}
        other = {**trial, "deterministic_result": {"final_state_sha256": "other"}}
        phase1.validate_repetitions([trial, trial, other], 2)
        with self.assertRaises(RuntimeError):
            phase1.validate_repetitions([trial, other, other], 2)

    def test_cli_selects_cuda_and_does_not_claim_success_on_invalid_result(self):
        for child_status, expected in (("GAIA_TRANSFORMER_BASELINE_READY", 0), ("FAILED", 40)):
            with self.subTest(status=child_status), tempfile.TemporaryDirectory() as tmp:
                def provision(session, requested, **kwargs):
                    self.assertEqual(requested, "gaia-transformer-cuda-pascal")
                    self.assertFalse(kwargs["prepare"])
                    session.report["effective_config"] = {"limits": {"max_experiment_seconds": 20}}
                    return Path("/managed/python"), {"GAIA_LOCAL_CONFIG": "/managed/config.json"}

                def command(session, stage, *args, **kwargs):
                    return json.dumps({"status": child_status}) if stage == "gaia-transformer-baseline" else ""

                with patch.object(bootstrap, "provision", side_effect=provision), \
                        patch.object(bootstrap.Session, "command", new=command):
                    self.assertEqual(bootstrap.dispatch(Path(tmp), ["gaia-transformer-baseline"]), expected)
                report_path = next((Path(tmp) / ".gaia/reports").glob("*/report.json"))
                result = json.loads(report_path.read_text())
                self.assertEqual(result["status"], "GAIA_TRANSFORMER_BASELINE_READY" if expected == 0 else "FAILED")


if __name__ == "__main__":
    unittest.main()
