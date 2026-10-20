"""Retention safety: backing dependencies, provenance, active/modified files."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from gaia import appliance_artifacts as a
from gaia.bootstrap import Session


class TestArtifactRetention(unittest.TestCase):
    def test_cleanup_removes_only_proven_fixtures_and_keeps_reference_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / ".gaia/reports"
            old, frame, current = [reports / name for name in ("old", "case", "current")]
            for path in (old, frame, current):
                path.mkdir(parents=True)
            base, reference = old / "disk.raw", current / "disk.raw"
            base.write_bytes(b"obsolete simulated base")
            reference.write_bytes(b"signed reference fixture")
            child, fat, unknown, cache = [frame / name for name in ("child.qcow2", "esp.fat", "unknown.fat", "bundle.ext4")]
            for path in (child, fat, unknown, cache):
                path.write_bytes(b"public temporary fixture")
            (old / "image-manifest.json").write_text(json.dumps({"release_image": False, "signed": False, "disk_sha256": a.sha256(base)}))
            (old / "report.json").write_text(json.dumps({"status": "DONE", "finished": time.time()}))
            record = {"status": "DONE", "finished": time.time(), "bundle_disk_sha256": a.sha256(cache), "steps": [
                {"command": ["qemu-img", "create", "-f", "qcow2", "-F", "raw", "-b", str(base), str(child)]},
                {"command": ["qemu-img", "dd", "if=" + str(child), "of=" + str(fat)]}]}
            (frame / "report.json").write_text(json.dumps(record))
            policy = {"preserve": [str(reference.relative_to(root))], "retire_base_images": [str(base.relative_to(root))],
                      "bundle_cache": str(cache.relative_to(root)), "retire_esp_staging": True}
            session = Session(root)
            info = SimpleNamespace(stdout=json.dumps({"format": "qcow2", "backing-filename": str(base)}))
            with patch.object(a, "idle", return_value=True), patch.object(a.subprocess, "run", return_value=info):
                a.cleanup(session, policy, apply=True)
            self.assertFalse(any(path.exists() for path in (base, child, fat, cache)))
            self.assertTrue(reference.exists() and unknown.exists())
            self.assertTrue((old / "report.json").exists() and (frame / "report.json").exists())
            self.assertEqual(len(session.report["removed"]), 4)

    def test_dependents_precede_base_and_protected_child_blocks_base(self):
        children = {"base": ["first", "second"], "first": ["grandchild"]}
        order, blocked = a.dependency_order(["base"], children, lambda p: True)
        self.assertLess(order.index("grandchild"), order.index("first"))
        self.assertEqual(order[-1], "base")
        order, blocked = a.dependency_order(["base"], children, lambda p: p != "second")
        self.assertNotIn("base", order)
        self.assertIn("base", blocked)
        self.assertIn("grandchild", order)

    def test_backing_cycle_is_not_deleted(self):
        with self.assertRaises(ValueError):
            a.dependency_order(["a"], {"a": ["b"], "b": ["a"]}, lambda p: True)

    def test_creator_is_output_not_backing_input(self):
        root = Path("/project")
        report = {"steps": [{"command": ["/usr/bin/qemu-img", "create", "-f", "qcow2", "-F", "raw",
                                          "-b", "/project/base.qcow2", "/project/child.qcow2"]}]}
        self.assertTrue(a.created_by_report(root / "child.qcow2", report, root))
        self.assertFalse(a.created_by_report(root / "base.qcow2", report, root))
        report = {"steps": [{"command": ["qemu-img", "dd", "if=/project/source", "of=/project/esp.fat"]}]}
        self.assertTrue(a.created_by_report(root / "esp.fat", report, root))
        self.assertFalse(a.created_by_report(root / "source", report, root))

    def test_symlink_current_reference_active_or_modified_artifact_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            reports = Path(directory)
            frame = reports / "case"
            frame.mkdir()
            path = frame / "disk.raw"
            path.write_bytes(b"public fixture")
            (frame / "report.json").write_text(json.dumps({"status": "VM_FOUNDATION_VALIDATED", "finished": time.time()}))
            with patch.object(a, "idle", return_value=True):
                self.assertTrue(a.eligible(path, reports, set()))
                reference = {(path.stat().st_dev, path.stat().st_ino)}
                self.assertFalse(a.eligible(path, reports, reference))
                link = frame / "alias.raw"
                link.symlink_to(path)
                self.assertFalse(a.eligible(link, reports, set()))
                os.utime(path, (time.time() + 100,) * 2)
                self.assertFalse(a.eligible(path, reports, set()))
            with patch.object(a, "idle", return_value=False):
                self.assertFalse(a.eligible(path, reports, set()))


if __name__ == "__main__":
    unittest.main()
