"""Inventory-bounded cleanup, permitted only after phases 0–5 are recorded OK.

Default is review only. --apply removes generated artifacts, never active sources.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidencia_renombrado"


def main():
    inventory = json.loads((OUT / "inventario_fase0.json").read_text())
    bounded = json.loads((OUT / "limpieza_delimitada_fase0.json").read_text())
    roots = bounded["obsolete_state_roots"] + bounded["obsolete_environments"] + bounded["obsolete_configs"]
    reviewed = []
    for name in bounded["reports_requiring_review"]:
        path = ROOT / name / "report.json"
        if not path.exists():
            readiness = ROOT / name / "interrupted/readiness.json"
            if readiness.exists():
                payload = json.loads(readiness.read_text())
                gates = payload["gates"]
                prefix = gates["G0_runtime"]["runtime"]["prefix"]
                hashes = gates["G3_integrity"]["hashes"]
                assert prefix in [str(ROOT / env) for env in bounded["obsolete_environments"]]
                assert any(p.startswith("gaia/tinygpt/") for p in hashes)
                workload = "tinygpt_cuda"
                roots.append(name)
                reviewed.append({"path": name, "workload": workload, "action": "remove",
                                 "reason": "Interrupted old CUDA recovery fixture; replaced by verified phase4 recovery"})
                continue
            reviewed.append({"path": name, "action": "preserve", "reason": "No bootstrap report: inspect separately; historical diagnostic evidence"})
            continue
        report = json.loads(path.read_text())
        profile = report.get("profile")
        workload = report.get("effective_config", {}).get("workload", {}).get("id")
        old_cuda = profile == "tinygpt-cuda-pascal" and workload in (None, "tinygpt_cuda")
        cpu_steps = [s["stage"] for s in report.get("steps", []) if s.get("stage") in ("selftest", "prepare")]
        remove = old_cuda and not cpu_steps
        reviewed.append({"path": name, "profile": profile, "workload": workload,
                         "cpu_campaign_steps": cpu_steps, "action": "remove" if remove else "preserve",
                         "reason": "Exclusive obsolete CUDA workload" if remove else "Mixed/CPU/diagnostic evidence retained"})
        if remove:
            roots.append(name)
    caches = [str(p.relative_to(ROOT)) for p in ROOT.glob("gaia/tinygpt/**/__pycache__")]
    caches += [str(p.relative_to(ROOT)) for p in ROOT.glob("tests/__pycache__/test_tinygpt*")]
    roots += caches
    # Roots must be concrete, local and drawn from the initial inventory or cache list.
    for name in roots:
        path = ROOT / name
        assert path.is_relative_to(ROOT) and not path.is_symlink()
    manifest = {"roots": roots, "report_review": reviewed,
                "preserved_roots": bounded["preserve"] + [".gaia/bootstrap-cache/"],
                "removed_files": [r for r in inventory["files"] if any(r["path"] == name or r["path"].startswith(name + "/") for name in roots)]}
    (OUT / "limpieza_fase6_revision.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"roots": roots, "reports_removed": sum(r["action"] == "remove" for r in reviewed),
                      "reports_preserved": sum(r["action"] == "preserve" for r in reviewed)}, indent=2))
    if "--apply" not in sys.argv:
        return
    plan = (ROOT / "docs/PLAN_RENOMBRADO_GAIA_TRANSFORMER.md").read_text()
    for phase in range(6):
        assert any(line.startswith(f"| {phase} |") and line.endswith("| OK |") for line in plan.splitlines())
    corpus = ROOT / "archives/text_prototype/sample_corpus.txt"
    assert hashlib.sha256(corpus.read_bytes()).hexdigest() == "3d8922516deb38620bc1edd5f5bd4c3194dc42b255d80dea890a9d85a8f8b4e7"
    for item in inventory["files"]:
        if item["path"].startswith("legacy_v0/"):
            assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    for name in roots:
        path = ROOT / name
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    for folder in (ROOT / "gaia/tinygpt/lab", ROOT / "gaia/tinygpt"):
        if folder.exists():
            folder.rmdir()
    manifest["status"] = "CLEANUP_APPLIED"
    (OUT / "limpieza_fase6_aplicada.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Removed {len(roots)} bounded artifact roots. Shared cache and CPU evidence preserved.")


if __name__ == "__main__":
    main()
