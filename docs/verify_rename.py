"""Execution checks with durable output; does not execute GPU experiments."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidencia_renombrado"


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "fase2"
    results = []
    inventory = json.loads((OUT / "inventario_fase0.json").read_text())
    lock = next(r for r in inventory["files"] if r["path"] == "requirements/tinygpt-cuda-pascal-py314.lock")
    assert hashlib.sha256((ROOT / "requirements/gaia-transformer-cuda-pascal-py314.lock").read_bytes()).hexdigest() == lock["sha256"]
    identity_changes = []
    for item in inventory["files"]:
        name = item["path"]
        if not (name.startswith(("gaia/", "tests/", "requirements/")) or name in {"gaia.py", ".gitignore"}):
            continue
        if "__pycache__" in name:
            continue
        destination = name.replace("tinygpt-", "gaia-transformer-").replace("tinygpt", "gaia_transformer")
        raw = (ROOT / destination).read_bytes()
        restored = raw.replace(b"gaia-transformer-", b"tinygpt-").replace(b"gaia_transformer", b"tinygpt").replace(b"GaiaTransformer", b"TinyGPT").replace(b"GAIA_TRANSFORMER", b"TINYGPT")
        assert hashlib.sha256(restored).hexdigest() == item["sha256"], destination
        identity_changes.append({"original": name, "current": destination, "identity_only": True})
    (OUT / "fase1_identidad_sin_cambios_algoritmicos.json").write_text(json.dumps(identity_changes, indent=2) + "\n")
    for path in [ROOT / "README.md", *ROOT.glob("docs/*.md")]:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if "://" not in target and not target.startswith("#"):
                assert (path.parent / target.split("#")[0]).exists(), (str(path), target)
    for path in [ROOT / "gaia.py", *ROOT.glob("gaia/**/*.py"), *ROOT.glob("gaia/**/*.json"), *ROOT.glob("tests/*.py")]:
        assert not re.search("tinygpt", path.read_text(), re.I), str(path)
    if "--static-only" in sys.argv:
        print("Static source identity, lock hash and Markdown links OK")
        return
    commands = []
    for command in ("baseline", "lab", "benchmark", "prepare", "run", "observe", "research", "meta"):
        prefix = ["python3", "gaia.py", "gaia-transformer-" + command]
        commands.append((prefix + ["--help"], 0))
        commands.append((prefix + ["--unknown-rename-check"], 2))
    for command, args in (("baseline", ["--steps", "0"]), ("observe", ["--steps", "0"]),
                          ("prepare", ["--minutes", "0"]), ("run", ["--max-experiments", "0"]),
                          ("research", ["--minutes", "0"])):
        commands.append((["python3", "gaia.py", "gaia-transformer-" + command, *args], 2))
    commands.append(([sys.executable, "-m", "unittest", "discover", "-s", "tests"], 0))
    for index, (command, expected) in enumerate(commands):
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
        log = OUT / f"{tag}_check_{index:02}.log"
        log.write_text(process.stdout + process.stderr)
        results.append({"command": command, "expected": expected, "returncode": process.returncode,
                        "log": str(log.relative_to(ROOT))})
        print(f"{process.returncode}: {' '.join(command)}", flush=True)
        if process.returncode != expected:
            print(process.stdout + process.stderr)
            raise SystemExit(1)
    (OUT / f"{tag}_checks.json").write_text(json.dumps(results, indent=2) + "\n")
    print("All identity, lock hash, CLI and suite checks passed")


if __name__ == "__main__":
    main()
