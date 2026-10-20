"""Política parametrizable del buscador; adopción solo con prueba reservada."""
import json
import math
from pathlib import Path


DEFAULT = {"version": 0, "ucb_c": math.sqrt(2), "p_global": 0.0, "small_model_prior": 0.0}


def validate(strategy):
    if set(strategy) != set(DEFAULT) or type(strategy["version"]) is not int or strategy["version"] < 0:
        raise ValueError("Estrategia de búsqueda inválida")
    for key, lo, hi in (("ucb_c", .1, 4.), ("p_global", 0., 1.), ("small_model_prior", 0., 1.)):
        if not isinstance(strategy[key], (int, float)) or not math.isfinite(strategy[key]) or not lo <= strategy[key] <= hi:
            raise ValueError("Parámetro de estrategia fuera de rango: " + key)
    return strategy


def choose_operator(stats, rng, total, strategy=None):
    strategy = validate(strategy or DEFAULT)
    scores = {key: (item["reward"] + .5) / (item["attempts"] + 1)
              + strategy["ucb_c"] * math.sqrt(math.log(total + 2) / (item["attempts"] + 1))
              + (strategy["small_model_prior"] if key in ("dim", "layers") else 0.)
              + rng.random() * .05 for key, item in stats.items()}
    if strategy["p_global"] and rng.random() < strategy["p_global"]:
        return rng.choice(list(stats))
    return max(scores, key=scores.get)


def paired_bound(reference, candidate, critical):
    import statistics
    if len(reference) != len(candidate) or len(reference) < 20:
        raise ValueError("Se requieren al menos 20 semillas de búsqueda pareadas")
    differences = [b - a for a, b in zip(reference, candidate)]
    if not all(math.isfinite(value) for value in differences):
        raise ValueError("Puntuaciones no finitas")
    mean = statistics.mean(differences)
    margin = critical * statistics.stdev(differences) / math.sqrt(len(differences))
    return {"mean_auc_diff": mean, "lower": mean - margin, "upper": mean + margin,
            "n": len(differences), "critical": critical, "supported": mean + margin < -.01}


def load(state, frozen):
    """No confía en una etiqueta adoptada; recalcula la prueba desde sus puntuaciones."""
    path = Path(state) / "strategy_gpu.json"
    if not path.exists():
        return dict(DEFAULT)
    saved = json.loads(path.read_text())
    report = json.loads(Path(saved["evidence"]).read_text())
    validate(saved["strategy"])
    from .metastudy import protocol_digest
    if (report.get("status") != "GPU_META_COMPLETE" or not report.get("adopted")
            or report["selected"] != saved["strategy"] or report["production_benchmark"] != frozen
            or report["protocol_digest"] != protocol_digest()):
        raise RuntimeError("Evidencia de metaestrategia distinta de su identidad")
    selected_scores = report["transfer_scores"]["selected"]
    for competitor in ("previous", "random"):
        if not paired_bound(report["transfer_scores"][competitor], selected_scores, 2.023)["supported"]:
            raise RuntimeError("Estrategia sin mejora de transferencia verificada")
    selected_tuning = next((item for item in report["tuning_candidates"] if item["strategy"] == saved["strategy"]), None)
    if selected_tuning is None or not paired_bound(report["tuning_previous_scores"], selected_tuning["scores"], 3.0)["supported"]:
        raise RuntimeError("Estrategia sin evidencia de ajuste")
    return saved["strategy"]
