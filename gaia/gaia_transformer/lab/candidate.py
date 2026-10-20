"""Render de la baseline conocida como candidato autónomo; aún sin genoma/búsqueda."""
import ast
from pathlib import Path


def baseline_source():
    root = Path(__file__).resolve().parents[1]
    model = (root / "model.py").read_text()
    trainer = (root / "trainer.py").read_text()
    tree = ast.parse(trainer)
    classes = [ast.get_source_segment(trainer, node) for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name in ("TrainConfig", "Trainer")]
    # get_source_segment no incluye decoradores; TrainConfig sigue siendo inmutable.
    classes[0] = "@dataclass(frozen=True)\n" + classes[0]
    return (model + "\nimport hashlib\nimport numpy as np\nfrom dataclasses import asdict\n\n" +
            "\n\n".join(classes) + "\n\nclass Candidate(Trainer):\n"
            "    def train(self, steps):\n"
            "        for _ in range(steps):\n"
            "            self.step()\n\n"
            "    def predict(self, contexts):\n"
            "        return self.predict_last(contexts)\n")
