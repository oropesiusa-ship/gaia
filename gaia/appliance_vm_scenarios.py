"""Bounded boot-selection scenarios on qcow2 overlays, never physical media."""
import json
from pathlib import Path
import re
import shutil
import tempfile

from .appliance_image import pe_section, qemu_command, replace_pe_section, vm_result
from .appliance_rootfs import sha256
from .appliance_image_build import new_file

SCENARIOS = ("normal-A", "normal-B", "attempt-exhaustion", "interrupted-publication", "corrupted-B", "data-recovery",
             "publication-interrupted", "health-bless", "health-reject", "usb-smoke")
COUNTED = ("attempt-exhaustion", "corrupted-B", "health-bless", "health-reject")


def extract_esp(session, tools, overlay, target, part):
    # qemu-img dd versions that cap the input at count*bs subtract skip from
    # the effective output count. Read through the absolute end, then bound the
    # output explicitly (also correct on versions with normal dd semantics).
    session.command("read-esp", [tools["qemu-img"], "dd", "-f", "qcow2", "-O", "raw", "bs=512",
        "skip=" + str(part["start"]), "count=" + str(part["start"] + part["sectors"]),
        "if=" + str(overlay), "of=" + str(target)], timeout=120)
    if target.is_symlink() or not target.is_file() or target.stat().st_size < part["bytes"]:
        raise ValueError("Truncated ESP extraction")
    with target.open("r+b") as stream:
        stream.truncate(part["bytes"])


def prepare_esp(session, tools, original, output, scenario):
    # Avoid an uncounted Type-2 UKI being selected alongside its counted Type-1
    # entry. Both UKIs live under EFI/GAIA, not the auto-discovered EFI/Linux.
    if original.get("uki_directory", "EFI/Linux") == "EFI/Linux":
        session.command("isolate-uki-entries", [tools["mren"], "-i", str(output), "::/EFI/Linux", "::/EFI/GAIA"])
    for slot in ("a", "b"):
        entry = session.directory / f"{scenario}-{slot}.conf"
        version = 2 if scenario in COUNTED and slot == "b" else 1
        entry.write_text(f"title GAIA lab slot {slot.upper()}\nversion {version}\nefi /EFI/GAIA/gaia-{slot}.efi\n")
        session.command("configure-entry", [tools["mcopy"], "-o", "-i", str(output), str(entry), f"::/loader/entries/gaia-{slot}.conf"])
    default = "gaia-a.conf" if scenario in ("normal-A", "interrupted-publication", "data-recovery", "publication-interrupted", "usb-smoke") else "gaia-b*"
    if scenario in COUNTED:
        # A candidate-only glob keeps selecting even the exhausted entry. The
        # known-good slot must participate in selection, with the newer version
        # preferred only while its boot counter remains usable.
        default = "gaia-*"
    loader = session.directory / f"{scenario}-loader.conf"
    loader.write_text(f"default {default}\ntimeout 0\neditor no\nauto-entries no\nauto-firmware no\n")
    session.command("configure-loader", [tools["mcopy"], "-o", "-i", str(output), str(loader), "::/loader/loader.conf"])
    if scenario in COUNTED:
        session.command("count-candidate", [tools["mren"], "-i", str(output), "::/loader/entries/gaia-b.conf", "::/loader/entries/gaia-b+3.conf"])
    if scenario == "interrupted-publication":
        partial = session.directory / "incomplete-candidate"
        partial.write_bytes(b"Interrupted lab publication; not an executable image")
        session.command("partial-uki", [tools["mcopy"], "-i", str(output), str(partial), "::/EFI/GAIA/gaia-b.efi.tmp"])
        session.command("partial-entry", [tools["mcopy"], "-i", str(output), str(partial), "::/loader/entries/gaia-b.conf.tmp"])
        # The known-good A UKI must remain byte-identical.
        preserved = session.directory / "preserved-a.efi"
        preserved.unlink(missing_ok=True)
        session.command("check-good-uki", [tools["mcopy"], "-i", str(output), "::/EFI/GAIA/gaia-a.efi", str(preserved)])
        if sha256(preserved) != original["uki_sha256"]["A"]:
            raise ValueError("Interrupted publication changed known-good UKI")
    expected_ukis = dict(original["uki_sha256"])
    selected = "b" if scenario in ("health-bless", "health-reject") else "a"
    for slot in ("a", "b"):
        flags = " gaia.mode=vm-test" if original.get("delivery_candidate") else ""
        if slot == selected and scenario in ("data-recovery", "publication-interrupted", "health-bless", "health-reject", "usb-smoke"):
            flags += " gaia.scenario=" + scenario
        if flags:
            staged = session.directory.resolve() / f"{scenario}-source-{slot}.efi"
            staged.unlink(missing_ok=True)
            session.command("read-scenario-uki", [tools["mcopy"], "-i", str(output), f"::/EFI/GAIA/gaia-{slot}.efi", str(staged)])
            if sha256(staged) != original["uki_sha256"][slot.upper()]:
                raise ValueError("Scenario UKI does not match source identity")
            cmdline = pe_section(staged, ".cmdline").rstrip(b"\0") + flags.encode() + b"\0"
            cmdfile = session.directory.resolve() / f"{scenario}-{slot}.cmdline"
            cmdfile.write_bytes(cmdline)
            revised = session.directory.resolve() / f"{scenario}-revised-{slot}.efi"
            revised.unlink(missing_ok=True)
            replace_pe_section(session, tools, staged, ".cmdline", cmdfile, revised, scenario + "-" + slot)
            session.command("stage-scenario-uki", [tools["mcopy"], "-o", "-i", str(output), str(revised), f"::/EFI/GAIA/gaia-{slot}.efi"])
            expected_ukis[slot.upper()] = sha256(revised)
    # -o controls DOS-side collisions, but Unix-side mcopy readbacks can still
    # ask interactively when the same scenario is prepared twice in a session.
    # Fresh output paths avoid prompts without overwriting diagnostic evidence.
    readbacks = Path(tempfile.mkdtemp(prefix=scenario + "-readbacks-", dir=session.directory.resolve()))
    for slot in ("a", "b"):
        readback = readbacks / f"gaia-{slot}.efi"
        session.command("verify-staged-uki-" + slot, [tools["mcopy"], "-i", str(output),
            f"::/EFI/GAIA/gaia-{slot}.efi", str(readback)])
        if sha256(readback) != expected_ukis[slot.upper()]:
            raise ValueError("Staged UKI is truncated or differs from its source: " + slot)
    return expected_ukis


