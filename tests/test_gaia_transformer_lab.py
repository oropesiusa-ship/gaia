"""Unidad de laboratorio GPU: sin Torch ni CUDA; integración real vía gaia-transformer-lab."""
import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from gaia import bootstrap
from gaia.protected import runtime
from gaia.gaia_transformer.lab import benchmark, guard, monitor, sandbox, validation
from gaia.gaia_transformer.lab.candidate import baseline_source
from gaia.gaia_transformer.lab.evaluator import Channel, ProtocolError, WorkerError, run_trial


class TestGpuGuard(unittest.TestCase):
    def test_known_baseline_is_self_contained_and_allowed(self):
        source = baseline_source()
        guard.check_source(source)
        self.assertNotIn("from .", source)
        self.assertNotIn("configure_cuda", source)

    def test_blocks_host_access_introspection_and_policy_assignment(self):
        for code in ("import os", "import gaia.gaia_transformer.data", "open('/proc/1/mem')", "np.load('secret.npy')",
                     "torch.load('secret.pt')", "x = torch.__dict__", "torch.backends.cudnn.benchmark = True",
                     "torch.cuda.set_device(1)", "getattr(torch,'os')", "from torch import *",
                     "from torch import os as escape", "from dataclasses import sys as escape",
                     "torch.from_file('secret')"):
            with self.subTest(code=code), self.assertRaises(guard.GuardError):
                guard.check_source(baseline_source() + "\n" + code + "\n")

    def test_runtime_fault_variants_are_not_accidentally_blocked_by_guard(self):
        for name, source, *_ in validation.cases(baseline_source(), {"limits": {}}, {"torch": {"version": "test"}}):
            if name != "bad_import":
                with self.subTest(case=name):
                    guard.check_source(source)


class TestGpuProtocol(unittest.TestCase):
    def channel(self, payload):
        proc = Mock()
        proc.stdout.fileno.return_value = 123
        proc.stdin = io.BytesIO()
        watchdog = Mock()
        channel = Channel(proc, watchdog)
        channel.buffer = payload
        return channel

    def test_ack_must_match_the_request(self):
        channel = self.channel(b'{"event":"OK","command":"INIT"}\n')
        channel.command("INIT", seed=9)
        self.assertEqual(json.loads(channel.proc.stdin.getvalue()), {"command": "INIT", "seed": 9})
        with self.assertRaises(ProtocolError):
            self.channel(b'{"event":"OK","command":"OTHER"}\n').command("INIT")

    def test_invalid_json_and_worker_errors_fail_closed(self):
        for payload in (b"garbage\n", b"[]\n", b"x" * 70000 + b"\n"):
            with self.subTest(size=len(payload)), self.assertRaises(ProtocolError):
                self.channel(payload).recv()
        with self.assertRaises(WorkerError) as exc:
            self.channel(b'{"event":"ERROR","code":"CUDA_OOM","reason":"OOM"}\n').recv()
        self.assertEqual(exc.exception.code, "CUDA_OOM")

    def test_private_trial_spec_and_dataset_are_not_worker_labels(self):
        train, contexts, labels, corpus = benchmark.private_data(benchmark.TrialSpec(target_loss=3.0))
        self.assertEqual(train.shape, (4096, 65))
        self.assertEqual(contexts.shape, (256, 64))
        self.assertEqual(labels.dtype, np.uint8)
        self.assertFalse(np.shares_memory(contexts, labels))
        self.assertEqual(len(corpus), 64)
        for kwargs in ({"steps": -1}, {"hits_needed": 1}, {"target_loss": float("nan")}, {"split": "train"}):
            with self.assertRaises(ValueError):
                benchmark.TrialSpec(**kwargs)


