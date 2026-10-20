"""Audit completed VM cases and prepare the first physical GPU diagnostic signature."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.appliance_rootfs import sha256
from gaia.appliance_vm_scenarios import SCENARIOS
from gaia.appliance_workspace import workspace
from gaia.bootstrap import Session, locked, write_json


def prepare(session):
    temporary, artifacts = workspace(ROOT)
    image_dir = artifacts / "20261019T111348Z-95cd9936"
    manifest = json.loads((image_dir / "image-manifest.json").read_text())
    if manifest["profile"] != "nvidia-delivery-candidate" or sha256(image_dir / "disk.raw") != manifest["disk_sha256"]:
        raise ValueError("NVIDIA candidate identity mismatch")
    first = artifacts / "20261019T112849Z-1a4842c4"
    second = artifacts / "20261019T122929Z-aa6cdca6"
    records = [json.loads((p / "report.json").read_text()) for p in (first, second)]
    if any(r["image_sha256"] != manifest["disk_sha256"] for r in records):
        raise ValueError("Mixed VM image identities")
    if records[1]["status"] != "VM_BOOT_SELECTION_VALIDATED":
        raise ValueError("Remaining scenarios did not complete")
    # Only complete saved cases are consumed from the tool-timeout run. The
    # partial health-reject repetition and its duplicate first case are excluded.
    rows = [r for r in records[0]["boot_scenarios"] if r["scenario"] not in ("health-reject", "usb-smoke")]
    rows += records[1]["boot_scenarios"]
    expected = {(scenario, repeat) for scenario in SCENARIOS for repeat in range(1, 4)}
    if len(rows) != 30 or {(r["scenario"], r["repeat"]) for r in rows} != expected or any(r["status"] != "ok" for r in rows):
        raise ValueError("Incomplete/nonunique NVIDIA VM matrix")
    if sum(len(r["boots"]) for r in rows) != 63:
        raise ValueError("Wrong accepted VM boot count")
    request_dir = artifacts / session.directory.name
    request_dir.mkdir()
    for name in ("disk.raw", "image-manifest.json"):
        os.link(image_dir / name, request_dir / name)
    request = {"schema": "gaia-signed-artifacts-v1", "purpose": "lab",
        "kind": "gaia-physical-gpu-preflight-v1", "signing_fingerprint": manifest["owner_fingerprint"],
        "profile": "nvidia-delivery-candidate", "authority": "L0",
        "scope": "First physical GPU diagnostic boot on owner-authorized external recovery HDD; not internal installation or F1 acceptance",
        "artifacts": [{"name": name, "bytes": (request_dir / name).stat().st_size,
                       "sha256": sha256(request_dir / name)} for name in ("disk.raw", "image-manifest.json")]}
    path = request_dir / "gpu-preflight-manifest.json"
    write_json(path, request)
    session.report.update(image_dir=str(image_dir), image_sha256=manifest["disk_sha256"],
        vm_evidence_reports=[str(first), str(second)], selected_complete_cases=30, accepted_matrix_boots=63,
        tool_timeout_run_status=records[0]["status"], excluded_partial_and_duplicate_health_cases=True,
        signature_request=str(path), manifest_sha256=sha256(path), expected_signature=str(path) + ".asc",
        gpu_tested=False, physical_media_written=False, f1_complete=False,
        pending=["owner detached signature for first GPU diagnostic image", "human privileged recovery-medium preparation",
                 "physical GPU diagnostic boot and evidence", "physical installer, sizing and S0/S2-S4 acceptance"])
    session.finish("AWAITING_OWNER_PHYSICAL_GPU_PREFLIGHT_SIGNATURE")


if __name__ == "__main__":
    session = Session(ROOT)
    try:
        with locked(ROOT / ".gaia/bootstrap.lock"):
            prepare(session)
    except Exception as exc:
        session.finish("FAILED", exc)
        raise
