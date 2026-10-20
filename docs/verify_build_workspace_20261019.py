"""Verify the mounted workspace and Linux file semantics, without host root."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.bootstrap import Session, locked, write_json


def verify(session):
    state_path = ROOT / ".gaia/build-workspace.json"
    state = json.loads(state_path.read_text())
    mountpoint = Path(state["mountpoint"])
    mounted = json.loads(subprocess.check_output(["findmnt", "--json", "--target", str(mountpoint),
        "--output", "SOURCE,TARGET,FSTYPE,UUID,OPTIONS"], text=True))["filesystems"][0]
    if (mountpoint.is_symlink() or mounted["target"] != str(mountpoint) or mounted["fstype"] != "ext4"
            or mounted["uuid"] != state["filesystem_uuid"] or "rw" not in mounted["options"].split(",")):
        raise ValueError("Workspace is not the expected mounted ext4 filesystem")
    device = Path(mounted["source"]).name
    backing = Path("/sys/class/block") / device / "loop/backing_file"
    if not backing.is_file() or Path(backing.read_text().strip()).resolve() != Path(state["image"]).resolve():
        raise ValueError("Workspace loop backing differs from the authorized file")
    if os.getuid() != state["owner_uid"] or mountpoint.stat().st_uid != os.getuid():
        raise ValueError("Workspace owner mismatch")
    free = shutil.disk_usage(mountpoint).free
    if free < 84521353216:
        raise ValueError("Workspace still lacks the current image build budget")
    with tempfile.TemporaryDirectory(prefix="gaia-fs-probe-", dir=mountpoint) as directory:
        probe = Path(directory)
        file = probe / "file"
        file.write_bytes(b"GAIA_WORKSPACE_PROBE\n")
        file.chmod(0o640)
        hard = probe / "hard"
        os.link(file, hard)
        link = probe / "symbolic"
        link.symlink_to("file")
        os.setxattr(file, "user.gaia_workspace_probe", b"verified")
        if (file.stat().st_mode & 0o777 != 0o640 or hard.stat().st_ino != file.stat().st_ino
                or link.read_bytes() != file.read_bytes()
                or os.getxattr(file, "user.gaia_workspace_probe") != b"verified"):
            raise ValueError("Linux file semantics failed")
        sparse = probe / "sparse"
        with sparse.open("xb") as stream:
            stream.truncate(64 * 1024**2)
        if sparse.stat().st_blocks * 512 >= sparse.stat().st_size:
            raise ValueError("Sparse-file probe failed")
    for name in ("tmp", "reports", "artifacts"):
        path = mountpoint / name
        if not path.exists():
            path.mkdir(mode=0o755)
        if path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid():
            raise ValueError("Unexpected workspace subdirectory")
    state.update(status="LINUX_BUILD_WORKSPACE_READY", mounted=True, free_bytes=free,
        verification_report=str(session.directory.resolve()), temporary_directory=str(mountpoint / "tmp"),
        artifacts_directory=str(mountpoint / "artifacts"), filesystem_semantics_verified=True)
    write_json(state_path, state)
    session.report.update(workspace=state, partitions_modified=False,
        remaining_integration="Use external artifact/report output as well as TMPDIR; the project storage gate remains until builder integration")
    session.finish("LINUX_BUILD_WORKSPACE_READY")


if __name__ == "__main__":
    session = Session(ROOT)
    try:
        with locked(ROOT / ".gaia/bootstrap.lock"):
            verify(session)
    except Exception as exc:
        session.finish("FAILED", exc)
        raise
