"""Provisioning gates and failure cleanup; all privileged commands are mocked."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gaia import appliance_key_usb as u


class TestCustodyUsb(unittest.TestCase):
    def setUp(self):
        self.expected = {"serial": "EXAMPLE_ONLY", "model": "Example", "bytes": 100000000,
                         "by_id": "/dev/disk/by-id/usb-example"}
        self.device = {"serial": "EXAMPLE_ONLY", "model": "Example", "size": 100000000,
                       "path": "/dev/mock-only", "tran": "usb", "type": "disk", "ro": False,
                       "mountpoints": [], "fstype": None}

    def test_exact_identity_and_by_id_required(self):
        with patch.object(Path, "is_block_device", return_value=True), \
                patch.object(Path, "resolve", return_value=Path("/dev/mock-only")):
            self.assertEqual(u.match_target(self.expected, [self.device]), self.device)
            for field, value in (("serial", "wrong"), ("size", 200000000), ("model", "different"),
                                 ("type", "part"), ("tran", "sata"), ("ro", True)):
                with self.subTest(field=field), self.assertRaises(ValueError):
                    u.match_target(self.expected, [{**self.device, field: value}])
            with self.assertRaises(ValueError):
                u.match_target(self.expected, [self.device, self.device])
        with patch.object(Path, "is_block_device", return_value=True), \
                patch.object(Path, "resolve", return_value=Path("/dev/wrong")):
            with self.assertRaises(ValueError):
                u.match_target(self.expected, [self.device])

    def test_existing_crypto_and_essential_mounts_are_never_candidates(self):
        for delta in ({"fstype": "crypto_LUKS"}, {"mountpoints": ["/"]},
                      {"children": [{"type": "crypt"}]}, {"mountpoints": [str(u.ROOT)]}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                u.match_target(self.expected, [{**self.device, **delta}])

    def test_actual_luks_detection_blocks_wipe_even_if_metadata_cache_empty(self):
        with patch.object(u, "match_target", return_value=self.device), patch.object(u, "inventory"), \
                patch.object(Path, "exists", return_value=False), \
                patch.object(u, "root_command", return_value=subprocess.CompletedProcess([], 0)) as root:
            with self.assertRaisesRegex(ValueError, "ya es LUKS"):
                u.prepare("primary", self.expected)
            self.assertEqual(root.call_count, 1)
            self.assertIn("isLuks", root.call_args.args[0])

    def test_mounted_partition_is_discovered_and_unmounted_before_wipe(self):
        partition = {"path": "/dev/mock-only1", "type": "part", "mountpoints": ["/media/test-usb"]}
        calls = []
        luks_checks = 0
        def lsblk(args, **kwargs):
            # Match util-linux behavior: JSON lacks children without NAME or
            # explicit --tree. PATH alone does not request a hierarchy.
            if "--tree" in args:
                devices = [{**self.device, "children": [partition]}]
            else:
                devices = [self.device, partition]
            return json.dumps({"blockdevices": devices})
        def command(args, check=True):
            nonlocal luks_checks
            calls.append(args)
            if "isLuks" in args:
                luks_checks += 1
                return subprocess.CompletedProcess(args, 1 if luks_checks == 1 else 0)
            if args[0] == u.TOOLS["umount"] and args[-1] == partition["path"]:
                partition["mountpoints"] = []
            if args[0] == u.TOOLS["wipefs"]:
                self.assertEqual(partition["mountpoints"], [], "wipefs reached while USB partition was mounted")
            return subprocess.CompletedProcess(args, 0)
        with patch.object(u.subprocess, "check_output", side_effect=lsblk), \
                patch.object(Path, "is_block_device", return_value=True), \
                patch.object(Path, "resolve", return_value=Path("/dev/mock-only")), \
                patch.object(Path, "exists", return_value=False), patch.object(u, "root_command", side_effect=command):
            u.prepare("primary", self.expected)
        unmount = next(i for i, args in enumerate(calls) if args[0] == u.TOOLS["umount"] and args[-1] == partition["path"])
        wipe = next(i for i, args in enumerate(calls) if args[0] == u.TOOLS["wipefs"])
        self.assertLess(unmount, wipe)

    def test_partition_unmount_failure_stops_before_wipe_and_format(self):
        device = {**self.device, "children": [{"path": "/dev/mock-only1", "mountpoints": ["/media/test-usb"]}]}
        calls = []
        def command(args, check=True):
            calls.append(args)
            if args[0] == u.TOOLS["umount"]:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 1 if "isLuks" in args else 0)
        with patch.object(u, "match_target", return_value=device), patch.object(u, "inventory"), \
                patch.object(Path, "exists", return_value=False), patch.object(u, "root_command", side_effect=command):
            with self.assertRaises(subprocess.CalledProcessError):
                u.prepare("primary", self.expected)
        self.assertFalse(any(args[0] == u.TOOLS["wipefs"] or "luksFormat" in args for args in calls))

    def test_success_checks_ext4_and_closes_container_without_key_generation(self):
        calls = []
        luks_checks = 0
        def command(args, check=True):
            nonlocal luks_checks
            calls.append(args)
            if "isLuks" in args:
                luks_checks += 1
                return subprocess.CompletedProcess(args, 1 if luks_checks == 1 else 0)
            return subprocess.CompletedProcess(args, 0)
        with patch.object(u, "match_target", return_value=self.device), patch.object(u, "inventory"), \
                patch.object(Path, "exists", return_value=False), patch.object(u, "root_command", side_effect=command):
            u.prepare("primary", self.expected)
        self.assertEqual(sum("luksFormat" in args for args in calls), 1)
        self.assertEqual(sum("open" in args for args in calls), 1)
        self.assertEqual(sum("close" in args for args in calls), 1)
        self.assertEqual(sum(args[0] == u.TOOLS["e2fsck"] for args in calls), 1)
        self.assertEqual(luks_checks, 2)
        self.assertTrue(all("gpg" not in str(args) for args in calls))

    def test_no_terminal_stops_before_sudo_or_disk_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".gaia").mkdir()
            config = {"primary": self.expected, "backup": {**self.expected, "serial": "BACKUP_EXAMPLE"}}
            (root / ".gaia/signing-usb-targets.json").write_text(json.dumps(config))
            with patch.object(u, "ROOT", root), patch.object(u, "inventory"), \
                    patch.object(u, "match_target", return_value=self.device), \
                    patch.object(u.os, "geteuid", return_value=1000), patch.object(u.os, "isatty", return_value=False), \
                    patch.object(u.sys, "argv", ["setup"]), patch.object(u.subprocess, "run") as command:
                self.assertEqual(u.main(), 10)
                command.assert_not_called()
            self.assertEqual(json.loads((root / ".gaia/signing-usb-preparation.json").read_text())["prepared"], [])

    def test_failed_unmount_does_not_delete_mounted_contents_or_close_mapper(self):
        with tempfile.TemporaryDirectory() as mountpoint:
            calls = []
            def command(args, check=True):
                calls.append(args)
                if args[0] == u.TOOLS["sync"]:
                    raise subprocess.CalledProcessError(1, args)
                if args[0] == u.TOOLS["umount"]:
                    return subprocess.CompletedProcess(args, 1)
                return subprocess.CompletedProcess(args, 1 if "isLuks" in args else 0)
            with patch.object(u, "match_target", return_value=self.device), patch.object(u, "inventory"), \
                    patch.object(Path, "exists", return_value=False), patch.object(u.tempfile, "mkdtemp", return_value=mountpoint), \
                    patch.object(u, "root_command", side_effect=command), patch.object(u.shutil, "rmtree") as remove:
                with self.assertRaisesRegex(RuntimeError, "conserva el montaje"):
                    u.prepare("primary", self.expected)
                remove.assert_not_called()
                self.assertFalse(any("close" in args for args in calls))

    def test_format_failure_closes_only_new_mapper_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as mountpoint:
            calls = []
            def command(args, check=True):
                calls.append(args)
                if args[0] == u.TOOLS["mkfs"]:
                    raise subprocess.CalledProcessError(1, args)
                return subprocess.CompletedProcess(args, 1 if "isLuks" in args else 0)
            with patch.object(u, "match_target", return_value=self.device), patch.object(u, "inventory"), \
                    patch.object(Path, "exists", return_value=False), patch.object(u.tempfile, "mkdtemp", return_value=mountpoint), \
                    patch.object(u, "root_command", side_effect=command), patch.object(u.shutil, "rmtree") as remove:
                with self.assertRaises(subprocess.CalledProcessError):
                    u.prepare("primary", self.expected)
                self.assertEqual(sum("luksFormat" in args for args in calls), 1)
                self.assertEqual(sum("close" in args for args in calls), 1)
                remove.assert_called_once_with(mountpoint)


if __name__ == "__main__":
    unittest.main()
