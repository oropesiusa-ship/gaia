"""Mechanical durable directory publication. Callers own locking and semantics."""
import ctypes
import errno
import os
from pathlib import Path
import re
import uuid


class InjectedFailure(RuntimeError):
    """Internal test-only crash boundary; never exposed through the CLI."""
    def __init__(self, phase):
        self.phase = phase
        super().__init__("Injected publication failure: " + phase)


def _checkpoint(fault, phase, path):
    if callable(fault):
        fault(phase, path)
    elif fault == phase:
        raise InjectedFailure(phase)


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_tree(path):
    """Flush already validated, small reference trees before publishing links."""
    path = Path(path)
    directories = [path]
    for entry in path.rglob("*"):
        if entry.is_symlink():
            raise ValueError("Refusing symlink in durable reference tree")
        if entry.is_dir():
            directories.append(entry)
        elif entry.is_file():
            with entry.open("rb") as stream:
                os.fsync(stream.fileno())
        else:
            raise ValueError("Non-regular durable reference")
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        fsync_directory(directory)


def read_current(stable):
    path = Path(stable) / "CURRENT"
    if path.is_symlink():
        raise ValueError("CURRENT must be a regular pointer file")
    return path.read_text().strip() if path.exists() else None


def _rename_no_replace(source, destination):
    # Linux is already required by the bwrap workloads. Unlike rename(), this
    # also refuses an empty destination created between exists() and rename().
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise RuntimeError("Durable publication requires Linux renameat2(RENAME_NOREPLACE)")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        number = ctypes.get_errno()
        if number == errno.EEXIST:
            raise FileExistsError(number, os.strerror(number), str(destination))
        raise OSError(number, os.strerror(number), str(destination))


def switch_current(stable, version, expected_current, validate, *, _test_fault=None):
    """Durable compare-and-switch of the existing pointer, under caller's lock."""
    stable = Path(stable)
    if not re.fullmatch(r"v[0-9]{4,}", version):
        raise ValueError("Invalid CURRENT destination")
    final = stable / version
    if read_current(stable) != expected_current:
        raise ValueError("CURRENT changed before pointer commit")
    temporary = stable / (".CURRENT-" + uuid.uuid4().hex + ".tmp")
    _checkpoint(_test_fault, "before_current_write", final)
    with temporary.open("xb") as stream:
        stream.write((version + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    _checkpoint(_test_fault, "before_current_replace", final)
    validate(final)
    if read_current(stable) != expected_current:
        raise ValueError("CURRENT changed during pointer commit")
    os.replace(temporary, stable / "CURRENT")
    _checkpoint(_test_fault, "after_current_replace", final)
    with (stable / "CURRENT").open("rb") as stream:
        os.fsync(stream.fileno())
    _checkpoint(_test_fault, "before_current_directory_fsync", final)
    fsync_directory(stable)
    _checkpoint(_test_fault, "after_current_commit", final)


def publish(stable, version, artifacts, validate, expected_current, *,
            staging_prefix=".staging-", artifact_mode=0o444, _test_fault=None):
    """Stage -> flush -> validate -> rename -> flush -> atomic CURRENT -> flush.

    No statistics, workload or recovery decisions live here. Failed staging is
    retained for the caller's recovery policy. Final directories are never
    overwritten or removed, even if CURRENT could not be committed.
    """
    stable = Path(stable)
    if not re.fullmatch(r"v\d{4,}", version):
        raise ValueError("Invalid version name")
    if not artifacts or any(Path(name).name != name or name in (".", "..") for name in artifacts):
        raise ValueError("Artifacts must be single regular filenames")
    artifacts = {name: bytes(contents) for name, contents in artifacts.items()}

    def check(directory):
        if directory.is_symlink() or {p.name for p in directory.iterdir()} != set(artifacts):
            raise ValueError("Published directory differs from prepared artifacts")
        for name, contents in artifacts.items():
            path = directory / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != contents:
                raise ValueError("Published artifact differs from prepared bytes: " + name)
        validate(directory)
    stable.mkdir(exist_ok=True)
    fsync_directory(stable.parent)
    final = stable / version
    if final.exists() or final.is_symlink():
        raise FileExistsError(str(final))
    if read_current(stable) != expected_current:
        raise ValueError("CURRENT changed before publication")
    staging = stable / f"{staging_prefix}{version}-{uuid.uuid4().hex}"
    staging.mkdir()
    fsync_directory(stable)
    for name, contents in artifacts.items():
        _checkpoint(_test_fault, "before_write:" + name, staging)
        with (staging / name).open("xb") as stream:
            stream.write(contents)
            stream.flush()
            if artifact_mode is not None:
                os.fchmod(stream.fileno(), artifact_mode)
            _checkpoint(_test_fault, "before_file_fsync", staging)
            os.fsync(stream.fileno())
    _checkpoint(_test_fault, "before_staging_fsync", staging)
    fsync_directory(staging)
    check(staging)
    _checkpoint(_test_fault, "before_version_rename", staging)
    _rename_no_replace(staging, final)
    fsync_directory(final)
    fsync_directory(stable)
    _checkpoint(_test_fault, "after_version_rename", final)
    check(final)
    # A non-cooperating pointer writer must not make a stale promotion current.
    if read_current(stable) != expected_current:
        raise ValueError("CURRENT changed before pointer commit")
    switch_current(stable, version, expected_current, check, _test_fault=_test_fault)
    return version
