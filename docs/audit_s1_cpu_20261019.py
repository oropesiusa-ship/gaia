"""Audit existing acceptance records without rebuilding or booting the candidate."""
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.bootstrap import Session, locked

IMAGE = "195cd3661217bd6cc4de8af38e314786a097994940cd61288ed4d1de2a9ed4de"
MANIFEST = "7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26"
FPR = "6BF5C62DC530889F3D7C644F678D00EC8B5BF748"


def require(value, message):
    if not value:
        raise ValueError(message)


def audit(session):
    sources = []

    def record(name, status):
        path = ROOT / ".gaia/reports" / name / "report.json"
        row = json.loads(path.read_text())
        require(row["status"] == status, f"Unexpected status: {name}")
        sources.append(str(path.relative_to(ROOT)))
        return row

    signature = record("20261019T091206Z-a19b9124", "SIGNED_ARTIFACTS_VERIFIED")
    require(signature["manifest_sha256"] == MANIFEST and signature["expected_fingerprint"] == FPR,
            "Wrong signed request")
    require(any(r["name"] == "disk.raw" and r["sha256"] == IMAGE for r in signature["verified_artifacts"]),
            "Wrong signed image")
    scenarios = []
    for name in ("20261019T081025Z-4e6e623f", "20261019T083236Z-4b77c01a"):
        row = record(name, "VM_BOOT_SELECTION_VALIDATED")
        require(row["image_sha256"] == IMAGE, "Scenario image mismatch")
        scenarios.extend(row["boot_scenarios"])
    expected = {"normal-A", "normal-B", "attempt-exhaustion", "interrupted-publication",
                "corrupted-B", "data-recovery", "publication-interrupted", "health-bless",
                "health-reject", "usb-smoke"}
    counts = Counter(r["scenario"] for r in scenarios)
    require(set(counts) == expected and all(n == 3 for n in counts.values()), "Incomplete scenario matrix")
    require(all(r["status"] == "ok" for r in scenarios), "Failed scenario")
    boots = [b for r in scenarios for b in r["boots"]]
    successes = [b for b in boots if b.get("status") == "VM_FOUNDATION_OK"]
    require(successes and all(b["offline"] and b["catalogue"] == "inventory-only"
            and b["sandbox"]["status"] == "SANDBOX_CPU_OK" for b in successes), "Isolation evidence missing")
    negative = record("20261019T085227Z-678598b8", "VM_INVALID_INSTALL_SIGNATURE_REJECTED")
    require(negative["image_sha256"] == IMAGE and len(negative["negative_recovery_results"]) == 3
            and all(r["signature_rejected"] and r["target_unchanged"] for r in negative["negative_recovery_results"]),
            "Signature rejection evidence missing")
    runtime = record("20261019T080658Z-5d9d1767", "CPU_DELIVERY_RUNTIME_VALIDATED")
    require(runtime["image_sha256"] == IMAGE and len(runtime["runtime_results"]) == 3,
            "Persistent runtime evidence missing")
    recovery = record("20261019T091600Z-78c27069", "VM_SIGNED_RECOVERY_VALIDATED")
    require(recovery["recovery_image_sha256"] == IMAGE and recovery["manifest_sha256"] == MANIFEST,
            "Recovery identity mismatch")
    rows = recovery["recovery_results"]
    require([(r["repeat"], r["mode"]) for r in rows] ==
            [(n, mode) for n in range(1, 4) for mode in ("install", "repair-system")], "Incomplete recovery suite")
    for row in rows:
        boot = row["installed_boot"]
        repair = row["mode"] == "repair-system"
        require(row["recovery"]["status"] == ("VM_SYSTEM_REPAIRED" if repair else "VM_IMAGE_INSTALLED"),
                "Wrong recovery result")
        require(not repair or row["recovery"]["data_preserved"], "DATA not preserved")
        require(boot["ledger_sequence"] == (2 if repair else 1) and boot["slot"] == "A", "Ledger/slot mismatch")
    for boot in runtime["runtime_results"] + [r["installed_boot"] for r in rows]:
        require(boot["status"] == "GAIA_RUNTIME_READY" and boot["authority"] == "L0"
                and boot["runtime"]["uid"] != 0 and boot["runtime"]["pip_check"] == "No broken requirements found."
                and boot["persistent_after_ready_seconds"] >= 10
                and boot["owner_public_trust"]["fingerprint"] == FPR, "Invalid operational boot")
    image = json.loads((ROOT / ".gaia/reports/20261019T075104Z-0bda6b85/image-manifest.json").read_text())
    cleanup = image["native_toolchain_cleanup"]
    require(image["disk_sha256"] == IMAGE and len(cleanup["removed"]) == 34
            and len(cleanup["retained"]) == 174 and not cleanup["autoremove_used"], "Toolchain inventory mismatch")
    session.report.update(image_sha256=IMAGE, manifest_sha256=MANIFEST, evidence_sources=sources,
        scenario_repetitions=dict(counts), matrix_boots=len(boots), signed_installs=3, signed_repairs=3,
        operational_boots_after_recovery=6, data_preserved=True, cpu_vm_acceptance_complete=True,
        s1_delivery_complete=False, f1_complete=False, physical_media_written=False,
        production_blockers=["Recovery installer and signed bundle enforce QEMU-only lab context",
                             "Physical NVIDIA/kernel/module profile not implemented or accepted"],
        interpretation="S1 CPU/VM requirements accepted; physical delivery gate remains open")
    session.finish("S1_CPU_VM_ACCEPTED")


if __name__ == "__main__":
    session = Session(ROOT)
    try:
        with locked(ROOT / ".gaia/bootstrap.lock"):
            audit(session)
    except Exception as exc:
        session.finish("FAILED", exc)
        raise
