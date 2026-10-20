"""Prepare an immutable, publicly verifiable VM installation signing request.

No signing/private-key operations. A fresh owner signature is required before
the recovery guest can write its explicitly identified virtual target.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil

from .appliance_rootfs import sha256
from .appliance_verify import fingerprint, regular_bytes
from .bootstrap import Session, locked, write_json
from .appliance_image import TOOLS, pe_section, qemu_command, replace_pe_section, run_runtime_guest, vm_result
from .appliance_image_build import new_file
from .appliance_vm_scenarios import extract_esp, prepare_esp


def parse_recovery_result(log):
    # printk may interrupt a /dev/console write at a character boundary. Remove
    # only the recognized block-partition notification, not arbitrary diagnostics
    # or malformed JSON. The complete validated record is still mandatory.
    log = re.sub(r"\[[ \t]*\d+\.\d+\][ \t]+(?:vd|sd)[a-z]+:(?:[ \t]+(?:vd|sd)[a-z]+\d+)+[ \t]*\r?\n", "", log)
    values = [json.loads(value) for value in re.findall(r"GAIA_RECOVERY_RESULT=(\{[^\r\n]*\})", log)]
    if len(values) != 1 or values[0].get("status") not in ("VM_IMAGE_INSTALLED", "VM_SYSTEM_REPAIRED"):
        raise ValueError("Recovery guest did not report one verified installation/repair")
    return values[0]


def boot_recovery_guest(session, tools, disk, manifest, target, bundle_disk, label, mode):
    code, template = Path("/usr/share/OVMF/OVMF_CODE_4M.fd"), Path("/usr/share/OVMF/OVMF_VARS_4M.fd")
    esp_part = manifest["partitions"][0]
    recovery = session.directory.resolve() / f"recovery-{label}.qcow2"
    variables = session.directory.resolve() / f"recovery-{label}-vars.fd"
    shutil.copyfile(template, variables)
    session.command("recovery-overlay", [tools["qemu-img"], "create", "-f", "qcow2", "-F", "raw", "-b", str(disk), str(recovery)])
    fat = session.directory.resolve() / f"recovery-{label}.fat"
    extract_esp(session, tools, recovery, fat, esp_part)
    if sha256(fat) != esp_part["sha256"]:
        raise ValueError("Recovery ESP extraction differs")
    prepare_esp(session, tools, manifest, fat, "normal-A")
    uki = session.directory.resolve() / f"recovery-{label}.efi"
    session.command("read-recovery-uki", [tools["mcopy"], "-i", str(fat), "::/EFI/GAIA/gaia-a.efi", str(uki)])
    commandline = pe_section(uki, ".cmdline").rstrip(b"\0").decode()
    commandline = re.sub(r"root=\S+", "root=/dev/sda3", commandline)
    commandline += (' gaia.scenario=usb-install gaia.recovery=' + mode + ' fstab=no systemd.gpt_auto=no'
        ' systemd.mask=gaia-vm-probe.service systemd.run="/usr/bin/mount -o ro,noload /dev/sda2 /core"'
        ' systemd.run="/opt/gaia/venv/bin/python -I /core/recovery_install.py"'
        ' systemd.run_success_action=poweroff systemd.run_failure_action=poweroff loglevel=3 systemd.show_status=no')
    cmdfile = session.directory.resolve() / f"recovery-{label}.cmdline"
    cmdfile.write_bytes(commandline.encode() + b"\0")
    revised = session.directory.resolve() / f"recovery-{label}-revised.efi"
    replace_pe_section(session, tools, uki, ".cmdline", cmdfile, revised, f"recovery-{label}")
    session.command("stage-recovery-uki", [tools["mcopy"], "-o", "-i", str(fat), str(revised), "::/EFI/GAIA/gaia-a.efi"])
    readback = session.directory.resolve() / f"recovery-{label}-readback.efi"
    session.command("verify-recovery-uki", [tools["mcopy"], "-i", str(fat), "::/EFI/GAIA/gaia-a.efi", str(readback)])
    if sha256(readback) != sha256(revised):
        raise ValueError("Recovery UKI readback differs")
    session.command("stage-recovery-esp", [tools["qemu-io"], "-f", "qcow2", "-c",
        f"write -q -s {fat} {esp_part['start'] * 512} {esp_part['bytes']}", str(recovery)], timeout=120)
    command = qemu_command(tools, recovery, code, variables, usb_boot=True)
    command += ["-drive", f"if=none,id=install_target,format=qcow2,file={target},cache=none,discard=unmap,detect-zeroes=unmap",
        "-device", "virtio-blk-pci,drive=install_target,serial=GAIA-LAB-TARGET",
        "-drive", f"if=none,id=install_bundle,format=raw,file={bundle_disk},readonly=on,cache=none",
        "-device", "virtio-blk-pci,drive=install_bundle,serial=GAIA-LAB-BUNDLE"]
    return session.command("usb-recovery-" + label, command, timeout=1800, text_errors="replace")


def negative_guest_check(session, image_dir, repeats=3):
    image_dir = image_dir.resolve()
    manifest = json.loads(regular_bytes(image_dir / "image-manifest.json", 2 * 1024 * 1024))
    disk = image_dir / "disk.raw"
    if disk.is_symlink() or not disk.is_file() or sha256(disk) != manifest["disk_sha256"]:
        raise ValueError("Recovery source integrity mismatch")
    tools = {name: shutil.which(name) for name in TOOLS}
    if not all(tools.values()):
        raise ValueError("Missing VM tools")
    data = session.directory.resolve() / "invalid-bundle"
    data.mkdir()
    (data / "install-manifest.json").write_text('{"schema":"gaia-signed-artifacts-v1","purpose":"lab","deliberately":"not the signed custody challenge"}\n')
    shutil.copyfile(session.root / "keys/gaia-custody-backup-check.json.asc", data / "install-manifest.json.asc")
    bundle = session.directory.resolve() / "invalid-bundle.ext4"
    new_file(bundle, 32 * 1024 * 1024)
    session.command("invalid-bundle-filesystem", [tools["mkfs.ext4"], "-q", "-F", "-m", "0", "-d", str(data), str(bundle)])
    zero = session.directory.resolve() / "zero.raw"
    new_file(zero, manifest["disk_bytes"])
    results = []
    for repeat in range(1, repeats + 1):
        target = session.directory.resolve() / f"unchanged-target-{repeat}.qcow2"
        session.command("blank-negative-target", [tools["qemu-img"], "create", "-f", "qcow2", str(target), str(manifest["disk_bytes"])])
        log = boot_recovery_guest(session, tools, disk, manifest, target, bundle, f"negative-signature-{repeat}", "install")
        errors = [json.loads(raw) for raw in re.findall(r"GAIA_RECOVERY_ERROR=(\{[^\r\n]*\})", log)]
        if len(errors) != 1 or "Public signature rejected by sqv" not in errors[0]["reason"] or "GAIA_RECOVERY_RESULT=" in log:
            raise ValueError("Expected native signature rejection was not observed")
        session.command("target-remained-zero", [tools["qemu-img"], "compare", "-f", "qcow2", "-F", "raw", str(target), str(zero)], timeout=180)
        results.append({"repeat": repeat, "signature_rejected": True, "target_unchanged": True})
        session.report["negative_recovery_results"] = results
        session.save()
    session.report.update(signature_rejected_in_guest=True, target_unchanged=True, private_key_used=False,
        image_sha256=manifest["disk_sha256"], s1_complete=False, physical_media_written=False)
    session.finish("VM_INVALID_INSTALL_SIGNATURE_REJECTED")


def checkpoint_target(session, previous_dir, previous, manifest, repeat, tools):
    target = Path(previous.get("target_locations", {}).get(str(repeat), str(previous_dir / f"target-{repeat}.qcow2")))
    if not target.resolve().is_relative_to((session.root / ".gaia/reports").resolve()):
        raise ValueError("Checkpoint target must remain inside local reports")
    if (target.is_symlink() or not target.is_file() or target.stat().st_uid != os.getuid()
            or target.stat().st_mtime > previous["finished"] + 2):
        raise ValueError("Checkpoint target changed after the failed run")
    info = json.loads(session.command("resume-target-info", [tools["qemu-img"], "info", "--output=json", str(target)]))
    if info["format"] != "qcow2" or info["virtual-size"] != manifest["disk_bytes"] or info.get("backing-filename"):
        raise ValueError("Unexpected resumed target format/geometry/backing")
    return target


def resume_checkpoint(session, previous_dir, manifest, repeats, tools, source_disk=None):
    previous_dir = previous_dir.resolve(strict=True)
    if not previous_dir.is_relative_to((session.root / ".gaia/reports").resolve()):
        raise ValueError("Resume checkpoint must be a local GAIA report")
    previous = json.loads(regular_bytes(previous_dir / "report.json", 4 * 1024 * 1024))
    if (previous.get("status") != "FAILED" or previous.get("recovery_image_sha256") != manifest["disk_sha256"]
            or previous.get("manifest_sha256") != session.report["manifest_sha256"]
            or previous.get("signature_sha256") != session.report["signature_sha256"]
            or previous.get("expected_fingerprint") != session.report["expected_fingerprint"]):
        raise ValueError("Resume checkpoint identity/signature mismatch")
    completed = previous.get("recovery_results", [])
    order = [(n, mode) for n in range(1, repeats + 1) for mode in ("install", "repair-system")]
    actual = [(row["repeat"], row["mode"]) for row in completed]
    if not completed or actual != order[:len(actual)] or len(actual) >= len(order):
        raise ValueError("Resume checkpoint is not a completed prefix of this suite")
    for row in completed:
        expected_status = "VM_IMAGE_INSTALLED" if row["mode"] == "install" else "VM_SYSTEM_REPAIRED"
        if (row["recovery"].get("status") != expected_status
                or row["recovery"].get("fingerprint") != session.report["expected_fingerprint"]
                or row["installed_boot"].get("status") not in ("VM_FOUNDATION_OK", "GAIA_RUNTIME_READY")):
            raise ValueError("Unverified result in resume prefix")
    cached_bundle = Path(previous.get("bundle_disk", str(previous_dir / "bundle.ext4")))
    if not cached_bundle.resolve().is_relative_to((session.root / ".gaia/reports").resolve()):
        raise ValueError("Cached bundle must remain inside local reports")
    if (cached_bundle.is_symlink() or not cached_bundle.is_file()
            or sha256(cached_bundle) != previous["bundle_disk_sha256"]):
        raise ValueError("Cached read-only bundle changed")
    target = None
    next_repeat, next_mode = order[len(actual)]
    last = previous.get("steps", [{}])[-1]
    if (source_disk is not None and next_mode == "install" and last.get("stage") == f"usb-recovery-{next_repeat}-install"
            and last.get("returncode") == 0):
        # A guest can finish successfully but its console record be interleaved.
        # Recover only after a whole-device comparison and an independent boot.
        if Path(last["stdout"]).name != last["stdout"]:
            raise ValueError("Invalid checkpoint log path")
        installed = parse_recovery_result((previous_dir / last["stdout"]).read_text(errors="replace"))
        if (installed["status"] != "VM_IMAGE_INSTALLED" or installed.get("disk_sha256") != manifest["disk_sha256"]
                or installed.get("fingerprint") != session.report["expected_fingerprint"]):
            raise ValueError("Incomplete guest installation does not match signed image")
        target = checkpoint_target(session, previous_dir, previous, manifest, next_repeat, tools)
        session.command("recover-installed-target-readback", [tools["qemu-img"], "compare", "-f", "qcow2", "-F", "raw",
            str(target), str(source_disk)], timeout=300)
        code, template = Path("/usr/share/OVMF/OVMF_CODE_4M.fd"), Path("/usr/share/OVMF/OVMF_VARS_4M.fd")
        variables = session.directory.resolve() / f"recovered-install-{next_repeat}-vars.fd"
        shutil.copyfile(template, variables)
        if manifest.get("delivery_candidate"):
            boot = run_runtime_guest(session, tools, target, code, variables, f"recovered-install-{next_repeat}")
        else:
            raw = session.command("recover-installed-boot", qemu_command(tools, target, code, variables), timeout=240, text_errors="replace")
            boot = vm_result(raw)
        if boot["slot"] != "A" or boot["ledger_sequence"] != 1 or (boot.get("owner_public_trust") or {}).get("status") != "OWNER_PUBLIC_SIGNATURE_OK":
            raise ValueError("Recovered install failed its independent boot")
        completed.append({"repeat": next_repeat, "mode": "install", "recovery": installed, "installed_boot": boot,
                          "recovered_from_interleaved_console": True})
        session.report["recovered_pending_install"] = next_repeat
        next_repeat, next_mode = order[len(completed)]
    if next_mode == "repair-system":
        if target is None:
            target = checkpoint_target(session, previous_dir, previous, manifest, next_repeat, tools)
    session.report.update(resumed_from=str(previous_dir), inherited_recovery_results=len(completed),
        recovery_results=completed, bundle_disk_sha256=previous["bundle_disk_sha256"])
    return cached_bundle, target, completed


def run_install_suite(session, image_dir, bundle, repeats, previous_dir=None):
    from .appliance_verify import verify
    image_dir, bundle = image_dir.resolve(), bundle.resolve()
    manifest = json.loads(regular_bytes(image_dir / "image-manifest.json", 2 * 1024 * 1024))
    disk = image_dir / "disk.raw"
    expected = fingerprint(regular_bytes(session.root / "keys/gaia-release-signing.fingerprint.txt", 1024).decode().strip())
    verify(session, session.root / "keys/gaia-release-signing.pub.gpg", expected,
        bundle / "install-manifest.json", bundle / "install-manifest.json.asc", bundle, "lab", finish_report=False)
    record = json.loads((bundle / "install-manifest.json").read_text())
    if (record.get("kind") != "gaia-vm-install-bundle-v1" or record.get("target_serial") != "GAIA-LAB-TARGET"
            or sha256(disk) != manifest["disk_sha256"]
            or sha256(bundle / "disk.raw") != manifest["disk_sha256"]
            or sha256(bundle / "image-manifest.json") != sha256(image_dir / "image-manifest.json")):
        raise ValueError("Signed bundle differs from the tested recovery image")
    tools = {name: shutil.which(name) for name in TOOLS}
    if not all(tools.values()):
        raise ValueError("Missing VM construction tools")
    resumed_target, results = None, []
    if previous_dir is not None:
        bundle_disk, resumed_target, results = resume_checkpoint(session, previous_dir, manifest, repeats, tools, disk)
        allocated = resumed_target.stat().st_blocks * 512 if resumed_target else 0
        budget = max(0, manifest["disk_bytes"] - allocated) + 4 * 1024**3
        if shutil.disk_usage(session.root).free < budget:
            raise ValueError("Insufficient workspace to complete the resumed disposable target")
    else:
        bundle_size = ((manifest["disk_bytes"] * 115 // 100 + 1024**3 - 1) // 1024**3) * 1024**3
        if shutil.disk_usage(session.root).free < bundle_size + manifest["disk_bytes"] + 4 * 1024**3:
            raise ValueError("Insufficient workspace for independent bundle and disposable target; preserve logs and reclaim obsolete VM disks first")
        staging = session.directory.resolve() / "bundle-files"
        staging.mkdir()
        for name in ("disk.raw", "image-manifest.json", "install-manifest.json", "install-manifest.json.asc"):
            source = bundle / name
            if source.is_symlink() or not source.is_file():
                raise ValueError("Bundle entries must be regular files")
            os.link(source, staging / name)
        bundle_disk = session.directory.resolve() / "bundle.ext4"
        new_file(bundle_disk, bundle_size)
        session.command("bundle-filesystem", [tools["mkfs.ext4"], "-q", "-F", "-m", "0", "-L", "GAIA-BUNDLE", "-d", str(staging), str(bundle_disk)], timeout=1200)
        session.command("bundle-filesystem-check", [tools["e2fsck"], "-f", "-n", str(bundle_disk)])
    code, template = Path("/usr/share/OVMF/OVMF_CODE_4M.fd"), Path("/usr/share/OVMF/OVMF_VARS_4M.fd")
    session.report.update(recovery_image_sha256=manifest["disk_sha256"], bundle_disk_sha256=sha256(bundle_disk), bundle_disk=str(bundle_disk),
        scenario_scope=["usb-install", "usb-repair-system"], s1_complete=False, physical_media_written=False)
    completed = {(row["repeat"], row["mode"]) for row in results}
    for repeat in range(1, repeats + 1):
        if (repeat, "repair-system") in completed:
            continue
        if (repeat, "install") in completed:
            if resumed_target is None:
                raise ValueError("Missing target for the verified install prefix")
            target = resumed_target
        else:
            target = session.directory.resolve() / f"target-{repeat}.qcow2"
            session.command("blank-lab-target", [tools["qemu-img"], "create", "-f", "qcow2", str(target), str(manifest["disk_bytes"])])
        session.report.setdefault("target_locations", {})[str(repeat)] = str(target)
        session.save()
        for mode in ("install", "repair-system"):
            if (repeat, mode) in completed:
                continue
            if mode == "repair-system":
                root_b = next(part for part in manifest["partitions"] if part["name"] == "GAIA-B")
                session.command("damage-installed-candidate", [tools["qemu-io"], "-f", "qcow2", "-c",
                    f"write -q -z {root_b['start'] * 512 + 1024} 4096", str(target)])
            log = boot_recovery_guest(session, tools, disk, manifest, target, bundle_disk, f"{repeat}-{mode}", mode)
            installed = parse_recovery_result(log)
            expected_status = "VM_IMAGE_INSTALLED" if mode == "install" else "VM_SYSTEM_REPAIRED"
            if installed["status"] != expected_status or installed["fingerprint"] != expected:
                raise ValueError("Incorrect recovery status/identity")
            variables2 = session.directory.resolve() / f"installed-{repeat}-{mode}-vars.fd"
            shutil.copyfile(template, variables2)
            if manifest.get("delivery_candidate"):
                boot = run_runtime_guest(session, tools, target, code, variables2, f"installed-{repeat}-{mode}")
            else:
                boot_log = session.command(f"installed-boot-{repeat}-{mode}", qemu_command(tools, target, code, variables2),
                                           timeout=240, text_errors="replace")
                boot = vm_result(boot_log)
            if boot["slot"] != "A" or (boot.get("owner_public_trust") or {}).get("status") != "OWNER_PUBLIC_SIGNATURE_OK":
                raise ValueError("Installed image did not pass independent boot without the recovery USB")
            if mode == "repair-system" and (not installed.get("data_preserved") or boot["ledger_sequence"] != 2):
                raise ValueError("OS repair lost persistent DATA evidence")
            results.append({"repeat": repeat, "mode": mode, "recovery": installed, "installed_boot": boot})
            session.report["recovery_results"] = results
            session.save()
        if repeat < repeats:
            # Only this freshly created disposable target is reclaimed. Logs,
            # signatures, hashes and the last recovered target remain available.
            target.unlink()
            session.report.setdefault("discarded_successful_targets", []).append(str(target.relative_to(session.root.resolve())))
            session.save()
    if sha256(disk) != manifest["disk_sha256"]:
        raise ValueError("Recovery tests modified the source image")
    session.finish("VM_SIGNED_RECOVERY_VALIDATED")


def prepare_request(session, image_dir):
    image_dir = image_dir.resolve()
    disk, original = image_dir / "disk.raw", image_dir / "image-manifest.json"
    image = json.loads(regular_bytes(original, 2 * 1024 * 1024))
    if (disk.is_symlink() or not disk.is_file() or disk.stat().st_size != image["disk_bytes"]
            or sha256(disk) != image["disk_sha256"] or not image.get("owner_public_trust_ready")):
        raise ValueError("Requires a verified lab image with owner public trust embedded")
    expected = fingerprint(regular_bytes(session.root / "keys/gaia-release-signing.fingerprint.txt", 1024).decode().strip())
    if image["owner_fingerprint"] != expected:
        raise ValueError("Image owner differs from pinned identity")
    directory = session.directory.resolve() / "install-bundle"
    directory.mkdir()
    # Same-filesystem hardlink: no multi-GiB duplicate. Never mutate it later.
    os.link(disk, directory / "disk.raw")
    (directory / "image-manifest.json").write_bytes(original.read_bytes())
    entries = [{"name": p.name, "bytes": p.stat().st_size, "sha256": sha256(p)}
               for p in (directory / "disk.raw", directory / "image-manifest.json")]
    record = {"schema": "gaia-signed-artifacts-v1", "purpose": "lab", "kind": "gaia-vm-install-bundle-v1",
        "signing_fingerprint": expected, "target_serial": "GAIA-LAB-TARGET", "target_bytes": image["disk_bytes"],
        "artifacts": entries}
    write_json(directory / "install-manifest.json", record)
    session.report.update(image_dir=str(image_dir), image_sha256=image["disk_sha256"],
        signing_request=str(directory / "install-manifest.json"), manifest_sha256=sha256(directory / "install-manifest.json"),
        expected_signature=str(directory / "install-manifest.json.asc"), expected_fingerprint=expected,
        purpose="lab", private_key_used=False, installation_executed=False, s1_complete=False)
    session.finish("AWAITING_OWNER_VM_INSTALL_SIGNATURE")


def main(root, args):
    parser = argparse.ArgumentParser(prog="gaia.py appliance-recovery", description=__doc__)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, help="owner-signed install bundle; absent prepares a request only")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--negative-check", action="store_true", help="USB guest rejects an unrelated signature without writing the target")
    parser.add_argument("--resume-report", type=Path, help="reuse verified bundle/target and completed prefix from a failed local suite")
    options = parser.parse_args(args)
    if options.negative_check and options.bundle_dir:
        parser.error("--negative-check cannot consume a signed bundle")
    if options.resume_report and not options.bundle_dir:
        parser.error("--resume-report requires --bundle-dir")
    session = Session(root)
    session.report["request"] = {"command": "appliance-recovery"}
    try:
        with locked(Path(root) / ".gaia/bootstrap.lock"):
            if options.negative_check:
                negative_guest_check(session, options.image_dir, options.repeats)
            elif options.bundle_dir:
                run_install_suite(session, options.image_dir, options.bundle_dir, options.repeats, options.resume_report)
            else:
                prepare_request(session, options.image_dir)
        return 0 if options.bundle_dir or options.negative_check else 10
    except KeyboardInterrupt as exc:
        session.finish("INTERRUPTED", exc)
        return 130
    except Exception as exc:
        session.finish("FAILED", exc)
        return 40
