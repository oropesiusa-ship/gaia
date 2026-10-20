"""Non-destructive, reproducible inventory for the rename execution record."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "evidencia_renombrado"


def main():
    OUT.mkdir(exist_ok=True)
    if (OUT / "inventario_fase0.json").exists():
        raise FileExistsError("Frozen phase-0 inventory already exists; do not overwrite provenance")
    records = []
    matches = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file() or path.is_symlink():
            continue
        if relative.startswith("docs/evidencia_renombrado/"):
            continue
        # Installed third-party files are inventoried as managed environments,
        # not as project sources; avoid reading several GiB of shared libraries.
        if relative.startswith((".gaia/venvs/", ".gaia/bootstrap-cache/")):
            continue
        raw = path.read_bytes()
        records.append({"path": relative, "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest()})
        if b"\0" not in raw:
            for number, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                if re.search("tinygpt", line, re.I):
                    matches.append({"path": relative, "line": number, "text": line})
    payload = {"files": records, "old_name_occurrences": matches,
               "managed_environments": [str(p.relative_to(ROOT)) for p in sorted((ROOT / ".gaia/venvs").iterdir())],
               "cache_roots": [str(p.relative_to(ROOT)) for p in sorted((ROOT / ".gaia/bootstrap-cache").iterdir())]}
    (OUT / "inventario_fase0.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    reports = {}
    for item in records:
        if item["path"].startswith(".gaia/reports/"):
            report = "/".join(item["path"].split("/")[:3])
            reports.setdefault(report, []).append(item["path"])
    affected = {m["path"] for m in matches}
    cleanup = {
        "obsolete_state_roots": [str(p.relative_to(ROOT)) for p in sorted(ROOT.glob("state_tinygpt*"))],
        "obsolete_environments": [p for p in payload["managed_environments"] if "tinygpt" in p],
        "obsolete_configs": [r["path"] for r in records if r["path"].startswith(".gaia/configs/") and r["path"] in affected],
        "reports_requiring_review": {k: v for k, v in reports.items() if any(p in affected for p in v)},
        "preserve": ["state/", "state_numpy_mlp_6446deabc01ec4be/", "demo_evidence/", ".gaia/venvs/cpu-numpy-6446deabc01ec4be/", ".gaia/configs/6446deabc01ec4be.json"],
    }
    (OUT / "limpieza_delimitada_fase0.json").write_text(json.dumps(cleanup, indent=2) + "\n")
    print(f"Inventoried {len(records)} files; {len(matches)} old-name lines")
    print("Legacy assets:")
    print(json.dumps([r for r in records if r["path"].startswith("legacy_v0/")], indent=2))


if __name__ == "__main__":
    main()
