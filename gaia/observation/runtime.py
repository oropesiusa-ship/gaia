"""Local runtime and source identities reusing v0.1 identity primitives."""
import hashlib
from importlib import metadata
import platform
from pathlib import Path
import shutil
import sys
import sysconfig

from .. import manifest, provenance
from .local import command


def version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def collect(root, cfg):
    python = {"version": platform.python_version(), "implementation": platform.python_implementation(),
              "abi": sysconfig.get_config_var("SOABI"),
              "executable_sha256": hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()}
    libraries = {name: version(name) for name in ("numpy", "torch", "psutil")}
    bwrap = provenance.bwrap_capability()
    sandbox = {"present": bwrap["available"], "verified": bwrap["verified"],
               "capabilities": bwrap["capabilities"],
               "version": command([shutil.which("bwrap"), "--version"]) if bwrap["available"] else None}
    try:
        identity = manifest.runtime_identity(root, cfg)
        # This identity uses logical paths and an explicit deterministic environment allowlist.
    except (ImportError, OSError, ValueError):
        identity = {"python": python, "libraries": libraries}
    return {"python": python, "libraries": libraries, "sandbox": sandbox,
            "blas_lapack": identity.get("numpy", {}).get("declared_native_backends", {}),
            "identity": identity, "identity_hash": provenance.digest(identity)}


def source(root, cfg):
    inventory = provenance.inventory(root)
    files = {item["path"]: item["sha256"] for item in inventory["files"]}
    for path in sorted((Path(root) / "gaia/observation").glob("*.py")):
        if path.is_symlink():
            raise ValueError("Observation source symlink")
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    protected = {p: h for p, h in files.items() if p.startswith("gaia/protected/")}
    return {"source_aggregate_hash": provenance.aggregate_hash(inventory["files"], cfg),
            "observation_source_hash": provenance.digest(files), "protected_source_identity": provenance.digest(protected),
            "files": files, "inventory_complete": inventory["ok"]}


def git(root):
    prefix = ["git", "-C", str(root)]
    if command(prefix + ["rev-parse", "--is-inside-work-tree"]) != "true":
        return {"repo_present": False}
    # Never record remotes, configuration, status filenames or author identities.
    branch = command(prefix + ["branch", "--show-current"])
    status = command(prefix + ["status", "--porcelain", "--untracked-files=normal"])
    return {"repo_present": True, "branch": branch, "commit": command(prefix + ["rev-parse", "HEAD"]),
            "dirty": bool(status) if status is not None else None}
