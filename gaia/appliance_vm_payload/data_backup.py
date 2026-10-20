"""Bounded DATA snapshot/restore primitive; callers must quiesce all writers.

No signature authority is created here. The expected manifest hash must come
from a separate trusted context, not from the received backup itself.
Version 1 covers agent/evidence regular files and directories, not links/devices.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile

MAX_FILES = 1024
MAX_BYTES = 32 * 1024 * 1024


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def sync_directory(path):
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def safe_name(name, roles):
    if not isinstance(name, str) or len(name.encode("utf-8")) > 240:
        raise ValueError("Invalid backup path")
    pieces = name.split("/")
    if (not pieces or pieces[0] not in roles or any(p in ("", ".", "..") for p in pieces)
            or any(ord(c) < 32 or c == "\\" for c in name)):
        raise ValueError("Backup path escapes the permitted DATA trees")
    return name


def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate manifest field")
        result[name] = value
    return result


def validate_rows(rows, roles):
    if not isinstance(rows, list) or not len(roles) <= len(rows) <= MAX_FILES:
        raise ValueError("Invalid backup entry count")
    expected = {}
    total = 0
    for row in rows:
        name = safe_name(row["name"], roles)
        if name in expected or row["kind"] not in ("file", "directory"):
            raise ValueError("Duplicate or unsupported backup entry")
        role = roles[name.split("/")[0]]
        if (row["uid"] != role["uid"] or row["gid"] not in role["gids"]
                or type(row["mode"]) is not int or row["mode"] & ~0o777
                or type(row["bytes"]) is not int or row["bytes"] < 0):
            raise ValueError("Unsafe owner, permissions or size")
        if row["kind"] == "directory" and (row["bytes"] != 0 or row["sha256"] is not None):
            raise ValueError("Invalid directory metadata")
        if row["kind"] == "file":
            checksum = row["sha256"]
            if not isinstance(checksum, str) or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
                raise ValueError("Invalid content digest")
        if type(row["mtime"]) is not int or row["mtime"] < 0:
            raise ValueError("Invalid modification time")
        expected[name] = row
        total += row["bytes"]
        if total > MAX_BYTES:
            raise ValueError("Backup content budget exceeded")
    for top in roles:
        if top not in expected or expected[top]["kind"] != "directory":
            raise ValueError("Missing role root")
    for name in expected:
        parent = str(Path(name).parent)
        if parent != "." and (parent not in expected or expected[parent]["kind"] != "directory"):
            raise ValueError("Missing or conflicting parent directory")
    return expected


def snapshot(source, destination, roles):
    if any(p.name not in {*roles, "lost+found"} for p in source.iterdir()):
        raise ValueError("DATA contains trees outside the v1 backup contract")
    rows, total = [], 0
    for top in sorted(roles):
        root = source / top
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Invalid role tree")
        for path in [root, *sorted(root.rglob("*"))]:
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError("Links and special files are not supported")
            regular = stat.S_ISREG(info.st_mode)
            if regular:
                if info.st_nlink != 1:
                    raise ValueError("Hard-linked files are not supported")
                total += info.st_size
                if total > MAX_BYTES:
                    raise ValueError("Backup content budget exceeded")
            rows.append({"name": path.relative_to(source).as_posix(), "kind": "file" if regular else "directory",
                "uid": info.st_uid, "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode),
                "mtime": int(info.st_mtime), "bytes": info.st_size if regular else 0,
                "sha256": digest(path) if regular else None})
            if len(rows) > MAX_FILES:
                raise ValueError("Backup entry budget exceeded")
    validate_rows(rows, roles)
    archive = destination / "data.tar"
    with archive.open("xb") as raw:
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as output:
            for row in rows:
                member = tarfile.TarInfo(row["name"])
                member.type = tarfile.REGTYPE if row["kind"] == "file" else tarfile.DIRTYPE
                member.uid, member.gid, member.mode, member.mtime, member.size = (
                    row["uid"], row["gid"], row["mode"], row["mtime"], row["bytes"])
                if row["kind"] == "file":
                    with (source / row["name"]).open("rb") as stream:
                        output.addfile(member, stream)
                else:
                    output.addfile(member)
        raw.flush()
        os.fsync(raw.fileno())
    manifest = {"schema": "gaia-data-backup-v1", "archive_sha256": digest(archive), "entries": rows}
    path = destination / "manifest.json"
    with path.open("x") as stream:
        json.dump(manifest, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(destination)
    expected_hash = digest(path)
    verify(destination, expected_hash, roles)
    return expected_hash


def verify(backup, expected_manifest_sha256, roles):
    manifest, archive = backup / "manifest.json", backup / "data.tar"
    for path, maximum in ((manifest, 2 * 1024 * 1024), (archive, MAX_BYTES + MAX_FILES * 2048 + 10240)):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
            raise ValueError("Invalid or oversized backup input")
    if digest(manifest) != expected_manifest_sha256:
        raise ValueError("Backup manifest does not match external trust anchor")
    record = json.loads(manifest.read_bytes(), object_pairs_hook=unique_fields)
    if record.get("schema") != "gaia-data-backup-v1" or digest(archive) != record["archive_sha256"]:
        raise ValueError("Backup archive hash mismatch")
    expected = validate_rows(record["entries"], roles)
    seen = set()
    with tarfile.open(archive, "r:") as tar:
        for member in tar:
            name = safe_name(member.name, roles)
            if name not in expected or name in seen or member.type not in (tarfile.REGTYPE, tarfile.DIRTYPE) or member.pax_headers:
                raise ValueError("Unexpected, duplicate or dangerous tar entry")
            seen.add(name)
            row = expected[name]
            if (member.uid, member.gid, member.mode, member.mtime, member.size, member.isdir()) != (
                    row["uid"], row["gid"], row["mode"], row["mtime"], row["bytes"], row["kind"] == "directory"):
                raise ValueError("Tar metadata differs from manifest")
            if member.isfile():
                value = hashlib.sha256()
                with tar.extractfile(member) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        value.update(chunk)
                if value.hexdigest() != row["sha256"]:
                    raise ValueError("Tar content differs from manifest")
    if seen != set(expected):
        raise ValueError("Missing backup entries")
    return expected


def check_tree(source, expected):
    observed = set()
    for top in {name.split("/")[0] for name in expected}:
        root = source / top
        for path in [root, *sorted(root.rglob("*"))]:
            name = path.relative_to(source).as_posix()
            if name not in expected:
                raise ValueError("Unexpected restored file")
            observed.add(name)
            row, info = expected[name], path.lstat()
            if (not (stat.S_ISDIR(info.st_mode) if row["kind"] == "directory" else stat.S_ISREG(info.st_mode))
                    or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), int(info.st_mtime)) != (
                        row["uid"], row["gid"], row["mode"], row["mtime"])):
                raise ValueError("Restored role, permissions or type differ")
            if row["kind"] == "file" and (info.st_size != row["bytes"] or digest(path) != row["sha256"]):
                raise ValueError("Restored content differs")
    if observed != set(expected):
        raise ValueError("Missing restored file")


def restore(backup, destination, expected_manifest_sha256, roles):
    # Validate the complete archive before touching destination data. The backup
    # must be mounted read-only, and writers stopped, for the two-pass operation.
    expected = verify(backup, expected_manifest_sha256, roles)
    for top in roles:
        path = destination / top
        if path.is_symlink() or not path.is_dir():
            raise ValueError("Refusing unsafe restore destination")
    for top in roles:
        root = destination / top
        for child in root.iterdir():
            if child.is_symlink() or not child.is_dir():
                child.unlink()
            else:
                shutil.rmtree(child)
    with tarfile.open(backup / "data.tar", "r:") as tar:
        for member in tar:
            target = destination / member.name
            if member.isdir():
                target.mkdir(exist_ok=True)
            else:
                with tar.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
            os.chown(target, member.uid, member.gid)
            os.chmod(target, member.mode)
            os.utime(target, (member.mtime, member.mtime), follow_symlinks=False)
            if member.isfile():
                with target.open("rb") as output:
                    os.fsync(output.fileno())
    # Preserve the role root inodes, including the guardian's private bind mount.
    for name in sorted(expected, key=lambda n: n.count("/"), reverse=True):
        if expected[name]["kind"] == "directory":
            os.utime(destination / name, (expected[name]["mtime"],) * 2)
            sync_directory(destination / name)
    sync_directory(destination)
    check_tree(destination, expected)
    return expected
