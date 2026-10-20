"""Recovery authorization, destination scope and DATA-preserving repair.

Only regular temporary files simulate block devices. No real keys or disks.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import tempfile
import unittest
from unittest.mock import patch

from gaia import appliance_recovery as host
from gaia.bootstrap import Session
from gaia.appliance_vm_payload import recovery_install as guest

FPR = "1234567890ABCDEF1234567890ABCDEF12345678"
MIB = 1024 * 1024


class TestRecovery(unittest.TestCase):
    def fixture(self, directory):
        source = directory / "disk.raw"
        names = ("GAIA-ESP", "GAIA-CORE", "GAIA-A", "GAIA-B", "GAIA-DATA")
        raw = b"\0" * MIB + b"".join(bytes([index + 1]) * MIB for index in range(5)) + b"\0" * MIB
        source.write_bytes(raw)
        image = {"disk_bytes": len(raw), "disk_sha256": guest.digest(source), "owner_public_trust_ready": True,
                 "owner_fingerprint": FPR, "partitions": [
                     {"name": name, "start": (i + 1) * MIB // 512, "sectors": MIB // 512, "bytes": MIB,
                      "sha256": hashlib.sha256(bytes([i + 1]) * MIB).hexdigest()} for i, name in enumerate(names)]}
        (directory / "image-manifest.json").write_text(json.dumps(image))
        artifacts = [{"name": p.name, "bytes": p.stat().st_size, "sha256": guest.digest(p)}
                     for p in (source, directory / "image-manifest.json")]
        record = {"schema": "gaia-signed-artifacts-v1", "kind": "gaia-vm-install-bundle-v1", "purpose": "lab",
                  "signing_fingerprint": FPR, "target_serial": "GAIA-LAB-TARGET", "target_bytes": len(raw), "artifacts": artifacts}
        (directory / "install-manifest.json").write_text(json.dumps(record))
        (directory / "install-manifest.json.asc").write_text("not a real signature; crypto is mocked")
        return source, image, record

    def test_signed_bundle_context_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, image, record = self.fixture(directory)
            with patch.object(guest, "verify_signature", return_value=FPR):
                self.assertEqual(guest.signed_payload(directory)[1], image)
                record["purpose"] = "release"
                (directory / "install-manifest.json").write_text(json.dumps(record))
                with self.assertRaises(ValueError):
                    guest.signed_payload(directory)
                record["purpose"] = "lab"
                (directory / "install-manifest.json").write_text(json.dumps(record))
                with source.open("r+b") as stream:
                    stream.write(b"altered")
                with self.assertRaises(ValueError):
                    guest.signed_payload(directory)

    def test_bad_signature_rejected_before_artifact_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            self.fixture(directory)
            with patch.object(guest, "verify_signature", side_effect=ValueError("bad signature")), \
                    patch.object(guest, "digest") as checksum:
                with self.assertRaisesRegex(ValueError, "bad signature"):
                    guest.signed_payload(directory)
                checksum.assert_not_called()

    def test_target_identity_size_mount_or_mapper_ambiguity_rejected(self):
        good = {"serial": "GAIA-LAB-TARGET", "path": "/dev/mock-only", "type": "disk", "size": 123, "mountpoints": []}
        self.assertEqual(guest.select_target([good], 123), Path("/dev/mock-only"))
        for devices in ([], [good, good], [{**good, "size": 1}], [{**good, "mountpoints": ["/"]}],
                        [{**good, "children": [{"type": "crypt", "mountpoints": []}]}]):
            with self.assertRaises(ValueError):
                guest.select_target(devices, 123)

    def test_install_readback_and_repair_preserve_modified_data(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, image, _ = self.fixture(directory)
            target = directory / "simulated-target"
            target.write_bytes(b"\0" * image["disk_bytes"])
            original_stat = Path.stat
            def block_stat(path, *args, **kwargs):
                info = original_stat(path, *args, **kwargs)
                if path == target:
                    fields = list(info)
                    fields[0] = stat.S_IFBLK | 0o600
                    return os.stat_result(fields)
                return info
            with patch.object(Path, "stat", block_stat):
                result = guest.apply_image(source, target, image, "install")
                self.assertEqual(result["status"], "VM_IMAGE_INSTALLED")
                self.assertEqual(guest.digest(target), image["disk_sha256"])
                data = next(p for p in image["partitions"] if p["name"] == "GAIA-DATA")
                candidate = next(p for p in image["partitions"] if p["name"] == "GAIA-B")
                with target.open("r+b") as stream:
                    stream.seek(data["start"] * 512)
                    stream.write(b"confirmed experiment data")
                    stream.seek(candidate["start"] * 512)
                    stream.write(b"broken candidate")
                with target.open("rb") as stream:
                    stream.seek(data["start"] * 512)
                    data_before = stream.read(data["bytes"])
                result = guest.apply_image(source, target, image, "repair-system")
                self.assertTrue(result["data_preserved"])
                with target.open("rb") as stream:
                    stream.seek(data["start"] * 512)
                    self.assertEqual(stream.read(data["bytes"]), data_before)
                    stream.seek(candidate["start"] * 512)
                    self.assertEqual(hashlib.sha256(stream.read(candidate["bytes"])).hexdigest(), candidate["sha256"])
                with target.open("r+b") as stream:
                    stream.write(b"wrong GPT")
                with self.assertRaisesRegex(ValueError, "GPT differs"):
                    guest.apply_image(source, target, image, "repair-system")

    def test_prepare_request_links_only_verified_image_without_signing(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source_dir = directory / "source"
            source_dir.mkdir()
            source, image, _ = self.fixture(source_dir)
            (directory / "keys").mkdir()
            (directory / "keys/gaia-release-signing.fingerprint.txt").write_text(FPR)
            session = Session(directory)
            host.prepare_request(session, source_dir)
            bundle = session.directory / "install-bundle"
            self.assertEqual((bundle / "disk.raw").stat().st_ino, source.stat().st_ino)
            self.assertFalse((bundle / "install-manifest.json.asc").exists())
            self.assertFalse(session.report["private_key_used"])
            self.assertEqual(session.report["status"], "AWAITING_OWNER_VM_INSTALL_SIGNATURE")

    def test_resume_requires_same_signature_completed_prefix_and_untouched_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = Session(root)
            cached = previous.directory / "bundle.ext4"
            cached.write_bytes(b"public immutable bundle fixture")
            target = previous.directory / "target-1.qcow2"
            target.write_bytes(b"simulated qcow header; qemu-img is mocked")
            install = {"repeat": 1, "mode": "install", "recovery": {"status": "VM_IMAGE_INSTALLED", "fingerprint": FPR},
                       "installed_boot": {"status": "VM_FOUNDATION_OK"}}
            metadata = {"status": "FAILED", "finished": time.time(), "recovery_image_sha256": "a" * 64,
                        "manifest_sha256": "b" * 64, "signature_sha256": "c" * 64, "expected_fingerprint": FPR,
                        "bundle_disk_sha256": host.sha256(cached), "recovery_results": [install]}
            (previous.directory / "report.json").write_text(json.dumps(metadata))
            session = Session(root)
            session.report.update(manifest_sha256="b" * 64, signature_sha256="c" * 64, expected_fingerprint=FPR)
            image = {"disk_sha256": "a" * 64, "disk_bytes": 123456}
            info = json.dumps({"format": "qcow2", "virtual-size": 123456})
            with patch.object(session, "command", return_value=info):
                bundle, resumed, results = host.resume_checkpoint(session, previous.directory, image, 3, {"qemu-img": "qemu-img"})
                self.assertEqual(bundle, cached)
                self.assertEqual(resumed, target)
                self.assertEqual(results, [install])
                session.report["signature_sha256"] = "d" * 64
                with self.assertRaisesRegex(ValueError, "identity/signature"):
                    host.resume_checkpoint(session, previous.directory, image, 3, {"qemu-img": "qemu-img"})
                session.report["signature_sha256"] = "c" * 64
                os.utime(target, (time.time() + 100,) * 2)
                with self.assertRaisesRegex(ValueError, "target changed"):
                    host.resume_checkpoint(session, previous.directory, image, 3, {"qemu-img": "qemu-img"})

    def test_qemu_exit_zero_without_unique_recovery_success_is_not_accepted(self):
        good = 'GAIA_RECOVERY_RESULT={"status":"VM_IMAGE_INSTALLED"}\n'
        self.assertEqual(host.parse_recovery_result(good)["status"], "VM_IMAGE_INSTALLED")
        for log in ("Poweroff", good + good, 'GAIA_RECOVERY_ERROR={"reason":"bad signature"}\n'):
            with self.assertRaises(ValueError):
                host.parse_recovery_result(log)
        interleaved = 'GAIA_RECOVERY_RESULT={"status":"VM_IMAGE_INSTALLED","purpos[  316.127537]  vda: vda1 vda2 vda3 vda4 vda5\ne":"lab"}\n'
        self.assertEqual(host.parse_recovery_result(interleaved)["purpose"], "lab")
        unknown = interleaved.replace('vda: vda1 vda2 vda3 vda4 vda5', 'EXT4-fs error: unknown corruption')
        with self.assertRaises(ValueError):
            host.parse_recovery_result(unknown)


if __name__ == "__main__":
    unittest.main()
