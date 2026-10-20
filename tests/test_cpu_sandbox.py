"""Real local bwrap isolation, including tests independent of the AST filter.

No network service outside a controlled loopback listener is used. Missing
host namespaces are a failing capability requirement, never a silent skip.
"""
import copy
import gc
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings

from gaia import config, engine, genome as G, provenance, readiness, research
from gaia.protected import benchmark, evaluator, sandbox


class CpuSandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        self.work = self.state / "tmp"
        self.work.mkdir(parents=True)
        self.bench = copy.deepcopy(benchmark.DEFAULT_SPEC)
        self.bench["tasks"]["main"].update(d=6, teacher_hidden=8, k=3, n_train=100, n_val=40)
        self.limits = {"max_ram_mb": 3000, "max_experiment_seconds": 10, "worker_threads": 1}

    def trial(self, source=None, **kwargs):
        return evaluator.run_trial(source or G.render(G.new_genome()), self.bench,
                                   "main", 0, 0, 10, self.limits, self.work,
                                   target=2.0, max_batches=50, **kwargs)

    def test_baseline_candidate_and_launch_command_are_always_sandboxed(self):
        popen = subprocess.Popen
        with patch.object(subprocess, "Popen", wraps=popen) as start:
            for source in (G.render(G.new_genome()), G.render(G.new_genome(hp={"lr": 0.08}))):
                result = self.trial(source)
                self.assertEqual(result["status"], "ok", result)
                self.assertTrue(result["sandbox"])
                self.assertTrue(result["sandbox_validation"])
                self.assertTrue(result["promotable"])
        for call in start.call_args_list:
            command = call.args[0]
            self.assertEqual(Path(command[0]).name, "bwrap")
            for name in sandbox.NAMESPACES:
                self.assertIn(f"--unshare-{name}", command)

    def test_missing_bwrap_never_launches_worker(self):
        with patch.object(shutil, "which", return_value=None), patch.object(subprocess, "Popen") as start:
            result = self.trial()
        start.assert_not_called()
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["reason"], "SANDBOX_UNAVAILABLE")
        self.assertFalse(result["promotable"])
        self.assertFalse(result["reached"])

    def test_local_probe_setup_failure_is_structured_and_fail_closed(self):
        with patch.object(sandbox.socket.socket, "bind", side_effect=PermissionError("local probe denied")):
            result = self.trial()
        self.assertEqual(result["reason"], "SANDBOX_UNAVAILABLE", result)
        self.assertFalse(result["promotable"])
        self.assertFalse(result["sandbox_validation"])

    def test_smoke_passes_but_real_sandbox_fails_and_g0_is_blocked(self):
        self.assertTrue(provenance.bwrap_capability()["verified"])
        binary = shutil.which("bwrap")
        with patch.object(sandbox, "command", return_value=[binary, "--invalid-gaia-sandbox-option"]):
            result = self.trial()
        self.assertEqual(result["reason"], "SANDBOX_UNAVAILABLE", result)
        self.assertFalse(result["promotable"])
        source_root = Path(__file__).resolve().parents[1]
        shutil.copytree(source_root / "gaia", self.root / "gaia", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(source_root / "gaia.py", self.root / "gaia.py")
        cfg = config.load(self.root)
        cfg["workload"]["state_dir"] = "certified_state"
        cfg["limits"].update(self.limits)
        eng = engine.Engine(self.root, cfg, log=lambda *args: None)
        small = copy.deepcopy(self.bench)
        small["max_batches"] = 1
        small["calibrated"] = {"main": {"ref_cost_s": 1.0}}
        with patch.object(benchmark, "calibrate", return_value=small):
            eng.init(initialize_mvp=True)
        with patch.object(sandbox, "command", return_value=[binary, "--invalid-gaia-sandbox-option"]):
            gate = readiness.g0_runtime(eng, G.render(G.new_genome()))
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["bwrap_status"], "BWRAP_AVAILABLE")
        self.assertNotEqual(gate["cpu_sandbox_status"], "CPU_SANDBOX_VERIFIED")

    def test_real_namespace_filesystem_and_rlimit_handshake(self):
        result = self.trial()
        self.assertEqual(result["status"], "ok", result)
        evidence = result["sandbox_evidence"]
        report = evidence["handshake"]
        for name in sandbox.NAMESPACES:
            self.assertNotEqual(report["namespaces"][name], sandbox.namespaces()[name])
            self.assertTrue(evidence["checks"][name])
        self.assertTrue(evidence["checks"]["parent_observed_namespaces"])
        self.assertIn(report["pid"], (1, 2))
        self.assertEqual(report["home"], "/work")
        self.assertEqual(report["tmpdir"], "/tmp")
        self.assertEqual(report["cwd"], "/work")
        self.assertTrue(report["work_writable"])
        self.assertTrue(report["outside_write_denied"])
        self.assertTrue(report["bundle_read_only"])
        self.assertTrue(report["runtime_read_only"])
        self.assertTrue(report["parent_loopback_unreachable"])
        self.assertEqual(report["limits"]["RLIMIT_AS"], [3000 * 2**20] * 2)
        self.assertEqual(report["limits"]["RLIMIT_CPU"], [20, 22])
        self.assertEqual(report["limits"]["RLIMIT_FSIZE"], [64 * 2**20] * 2)
        self.assertEqual(report["limits"]["RLIMIT_CORE"], [0, 0])
        self.assertEqual(evidence["candidate_sha256"], hashlib.sha256(G.render(G.new_genome()).encode()).hexdigest())
        self.assertEqual(len(evidence["bundle_sha256"]), 64)
        self.assertTrue(evidence["timestamp"])
        self.assertEqual(list(self.work.iterdir()), [])
        source_root = Path(__file__).resolve().parents[1]
        shutil.copytree(source_root / "gaia", self.root / "gaia", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(source_root / "gaia.py", self.root / "gaia.py")
        cfg = config.load(self.root)
        cfg["workload"]["state_dir"] = "certified_state"
        cfg["limits"].update(self.limits)
        eng = engine.Engine(self.root, cfg, log=lambda *args: None)
        small = copy.deepcopy(self.bench)
        small["max_batches"] = 1
        small["calibrated"] = {"main": {"ref_cost_s": 1.0}}
        with patch.object(benchmark, "calibrate", return_value=small):
            eng.init(initialize_mvp=True)
        gate = readiness.g0_runtime(eng, G.render(G.new_genome()))
        self.assertTrue(gate["ok"], gate)
        self.assertEqual(gate["cpu_sandbox_status"], "CPU_SANDBOX_VERIFIED")

    def test_invalid_handshake_cannot_be_promotable(self):
        with patch.object(sandbox.Session, "verify", side_effect=sandbox.SandboxError(
                "SANDBOX_VIOLATION", "namespace equality")):
            result = self.trial()
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["reason"], "SANDBOX_VIOLATION")
        self.assertFalse(result["sandbox_validation"])
        self.assertFalse(result["promotable"])
        self.assertFalse(result["reached"])
        self.assertIsNone(result["cost_s"])

    def test_forged_network_namespace_is_rejected_by_parent(self):
        original = evaluator._Chan.recv

        def receive(channel, timeout):
            line = original(channel, timeout)
            if line.startswith("ISOLATED "):
                report = json.loads(line[len("ISOLATED "):])
                report["namespaces"]["net"] = sandbox.namespaces()["net"]
                return "ISOLATED " + json.dumps(report)
            return line

        with patch.object(evaluator._Chan, "recv", receive):
            result = self.trial()
        self.assertEqual(result["reason"], "SANDBOX_VIOLATION", result)
        self.assertFalse(result["promotable"])
        self.assertFalse(result["sandbox_evidence"]["checks"]["net"])
        self.assertFalse(result["sandbox_evidence"]["checks"]["parent_observed_namespaces"])

    def test_source_snapshot_stable_state_parent_and_decoy_cannot_be_written(self):
        targets = [self.state / "provenance/snapshots/src-000001/gaia.py",
                   self.state / "stable/v0000/trainer.py", self.root / "sources/gaia.py",
                   self.root / "outside-state.txt"]
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"must remain unchanged")
        # Intentionally bypass AST only in this test: the OS boundary must hold
        # even for a candidate that the preventive filter would normally reject.
        source = ("import os\nimport numpy as np\nclass Trainer:\n"
                  "    def __init__(self,X,y,k,seed):\n"
                  f"        targets={list(map(str, targets))!r} + ['/lab/worker.py','/lab/trainer.py','/lab/decoy.txt',np.__file__]\n"
                  "        for path in targets:\n"
                  "            if path.startswith('/lab/'):\n"
                  "                try: os.chmod(path,0o600)\n"
                  "                except OSError: pass\n"
                  "            try:\n"
                  "                with open(path,'ab') as f: f.write(b'corrupt')\n"
                  "            except OSError: continue\n"
                  "            raise AssertionError('write outside work: '+path)\n"
                  "        assert os.environ['HOME']=='/work' and os.environ['TMPDIR']=='/tmp'\n"
                  "        assert 'AWS_SECRET_ACCESS_KEY' not in os.environ and 'HTTPS_PROXY' not in os.environ\n"
                  "        with open('/work/allowed','w') as f: f.write('yes')\n"
                  "        with open('/tmp/allowed','w') as f: f.write('yes')\n"
                  "    def train(self,n): pass\n"
                  "    def predict(self,X): return np.zeros(len(X),dtype=np.int64)\n")
        original = sandbox.bundle_files

        def bundle(*args):
            hashes = original(*args)
            decoy = Path(args[0]) / "decoy.txt"
            decoy.write_bytes(b"read only sentinel")
            hashes[decoy.name] = hashlib.sha256(decoy.read_bytes()).hexdigest()
            return hashes

        with patch.object(evaluator.guard, "check_source"), patch.object(sandbox, "bundle_files", side_effect=bundle), \
                patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": "secret", "HTTPS_PROXY": "http://secret"}):
            result = self.trial(source)
        self.assertEqual(result["status"], "ok", result)
        for target in targets:
            self.assertEqual(target.read_bytes(), b"must remain unchanged")

    def test_minimal_environment_and_no_host_workspace_mount(self):
        environment = sandbox.environment(1)
        self.assertEqual(set(environment), {"HOME", "TMPDIR", "PATH", "PYTHONHASHSEED",
                                          "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"})
        result = self.trial()
        self.assertEqual(result["status"], "ok", result)
        args = result["sandbox_evidence"]["command"]
        for path in ("/home", "/run", "/sys"):
            self.assertNotIn(path, args)
        self.assertNotIn(str(Path(__file__).resolve().parents[1]), args)

    def test_baseline_calibration_uses_sandbox_for_every_trial(self):
        bench = copy.deepcopy(self.bench)
        bench["tiers"]["calibration"] = [0]
        bench["ref_batches"] = 50
        bench["max_batches"] = 100
        bench["eval_every"] = 10
        real_trial = evaluator.run_trial
        results = []

        def trial(*args, **kwargs):
            result = real_trial(*args, **kwargs)
            results.append(result)
            return result

        with patch.object(evaluator, "run_trial", side_effect=trial):
            calibrated = benchmark.calibrate(G.render(G.new_genome()), "main", bench,
                                             self.limits, self.work, log=lambda *args: None)
        self.assertIn("main", calibrated["calibrated"])
        self.assertGreaterEqual(len(results), 7)
        self.assertTrue(all(r["sandbox_validation"] and r["status"] == "ok" for r in results))

    def test_g1_correctness_is_also_executed_in_sandbox(self):
        popen = subprocess.Popen
        with patch.object(subprocess, "Popen", wraps=popen) as start:
            result = evaluator.check_correctness(G.render(G.new_genome()))
        self.assertLess(result["gradient_error"], 1e-4)
        self.assertTrue(result["sampler_valid"])
        self.assertTrue(start.called)
        self.assertTrue(all(Path(call.args[0][0]).name == "bwrap" for call in start.call_args_list))

    def test_observation_cannot_execute_champion_outside_sandbox(self):
        eng = SimpleNamespace(root=self.root, bench=self.bench, lim=self.limits,
                              cfg={"research": {"profile_batches": 10}}, source_context=lambda: {},
                              store=SimpleNamespace(tmp=self.work, stable=self.state / "stable"),
                              trial=lambda *args: {"reached": True, "cost_s": 1.0, "t_init": 0.1, "status": "ok"})
        result = research.observe(eng, G.render(G.new_genome()), batches=10)
        self.assertTrue(result["sandbox_evidence"]["validated"])

    def test_success_and_error_close_all_descriptors_without_resourcewarnings(self):
        gc.collect()
        before = len(list(Path("/proc/self/fd").iterdir()))
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always", ResourceWarning)
            self.assertEqual(self.trial()["status"], "ok")
            with patch.object(sandbox.Session, "verify", side_effect=sandbox.SandboxError("SANDBOX_VIOLATION", "test")):
                self.assertEqual(self.trial()["status"], "invalid")
            gc.collect()
        self.assertFalse([w for w in recorded if issubclass(w.category, ResourceWarning)])
        self.assertLessEqual(len(list(Path("/proc/self/fd").iterdir())), before)


if __name__ == "__main__":
    unittest.main()