def validate(session, directory, tools, repeats, scenarios=None):
    directory = directory.resolve()
    manifest = json.loads((directory / "image-manifest.json").read_text())
    disk = directory / "disk.raw"
    if disk.is_symlink() or not disk.is_file() or sha256(disk) != manifest["disk_sha256"]:
        raise ValueError("VM source image integrity mismatch")
    code = Path("/usr/share/OVMF/OVMF_CODE_4M.fd")
    template = Path("/usr/share/OVMF/OVMF_VARS_4M.fd")
    session.report.update(image_dir=str(directory), image_sha256=manifest["disk_sha256"], s1_complete=False,
        firmware={"code_sha256": sha256(code), "vars_template_sha256": sha256(template)})
    esp = next(p for p in manifest["partitions"] if p["name"] == "GAIA-ESP")
    results = []
    session.report["scenario_scope"] = list(scenarios or SCENARIOS)
    for scenario in session.report["scenario_scope"]:
        for repeat in range(1, repeats + 1):
            prefix = f"{scenario}-{repeat}"
            overlay = session.directory.resolve() / (prefix + ".qcow2")
            variables = session.directory.resolve() / (prefix + "-vars.fd")
            shutil.copyfile(template, variables)
            session.command("scenario-overlay", [tools["qemu-img"], "create", "-f", "qcow2", "-F", "raw", "-b", str(disk), str(overlay)])
            fat = session.directory.resolve() / (prefix + ".fat")
            extract_esp(session, tools, overlay, fat, esp)
            if sha256(fat) != esp["sha256"]:
                raise ValueError("Initial ESP extraction differs from source partition")
            staged_ukis = prepare_esp(session, tools, manifest, fat, scenario)
            session.command("stage-esp", [tools["qemu-io"], "-f", "qcow2", "-c",
                f"write -q -s {fat} {esp['start'] * 512} {esp['bytes']}", str(overlay)], timeout=120)
            if scenario == "corrupted-B":
                candidate = next(p for p in manifest["partitions"] if p["name"] == "GAIA-B")
                # Destroy the primary ext4 superblock of B in this overlay only.
                session.command("corrupt-candidate", [tools["qemu-io"], "-f", "qcow2", "-c",
                    f"write -q -z {candidate['start'] * 512 + 1024} 4096", str(overlay)])
            boots = []
            backup = None
            if scenario == "data-recovery":
                backup = session.directory.resolve() / (prefix + "-independent-backup.ext4")
                new_file(backup, 512 * 1024 * 1024)
                session.command("create-independent-backup", [tools["mkfs.ext4"], "-q", "-F", "-m", "0", "-L", "GAIA-BACKUP", str(backup)])
            slots = ["B", "B", "B", "A"] if scenario in ("attempt-exhaustion", "corrupted-B") else ["B" if scenario == "normal-B" else "A"]
            if scenario == "publication-interrupted":
                slots = ["A", "A"]
            if scenario == "health-bless":
                slots = ["B", "B"]
            if scenario == "health-reject":
                slots = ["B", "B", "B", "A"]
            for index, expected in enumerate(slots):
                command = qemu_command(tools, overlay, code, variables, usb_boot=scenario == "usb-smoke")
                if backup is not None:
                    command += ["-drive", f"if=none,id=gaia_backup,format=raw,file={backup},cache=none",
                                "-device", "virtio-blk-pci,drive=gaia_backup,serial=GAIA-LAB-BACKUP"]
                raw = session.command(prefix + f"-boot-{index + 1}", command,
                                      timeout=240, text_errors="replace")
                if scenario == "health-reject" and expected == "B":
                    if "GAIA_HEALTH_REJECTED=" not in raw or "GAIA_VM_RESULT=" in raw:
                        raise ValueError("Unhealthy candidate was not rejected before blessing")
                    result = {"status": "EXPECTED_HEALTH_GATE_FAILURE", "slot": "B"}
                elif scenario == "corrupted-B" and expected == "B":
                    if "gaia.slot=B" not in raw or "GAIA_VM_RESULT=" in raw or not re.search(
                            r"Failed to mount|mounting .*failed|bad superblock|bad magic", raw, re.IGNORECASE):
                        raise ValueError("Missing expected corrupted-root failure")
                    result = {"status": "EXPECTED_CORRUPTED_SLOT_FAILURE", "slot": "B"}
                else:
                    result = vm_result(raw)
                    if result.get("slot") != expected or not result.get("offline") or result["sandbox"]["status"] != "SANDBOX_CPU_OK":
                        raise ValueError("Unexpected guest evaluation in " + prefix)
                    expected_sequence = 1 if scenario == "corrupted-B" else (2 if scenario == "data-recovery" else index + 1)
                    if result["ledger_sequence"] != expected_sequence:
                        raise ValueError("Persistent evidence prefix did not survive normal reboot")
                    if scenario == "data-recovery":
                        recovery = result.get("data_recovery") or {}
                        if recovery.get("status") != "DATA_RESTORED" or not all(recovery.get(key) for key in (
                                "independent_backup_device", "backup_read_only_during_restore",
                                "tampered_backup_rejected_before_write", "logical_corruption_detected")):
                            raise ValueError("DATA backup/restore validation missing")
                        session.report.setdefault("data_backup_artifacts", []).append({"path": str(backup), "sha256": sha256(backup),
                            "manifest_sha256": recovery["manifest_sha256"], "fixture_sha256": recovery["fixture_sha256"]})
                    if scenario == "publication-interrupted":
                        publication = result.get("publication") or {}
                        if publication.get("status") != "INTERRUPTED_PUBLICATION_SAFE" or publication["sequence"] != index + 1:
                            raise ValueError("Actual interrupted publication was not verified")
                        if index and publication["active_a_sha256"] != boots[0]["publication"]["active_a_sha256"]:
                            raise ValueError("Known-good UKI changed after interrupted publication reboot")
                    if scenario == "health-bless" and (result.get("health") or {}).get("status") != "HEALTHY_CANDIDATE_COMMITTED":
                        raise ValueError("Healthy candidate was not committed")
                    if scenario == "usb-smoke" and (result.get("usb_boot") or {}).get("status") != "USB_RECOVERY_BOOT_OK":
                        raise ValueError("Recovery did not boot from emulated USB")
                    if manifest.get("owner_public_trust_ready") and (result.get("owner_public_trust") or {}).get("status") != "OWNER_PUBLIC_SIGNATURE_OK":
                        raise ValueError("Guest did not verify the owner's signature")
                boots.append(result)
                if scenario in ("attempt-exhaustion", "corrupted-B", "health-reject", "health-bless"):
                    extract_esp(session, tools, overlay, fat, esp)
                    listing = session.command("check-boot-counter", [tools["mdir"], "-b", "-i", str(fat), "::/loader/entries"])
                    if scenario == "health-bless":
                        if "gaia-b.conf" not in listing.lower() or "gaia-b+" in listing.lower():
                            raise ValueError("Healthy entry still has an attempt counter")
                    else:
                        left, done = max(0, 2 - index), min(index + 1, 3)
                        if not re.search(rf"gaia-b\+{left}-{done}\.conf", listing, re.IGNORECASE):
                            raise ValueError("Unexpected systemd-boot attempt counter: " + listing)
            results.append({"scenario": scenario, "repeat": repeat, "boots": boots,
                            "staged_uki_sha256": staged_ukis, "status": "ok"})
            session.report["boot_scenarios"] = results
            session.save()
    if sha256(disk) != manifest["disk_sha256"]:
        raise ValueError("Scenario suite modified the source image")
    session.report["pending_s1"] = ["installation from recovery medium", "corrupted slot recovery",
        "DATA corruption and backup restoration", "release trust/signing and full CORE policy", "release toolchain removal"]
    session.finish("VM_BOOT_SELECTION_VALIDATED")
