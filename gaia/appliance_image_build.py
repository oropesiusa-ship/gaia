"""Internal image assembler, invoked only inside mmdebstrap's user namespace.

All mkfs targets are freshly created regular files in a new build directory.
No mounts, loop devices, physical devices or host privilege elevation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
import zlib

MIB = 1024 ** 2
GIB = 1024 ** 3
SECTOR = 512


def run(args, **kwargs):
    print("image:", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def align(value, alignment=MIB):
    return (value + alignment - 1) // alignment * alignment


def new_file(path, size):
    with path.open("xb") as stream:
        stream.truncate(size)


def uki_sections(stub, sections):
    """Place sections after the existing PE image, respecting its alignment/base."""
    pe = struct.unpack_from("<I", stub, 60)[0]
    if stub[pe:pe + 4] != b"PE\0\0":
        raise ValueError("Not a PE image")
    count = struct.unpack_from("<H", stub, pe + 6)[0]
    optional_size = struct.unpack_from("<H", stub, pe + 20)[0]
    optional = pe + 24
    if struct.unpack_from("<H", stub, optional)[0] != 0x20B:
        raise ValueError("Expected x86_64 PE32+ stub")
    base = struct.unpack_from("<Q", stub, optional + 24)[0]
    alignment = struct.unpack_from("<I", stub, optional + 32)[0]
    if not alignment or alignment & (alignment - 1):
        raise ValueError("Invalid PE section alignment")
    table = optional + optional_size
    end = 0
    for index in range(count):
        size, address, raw_size = struct.unpack_from("<III", stub, table + index * 40 + 8)
        end = max(end, address + max(size, raw_size))
    result = {}
    for name, size in sections:
        end = align(end, alignment)
        result[name] = base + end
        end += size
        if end >= 2**32:
            raise ValueError("UKI too large for PE image")
    return result


def gpt_layout(partitions):
    start = 2048
    for part in partitions:
        part["start"] = start
        part["sectors"] = align(part["bytes"]) // SECTOR
        start += part["sectors"]
    # Explicit unallocated reserve plus backup GPT.
    sectors = align((start + 34) * SECTOR + 256 * MIB) // SECTOR
    return sectors


def write_gpt(path, partitions, sectors):
    new_file(path, sectors * SECTOR)
    entries = bytearray(128 * 128)
    for index, part in enumerate(partitions):
        name = part["name"].encode("utf-16-le")
        struct.pack_into("<16s16sQQQ72s", entries, index * 128,
            uuid.UUID(part["type"]).bytes_le, uuid.UUID(part["uuid"]).bytes_le,
            part["start"], part["start"] + part["sectors"] - 1, 0, name)
    disk_uuid = uuid.uuid4().bytes_le
    def header(current, backup, entry_lba):
        raw = bytearray(SECTOR)
        struct.pack_into("<8sIIIIQQQQ16sQIII", raw, 0, b"EFI PART", 0x10000, 92, 0, 0,
                         current, backup, 34, sectors - 34, disk_uuid, entry_lba,
                         128, 128, zlib.crc32(entries))
        struct.pack_into("<I", raw, 16, zlib.crc32(raw[:92]))
        return raw
    mbr = bytearray(SECTOR)
    struct.pack_into("<B3sB3sII", mbr, 446, 0, b"\0\2\0", 0xEE, b"\xff\xff\xff", 1, min(sectors - 1, 0xFFFFFFFF))
    mbr[510:] = b"\x55\xaa"
    with path.open("r+b") as stream:
        stream.write(mbr)
        stream.write(header(1, sectors - 1, 2))
        stream.write(entries)
        stream.seek((sectors - 33) * SECTOR)
        stream.write(entries)
        stream.write(header(sectors - 1, 1, sectors - 33))


def sparse_copy(source, destination, offset):
    # Preserve holes in multi-GiB ext4 files. Do not turn VM disks into full copies.
    # os.lseek and buffered reads must not share a file offset: a short extent
    # can otherwise leave buffered hole bytes that corrupt the next extent.
    with source.open("rb", buffering=0) as src, destination.open("r+b", buffering=0) as dst:
        size = source.stat().st_size
        position = 0
        while position < size:
            try:
                data = os.lseek(src.fileno(), position, os.SEEK_DATA)
            except OSError as exc:
                if exc.errno == 6:  # ENXIO: no further allocated extent
                    break
                raise
            end = min(os.lseek(src.fileno(), data, os.SEEK_HOLE), size)
            src.seek(data)
            dst.seek(offset + data)
            while data < end:
                chunk = src.read(min(MIB, end - data))
                if not chunk:
                    raise ValueError("Truncated image extent")
                dst.write(chunk)
                data += len(chunk)
            position = end


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(MIB), b""):
            result.update(chunk)
    return result.hexdigest()


def package_inventory(tree):
    output = subprocess.check_output(["chroot", str(tree), "/usr/bin/dpkg-query", "-W",
        "-f=${Package}\\t${Status}\\t${Version}\\n"], text=True)
    result = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[1] == "install ok installed":
            result[parts[0]] = parts[2]
    return result


def build_only_packages(installed):
    selected = []
    for name in installed:
        compiler = name in ("gcc", "g++", "cpp") or name.startswith(("gcc-", "g++-", "cpp-"))
        if re.fullmatch(r"gcc-\d+-base", name):
            compiler = False  # runtime ABI package required by libgcc/libstdc++
        # Keep common metadata required by libbinutils/libctf/libgprofng: remove
        # executables, not their dependency closure by accident.
        binutils_tools = name.startswith("binutils") and name != "binutils-common"
        if (compiler or binutils_tools or name.endswith("-dev")
                or name in ("build-essential", "make", "dpkg-dev", "libc-dev-bin")):
            selected.append(name)
    return sorted(selected)


def strip_build_tools(tree):
    before = package_inventory(tree)
    selected = build_only_packages(before)
    if not selected:
        raise ValueError("No build toolchain found in the expected construction rootfs")
    command = ["chroot", str(tree), "/usr/bin/apt-get", "--no-download", "--yes"]
    plan = subprocess.check_output([*command, "--simulate", "purge", *selected], text=True)
    removed = {line.split()[1].split(":")[0] for line in plan.splitlines() if line.startswith(("Remv ", "Purg "))}
    if not removed or removed - set(selected):
        print(plan, flush=True)
        raise ValueError("Toolchain purge would remove out-of-scope dependencies: " + repr(sorted(removed - set(selected)))
                         + f"; selected={len(selected)}, simulated={len(removed)}")
    run([*command, "purge", *selected])
    after = package_inventory(tree)
    if any(name in after for name in selected) or set(before) - set(after) != removed:
        raise ValueError("Actual package removal differs from the simulated plan")
    if any(before[name] != version for name, version in after.items()):
        raise ValueError("Runtime package versions changed during cleanup")
    run(["chroot", tree, "/bin/sh", "-ec",
        'for name in gcc g++ cpp cc c++ make objcopy; do if command -v "$name" >/dev/null 2>&1; then exit 1; fi; done'])
    return {"status": "NATIVE_BUILD_TOOLCHAIN_REMOVED", "removed": {name: before[name] for name in sorted(removed)},
            "retained": after, "autoremove_used": False, "host_packages_modified": False}


def prepare_root(tree, payload, delivery=False, nvidia=False):
    run(["chroot", tree, "/usr/sbin/useradd", "--system", "--no-create-home",
         "--home-dir", "/data/evidence", "--shell", "/usr/sbin/nologin", "gaia-guardian"])
    for name in ("core", "data", "tmp", "var", "efi"):
        (tree / name).mkdir(exist_ok=True)
    (tree / "etc/machine-id").write_text("")
    hostname = "gaia" if delivery else "gaia-vm"
    (tree / "etc/hostname").write_text(hostname + "\n")
    (tree / "etc/hosts").write_text(f"127.0.0.1 localhost\n127.0.1.1 {hostname}\n::1 localhost\n")
    (tree / "etc/fstab").write_text(
        "LABEL=GAIA-CORE /core ext4 ro,noload 0 0\n"
        "LABEL=GAIA-DATA /data ext4 defaults 0 2\n"
        "tmpfs /tmp tmpfs nosuid,nodev,mode=1777 0 0\n"
        "tmpfs /var tmpfs nosuid,nodev,mode=0755 0 0\n")
    (tree / "etc/tmpfiles.d/gaia.conf").write_text(
        "d /data/agent 0700 gaia gaia -\n"
        "d /data/evidence 0700 gaia-guardian gaia-guardian -\n"
        "d /var/log 0755 root root -\n")
    units = tree / "etc/systemd/system"
    for source in payload.glob("*.service"):
        shutil.copyfile(source, units / source.name)
    if nvidia:
        unit = units / "gaia-runtime.service"
        text = unit.read_text().replace("PrivateDevices=yes", "PrivateDevices=no\nDevicePolicy=closed\n"
            "DeviceAllow=/dev/nvidia0 rw\nDeviceAllow=/dev/nvidiactl rw\nDeviceAllow=/dev/nvidia-uvm rw")
        text = text.replace("Requires=gaia-guardian.service gaia-offline.service", "Requires=gaia-guardian.service gaia-offline.service gaia-gpu.service")
        text = text.replace("After=gaia-guardian.service gaia-offline.service", "After=gaia-guardian.service gaia-offline.service gaia-gpu.service")
        unit.write_text(text)
    wants = units / "multi-user.target.wants"
    wants.mkdir(exist_ok=True)
    service = "gaia-mode.service" if delivery else "gaia-vm-probe.service"
    (wants / service).symlink_to("../" + service)
    # Automatic boot success must not bless an unhealthy candidate.
    (units / "systemd-bless-boot.service").symlink_to("/dev/null")


def assemble(spec):
    if os.geteuid() != 0 or os.readlink("/proc/self/ns/user") == spec["host_user_namespace"]:
        raise ValueError("Requires the mapped-root namespace, not host root")
    output = Path(spec["output"])
    payload = Path(spec["payload"])
    parts = spec["partitions"]
    with tempfile.TemporaryDirectory(prefix="image-work-", dir=output) as temporary:
        work = Path(temporary)
        tree = work / "root"
        tree.mkdir()
        run(["tar", "--extract", "--file", spec["source"], "--directory", tree,
             "--numeric-owner", "--same-owner", "--anchored", "--exclude=./dev/*", "--exclude=dev/*"])
        delivery = spec.get("delivery_candidate", False)
        nvidia = spec.get("nvidia_candidate", False)
        if nvidia:
            modprobe = tree / "var/cache/apt/archives/nvidia-modprobe_580.178.04-1_amd64.deb"
            if not modprobe.is_file():
                raise ValueError("Verified NVIDIA device-node helper absent from runtime cache")
            run(["chroot", tree, "/usr/bin/dpkg", "--install", "/var/cache/apt/archives/" + modprobe.name])
            modules = tree / "etc/initramfs-tools/modules"
            with modules.open("a") as stream:
                stream.write("\nnvidia\nnvidia_uvm\n")
            run(["chroot", tree, "/usr/sbin/update-initramfs", "-u", "-k", "6.12.107+deb13-amd64"])
        cleanup = strip_build_tools(tree) if delivery else None
        prepare_root(tree, payload, delivery, nvidia)
        # Runtime/ABI validation happens in the actual VM, with its real kernel
        # and devices. A built candidate is never accepted on package metadata.
        smoke = {"status": "PENDING_ACTUAL_VM_RUNTIME_VALIDATION"} if delivery else None
        core_tree = work / "core"
        core_tree.mkdir()
        for source in sorted(payload.iterdir()):
            if source.is_file() and source.suffix != ".service":
                shutil.copyfile(source, core_tree / source.name)
        sums = "".join(f"{digest(p)}  {p.name}\n" for p in sorted(core_tree.iterdir()))
        (core_tree / "SHA256SUMS").write_text(sums)
        core_hash = digest(core_tree / "SHA256SUMS")
        core_image = work / "core.ext4"
        new_file(core_image, parts[1]["bytes"])
        run(["mkfs.ext4", "-q", "-F", "-L", "GAIA-CORE", "-m", "0", "-d", core_tree, core_image])
        run(["e2fsck", "-f", "-n", core_image])
        data_image = work / "data.ext4"
        new_file(data_image, parts[4]["bytes"])
        run(["mkfs.ext4", "-q", "-F", "-L", "GAIA-DATA", "-m", "0", data_image])
        run(["e2fsck", "-f", "-n", data_image])
        root_image = work / "root.ext4"
        new_file(root_image, parts[2]["bytes"])
        run(["mkfs.ext4", "-q", "-F", "-L", "GAIA-SYSTEM", "-m", "0",
             "-E", "lazy_itable_init=0,lazy_journal_init=0", "-d", tree, root_image])
        run(["e2fsck", "-f", "-n", root_image])
        # The slot identity is the GPT PARTUUID and bound UKI cmdline, not this
        # shared filesystem UUID. Both roots are immutable during the lab runs.
        manifest_root_hash = digest(root_image)
        kernel = tree / spec["kernel"]
        initrd = tree / spec["initramfs"]
        stub = tree / "usr/lib/systemd/boot/efi/linuxx64.efi.stub"
        osrel = tree / "usr/lib/os-release"
        ukis = {}
        for slot, part in (("A", parts[2]), ("B", parts[3])):
            commandline = ("root=PARTUUID=" + part["uuid"] + " ro rootfstype=ext4 rootflags=noload "
                "console=tty0 console=ttyS0,115200 panic=5 "
                "gaia.lab=1 gaia.slot=" + slot + " gaia.core=" + core_hash)
            cmdfile = work / (slot + ".cmdline")
            cmdfile.write_bytes(commandline.encode() + b"\0")
            sections = {".osrel": osrel, ".cmdline": cmdfile, ".linux": kernel, ".initrd": initrd}
            addresses = uki_sections(stub.read_bytes(), [(name, path.stat().st_size) for name, path in sections.items()])
            args = ["objcopy"]
            for name, path in sections.items():
                args += ["--add-section", name + "=" + str(path), "--change-section-vma", name + "=" + hex(addresses[name]),
                         "--set-section-flags", name + "=contents,alloc,load,readonly,data"]
            uki = output / ("gaia-" + slot.lower() + ".efi")
            run([*args, stub, uki])
            ukis[slot] = uki
        esp_size = align(sum(p.stat().st_size for p in ukis.values()) * 2 + 64 * MIB)
        parts[0]["bytes"] = esp_size
        esp = work / "esp.fat"
        new_file(esp, esp_size)
        run(["mformat", "-i", esp, "-F", "-v", "GAIA-ESP", "::"])
        for directory in ("::/EFI", "::/EFI/BOOT", "::/EFI/GAIA", "::/loader", "::/loader/entries"):
            run(["mmd", "-i", esp, directory])
        run(["mcopy", "-i", esp, tree / "usr/lib/systemd/boot/efi/systemd-bootx64.efi", "::/EFI/BOOT/BOOTX64.EFI"])
        loader = work / "loader.conf"
        loader.write_text("default gaia-a.conf\ntimeout 0\neditor no\nauto-entries no\nauto-firmware no\n")
        run(["mcopy", "-i", esp, loader, "::/loader/loader.conf"])
        for slot, uki in ukis.items():
            run(["mcopy", "-i", esp, uki, "::/EFI/GAIA/" + uki.name])
            entry = work / ("gaia-" + slot.lower() + ".conf")
            entry.write_text(f"title GAIA lab slot {slot}\nversion 1\nefi /EFI/GAIA/{uki.name}\n")
            run(["mcopy", "-i", esp, entry, "::/loader/entries/" + entry.name])
        sectors = gpt_layout(parts)
        disk = output / "disk.raw"
        write_gpt(disk, parts, sectors)
        for part, image in zip(parts, (esp, core_image, root_image, root_image, data_image)):
            sparse_copy(image, disk, part["start"] * SECTOR)
            expected = digest(image)
            actual = hashlib.sha256()
            with disk.open("rb") as stream:
                stream.seek(part["start"] * SECTOR)
                remaining = image.stat().st_size
                while remaining:
                    chunk = stream.read(min(MIB, remaining))
                    if not chunk:
                        raise ValueError("Truncated partition")
                    actual.update(chunk)
                    remaining -= len(chunk)
            if actual.hexdigest() != expected:
                raise ValueError("Partition embedding mismatch: " + part["name"])
            part["sha256"] = expected
        run(["sfdisk", "--verify", disk])
        manifest = {"status": "NVIDIA_DELIVERY_CANDIDATE_BUILT" if nvidia else "CPU_DELIVERY_CANDIDATE_BUILT" if delivery else "VM_FOUNDATION_IMAGE_BUILT",
            "profile": "nvidia-delivery-candidate" if nvidia else "cpu-delivery-candidate" if delivery else "vm-cpu-l0", "delivery_candidate": delivery,
            "nvidia": spec.get("nvidia"), "gpu_tested": False,
            "native_toolchain_cleanup": cleanup, "clean_runtime_smoke": smoke,
            "disk": "disk.raw", "disk_sha256": digest(disk), "disk_bytes": sectors * SECTOR,
            "source_sha256": spec["source_sha256"], "core_manifest_sha256": core_hash,
            "root_partition_sha256": manifest_root_hash, "partitions": parts,
            "uki_directory": "EFI/GAIA",
            "uki_sha256": {key: digest(value) for key, value in ukis.items()},
            "owner_public_trust_ready": spec.get("owner_public_trust_ready", False),
            "owner_fingerprint": spec.get("owner_fingerprint"),
            "s1_complete": False, "release_image": False, "signed": False,
             "pending": ["boot/fallback/recovery acceptance", "release signing and external trust anchor",
                         "release toolchain removal", "physical NVIDIA validation"]}
        if delivery:
            manifest["pending"] = ["VM acceptance and owner signature for this new identity",
                "signed install/repair of this candidate", "physical preflight and NVIDIA profile validation",
                "final production acceptance"]
        (output / "image-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    parser.add_argument("--staging-root", type=Path)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    if args.staging_root:
        for name in ("source", "output", "payload"):
            spec[name] = str(args.staging_root / spec[name].lstrip("/"))
    assemble(spec)
