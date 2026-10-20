"""Audit the new runtime against prebuilt modules and remaining image budget."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.appliance_image import partition_spec, GIB, MIB
from gaia.appliance_rootfs import sha256
from gaia.bootstrap import Session, locked


def audit(session):
    runtime = ROOT / ".gaia/reports/20261019T103937Z-05e8888d"
    built = ROOT / ".gaia/reports/20261019T103018Z-602c9ef1"
    manifest = json.loads((runtime / "rootfs-manifest.json").read_text())
    if sha256(runtime / "rootfs.tar") != manifest["rootfs_sha256"]:
        raise ValueError("NVIDIA rootfs hash mismatch")
    expected = {}
    with tarfile.open(built / "nvidia-modules.tar") as archive:
        for member in archive:
            if member.isfile() and ".ko" in member.name:
                expected[Path(member.name).name] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
    observed = {}
    with tarfile.open(runtime / "rootfs.tar", "r|") as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if member.isfile() and name.startswith("lib/modules/6.12.107+deb13-amd64/updates/dkms/"):
                observed[Path(name).name] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
    # usr-merged roots may store modules under usr/lib.
    if not observed:
        with tarfile.open(runtime / "rootfs.tar", "r|") as archive:
            for member in archive:
                name = member.name.removeprefix("./")
                if member.isfile() and name.startswith("usr/lib/modules/6.12.107+deb13-amd64/updates/dkms/"):
                    observed[Path(name).name] = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
    if len(expected) != 4 or observed != expected:
        raise ValueError("Integrated modules do not match the verified module build")
    for name in ("libcuda1", "libnvidia-ml1", "nvidia-smi"):
        if manifest["packages"][name]["Version"] != "580.178.04-1":
            raise ValueError("NVIDIA runtime package version mismatch")
    parts = partition_spec(manifest["rootfs_bytes"])
    disk_estimate = sum(p["bytes"] for p in parts) + 258 * MIB
    budget = (2 * manifest["rootfs_bytes"] + parts[2]["bytes"] + 2 * disk_estimate
              + sum(p["bytes"] for p in parts if p["name"] in ("GAIA-ESP", "GAIA-CORE", "GAIA-DATA")) + 5 * GIB)
    free = shutil.disk_usage(ROOT).free
    session.report.update(runtime_dir=str(runtime), runtime_sha256=manifest["rootfs_sha256"],
        rootfs_bytes=manifest["rootfs_bytes"], module_hashes=observed, integrated_module_readback_ok=True,
        required_image_build_budget_bytes=budget, workspace_free_bytes=free,
        workspace_deficit_bytes=max(0, budget - free), gpu_tested=False, physical_media_written=False,
        cpu_vm_reference_unchanged=True, f1_complete=False,
        pending=["CUDA runtime/installer image construction", "new image VM acceptance and physical signature",
                 "physical preparation and S0/S2-S4"])
    session.finish("NVIDIA_IMAGE_WORKSPACE_BLOCKED" if free < budget else "NVIDIA_RUNTIME_AUDITED")


if __name__ == "__main__":
    session = Session(ROOT)
    try:
        with locked(ROOT / ".gaia/bootstrap.lock"):
            audit(session)
    except Exception as exc:
        session.finish("FAILED", exc)
        raise
