"""El código del evaluador y el benchmark están protegidos por hash."""
import json
from pathlib import Path

from .store import sha256, atomic_write


def protected_files(root, state_dir="state"):
    root = Path(root)
    state = Path(state_dir)
    if not state.is_absolute():
        state = root / state
    fs = sorted((root / "gaia" / "protected").glob("*.py"))
    fs += [state / "benchmark.json", state / "stable" / "v0000" / "trainer.py"]
    return [f for f in fs if f.exists()]


def write_manifest(root, state_dir="state"):
    root = Path(root)
    state = Path(state_dir)
    if not state.is_absolute():
        state = root / state
    m = {str(f.relative_to(root)): sha256(f) for f in protected_files(root, state)}
    atomic_write(state / "manifest.json", json.dumps(m, indent=1))


def verify(root, state_dir="state"):
    """Devuelve lista de archivos protegidos modificados (vacía si todo coincide)."""
    root = Path(root)
    state = Path(state_dir)
    if not state.is_absolute():
        state = root / state
    mf = state / "manifest.json"
    if not mf.exists():
        return []
    m = json.loads(mf.read_text())
    bad = []
    for rel, h in m.items():
        p = root / rel
        if not p.exists() or sha256(p) != h:
            bad.append(rel)
    return bad
