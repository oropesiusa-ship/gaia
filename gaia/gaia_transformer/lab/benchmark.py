from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from .. import data
from ..phase1 import cross_entropy


@dataclass(frozen=True)
class TrialSpec:
    seed: int = 9000
    steps: int = 100
    eval_every: int = 25
    split: str = "validation"
    target_loss: float | None = None
    hits_needed: int = 2

    def __post_init__(self):
        if (type(self.seed) is not int or not 0 <= self.seed < 2**32 or type(self.steps) is not int
                or not 0 <= self.steps <= 10000 or type(self.eval_every) is not int or not 1 <= self.eval_every <= 10000
                or self.split not in ("validation", "audit") or type(self.hits_needed) is not int or self.hits_needed < 2):
            raise ValueError("Especificación de trial GPU inválida")
        if self.target_loss is not None and (not math.isfinite(self.target_loss) or self.target_loss < 0):
            raise ValueError("Objetivo de pérdida inválido")


def private_data(spec):
    frozen = json.loads(Path(data.__file__).with_name("corpus_v1.json").read_text())
    if data.manifest() != frozen:
        raise RuntimeError("CORPUS_INTEGRITY: digest del corpus no coincide")
    train = data.records(data.generate_split(data.DEFAULT_SPEC, "train"))
    contexts, targets = data.private_validation(data.generate_split(data.DEFAULT_SPEC, spec.split))
    return train, contexts, targets, frozen["sha256"]


def identity():
    root = Path(__file__).resolve().parents[3]
    tiny = Path(__file__).resolve().parents[1]
    files = list(Path(__file__).parent.glob("*.py"))
    files += [tiny / name for name in ("data.py", "corpus_v1.json", "model.py", "trainer.py", "phase1.py")]
    files += [root / "gaia/protected/runtime.py"]
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}
