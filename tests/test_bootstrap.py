"""Provisión sin red: selección, aislamiento, recuperación y evidencia de fallos."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gaia import bootstrap as b

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "gaia/bootstrap_profiles.json").read_text())
HOST = {"host": {"system": "Linux", "machine": "x86_64", "cpu": "test",
                 "cores": 4, "ram_mb": 8192, "host_id": "test", "gpu": {"devices": []}},
        "python": [3, 14, 4], "disk_free_mb": 8192}


class TestBootstrap(unittest.TestCase):
    def test_old_and_new_python_select_distinct_compatible_wheels(self):
        old = copy.deepcopy(HOST)
        old["python"] = [3, 9, 1]
        self.assertEqual(b.select_profile(CATALOG, old)["packages"], ["numpy==2.0.2"])
        self.assertEqual(b.select_profile(CATALOG, HOST)["packages"], ["numpy==2.3.5"])

    def test_gpu_does_not_activate_unimplemented_workload(self):
        host = copy.deepcopy(HOST)
        host["host"]["gpu"]["devices"] = [{"name": "modern GPU"}]
        self.assertEqual(b.select_profile(CATALOG, host)["id"], "cpu-numpy")
        with self.assertRaises(b.BootstrapError):
            b.select_profile(CATALOG, host, "gaia_transformer_cuda")

    def test_unsupported_hosts_and_profiles_fail_explicitly(self):
        for field, value in (("system", "Windows"), ("machine", "mips")):
            host = copy.deepcopy(HOST)
            host["host"][field] = value
            with self.assertRaises(b.BootstrapError):
                b.select_profile(CATALOG, host)
        with self.assertRaises(b.BootstrapError):
            b.select_profile(CATALOG, HOST, requested="missing")
        host = copy.deepcopy(HOST)
        host["python"] = [3, 15, 0]
        with self.assertRaises(b.BootstrapError):
            b.select_profile(CATALOG, host)

    def test_local_config_preserves_user_and_historical_state(self):
        user = {"workload": {"id": "numpy_mlp", "state_dir": "state"},
                "limits": {"max_ram_mb": 99999, "max_experiment_seconds": 60}}
        original = copy.deepcopy(user)
        cfg = b.local_config(user, HOST, "new-host")
        self.assertEqual(user, original)
        self.assertEqual(cfg["workload"]["state_dir"], "state_numpy_mlp_new-host")
        self.assertEqual(cfg["limits"]["max_ram_mb"], 3000)
        self.assertEqual(cfg["limits"]["max_experiment_seconds"], 60)
        self.assertNotEqual(cfg, b.local_config(user, HOST, "other-host"))

    def test_low_memory_profile_and_explicit_insufficient_resources(self):
        host = copy.deepcopy(HOST)
        host["host"]["ram_mb"] = 1536
        cfg = b.local_config({}, host, "low")
        self.assertEqual(cfg["benchmark_profile"], "easy")
        self.assertLess(cfg["limits"]["max_ram_mb"], 700)
        host["host"]["ram_mb"] = 512
        with self.assertRaises(b.BootstrapError):
            b.local_config({}, host, "too-low")

    def test_lock_exclusion_and_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bootstrap.lock"
            with b.locked(path):
                with self.assertRaises(b.BootstrapError):
                    with b.locked(path):
                        self.fail("acquired twice")
            with b.locked(path):
                pass

    def test_subprocess_failure_is_reported_with_complete_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = b.Session(tmp)
            with self.assertRaises(b.BootstrapError) as error:
                session.command("install", [sys.executable, "-c",
                                "import sys;print('reason',file=sys.stderr);sys.exit(7)"])
            session.finish("FAILED", error.exception)
            report = json.loads((session.directory / "report.json").read_text())
            self.assertEqual(report["failure"]["stage"], "install")
            self.assertEqual(report["steps"][0]["returncode"], 7)
            self.assertIn("reason", (session.directory / report["steps"][0]["stderr"]).read_text())
            self.assertTrue((session.directory / "REPORT.md").exists())

    def test_timeout_is_bounded_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = b.Session(tmp)
            with self.assertRaises(b.BootstrapError) as error:
                session.command("probe", [sys.executable, "-c", "import time;time.sleep(20)"], timeout=0.1)
            session.finish("FAILED", error.exception)
            self.assertEqual(session.report["steps"][0]["timeout"], 0.1)

    def test_bootstrap_import_does_not_require_site_packages(self):
        script = "import sys;sys.path.insert(0,sys.argv[1]);from gaia import bootstrap"
        result = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(ROOT)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_doctor_never_creates_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gaia").mkdir()
            (root / "gaia/bootstrap_profiles.json").write_text(json.dumps(CATALOG))
            session = b.Session(root)
            with patch.object(b, "detect", return_value=HOST), patch.object(b, "preflight", return_value="venv"), patch.object(session, "command") as command:
                with self.assertRaises(b.BootstrapError) as error:
                    b.provision(session, doctor=True)
                self.assertEqual(error.exception.stage, "environment")
                command.assert_not_called()
                self.assertFalse((root / ".gaia/venvs").exists())

    def test_preflight_selects_fallback_when_ensurepip_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = b.Session(tmp)
            checks = {key: True for key in ("venv", "ensurepip", "ssl", "zlib", "ctypes", "resource")}
            checks["ensurepip"] = "No module named ensurepip"
            with patch.object(session, "command", return_value=json.dumps(checks)):
                self.assertEqual(b.preflight(session, {}), "virtualenv")
            self.assertFalse(session.report["preflight"]["needs_sudo"])
            checks["ensurepip"] = True
            with patch.object(session, "command", return_value=json.dumps(checks)):
                self.assertEqual(b.preflight(session, {}), "venv")

    def test_missing_ssl_stops_before_download_or_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = b.Session(tmp)
            checks = {key: True for key in ("venv", "ensurepip", "ssl", "zlib", "ctypes", "resource")}
            checks["ssl"] = "missing ssl"
            with patch.object(session, "command", return_value=json.dumps(checks)):
                with self.assertRaises(b.BootstrapError) as error:
                    b.preflight(session, {})
            self.assertEqual(error.exception.stage, "preflight")
            self.assertFalse((Path(tmp) / ".gaia/venvs").exists())

    def test_download_integrity_cache_and_offline_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = b.Session(tmp)
            data = b"verified wheel"
            artifact = {"url": "https://example.org/test.whl", "sha256": hashlib.sha256(data).hexdigest()}
            with patch.object(b.urllib.request, "urlopen", return_value=io.BytesIO(data)) as download:
                wheel = b.verified_download(session, artifact)
                download.assert_called_once()
            with patch.object(b.urllib.request, "urlopen", side_effect=OSError("offline")) as download:
                self.assertEqual(wheel, b.verified_download(session, artifact))
                download.assert_not_called()
            # Una caché alterada no se ejecuta; se intenta recuperarla y se reporta el fallo de red.
            wheel.write_bytes(b"corrupt")
            with patch.object(b.urllib.request, "urlopen", side_effect=OSError("offline")):
                with self.assertRaises(b.BootstrapError) as error:
                    b.verified_download(session, artifact)
            self.assertEqual(error.exception.stage, "download")

    def test_invalid_download_does_not_create_target_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gaia").mkdir()
            tools = {"artifacts": [{"url": "https://example.org/bad.whl", "sha256": "0" * 64}]}
            (root / "gaia/bootstrap_tools.json").write_text(json.dumps(tools))
            session = b.Session(root)
            venv = root / ".gaia/venvs/test"
            with patch.object(b.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong hash")):
                with self.assertRaises(b.BootstrapError):
                    b.create_environment(session, venv, {}, "virtualenv")
            self.assertFalse(venv.exists())
            self.assertFalse(list((root / ".gaia/bootstrap-cache").rglob("*.part")))

    def test_stop_is_available_without_environment_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(b, "provision") as provision:
                self.assertEqual(b.dispatch(tmp, ["stop"]), 0)
                self.assertTrue((Path(tmp) / "STOP").exists())
                self.assertEqual(b.dispatch(tmp, ["resume"]), 0)
                self.assertFalse((Path(tmp) / "STOP").exists())
                provision.assert_not_called()

    def test_dispatch_reports_unsupported_workload_without_installing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gaia").mkdir()
            (root / "gaia/bootstrap_profiles.json").write_text(json.dumps(CATALOG))
            (root / "gaia.json").write_text(json.dumps({"workload": {"id": "unknown_workload"}}))
            with patch.object(b, "detect", return_value=HOST), patch.object(b.Session, "command") as command:
                self.assertEqual(b.dispatch(root, ["bootstrap"]), 40)
                command.assert_not_called()
            reports = list((root / ".gaia/reports").glob("*/report.json"))
            report = json.loads(reports[0].read_text())
            self.assertEqual(report["failure"]["stage"], "profile")
            self.assertFalse((root / "state").exists())

    def test_manual_mode_and_managed_child_do_not_recurse(self):
        args = ["--no-bootstrap", "status"]
        self.assertIsNone(b.dispatch(ROOT, args))
        self.assertEqual(args, ["status"])
        with patch.dict(os.environ, {"GAIA_MANAGED": "1"}):
            self.assertIsNone(b.dispatch(ROOT, ["prepare"]))

    def test_managed_config_cannot_leak_into_other_project_roots(self):
        from gaia import config
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, other = root / "project", root / "other"
            (project / ".gaia/configs").mkdir(parents=True)
            other.mkdir()
            local = project / ".gaia/configs/local.json"
            local.write_text(json.dumps({"workload": {"state_dir": "state_managed"}}))
            (other / "gaia.json").write_text(json.dumps({"workload": {"state_dir": "state_other"}}))
            with patch.dict(os.environ, {"GAIA_LOCAL_CONFIG": str(local)}):
                self.assertEqual(config.load(project)["workload"]["state_dir"], "state_managed")
                self.assertEqual(config.load(other)["workload"]["state_dir"], "state_other")
                (other / "gaia.json").unlink()
                self.assertEqual(config.load(other)["workload"]["state_dir"], "state")


if __name__ == "__main__":
    unittest.main()
