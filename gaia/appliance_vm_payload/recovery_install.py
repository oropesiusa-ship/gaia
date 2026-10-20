"""Signed-image installer/OS repair for explicitly identified QEMU lab targets.

Not the physical installer: physical S0 identity/health/authorization gates are
required before a different production profile can ever permit physical writes.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

if __package__:
    from .public_trust import custody_check, verify_signature
    from .data_backup import unique_fields
else:
    sys.path.insert(0, "/core")
    from public_trust import custody_check, verify_signature
    from data_backup import unique_fields


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def console(value):
    with open("/dev/console", "w") as stream:
        stream.write(value + "\n")
        stream.flush()


def run(args):
    return subprocess.check_output(args, text=True, timeout=60)


def nodes(row):
    yield row
    for child in row.get("children", []):
        yield from nodes(child)


def context():
    args = dict(p.split("=", 1) for p in Path("/proc/cmdline").read_text().split() if "=" in p)
    if (os.geteuid() != 0 or args.get("gaia.lab") != "1" or args.get("gaia.scenario") != "usb-install"
            or Path("/sys/class/dmi/id/sys_vendor").read_text().strip() != "QEMU"):
        raise ValueError("Installer requires the explicit QEMU recovery profile")
    if hashlib.sha256(Path("/core/SHA256SUMS").read_bytes()).hexdigest() != args["gaia.core"]:
        raise ValueError("Untrusted recovery CORE")
    subprocess.run(["/usr/bin/sha256sum", "--check", "/core/SHA256SUMS"], cwd="/core", check=True)
    custody_check()
    subprocess.run(["/bin/sh", "/core/offline.sh"], check=True)
    return args


def signed_payload(directory):
    path, signature = directory / "install-manifest.json", directory / "install-manifest.json.asc"
    if (path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024
            or signature.is_symlink() or not signature.is_file() or signature.stat().st_size > 1024 * 1024):
        raise ValueError("Invalid install manifest")
    fingerprint = verify_signature(path, signature)
    record = json.loads(path.read_bytes(), object_pairs_hook=unique_fields)
    if (record.get("schema") != "gaia-signed-artifacts-v1" or record.get("kind") != "gaia-vm-install-bundle-v1"
            or record.get("purpose") != "lab" or record.get("signing_fingerprint") != fingerprint
            or record.get("target_serial") != "GAIA-LAB-TARGET"):
        raise ValueError("Signature does not authorize this lab install bundle")
    expected = record.get("artifacts")
    if not isinstance(expected, list) or len(expected) != 2 or {r["name"] for r in expected} != {"disk.raw", "image-manifest.json"}:
        raise ValueError("Incorrect install artifact set")
    for row in expected:
        source = directory / row["name"]
        if (type(row["bytes"]) is not int or not 0 < row["bytes"] <= 64 * 1024**3
                or row["name"] == "image-manifest.json" and row["bytes"] > 2 * 1024 * 1024
                or source.is_symlink() or not source.is_file() or source.stat().st_size != row["bytes"]
                or digest(source) != row["sha256"]):
            raise ValueError("Install artifact integrity mismatch")
    image = json.loads((directory / "image-manifest.json").read_bytes(), object_pairs_hook=unique_fields)
    if (record.get("target_bytes") != image["disk_bytes"] or image["disk_bytes"] != (directory / "disk.raw").stat().st_size
            or image["disk_sha256"] != next(r["sha256"] for r in expected if r["name"] == "disk.raw")):
        raise ValueError("Signed disk geometry/content mismatch")
    parts = image["partitions"]
    names = [part["name"] for part in parts]
    if names != ["GAIA-ESP", "GAIA-CORE", "GAIA-A", "GAIA-B", "GAIA-DATA"]:
        raise ValueError("Unexpected partition schema")
    end = 1024 * 1024
    for part in parts:
        start, size = part["start"] * 512, part["bytes"]
        if (type(part["start"]) is not int or type(size) is not int or size <= 0
                or size != part["sectors"] * 512 or start < end or start + size > image["disk_bytes"] - 34 * 512):
            raise ValueError("Overlapping or out-of-bounds signed partition")
        end = start + size
    return record, image


def select_target(devices, size):
    selected = [d for d in devices if d.get("serial") == "GAIA-LAB-TARGET"]
    if len(selected) != 1 or selected[0].get("type") != "disk" or selected[0].get("size") != size:
        raise ValueError("Ambiguous or incorrect lab target")
    for child in nodes(selected[0]):
        if any(child.get("mountpoints") or []) or child.get("type") in ("crypt", "lvm"):
            raise ValueError("Lab target is mounted or mapped")
    return Path(selected[0]["path"])


def range_hash(fd, start, size):
    os.lseek(fd, start, os.SEEK_SET)
    result = hashlib.sha256()
    while size:
        chunk = os.read(fd, min(size, 1024 * 1024))
        if not chunk:
            raise ValueError("Short device read")
        result.update(chunk)
        size -= len(chunk)
    return result.hexdigest()


def copy_range(source, target, start, size):
    source.seek(start)
    os.lseek(target, start, os.SEEK_SET)
    while size:
        chunk = source.read(min(size, 1024 * 1024))
        if not chunk:
            raise ValueError("Short install source")
        pending = memoryview(chunk)
        while pending:
            count = os.write(target, pending)
            if count <= 0:
                raise ValueError("Short install write")
            pending = pending[count:]
        size -= len(chunk)


def apply_image(source, target, image, mode):
    if mode not in ("install", "repair-system"):
        raise ValueError("Unknown recovery operation")
    if not stat.S_ISBLK(target.stat().st_mode):
        raise ValueError("Target must be the identified virtual block device")
    fd = os.open(target, os.O_RDWR | os.O_EXCL)
    try:
        with source.open("rb") as payload:
            if mode == "install":
                copy_range(payload, fd, 0, image["disk_bytes"])
                os.fsync(fd)
                if range_hash(fd, 0, image["disk_bytes"]) != image["disk_sha256"]:
                    raise ValueError("Installed image readback differs")
                return {"status": "VM_IMAGE_INSTALLED", "disk_sha256": image["disk_sha256"]}
            # A repair is permitted only when the installed GPT/padding matches
            # this signed image. DATA extent is then fixed and excluded from writes.
            for start, size in ((0, 1024 * 1024), (image["disk_bytes"] - 34 * 512, 34 * 512)):
                payload.seek(start)
                if range_hash(fd, start, size) != hashlib.sha256(payload.read(size)).hexdigest():
                    raise ValueError("GPT differs: cannot safely preserve DATA during repair")
            data = next(part for part in image["partitions"] if part["name"] == "GAIA-DATA")
            before = range_hash(fd, data["start"] * 512, data["bytes"])
            for part in image["partitions"]:
                if part["name"] != "GAIA-DATA":
                    copy_range(payload, fd, part["start"] * 512, part["bytes"])
            os.fsync(fd)
            for part in image["partitions"]:
                if part["name"] != "GAIA-DATA" and range_hash(fd, part["start"] * 512, part["bytes"]) != part["sha256"]:
                    raise ValueError("Repaired partition readback differs")
            after = range_hash(fd, data["start"] * 512, data["bytes"])
            if before != after:
                raise ValueError("Recovery modified DATA")
            return {"status": "VM_SYSTEM_REPAIRED", "data_preserved": True, "data_sha256": after}
    finally:
        os.close(fd)


def main():
    args = context()
    devices = json.loads(run(["/usr/bin/lsblk", "--json", "--tree", "--bytes", "--output", "PATH,TYPE,SERIAL,SIZE,MOUNTPOINTS"]))["blockdevices"]
    recovery = [d for d in devices if d.get("serial") == "GAIA-LAB-RECOVERY"]
    bundle = [d for d in devices if d.get("serial") == "GAIA-LAB-BUNDLE"]
    if len(recovery) != 1 or not any("/" in (n.get("mountpoints") or []) for n in nodes(recovery[0])) or len(bundle) != 1:
        raise ValueError("Recovery must boot from the identified USB and use an independent bundle disk")
    mount = Path("/run/gaia-install-bundle")
    mount.mkdir(mode=0o700)
    run(["/usr/bin/mount", "-o", "ro,nodev,nosuid,noexec", bundle[0]["path"], str(mount)])
    try:
        record, image = signed_payload(mount)
        target = select_target(devices, record["target_bytes"])
        if target in (Path(recovery[0]["path"]), Path(bundle[0]["path"])):
            raise ValueError("Recovery source cannot be an installation target")
        result = apply_image(mount / "disk.raw", target, image, args.get("gaia.recovery", "install"))
        result.update(purpose="lab", fingerprint=record["signing_fingerprint"], virtual_only=True)
        console("GAIA_RECOVERY_RESULT=" + json.dumps(result))
    finally:
        run(["/usr/bin/umount", str(mount)])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        console("GAIA_RECOVERY_ERROR=" + json.dumps({"reason": str(exc)}))
        raise
