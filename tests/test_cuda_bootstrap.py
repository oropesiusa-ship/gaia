"""Reglas de plataforma y rechazo: no requieren Torch ni una GPU para ejecutarse."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia import bootstrap as b, config, engine

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "gaia/bootstrap_profiles.json").read_text())
PROFILE = next(p for p in CATALOG["profiles"] if p["id"] == "gaia-transformer-cuda-pascal")
GPU = {"name": "Pascal", "uuid": "GPU-7f51f56b-b660-40c6-3248-47101541b887", "vram_mb": "6144",
       "compute_capability": "6.1", "driver": "580.178.04"}
HOST = {"host": {"system": "Linux", "machine": "x86_64", "ram_mb": 15353,
                 "gpu": {"devices": [GPU]}}, "python": [3, 14, 4], "implementation": "CPython",
        "free_threaded": False, "libc": ["glibc", "2.43"], "disk_free_mb": 100000}


def result():
    return {"status": "ok", "runtime": {"torch": {"version": "2.14.0+cu126", "cuda": "12.6"}},
            "gpu": {"uuid": GPU["uuid"].removeprefix("GPU-")},
            "policy": {"deterministic": True, "cudnn_deterministic": True, "tf32_matmul": False,
                       "tf32_cudnn": False, "cudnn_benchmark": False,
                       "cublas_workspace_config": ":4096:8", "dtype": "float32"},
            "determinism": {"output": "hash", "gradients": ["hash2"], "losses": [1.0]},
            "metrics": {"seconds": 1}}


class TestCudaBootstrap(unittest.TestCase):
    def test_pascal_selected_only_for_cuda_workload(self):
        self.assertEqual(b.select_profile(CATALOG, HOST, "gaia_transformer_cuda")["id"], PROFILE["id"])
        self.assertEqual(b.select_profile(CATALOG, HOST)["id"], "cpu-numpy")

    def test_rejects_incompatible_arch_driver_vram_and_python(self):
        for key, value in (("compute_capability", "8.6"), ("driver", "550.1"), ("vram_mb", "1024")):
            host = copy.deepcopy(HOST)
            host["host"]["gpu"]["devices"][0][key] = value
            with self.assertRaises(b.BootstrapError):
                b.select_profile(CATALOG, host, "gaia_transformer_cuda")
        host = copy.deepcopy(HOST)
        host["python"] = [3, 13, 9]
        with self.assertRaises(b.BootstrapError):
            b.select_profile(CATALOG, host, "gaia_transformer_cuda")

    def test_rejects_nonstandard_python_old_glibc_and_low_ram(self):
        for key, value in (("free_threaded", True), ("implementation", "PyPy"), ("libc", ["glibc", "2.27"])):
            host = copy.deepcopy(HOST)
            host[key] = value
            with self.assertRaises(b.BootstrapError):
                b.validate_cuda_host(PROFILE, host)
        host = copy.deepcopy(HOST)
        host["host"]["ram_mb"] = 2048
        with self.assertRaises(b.BootstrapError):
            b.validate_cuda_host(PROFILE, host)

    def test_selects_compatible_gpu_in_multigpu_host(self):
        host = copy.deepcopy(HOST)
        host["host"]["gpu"]["devices"].insert(0, {**GPU, "compute_capability": "9.0", "uuid": "other"})
        self.assertEqual(b.validate_cuda_host(PROFILE, host)["uuid"], GPU["uuid"])

    def test_local_gpu_config_is_separate_and_fits_vram(self):
        host = copy.deepcopy(HOST)
        host["host"]["gpu"]["devices"][0]["vram_mb"] = "2048"
        cfg = b.local_config({}, host, "test", PROFILE)
        self.assertEqual(cfg["workload"]["state_dir"], "state_gaia_transformer_cuda_test")
        self.assertEqual(cfg["workload"]["id"], "gaia_transformer_cuda")
        self.assertEqual(cfg["cuda"]["device_uuid"], GPU["uuid"])
        self.assertLess(cfg["limits"]["max_vram_mb"], 2048)

    def test_normalizes_nvidia_and_torch_uuid_and_ignores_timing_noise(self):
        cfg = b.local_config({}, HOST, "test", PROFILE)
        a, other = result(), result()
        other["metrics"]["seconds"] = 2
        b.validate_cuda_results([a, other, a], PROFILE, cfg)

    def test_rejects_nondeterminism_and_runtime_drift(self):
        cfg = b.local_config({}, HOST, "test", PROFILE)
        for key, value in (("determinism", {"output": "different"}), ("runtime", {"torch": "other"})):
            other = result()
            other[key] = value
            with self.assertRaises(b.BootstrapError) as error:
                b.validate_cuda_results([result(), other, result()], PROFILE, cfg)
            self.assertEqual(error.exception.stage, "cuda-runtime")

    def test_rejects_wrong_device_flags_and_torch_version(self):
        cfg = b.local_config({}, HOST, "test", PROFILE)
        for section, key, value in (("gpu", "uuid", "different"), ("policy", "deterministic", False),
                                     ("policy", "tf32_matmul", True)):
            a = result()
            a[section][key] = value
            with self.assertRaises(b.BootstrapError) as error:
                b.validate_cuda_results([a, a, a], PROFILE, cfg)
            self.assertEqual(error.exception.stage, "cuda-policy")
        a = result()
        a["runtime"]["torch"]["version"] = "another"
        with self.assertRaises(b.BootstrapError):
            b.validate_cuda_results([a, a, a], PROFILE, cfg)

    def test_cuda_bootstrap_never_calls_campaign_prepare_or_creates_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gaia").mkdir()
            (root / "requirements").mkdir()
            (root / "gaia/bootstrap_profiles.json").write_text(json.dumps(CATALOG))
            (root / PROFILE["lockfile"]).write_text((ROOT / PROFILE["lockfile"]).read_text())
            session = b.Session(root)
            seen = []

            def command(stage, args, *rest, **kwargs):
                seen.append(stage)
                if stage.startswith("probe-"):
                    return json.dumps({"prefix": session.report["environment"], "numpy": "2.3.5"})
                return ""

            def creator(session, path, *args):
                path.mkdir(parents=True)

            with patch.object(b, "detect", return_value=HOST), patch.object(b, "preflight", return_value="virtualenv"), \
                    patch.object(b, "create_environment", side_effect=creator), \
                    patch.object(session, "command", side_effect=command), patch.object(b, "diagnose_cuda") as diagnose:
                b.provision(session, requested=PROFILE["id"], prepare=True)
                diagnose.assert_called_once()
            self.assertNotIn("selftest", seen)
            self.assertNotIn("prepare", seen)
            self.assertFalse(list(root.glob("state*")))
            self.assertTrue((root / ".gaia/configs").exists())

    def test_future_workload_cannot_run_mlp_even_in_manual_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = config.load(root)
            cfg["workload"] = {"id": "gaia_transformer_cuda", "state_dir": "must_not_exist"}
            with self.assertRaisesRegex(ValueError, "Workload no implementado"):
                engine.Engine(root, cfg)
            self.assertFalse((root / "must_not_exist").exists())

    def test_hashed_lock_pins_every_requirement(self):
        lines = [s for s in (ROOT / PROFILE["lockfile"]).read_text().splitlines() if s and not s.startswith("#")]
        for line in lines:
            self.assertRegex(line, r" --hash=sha256:[a-f0-9]{64}$")
            self.assertTrue("==" in line or " @ https://download-r2.pytorch.org/" in line)


if __name__ == "__main__":
    unittest.main()
