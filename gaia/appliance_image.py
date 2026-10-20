"""Build and boot disposable S1 UEFI images from a verified runtime rootfs.

VM-only foundation, not a signed release or a completed S1 acceptance suite.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import tarfile
import struct
import uuid
import sys

from .appliance_rootfs import PROFILE, inspect_rootfs, select_tmpdir, sha256
from .bootstrap import BootstrapError, Session, locked, write_json

MIB = 1024 ** 2
GIB = 1024 ** 3
TOOLS = ("mmdebstrap", "mkfs.ext4", "e2fsck", "sfdisk", "objcopy", "mformat", "mmd", "mcopy",
         "tar", "chroot", "qemu-img", "qemu-system-x86_64", "qemu-io", "debugfs", "cp", "mren", "mdir")


def verified_source(manifest_path):
    manifest_path = manifest_path.resolve(strict=True)
    if not manifest_path.is_file():
        raise ValueError("Rootfs manifest must be a regular file")
    manifest = json.loads(manifest_path.read_text())
    source = manifest_path.parent / "rootfs.tar"
    if source.is_symlink() or not source.is_file():
        raise ValueError("Rootfs must be a regular non-symlink file")
    if manifest.get("status") != "DEBIAN_RUNTIME_ROOTFS_BUILT":
        raise ValueError("Requires the completed runtime rootfs")
    if source.stat().st_size != manifest["rootfs_bytes"] or sha256(source) != manifest["rootfs_sha256"]:
        raise ValueError("Rootfs integrity mismatch")
    contents = inspect_rootfs(source)
    if any(contents[key] != manifest.get(key) for key in contents):
        raise ValueError("Rootfs inventory does not match manifest")
    if contents["runtime"]["status"] != "GAIA_RUNTIME_CPU_SMOKE_OK" or contents["runtime"]["uid"] == 0:
        raise ValueError("Requires a non-root CPU smoke")
    if len(contents["kernels"]) != 1 or len(contents["initramfs"]) != 1:
        raise ValueError("Ambiguous kernel/initramfs selection")
    return source, manifest


def partition_spec(rootfs_bytes):
    # Initial VM DATA is small, not a proposed physical appliance capacity.
    root_size = ((rootfs_bytes * 13 // 10 + 512 * MIB + GIB - 1) // GIB) * GIB
    linux = "0fc63daf-8483-4772-8e79-3d69d8477de4"
    return [{"name": name, "bytes": size, "uuid": str(uuid.uuid4()), "type": kind}
            for name, size, kind in (("GAIA-ESP", 256 * MIB, "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"),
                ("GAIA-CORE", 32 * MIB, linux), ("GAIA-A", root_size, linux),
                ("GAIA-B", root_size, linux), ("GAIA-DATA", 512 * MIB, linux))]


def qemu_command(tools, overlay, code, variables, usb_boot=False):
    command = [tools["qemu-system-x86_64"], "-machine", "q35,accel=kvm", "-cpu", "host", "-smp", "2", "-m", "3072",
        "-drive", f"if=pflash,format=raw,readonly=on,file={code}",
        "-drive", f"if=pflash,format=raw,file={variables}"]
    if usb_boot:
        command += ["-device", "qemu-xhci,id=gaia_usb", "-drive", f"if=none,id=recovery,format=qcow2,file={overlay},cache=none",
                    "-device", "usb-storage,drive=recovery,bootindex=1,serial=GAIA-LAB-RECOVERY"]
    else:
        command += ["-drive", f"if=virtio,format=qcow2,file={overlay},cache=none"]
    return command + [
        "-nic", "user,model=virtio-net-pci,restrict=on", "-display", "none", "-serial", "stdio", "-monitor", "none",
        "-no-reboot", "-sandbox", "on,obsolete=deny,elevateprivileges=deny,spawn=deny,resourcecontrol=deny"]


def vm_result(log):
    results = [json.loads(match) for match in re.findall(r"GAIA_VM_RESULT=(\{[^\r\n]*\})", log)]
    if len(results) != 1 or results[0].get("status") != "VM_FOUNDATION_OK":
        raise ValueError("Missing unique successful guest evaluation; inspect VM serial log")
    return results[0]


def pe_section_details(path, name):
    raw = path.read_bytes()
    pe = struct.unpack_from("<I", raw, 60)[0]
    if raw[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Invalid PE")
    count = struct.unpack_from("<H", raw, pe + 6)[0]
    optional = pe + 24
    if struct.unpack_from("<H", raw, optional)[0] != 0x20B:
        raise ValueError("Expected PE32+ UKI")
    image_base = struct.unpack_from("<Q", raw, optional + 24)[0]
    table = pe + 24 + struct.unpack_from("<H", raw, pe + 20)[0]
    for index in range(count):
        section = table + 40 * index
        if raw[section:section + 8].rstrip(b"\0").decode() == name:
            size = struct.unpack_from("<I", raw, section + 8)[0]
            address = struct.unpack_from("<I", raw, section + 12)[0]
            offset = struct.unpack_from("<I", raw, section + 20)[0]
            if offset + size > len(raw):
                raise ValueError("Truncated PE section")
            following = [struct.unpack_from("<I", raw, table + 40 * i + 12)[0] for i in range(count)]
            limit = min((value for value in following if value > address), default=2**32)
            return {"contents": raw[offset:offset + size], "vma": image_base + address, "capacity": limit - address}
    raise ValueError("Missing PE section: " + name)


def pe_section(path, name):
    return pe_section_details(path, name)["contents"]


def replace_pe_section(session, tools, source, name, replacement, target, label):
    # objcopy --update-section can retain the old VirtualSize on PE images,
    # silently truncating a longer cmdline as seen by systemd-stub. Re-add it
    # at the same safe VMA and verify the bytes visible through the PE header.
    details = pe_section_details(source, name)
    data = replacement.read_bytes()
    if len(data) > details["capacity"]:
        raise ValueError("Replacement section would overlap the next PE section")
    stripped = session.directory.resolve() / ("pe-stripped-" + label + ".efi")
    session.command("pe-remove-" + label, [tools["objcopy"], "--remove-section", name, str(source), str(stripped)])
    session.command("pe-add-" + label, [tools["objcopy"], "--add-section", name + "=" + str(replacement),
        "--change-section-vma", name + "=" + hex(details["vma"]),
        "--set-section-flags", name + "=contents,alloc,load,readonly,data", str(stripped), str(target)])
    if pe_section(target, name) != data:
        raise ValueError("PE section replacement was truncated or corrupted")


def stage_payload(session):
    """Snapshot code and the already owner-pinned public proof, never custody."""
    from .appliance_verify import fingerprint, public_identity, public_packets, regular_bytes, valid_signature, verify_artifacts
    source = Path(__file__).with_name("appliance_vm_payload").resolve()
    payload = session.directory.resolve() / "staged-payload"
    payload.mkdir()
    for path in sorted(source.iterdir()):
        if path.is_file():
            shutil.copyfile(path, payload / path.name)
    keys = session.root / "keys"
    if not (keys / "gaia-release-signing.pub.gpg").exists():
        session.report["owner_public_trust_ready"] = False
        return payload
    expected = fingerprint(regular_bytes(keys / "gaia-release-signing.fingerprint.txt", 1024).decode().strip())
    key = public_packets(regular_bytes(keys / "gaia-release-signing.pub.gpg", 1024 * 1024))
    proof = regular_bytes(keys / "gaia-custody-backup-check.json", 4 * 1024 * 1024)
    signature = regular_bytes(keys / "gaia-custody-backup-check.json.asc", 1024 * 1024)
    home = session.directory.resolve() / "owner-public-only"
    home.mkdir(mode=0o700)
    public, manifest, signed = [payload / name for name in ("owner-public.pgp", "owner-proof.json", "owner-proof.asc")]
    public.write_bytes(key)
    manifest.write_bytes(proof)
    signed.write_bytes(signature)
    gpg, gpgv = shutil.which("gpg"), shutil.which("gpgv")
    if not gpg or not gpgv:
        raise ValueError("Public GnuPG verification tools missing")
    listing = session.command("owner-public-identity", [gpg, "--batch", "--no-options", "--homedir", str(home),
        "--no-auto-key-retrieve", "--no-auto-check-trustdb", "--with-colons", "--show-keys", str(public)])
    public_identity(listing, expected)
    status = session.command("owner-public-proof", [gpgv, "--homedir", str(home), "--status-fd", "1", "--keyring", str(public),
        "--", str(signed), str(manifest)])
    valid_signature(status, expected)
    verify_artifacts(proof, keys, expected, "lab")
    if json.loads(proof).get("kind") != "gaia-custody-backup-check-v1":
        raise ValueError("Expected the owner's custody proof, not an unrelated signature")
    write_json(payload / "owner-trust.json", {"fingerprint": expected,
        "public_key_sha256": sha256(public), "proof_manifest_sha256": sha256(manifest),
        "proof_signature_sha256": sha256(signed)})
    session.report.update(owner_public_trust_ready=True, owner_fingerprint=expected, private_key_used=False)
    return payload


def refresh_core(session, directory, tools):
    """Revision in a new regular image; keep both root slots and original intact."""
    from .appliance_image_build import sparse_copy
    directory = directory.resolve()
    manifest = json.loads((directory / "image-manifest.json").read_text())
    original = directory / "disk.raw"
    if original.is_symlink() or not original.is_file() or sha256(original) != manifest["disk_sha256"]:
        raise ValueError("Original image integrity mismatch")
    if shutil.disk_usage(session.root).free < manifest["disk_bytes"] + GIB:
        raise ValueError("Insufficient storage for immutable image revision")
    payload = stage_payload(session)
    parent = json.loads((directory / "report.json").read_text())
    original_payload = parent["payload_sha256"]
    for source in payload.glob("*.service"):
        if sha256(source) != original_payload[source.name]:
            raise ValueError("Service units changed: requires rootfs image rebuild")
    output = session.directory.resolve()
    disk = output / "disk.raw"
    if disk.exists():
        raise ValueError("Refusing to overwrite an existing image")
    session.report.update(parent_image=str(directory), parent_manifest_sha256=sha256(directory / "image-manifest.json"),
        payload_sha256={p.name: sha256(p) for p in sorted(payload.iterdir()) if p.is_file()})
    session.command("clone-image", [tools["cp"], "--reflink=auto", "--sparse=always", str(original), str(disk)], timeout=600)
    part = next(p for p in manifest["partitions"] if p["name"] == "GAIA-CORE")
    core = output / "core.ext4"
    with original.open("rb") as src, core.open("xb") as dst:
        src.seek(part["start"] * 512)
        remaining = part["bytes"]
        while remaining:
            chunk = src.read(min(MIB, remaining))
            if not chunk:
                raise ValueError("Truncated CORE")
            dst.write(chunk)
            remaining -= len(chunk)
    sums = "".join(f"{sha256(p)}  {p.name}\n" for p in sorted(payload.iterdir()) if p.is_file() and p.suffix != ".service")
    sums_path = output / "SHA256SUMS"
    sums_path.write_text(sums)
    commands = []
    for source in [*(p for p in sorted(payload.iterdir()) if p.is_file() and p.suffix != ".service"), sums_path]:
        commands += ["rm /" + source.name, "write " + json.dumps(str(source)) + " /" + source.name,
            "set_inode_field /" + source.name + " uid 0", "set_inode_field /" + source.name + " gid 0"]
    script = output / "debugfs-update.txt"
    script.write_text("\n".join(commands) + "\n")
    session.command("revise-core", [tools["debugfs"], "-w", "-f", str(script), str(core)])
    session.command("verify-core", [tools["e2fsck"], "-f", "-n", str(core)])
    # debugfs can report command failures with exit 0: verify every file's bytes.
    for source in [*(p for p in sorted(payload.iterdir()) if p.is_file() and p.suffix != ".service"), sums_path]:
        extracted = output / ("verified-" + source.name)
        session.command("verify-core-file", [tools["debugfs"], "-R", f"dump /{source.name} {extracted}", str(core)])
        if sha256(source) != sha256(extracted):
            raise ValueError("CORE revision did not preserve file contents")
    sparse_copy(core, disk, part["start"] * 512)
    core_hash = sha256(sums_path)
    esp = next(p for p in manifest["partitions"] if p["name"] == "GAIA-ESP")
    uki_hashes = {}
    for slot in ("A", "B"):
        name = "gaia-" + slot.lower() + ".efi"
        original_uki = directory / name
        if sha256(original_uki) != manifest["uki_sha256"][slot]:
            raise ValueError("UKI integrity mismatch")
        cmdline = pe_section(original_uki, ".cmdline").rstrip(b"\0").decode()
        needle = "gaia.core=" + manifest["core_manifest_sha256"]
        if needle not in cmdline:
            raise ValueError("Missing bound CORE identity")
        cmdfile = output / (slot + ".cmdline")
        cmdfile.write_bytes(cmdline.replace(needle, "gaia.core=" + core_hash).encode() + b"\0")
        uki = output / name
        session.command("revise-uki-" + slot, [tools["objcopy"], "--update-section", ".cmdline=" + str(cmdfile), str(original_uki), str(uki)])
        session.command("publish-uki-" + slot, [tools["mcopy"], "-o", "-i", str(disk) + "@@" + str(esp["start"] * 512), str(uki), "::/" + manifest.get("uki_directory", "EFI/Linux") + "/" + name])
        uki_hashes[slot] = sha256(uki)
    for part in manifest["partitions"]:
        result = hashlib.sha256()
        with disk.open("rb") as stream:
            stream.seek(part["start"] * 512)
            remaining = part["bytes"]
            while remaining:
                chunk = stream.read(min(MIB, remaining))
                if not chunk:
                    raise ValueError("Truncated revised partition")
                result.update(chunk)
                remaining -= len(chunk)
        actual = result.hexdigest()
        if part["name"] in ("GAIA-A", "GAIA-B", "GAIA-DATA") and actual != part["sha256"]:
            raise ValueError("Revision changed a preserved partition")
        if part["name"] == "GAIA-CORE" and actual != sha256(core):
            raise ValueError("Revised CORE embedding failed")
        part["sha256"] = actual
    manifest.update(core_manifest_sha256=core_hash, uki_sha256=uki_hashes, disk_sha256=sha256(disk),
        parent_manifest_sha256=session.report["parent_manifest_sha256"],
        owner_public_trust_ready=session.report.get("owner_public_trust_ready", False),
        owner_fingerprint=session.report.get("owner_fingerprint"))
    write_json(output / "image-manifest.json", manifest)
    session.report["image_manifest"] = str(output / "image-manifest.json")
    session.save()


def boot(session, directory, tools, repeats):
    directory = directory.resolve()
    manifest = json.loads((directory / "image-manifest.json").read_text())
    disk = directory / "disk.raw"
    if disk.is_symlink() or not disk.is_file() or sha256(disk) != manifest["disk_sha256"]:
        raise ValueError("VM disk integrity mismatch")
    code = Path("/usr/share/OVMF/OVMF_CODE_4M.fd")
    template = Path("/usr/share/OVMF/OVMF_VARS_4M.fd")
    if not all(path.is_file() for path in (code, template)) or not os.access("/dev/kvm", os.R_OK | os.W_OK):
        raise BootstrapError("appliance-vm", "KVM or OVMF unavailable", "Run appliance-bootstrap --preflight.")
    session.report["firmware"] = {"code_sha256": sha256(code), "vars_template_sha256": sha256(template)}
    session.report.update(image_dir=str(directory), image_sha256=manifest["disk_sha256"])
    if manifest.get("delivery_candidate"):
        return boot_runtime(session, directory, tools, repeats, manifest, code, template)
    results = []
    for index in range(repeats):
        overlay = session.directory.resolve() / f"vm-{index + 1}.qcow2"
        variables = session.directory.resolve() / f"vm-{index + 1}-vars.fd"
        shutil.copyfile(template, variables)
        session.command(f"vm-overlay-{index + 1}", [tools["qemu-img"], "create", "-f", "qcow2", "-F", "raw", "-b", str(disk), str(overlay)])
        log = session.command(f"vm-boot-{index + 1}", qemu_command(tools, overlay, code, variables), timeout=240,
                              text_errors="replace")
        result = vm_result(log)
        if result["slot"] != "A" or not result["offline"] or result["sandbox"]["status"] != "SANDBOX_CPU_OK":
            raise ValueError("VM foundation assertions failed")
        results.append(result)
        session.report["vm_results"] = results
        session.save()
    session.report["s1_complete"] = False
    session.finish("VM_FOUNDATION_VALIDATED")


def boot_runtime(session, directory, tools, repeats, manifest, code, template):
    results = []
    for index in range(repeats):
        overlay = session.directory.resolve() / f"runtime-{index + 1}.qcow2"
        variables = session.directory.resolve() / f"runtime-{index + 1}-vars.fd"
        shutil.copyfile(template, variables)
        session.command("runtime-overlay", [tools["qemu-img"], "create", "-f", "qcow2", "-F", "raw", "-b", str(directory / "disk.raw"), str(overlay)])
        ready = run_runtime_guest(session, tools, overlay, code, variables, f"runtime-{index + 1}")
        if ready["profile"] != manifest["profile"] or ready["persistent_after_ready_seconds"] != 10:
            raise ValueError("Operational runtime profile/readiness mismatch")
        results.append(ready)
        session.report["runtime_results"] = results
        session.save()
    session.report["s1_complete"] = False
    session.finish("CPU_DELIVERY_RUNTIME_VALIDATED")


def run_runtime_guest(session, tools, overlay, code, variables, label):
    import tempfile
    runner = Path(__file__).with_name("appliance_runtime_vm.py").resolve()
    # Short private socket path; no host privilege or physical device attached.
    with tempfile.TemporaryDirectory(prefix="gaia-qmp-") as sockets:
        qmp = Path(sockets) / "control"
        command = qemu_command(tools, overlay, code, variables)
        command += ["-qmp", f"unix:{qmp},server=on,wait=off"]
        spec = {"command": command, "qmp": str(qmp),
            "serial": str(session.directory.resolve() / (label + ".serial.log")),
            "errors": str(session.directory.resolve() / (label + ".qemu.stderr.log"))}
        path = session.directory.resolve() / (label + ".json")
        write_json(path, spec)
        raw = session.command("persistent-runtime", [sys.executable, "-I", str(runner), str(path)], timeout=240)
    return json.loads(raw)


def build(session, manifest_path, tools, delivery=False, external=False, nvidia=False):
    source, manifest = verified_source(manifest_path)
    parts = partition_spec(manifest["rootfs_bytes"])
    disk_estimate = sum(p["bytes"] for p in parts) + 258 * MIB
    budget = (2 * manifest["rootfs_bytes"] + parts[2]["bytes"] + 2 * disk_estimate
              + sum(p["bytes"] for p in parts if p["name"] in ("GAIA-ESP", "GAIA-CORE", "GAIA-DATA")) + 5 * GIB)
    output = session.directory.resolve()
    if external:
        from .appliance_workspace import workspace
        temporary_path, artifacts = workspace(session.root)
        output = artifacts / session.directory.name
        output.mkdir()
        temporary = select_tmpdir(True, temporary_path)
    else:
        temporary = select_tmpdir(True)
    if shutil.disk_usage(output).free < budget:
        raise BootstrapError("appliance-image-space", f"Requires {budget} bytes of build budget", "Free workspace storage; no physical disks are used.")
    payload = stage_payload(session)
    profile_name = "nvidia-delivery-candidate" if nvidia else "cpu-delivery-candidate"
    if nvidia:
        proof = manifest.get("nvidia", {})
        if proof.get("status") != "NVIDIA_RUNTIME_LINKS_AND_MODULES_OK" or proof.get("driver") != "580.178.04":
            raise ValueError("NVIDIA candidate requires the verified NVIDIA runtime")
    if delivery:
        if not session.report.get("owner_public_trust_ready"):
            raise ValueError("Delivery candidate requires the pinned owner public proof")
        write_json(payload / "runtime-profile.json", {"name": profile_name, "authority": "L0",
            "execution_profile": "cuda" if nvidia else "cpu", "gpu_validation": "pending physical hardware", "version": 1,
            "driver": "580.178.04" if nvidia else None})
    helper = Path(__file__).with_name("appliance_image_build.py").resolve()
    spec = {"source": "/tmp/rootfs.tar", "source_sha256": manifest["rootfs_sha256"],
        "kernel": manifest["kernels"][0], "initramfs": manifest["initramfs"][0],
        "output": "/tmp/image-output", "payload": "/tmp/image-payload",
        "partitions": parts, "host_user_namespace": os.readlink("/proc/self/ns/user")}
    spec["owner_public_trust_ready"] = session.report.get("owner_public_trust_ready", False)
    spec["owner_fingerprint"] = session.report.get("owner_fingerprint")
    spec["delivery_candidate"] = delivery
    spec["nvidia_candidate"] = nvidia
    spec["nvidia"] = manifest.get("nvidia") if nvidia else None
    session.report.update(source_manifest=str(manifest_path.resolve()), source_sha256=manifest["rootfs_sha256"],
        helper_sha256=sha256(helper), payload_sha256={p.name: sha256(p) for p in sorted(payload.iterdir()) if p.is_file()},
        profile=profile_name if delivery else "vm-cpu-l0", build_budget_bytes=budget, s1_complete=False,
        artifact_directory=str(output), external_workspace=external)
    write_json(session.directory / "build-spec.json", spec)
    payload_tar = session.directory.resolve() / "image-payload.tar"
    with tarfile.open(payload_tar, "w") as archive:
        for path in sorted(payload.iterdir()):
            if path.is_file():
                archive.add(path, arcname=path.name, recursive=False)
    hooks = ['--customize-hook=mkdir -p "$1/tmp/image-output" "$1/tmp/image-payload"',
        "--customize-hook=" + shlex.join(["tar-in", str(payload_tar), "/tmp/image-payload"])]
    for path in (source, helper, (session.directory / "build-spec.json").resolve()):
        hooks.append("--customize-hook=" + shlex.join(["copy-in", str(path), "/tmp"]))
    hooks.append('--customize-hook=/usr/bin/python3 -I "$1/tmp/appliance_image_build.py" "$1/tmp/build-spec.json" --staging-root "$1"')
    for name in ("disk.raw", "image-manifest.json", "gaia-a.efi", "gaia-b.efi"):
        hooks.append("--customize-hook=" + shlex.join(["copy-out", "/tmp/image-output/" + name, str(output)]))
    if shutil.disk_usage(temporary["path"]).free < budget:
        raise BootstrapError("appliance-image-space", "Insufficient build filesystem capacity", "Choose a disk-backed TMPDIR with enough space.")
    session.report["build_tmpdir"] = temporary
    command = [tools["mmdebstrap"], "--mode=unshare", "--format=null", "--variant=minbase",
        "--architectures=amd64", "--components=main", "--keyring=" + PROFILE["keyring"],
        '--aptopt=Acquire::Check-Valid-Until "false"', '--aptopt=Acquire::Languages "none"',
        *hooks, PROFILE["suite"], "/dev/null", PROFILE["mirror"]]
    session.command("image-build", command, env={**os.environ, "TMPDIR": temporary["path"]}, timeout=1200)
    session.report["image_manifest"] = str(output / "image-manifest.json")
    session.save()
    return output


def main(root, args):
    parser = argparse.ArgumentParser(prog="gaia.py appliance-image", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--rootfs-manifest", type=Path)
    group.add_argument("--image-dir", type=Path, help="validate/boot an existing image without rebuilding")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--refresh-core", action="store_true", help="new image revision from --image-dir, preserving both root slots")
    parser.add_argument("--delivery-candidate", action="store_true", help="remove native build toolchain, validate ABI and boot persistent CPU runtime")
    parser.add_argument("--nvidia-candidate", action="store_true", help="build persistent CUDA candidate; GPU acceptance requires physical hardware")
    parser.add_argument("--workspace", action="store_true", help="use the verified SSD for build temporaries and large output files")
    parser.add_argument("--build-only", action="store_true", help="construct image without claiming an operational VM or GPU boot")
    parser.add_argument("--boot-scenarios", action="store_true", help="normal A/B, attempt exhaustion/fallback and interrupted staging (not full S1)")
    parser.add_argument("--scenario", action="append", choices=("normal-A", "normal-B", "attempt-exhaustion", "interrupted-publication", "corrupted-B", "data-recovery", "publication-interrupted", "health-bless", "health-reject", "usb-smoke"),
                        help="select scenario(s); default is all implemented scenarios")
    options = parser.parse_args(args)
    if options.refresh_core and not options.image_dir:
        parser.error("--refresh-core requires --image-dir")
    if options.delivery_candidate and not options.rootfs_manifest:
        parser.error("--delivery-candidate requires --rootfs-manifest")
    if (options.nvidia_candidate or options.build_only) and not options.rootfs_manifest:
        parser.error("build options require --rootfs-manifest")
    if options.nvidia_candidate and not (options.build_only or options.boot_scenarios):
        parser.error("NVIDIA candidate requires --build-only or --boot-scenarios; CPU VM is not a GPU runtime")
    if options.scenario and not options.boot_scenarios:
        parser.error("--scenario requires --boot-scenarios")
    if options.workspace and options.image_dir:
        from .appliance_workspace import WorkspaceSession
        session = WorkspaceSession(root)
    else:
        session = Session(root)
    session.report["request"] = {"command": "appliance-image", "repeats": options.repeats}
    try:
        with locked(Path(root) / ".gaia/bootstrap.lock"):
            if os.geteuid() == 0:
                raise ValueError("Run as the normal user, not host root")
            tools = {name: shutil.which(name) for name in TOOLS}
            if not all(tools.values()):
                raise ValueError("Missing tools: " + str([key for key, value in tools.items() if not value]))
            if options.rootfs_manifest:
                built_directory = build(session, options.rootfs_manifest, tools,
                    options.delivery_candidate or options.nvidia_candidate, options.workspace, options.nvidia_candidate)
                if options.build_only:
                    session.finish("NVIDIA_DELIVERY_CANDIDATE_BUILT" if options.nvidia_candidate else "IMAGE_BUILT_AWAITING_BOOT")
                    return 0
            elif options.refresh_core:
                refresh_core(session, options.image_dir, tools)
            directory = session.directory if options.refresh_core else options.image_dir or built_directory
            if options.boot_scenarios:
                from .appliance_vm_scenarios import validate
                validate(session, directory, tools, options.repeats, options.scenario)
            else:
                boot(session, directory, tools, options.repeats)
        return 0
    except KeyboardInterrupt as exc:
        session.finish("INTERRUPTED", exc)
        return 130
    except Exception as exc:
        session.finish("FAILED", exc)
        return 40
