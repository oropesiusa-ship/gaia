"""Artifact validation and bounded rootless build commands, without downloads."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from gaia import appliance_rootfs as r, bootstrap as b


class TestApplianceRootfs(unittest.TestCase):
    def archive(self, path, omit=(), extra=()):
        status = "\n\n".join(f"Package: {name}\nStatus: install ok installed\nVersion: 1.0\nArchitecture: amd64"
                             for name in r.PROFILE["packages"] if name not in omit)
        files = {"./var/lib/dpkg/status": status.encode(), "./boot/vmlinuz-6.12": b"kernel",
                 "./boot/initrd.img-6.12": b"initrd", "./usr/lib/systemd/boot/efi/systemd-bootx64.efi": b"efi"}
        for name in omit:
            files.pop(name, None)
        with tarfile.open(path, "w") as archive:
            for name, raw in [*files.items(), *extra]:
                item = tarfile.TarInfo(name)
                item.size = len(raw)
                archive.addfile(item, io.BytesIO(raw))

    def test_manifest_reads_actual_packages_kernel_initrd_efi_without_extracting(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "rootfs.tar"
            self.archive(path)
            result = r.inspect_rootfs(path)
            self.assertEqual(result["packages"]["systemd-sysv"]["Version"], "1.0")
            self.assertEqual(result["kernels"], ["boot/vmlinuz-6.12"])
            self.assertEqual(list(Path(root).iterdir()), [path])

    def test_incomplete_and_duplicate_dpkg_inventory_rejected(self):
        for omit, extra in ((["systemd-sysv"], []), (["./boot/vmlinuz-6.12"], []),
                            (["./boot/initrd.img-6.12"], []),
                            ([], [("var/lib/dpkg/status", b"duplicate")])):
            with self.subTest(omit=omit, duplicate=bool(extra)), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "rootfs.tar"
                self.archive(path, omit, extra)
                with self.assertRaises(ValueError):
                    r.inspect_rootfs(path)

    def test_runtime_smoke_is_read_from_artifact(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "rootfs.tar"
            smoke = {"status": "GAIA_RUNTIME_CPU_SMOKE_OK", "uid": 999, "cuda_runtime": "12.6"}
            self.archive(path, extra=[("opt/gaia/build-runtime.json", json.dumps(smoke).encode())])
            self.assertEqual(r.inspect_rootfs(path)["runtime"], smoke)

    def test_command_uses_signed_dated_snapshot_rootless_no_privileged_shell(self):
        command = r.build_command("/usr/bin/mmdebstrap", Path("/workspace/rootfs.tar"))
        self.assertIn("--mode=unshare", command)
        self.assertIn("--keyring=" + r.PROFILE["keyring"], command)
        self.assertTrue(command[-1].startswith("https://snapshot.debian.org/archive/debian/20261015T000000Z/"))
        self.assertNotIn("sudo", " ".join(command))
        self.assertNotIn("--skip", " ".join(command))
        self.assertNotIn("AllowUnauthenticated", " ".join(command))

    def test_blocked_host_never_launches_builder(self):
        with tempfile.TemporaryDirectory() as root:
            session = b.Session(root)
            with patch.object(r, "diagnose", return_value={"missing_packages": ["ovmf"]}), \
                    patch.object(session, "command") as command:
                with self.assertRaises(b.BootstrapError):
                    r.build(session)
                command.assert_not_called()

    def test_success_records_tar_digest_and_uses_workspace_temporaries(self):
        with tempfile.TemporaryDirectory() as root:
            session = b.Session(root)
            keyring = Path(root) / "debian.pgp"
            keyring.write_bytes(b"fixture keyring")
            profile = {**r.PROFILE, "keyring": str(keyring)}
            host = {"missing_packages": [], "rootfs_namespace_probe": {"available": True, "mode": "mmdebstrap-unshare"},
                    "disk_free_bytes": 64 * 2**30, "tools": {"mmdebstrap": "/usr/bin/mmdebstrap"}, "installed_versions": {}}
            def command(stage, args, **kwargs):
                self.assertEqual(kwargs["env"]["TMPDIR"], session.report["build_tmpdir"]["path"])
                self.assertIn("--mode=unshare", args)
                self.assertNotIn("sudo", " ".join(args))
                self.archive(session.directory / "rootfs.tar")
            with patch.object(r, "diagnose", return_value=host), patch.object(r, "PROFILE", profile), \
                    patch.object(r, "check_tmpdir", return_value={"path": "/tmp", "required_bytes": 2 * 2**30}), \
                    patch.object(session, "command", side_effect=command):
                self.assertEqual(r.build(session), 0)
            manifest = json.loads((session.directory / "rootfs-manifest.json").read_text())
            self.assertEqual(manifest["rootfs_sha256"], r.sha256(session.directory / "rootfs.tar"))
            self.assertFalse(manifest["s1_complete"])
            self.assertFalse(manifest["bootable_media"])

    def test_private_home_temporaries_rejected_before_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(b.BootstrapError) as error:
                r.check_tmpdir(Path(directory), with_runtime=True)
            self.assertEqual(error.exception.stage, "appliance-rootfs-tmpdir")

    def test_runtime_tmpfs_capacity_budget_checked(self):
        with patch.object(r.shutil, "disk_usage", return_value=type("Usage", (), {"free": 7 * 2**30})()):
            with self.assertRaises(b.BootstrapError) as error:
                r.check_tmpdir(Path("/tmp"), with_runtime=True)
        self.assertIn("16 GiB", str(error.exception))

    def test_automatic_fallback_to_disk_tmp_and_explicit_selection_no_fallback(self):
        denied = b.BootstrapError("tmpdir", "tmpfs too small", "inspect")
        with patch.object(r.tempfile, "gettempdir", return_value="/tmp"), \
                patch.object(r, "check_tmpdir", side_effect=[denied, {"path": "/var/tmp"}]) as check:
            result = r.select_tmpdir(True)
        self.assertEqual(result["path"], "/var/tmp")
        self.assertEqual(result["rejected_candidates"][0]["path"], "/tmp")
        self.assertEqual(check.call_count, 2)
        with patch.object(r, "check_tmpdir", side_effect=denied) as check:
            with self.assertRaises(b.BootstrapError):
                r.select_tmpdir(True, Path("/explicit"))
            check.assert_called_once_with(Path("/explicit"), True)


if __name__ == "__main__":
    unittest.main()
