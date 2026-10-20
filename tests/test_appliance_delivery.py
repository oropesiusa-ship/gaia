"""Delivery dependency removal must not remove native runtime libraries."""
from pathlib import Path
import unittest
from unittest.mock import patch

from gaia import appliance_image_build as b
from gaia.appliance_runtime_vm import readiness


class TestCpuDelivery(unittest.TestCase):
    def test_readiness_waits_for_whole_console_record(self):
        record = 'prefix GAIA_RUNTIME_READY={"status":"GAIA_RUNTIME_READY","nested":{"ok":true},"tail":"complete"}\n'
        for length in range(len(record)):
            self.assertIsNone(readiness(record[:length]))
        self.assertEqual(readiness(record)["tail"], "complete")
        with self.assertRaises(ValueError):
            readiness(record + record)
        with self.assertRaises(ValueError):
            readiness('GAIA_RUNTIME_READY={"broken":}\n')

    def test_compiler_runtime_abi_is_retained_while_toolchain_and_headers_selected(self):
        packages = {name: "1" for name in ("gcc", "gcc-14", "gcc-14-base", "gcc-14-x86-64-linux-gnu",
            "g++-14", "cpp-x86-64-linux-gnu", "binutils", "binutils-common", "libgcc-14-dev", "libssl-dev",
            "make", "build-essential", "libc-dev-bin", "libgcc-s1", "libstdc++6", "libgomp1", "libssl3t64", "systemd")}
        selected = b.build_only_packages(packages)
        self.assertTrue({"gcc", "gcc-14", "cpp-x86-64-linux-gnu", "libssl-dev", "libgcc-14-dev"} <= set(selected))
        self.assertFalse({"gcc-14-base", "binutils-common", "libgcc-s1", "libstdc++6", "libgomp1", "libssl3t64", "systemd"} & set(selected))

    def test_simulated_removal_of_runtime_blocks_real_purge(self):
        with patch.object(b, "package_inventory", return_value={"gcc": "1", "libc6": "2"}), \
                patch.object(b.subprocess, "check_output", return_value="Purg gcc [1]\nPurg libc6 [2]\n"), \
                patch.object(b, "run") as command:
            with self.assertRaisesRegex(ValueError, "out-of-scope"):
                b.strip_build_tools(Path("/never-chrooted-fixture"))
            command.assert_not_called()

    def test_actual_purge_plan_and_retained_versions_are_checked(self):
        before = {"gcc": "1", "libgcc-s1": "2", "gcc-14-base": "3"}
        after = {"libgcc-s1": "2", "gcc-14-base": "3"}
        with patch.object(b, "package_inventory", side_effect=[before, after]), \
                patch.object(b.subprocess, "check_output", return_value="Purg gcc [1]\n"), patch.object(b, "run") as command:
            result = b.strip_build_tools(Path("/never-chrooted-fixture"))
        self.assertEqual(result["removed"], {"gcc": "1"})
        self.assertEqual(result["retained"], after)
        self.assertFalse(result["autoremove_used"])
        self.assertIn("--no-download", command.call_args_list[0].args[0])
        changed = {"libgcc-s1": "different", "gcc-14-base": "3"}
        with patch.object(b, "package_inventory", side_effect=[before, changed]), \
                patch.object(b.subprocess, "check_output", return_value="Purg gcc [1]\n"), patch.object(b, "run"):
            with self.assertRaisesRegex(ValueError, "versions changed"):
                b.strip_build_tools(Path("/never-chrooted-fixture"))


if __name__ == "__main__":
    unittest.main()
