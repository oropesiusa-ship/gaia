"""External workspace identity and physical CUDA readiness must fail closed."""
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gaia.appliance_workspace import workspace, WorkspaceSession


class WorkspaceTests(unittest.TestCase):
    def test_missing_mount_or_changed_uuid_never_creates_artifacts_on_host_disk(self):
        for target, fstype, uuid in (("/", "ext4", "expected"), ("/mnt/test", "ntfs3", "expected"),
                                     ("/mnt/test", "ext4", "other")):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".gaia").mkdir()
                (root / ".gaia/build-workspace.json").write_text(json.dumps({"status": "LINUX_BUILD_WORKSPACE_READY",
                    "mountpoint": "/mnt/test", "filesystem_uuid": "expected"}))
                row = {"target": target, "fstype": fstype, "uuid": uuid, "source": "/dev/loop9", "options": "rw"}
                with patch("gaia.appliance_workspace.subprocess.check_output",
                           return_value=json.dumps({"filesystems": [row]})):
                    with self.assertRaises(ValueError):
                        workspace(root)

    def test_external_session_keeps_local_report_mirror(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            external = Path(directory) / "external"
            external.mkdir()
            with patch("gaia.appliance_workspace.workspace", return_value=(external, external)):
                session = WorkspaceSession(root)
                session.report["artifact"] = "external fixture"
                session.finish("TEST_COMPLETED")
            self.assertEqual(json.loads((session.local_directory / "report.json").read_text())["status"], "TEST_COMPLETED")
            self.assertEqual((session.directory / "REPORT.md").read_bytes(), (session.local_directory / "REPORT.md").read_bytes())

    def test_cuda_check_rejects_wrong_driver_or_missing_gpu_without_cpu_fallback(self):
        source = Path(__file__).resolve().parents[1] / "gaia/appliance_vm_payload/runtime_checks.py"
        spec = importlib.util.spec_from_file_location("gaia_runtime_checks_test", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
        for version in ("550.163.01", "580.178.04"):
            with patch.dict(sys.modules, {"torch": torch}), patch.object(module.subprocess, "check_output", return_value=version):
                with self.assertRaisesRegex(ValueError, "requires one GPU"):
                    module.cuda_smoke("580.178.04")
