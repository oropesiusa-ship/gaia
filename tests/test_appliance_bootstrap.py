"""Host bootstrap: no real apt/sudo, media access or network in these tests."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gaia import appliance_bootstrap as a, bootstrap as b

ROOT = Path(__file__).resolve().parents[1]


def diagnosis(missing=(), namespace=True):
    return {"missing_packages": list(missing), "rootfs_namespace_probe": {"available": namespace},
            "os": {"ID": "ubuntu"}, "architecture": "x86_64", "disk_free_bytes": 100 * 2**30, "kvm_access_rw": True,
            "tools": {"mmdebstrap": "/usr/bin/mmdebstrap", "qemu-system-x86_64": "/usr/bin/qemu-system-x86_64",
                      "qemu-img": "/usr/bin/qemu-img"}}


class TestApplianceBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def report(self):
        path = next((self.root / ".gaia/reports").glob("*/report.json"))
        return json.loads(path.read_text())

    def interactive(self):
        for stream in ("stdin", "stdout", "stderr"):
            self.stack.enter_context(patch.object(getattr(a.sys, stream), "isatty", return_value=True))

    def test_cli_dispatch_is_independent_of_runtime_and_managed_environment(self):
        with patch.dict(os.environ, {"GAIA_MANAGED": "1"}), patch.object(a, "main", return_value=10) as main, \
                patch.object(b, "provision") as provision:
            self.assertEqual(b.dispatch(self.root, ["appliance-bootstrap", "--preflight"]), 10)
            main.assert_called_once_with(self.root, ["--preflight"])
            provision.assert_not_called()

    def test_help_works_without_site_packages_and_without_report_creation(self):
        result = subprocess.run([sys.executable, "-S", str(ROOT / "gaia.py"), "appliance-bootstrap", "--help"],
                                capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--preflight", result.stdout)

    def test_preflight_reports_missing_packages_without_prompt_or_install(self):
        with patch.object(a, "diagnose", return_value=diagnosis(["ovmf"])), \
                patch("builtins.input") as prompt, patch.object(a, "terminal_command") as install:
            self.assertEqual(a.main(self.root, ["--preflight"]), 10)
            prompt.assert_not_called()
            install.assert_not_called()
        self.assertEqual(self.report()["status"], "APPLIANCE_HOST_PACKAGES_MISSING")
        self.assertTrue(next((self.root / ".gaia/reports").glob("*/REPORT.md")).exists())

    def test_missing_packages_require_terminal_even_with_cached_sudo(self):
        with patch.object(a, "diagnose", return_value=diagnosis(["ovmf"])), \
                patch.object(a.sys.stdin, "isatty", return_value=False), \
                patch.object(a, "terminal_command") as install:
            self.assertEqual(a.main(self.root, []), 10)
            install.assert_not_called()
        self.assertEqual(self.report()["status"], "NEEDS_INTERACTIVE_TERMINAL")

    def test_decline_and_eof_never_install(self):
        self.interactive()
        for answer in ("", "no", EOFError()):
            with self.subTest(answer=repr(answer)), tempfile.TemporaryDirectory() as root, \
                    patch.object(a, "diagnose", return_value=diagnosis(["ovmf"])), \
                    patch("builtins.input", **({"side_effect": answer} if isinstance(answer, Exception) else {"return_value": answer})), \
                    patch.object(a, "terminal_command") as install:
                self.assertEqual(a.main(root, []), 130)
                install.assert_not_called()

    def test_install_fixed_missing_packages_and_recheck_not_marker(self):
        self.interactive()
        with patch.object(a.os, "geteuid", return_value=1000), \
                patch.object(a, "diagnose", side_effect=[diagnosis(["ovmf", "mmdebstrap"]), diagnosis()]), \
                patch("builtins.input", return_value="sí"), patch.object(a, "terminal_command") as install, \
                patch.object(b.Session, "command", return_value="version"):
            self.assertEqual(a.main(self.root, []), 0)
        self.assertEqual(install.call_args_list[0].args[1], ["/usr/bin/sudo", "--", "/usr/bin/apt-get", "update", "--error-on=any"])
        self.assertEqual(install.call_args_list[1].args[1], ["/usr/bin/sudo", "--", "/usr/bin/apt-get", "install",
                         "--no-install-recommends", "--no-remove", "--yes", "ovmf", "mmdebstrap"])
        self.assertTrue(self.report()["installation_confirmed"])
        self.assertEqual(self.report()["status"], "APPLIANCE_HOST_READY")

    def test_rerun_does_not_prompt_install_or_touch_campaign_state(self):
        state = self.root / "state"
        state.mkdir()
        (state / "ledger.jsonl").write_text("existing evidence\n")
        with patch.object(a, "diagnose", return_value=diagnosis()), patch("builtins.input") as prompt, \
                patch.object(a, "terminal_command") as install, patch.object(b.Session, "command", return_value="version"):
            self.assertEqual(a.main(self.root, []), 0)
            prompt.assert_not_called()
            install.assert_not_called()
        self.assertEqual((state / "ledger.jsonl").read_text(), "existing evidence\n")
        self.assertFalse((self.root / ".gaia/venvs").exists())

    def test_denied_namespace_remains_blocker_without_reinstall(self):
        with patch.object(a, "diagnose", return_value=diagnosis(namespace=False)), \
                patch.object(a, "terminal_command") as install, patch.object(b.Session, "command", return_value="version"):
            self.assertEqual(a.main(self.root, []), 10)
            install.assert_not_called()
        report = self.report()
        self.assertTrue(report["host_tools_ready"])
        self.assertEqual(report["status"], "APPLIANCE_HOST_TOOLS_READY_ROOTFS_BLOCKED")

    def test_install_failure_stops_before_second_command_and_preserves_report(self):
        self.interactive()
        error = b.BootstrapError("appliance-host-install", "apt failed", "retry")
        with patch.object(a, "diagnose", return_value=diagnosis(["ovmf"])), \
                patch("builtins.input", return_value="s"), patch.object(a, "terminal_command", side_effect=error) as install:
            self.assertEqual(a.main(self.root, []), 40)
            install.assert_called_once()
        self.assertEqual(self.report()["failure"]["stage"], "appliance-host-install")

    def test_apt_success_with_missing_firmware_is_not_ready(self):
        self.interactive()
        with patch.object(a, "diagnose", return_value=diagnosis(["ovmf"])), \
                patch("builtins.input", return_value="s"), patch.object(a, "terminal_command"):
            self.assertEqual(a.main(self.root, []), 40)
        self.assertEqual(self.report()["failure"]["stage"], "appliance-host-check")

    def test_terminal_child_inherits_stdio_and_records_exit_not_password(self):
        session = b.Session(self.root)
        command = ["/usr/bin/sudo", "--", "/usr/bin/apt-get", "update", "--error-on=any"]
        with patch.object(a.subprocess, "run", return_value=subprocess.CompletedProcess(command, 0)) as child:
            a.terminal_command(session, command)
            child.assert_called_once_with(command, cwd="/", check=False)
        step = self.report()["steps"][0]
        self.assertEqual(step["returncode"], 0)
        self.assertEqual(step["io"], "inherited-terminal")
        self.assertNotIn("stdout", step)
        self.assertNotIn("stdin", step)

    def test_terminal_child_failure_and_interrupt_are_recorded(self):
        for error in (None, KeyboardInterrupt()):
            with self.subTest(interrupt=error is not None), tempfile.TemporaryDirectory() as root:
                session = b.Session(root)
                with patch.object(a.subprocess, "run", side_effect=error,
                                  return_value=subprocess.CompletedProcess(["sudo"], 1)):
                    with self.assertRaises(KeyboardInterrupt if error else b.BootstrapError):
                        a.terminal_command(session, ["/usr/bin/sudo", "--", "/usr/bin/apt-get", "update"])
                self.assertIn("seconds", session.report["steps"][0])

    def test_catalog_rejects_arbitrary_packages_and_shell_fragments(self):
        for values in ([], ["ovmf; reboot"], ["--allow-unauthenticated"], ["curl"]):
            with self.assertRaises(ValueError):
                a.installation_commands(values)

    def test_diagnosis_distinguishes_installed_package_from_missing_tool_or_firmware(self):
        session = b.Session(self.root)
        raw = "\n".join(f"{name}\tinstall ok installed\t1.0" for name in a.PACKAGES)
        with patch.object(a, "os_release", return_value={"ID": "ubuntu"}), \
                patch.object(a.platform, "system", return_value="Linux"), \
                patch.object(a.platform, "machine", return_value="x86_64"), \
                patch.object(a.os, "geteuid", return_value=1000), \
                patch.object(a.shutil, "which", side_effect=lambda name, **kw: None if name == "qemu-img" else "/usr/bin/" + name), \
                patch.object(a.os, "access", return_value=False), patch.object(session, "command", return_value=raw):
            result = a.diagnose(session)
        self.assertEqual(result["missing_packages"], ["qemu-utils", "ovmf"])

    def test_unsupported_host_stops_before_any_package_command(self):
        session = b.Session(self.root)
        with patch.object(a, "os_release", return_value={"ID": "fedora"}), patch.object(session, "command") as command:
            with self.assertRaises(b.BootstrapError):
                a.diagnose(session)
            command.assert_not_called()

    def test_partial_dpkg_query_and_namespace_failure_are_reported(self):
        session = b.Session(self.root)
        def command(stage, args, **kwargs):
            if stage == "appliance-packages":
                (session.directory / "packages.log").write_text("ovmf\thold ok installed\t1.0\n")
                session.report["steps"].append({"returncode": 1, "stdout": "packages.log"})
                raise b.BootstrapError(stage, "some packages absent", "inspect")
            raise b.BootstrapError(stage, "namespace denied", "inspect")
        with patch.object(a, "os_release", return_value={"ID": "debian"}), \
                patch.object(a.platform, "system", return_value="Linux"), \
                patch.object(a.platform, "machine", return_value="x86_64"), \
                patch.object(a.os, "geteuid", return_value=1000), \
                patch.object(a.shutil, "which", side_effect=lambda name, **kw: "/usr/bin/" + name), \
                patch.object(a.os, "access", return_value=True), patch.object(session, "command", side_effect=command):
            result = a.diagnose(session)
        self.assertNotIn("ovmf", result["missing_packages"])
        self.assertIn("mmdebstrap", result["missing_packages"])
        self.assertFalse(result["rootfs_namespace_probe"]["available"])
        self.assertEqual(result["installed_versions"]["ovmf"], "1.0")

    def test_probe_timeout_and_failed_executable_do_not_claim_success(self):
        with patch.object(a, "diagnose", return_value=diagnosis()), \
                patch.object(b.Session, "command", side_effect=b.BootstrapError("version", "probe timeout", "inspect")):
            self.assertEqual(a.main(self.root, []), 40)
        self.assertEqual(self.report()["status"], "FAILED")

    def test_existing_bootstrap_lock_prevents_installation(self):
        with b.locked(self.root / ".gaia/bootstrap.lock"), patch.object(a, "diagnose") as probe, \
                patch.object(a, "terminal_command") as install:
            self.assertEqual(a.main(self.root, []), 40)
            probe.assert_not_called()
            install.assert_not_called()

    def test_mmdebstrap_profile_can_work_when_generic_unshare_is_denied(self):
        session = b.Session(self.root)
        commands = []
        raw = "\n".join(f"{name}\tinstall ok installed\t1.0" for name in a.PACKAGES)
        def command(stage, args, **kwargs):
            commands.append((stage, args))
            if stage == "appliance-packages":
                return raw
            if stage == "appliance-userns":
                raise b.BootstrapError(stage, "generic denied", "inspect")
            if stage == "appliance-media-inventory":
                return '{"blockdevices": []}'
            return ""
        with patch.object(a, "os_release", return_value={"ID": "ubuntu"}), \
                patch.object(a.platform, "system", return_value="Linux"), \
                patch.object(a.platform, "machine", return_value="x86_64"), \
                patch.object(a.os, "geteuid", return_value=1000), \
                patch.object(a.shutil, "which", side_effect=lambda name, **kw: "/usr/bin/" + name), \
                patch.object(a.os, "access", return_value=True), patch.object(session, "command", side_effect=command):
            result = a.diagnose(session)
        probe = result["rootfs_namespace_probe"]
        self.assertTrue(probe["available"])
        self.assertFalse(probe["generic_probe"]["available"])
        self.assertEqual(probe["mode"], "mmdebstrap-unshare")
        helper = next(args for stage, args in commands if stage == "appliance-mmdebstrap-userns")
        self.assertEqual(helper, ["/usr/bin/mmdebstrap", "--unshare-helper", "/usr/bin/unshare", "--mount", "/usr/bin/true"])


if __name__ == "__main__":
    unittest.main()