class TestGpuMonitor(unittest.TestCase):
    def watchdog(self, root, limits=None):
        return monitor.Watchdog(Mock(pid=123), root, Mock(processes=lambda: {123: 20, 124: 30, 999: 10000}),
                                limits or {"ram_mb": 1000, "vram_mb": 100, "disk_mb": 10}, time.monotonic() + 10)

    def test_only_trial_pids_contribute_to_memory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(monitor, "descendants", return_value={123, 124}), \
                patch.object(monitor, "rss_mb", return_value=200):
            watchdog = self.watchdog(Path(tmp))
            watchdog.check(force=True)
            self.assertEqual(watchdog.peak_vram_mb, 50)
            self.assertEqual(watchdog.peak_rss_mb, 400)
            self.assertTrue(watchdog.gpu_seen)

    def test_ram_vram_and_disk_excess_are_distinct(self):
        for resource in ("ram_mb", "vram_mb", "disk_mb"):
            with self.subTest(resource=resource), tempfile.TemporaryDirectory() as tmp, \
                    patch.object(monitor, "descendants", return_value={123, 124}), \
                    patch.object(monitor, "rss_mb", return_value=200), patch.object(monitor, "directory_mb", return_value=5):
                limits = {"ram_mb": 1000, "vram_mb": 100, "disk_mb": 10}
                limits[resource] = 1
                with self.assertRaises(monitor.LimitExceeded) as error:
                    self.watchdog(Path(tmp), limits).check(force=True)
                self.assertEqual(error.exception.resource, resource)

    def test_deadline_stop_and_lost_telemetry_cannot_be_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            watchdog = self.watchdog(Path(tmp))
            watchdog.deadline = time.monotonic() - 1
            with self.assertRaises(TimeoutError):
                watchdog.check()
            watchdog.deadline = time.monotonic() + 10
            stop = Path(tmp) / "STOP"
            stop.touch()
            watchdog.stop_file = stop
            with self.assertRaises(InterruptedError):
                watchdog.check()
            watchdog.stop_file = None
            watchdog.nvml.processes = Mock(side_effect=monitor.MonitorError("lost"))
            with patch.object(monitor, "descendants", return_value={123}), patch.object(monitor, "rss_mb", return_value=10):
                with self.assertRaises(monitor.MonitorError):
                    watchdog.check(force=True)

    def test_environment_does_not_inherit_api_secrets(self):
        with patch.dict("os.environ", {"SECRET_TOKEN": "not-for-candidate", "PYTHONPATH": "/host"}):
            env = sandbox.environment("GPU-test", Path("/tmp/private"))
        self.assertNotIn("SECRET_TOKEN", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env["CUBLAS_WORKSPACE_CONFIG"], ":4096:8")


class TestGpuEvaluator(unittest.TestCase):
    def test_invalid_source_and_integrity_mismatch_never_start_a_process(self):
        expected_runtime = runtime.fingerprint()
        for source, identity, expected in (("import os", None, "invalid"),
                                           (baseline_source(), {"wrong": "hash"}, "error")):
            with tempfile.TemporaryDirectory() as tmp, patch("subprocess.Popen") as launch:
                result = run_trial(source, {}, expected_runtime, Path(tmp) / "trial", expected_identity=identity)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["valid"])
                self.assertIsNone(result["cost_s"])
                self.assertTrue(result["temporary_files_removed"])
                launch.assert_not_called()

    def test_sandbox_is_required_and_not_silently_downgraded(self):
        expected_runtime = runtime.fingerprint()
        with tempfile.TemporaryDirectory() as tmp, patch.object(sandbox, "available", return_value=(None, "blocked")), \
                patch("subprocess.Popen") as launch:
            result = run_trial(baseline_source(), {}, expected_runtime, Path(tmp) / "trial")
            self.assertEqual(result["status"], "error")
            self.assertIn("SANDBOX_UNAVAILABLE", result["error"])
            launch.assert_not_called()

    def test_cli_requires_all_lab_checks_to_succeed(self):
        for status, expected in (("GPU_LAB_READY", 0), ("FAILED", 40)):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                def provision(session, requested, **kwargs):
                    self.assertEqual(requested, "gaia-transformer-cuda-pascal")
                    self.assertFalse(kwargs["prepare"])
                    return Path("/managed/python"), {"GAIA_LOCAL_CONFIG": "/managed/config.json"}

                def command(session, stage, *args, **kwargs):
                    return json.dumps({"status": status}) if stage == "gaia-transformer-lab" else ""

                with patch.object(bootstrap, "provision", side_effect=provision), \
                        patch.object(bootstrap.Session, "command", new=command):
                    self.assertEqual(bootstrap.dispatch(Path(tmp), ["gaia-transformer-lab"]), expected)


if __name__ == "__main__":
    unittest.main()
