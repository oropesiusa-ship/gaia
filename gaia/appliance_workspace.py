"""Validate the specifically authorized mounted build filesystem before use."""
import json
import os
from pathlib import Path
import subprocess
import shutil

from .bootstrap import Session, write_json


class WorkspaceSession(Session):
    """Large VM fixtures on SSD; mirror machine-readable/final reports locally."""
    def __init__(self, root):
        temporary, artifacts = workspace(root)
        super().__init__(root)
        self.local_directory = self.directory
        self.directory = artifacts / self.directory.name
        self.directory.mkdir()
        self.report.update(local_report_directory=str(self.local_directory.resolve()),
                           external_report_directory=str(self.directory.resolve()))

    def save(self):
        super().save()
        write_json(self.local_directory / "report.json", self.report)

    def finish(self, status, error=None):
        super().finish(status, error)
        shutil.copyfile(self.directory / "REPORT.md", self.local_directory / "REPORT.md")


def workspace(root):
    state = json.loads((Path(root) / ".gaia/build-workspace.json").read_text())
    mount = Path(state["mountpoint"])
    if state.get("status") != "LINUX_BUILD_WORKSPACE_READY" or mount.is_symlink():
        raise ValueError("Build workspace has not been verified")
    row = json.loads(subprocess.check_output(["findmnt", "--json", "--target", str(mount),
        "--output", "SOURCE,TARGET,FSTYPE,UUID,OPTIONS"], text=True))["filesystems"][0]
    if (row["target"] != str(mount) or row["uuid"] != state["filesystem_uuid"]
            or row["fstype"] != "ext4" or "rw" not in row["options"].split(",")):
        raise ValueError("Workspace mount changed or disappeared")
    backing = Path("/sys/class/block") / Path(row["source"]).name / "loop/backing_file"
    if Path(backing.read_text().strip()).resolve() != Path(state["image"]).resolve():
        raise ValueError("Workspace backing file changed")
    paths = [mount / name for name in ("tmp", "artifacts")]
    for path in paths:
        if (path.is_symlink() or not path.is_dir() or path.stat().st_uid != os.getuid()
                or path.stat().st_dev != mount.stat().st_dev):
            raise ValueError("Invalid workspace subdirectory")
    return paths
