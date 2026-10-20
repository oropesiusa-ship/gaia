"""Create only the owner-authorized ext4 file on the identified Samsung SSD."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.bootstrap import Session, locked, write_json

VOLUME = Path("/run/media/mingororo/661EC3B41EC37C15")
IMAGE = VOLUME / "GAIA-build-workspace.ext4"
SIZE = 120 * 1024**3


def prepare(session):
    if os.geteuid() == 0:
        raise ValueError("Prepare as the normal owner, not host root")
    mount = json.loads(subprocess.check_output(["findmnt", "--json", "--target", str(VOLUME),
        "--output", "SOURCE,TARGET,FSTYPE,UUID,OPTIONS"], text=True))["filesystems"][0]
    if (mount["target"] != str(VOLUME) or mount["uuid"] != "661EC3B41EC37C15"
            or mount["fstype"] != "ntfs3" or "rw" not in mount["options"].split(",")):
        raise ValueError("Authorized SSD volume is not mounted read/write at the expected path")
    inventory = json.loads(subprocess.check_output(["lsblk", "--json", "--tree", "--bytes", "--output",
        "PATH,TYPE,MODEL,SERIAL,SIZE,UUID"], text=True))["blockdevices"]
    owners = [disk for disk in inventory if any(p.get("uuid") == mount["uuid"] for p in disk.get("children", []))]
    if (len(owners) != 1 or owners[0]["model"] != "Samsung SSD 870 EVO 1TB"
            or owners[0]["serial"] != "S626NF0R252560W" or owners[0]["size"] != 1000204886016):
        raise ValueError("SSD identity mismatch")
    if VOLUME.is_symlink() or not VOLUME.is_dir() or IMAGE.exists() or IMAGE.is_symlink():
        raise ValueError("Workspace file already exists or path is not the expected volume")
    free = shutil.disk_usage(VOLUME).free
    if free < SIZE + 20 * 1024**3:
        raise ValueError("Insufficient SSD space for allocation and retained margin")
    session.report.update(authorization="Owner explicitly approved this ext4 workspace file on the Samsung SSD",
        volume_uuid=mount["uuid"], image=str(IMAGE), image_bytes=SIZE, before_free_bytes=free,
        physical_partitions_modified=False, existing_files_modified=False,
        mount_requires_human=True)
    session.save()
    with IMAGE.open("xb"):
        pass
    session.command("allocate-workspace-file", ["fallocate", "--length", str(SIZE), str(IMAGE)], timeout=600)
    session.command("create-workspace-ext4", ["mkfs.ext4", "-q", "-m", "0", "-L", "GAIA-BUILD",
        "-E", f"root_owner={os.getuid()}:{os.getgid()}", str(IMAGE)], timeout=600)
    session.command("check-workspace-ext4", ["e2fsck", "-f", "-n", str(IMAGE)], timeout=600)
    uuid = session.command("workspace-ext4-identity", ["blkid", "-p", "-s", "UUID", "-o", "value", str(IMAGE)]).strip()
    state = {"status": "EXT4_WORKSPACE_FILE_READY_AWAITING_MOUNT", "image": str(IMAGE),
        "image_bytes": SIZE, "filesystem_uuid": uuid, "volume_uuid": mount["uuid"],
        "mountpoint": "/mnt/gaia-build", "owner_uid": os.getuid(), "owner_gid": os.getgid(),
        "allocated_bytes": IMAGE.stat().st_blocks * 512, "report_dir": str(session.directory.resolve()),
        "partitions_modified": False, "mounted": False}
    write_json(ROOT / ".gaia/build-workspace.json", state)
    session.report.update(workspace=state, after_free_bytes=shutil.disk_usage(VOLUME).free)
    session.finish(state["status"])


if __name__ == "__main__":
    session = Session(ROOT)
    try:
        with locked(ROOT / ".gaia/bootstrap.lock"):
            prepare(session)
    except Exception as exc:
        session.finish("FAILED", exc)
        raise
