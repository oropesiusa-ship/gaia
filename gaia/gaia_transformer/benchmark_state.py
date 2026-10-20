"""Carga verificada del benchmark de Fase 3 antes de futuras comparaciones."""
import hashlib
import json
from pathlib import Path

from gaia.gaia_transformer.lab import benchmark
from gaia.gaia_transformer.lab.calibration import SPEC


def load(root, cfg, runtime):
    state_dir = Path(cfg["workload"]["state_dir"])
    if state_dir.is_absolute() or len(state_dir.parts) != 1 or state_dir.name in (".", "..", ""):
        raise ValueError("Directorio de benchmark debe ser relativo, único y local")
    state = Path(root) / state_dir
    frozen = json.loads((state / "benchmark.json").read_text())
    baseline = json.loads((state / "baseline.json").read_text())
    if (frozen["config"] != cfg or frozen["runtime"] != runtime or frozen["spec"] != SPEC
            or frozen["identity"] != benchmark.identity()):
        raise RuntimeError("Identidad de benchmark distinta: nueva calibración/estado requeridos")
    actual_hash = hashlib.sha256(baseline["source"].encode()).hexdigest()
    if actual_hash != baseline["sha256"] or actual_hash != frozen["baseline_sha256"]:
        raise RuntimeError("Baseline congelada modificada")
    return frozen, baseline["source"]
