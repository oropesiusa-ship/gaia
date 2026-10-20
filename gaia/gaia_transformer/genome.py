"""Espacio conocido GaiaTransformer fp32; propuestas adaptativas, sin alterar laboratorio."""
import ast
import hashlib
import json
import math
import random

from .lab.candidate import baseline_source
from .lab.guard import check_source
from .search_strategy import DEFAULT, choose_operator

BASE = {"dim": 64, "layers": 2, "heads": 2, "batch": 32, "lr": 0.003,
        "weight_decay": 0.01, "dropout": 0.0, "optimizer": "adamw"}
SPACE = {"dim": [32, 64, 96], "layers": [1, 2, 3], "heads": [1, 2, 4],
         "batch": [16, 32, 64], "lr": [0.001, 0.003, 0.006],
         "weight_decay": [0.0, 0.01, 0.1], "dropout": [0.0, 0.1], "optimizer": ["adamw", "sgd"]}
RESEARCH_SPACE = {"optimizer_impl": ["scalar", "foreach"], "clip_impl": ["scalar", "foreach"]}


def validate(genome):
    if (not set(BASE) <= set(genome) or set(genome) - set(BASE) - set(RESEARCH_SPACE)
            or any(genome[key] not in values for key, values in SPACE.items())
            or any(genome[key] not in RESEARCH_SPACE[key] for key in RESEARCH_SPACE if key in genome)):
        raise ValueError("Genoma fuera del espacio GaiaTransformer fp32")
    if any(type(genome[k]) is not int for k in ("dim", "layers", "heads", "batch")) or genome["dim"] % genome["heads"]:
        raise ValueError("Dimensiones/heads incompatibles")
    return genome


def digest(genome):
    validate(genome)
    canonical = {key: value for key, value in genome.items() if key not in RESEARCH_SPACE or value != "scalar"}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def render(genome):
    validate(genome)
    source = baseline_source()
    if all(genome.get(key, "scalar") == "scalar" for key in RESEARCH_SPACE) and all(genome[key] == value for key, value in BASE.items()):
        return source
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in ("ModelConfig", "TrainConfig"):
            for field in node.body:
                if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name) and field.target.id in genome:
                    field.value = ast.Constant(genome[field.target.id])
    if genome["optimizer"] == "sgd":
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "AdamW":
                node.func.attr = "SGD"
                node.keywords = [keyword for keyword in node.keywords if keyword.arg != "fused"]
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if ((node.func.attr in ("AdamW", "SGD") and genome.get("optimizer_impl") == "foreach")
                    or (node.func.attr == "clip_grad_norm_" and genome.get("clip_impl") == "foreach")):
                for keyword in node.keywords:
                    if keyword.arg == "foreach":
                        keyword.value = ast.Constant(True)
    source = ast.unparse(ast.fix_missing_locations(tree)) + "\n"
    check_source(source)
    return source


def operator_stats(records):
    stats = {key: {"attempts": 0, "reward": 0.0} for key in (*SPACE, *RESEARCH_SPACE)}
    for record in records:
        if record.get("type") != "end" or record.get("operator") not in stats:
            continue
        item = stats[record["operator"]]
        item["attempts"] += 1
        item["reward"] += 1.0 if record.get("decision") == "accepted" else 0.0
    return stats


def propose(champion, records, experiment_id, unlocked=(), strategy=None):
    validate(champion)
    space = {**SPACE, **{key: values for key, values in RESEARCH_SPACE.items() if key in unlocked}}
    stats = {key: value for key, value in operator_stats(records).items() if key in space}
    seen = {digest(BASE)} | {record["genome_sha256"] for record in records if "genome_sha256" in record}
    rng = random.Random(experiment_id * 7919 + 13)
    total = sum(item["attempts"] for item in stats.values())
    initial_v0 = total == 0 and not (strategy or DEFAULT)["small_model_prior"] and not (strategy or DEFAULT)["p_global"]
    for attempt in range(500):
        # Explorar operadores con UCB; la recompensa deriva solo de aceptación verificada.
        operator = choose_operator(stats, rng, total, strategy)
        new_options = [key for key in RESEARCH_SPACE if key in unlocked and stats[key]["attempts"] == 0]
        if new_options and attempt == 0:
            operator = new_options[0]
        elif initial_v0 and attempt == 0:
            operator = "lr"
        candidate = dict(champion)
        choices = [value for value in space[operator] if value != candidate.get(operator, "scalar")]
        candidate[operator] = 0.006 if operator == "lr" and initial_v0 and attempt == 0 else rng.choice(choices)
        if attempt > 20:
            operator = rng.choice(list(space))
            candidate = dict(champion)
            candidate[operator] = rng.choice(space[operator])
        validate(candidate)
        if digest(candidate) not in seen:
            return candidate, operator, {"limitation": "coste hasta calidad privada", "component": operator,
                "reason": "Explorar una alternativa conocida mediante estadística UCB del ledger",
                "expected": "reducir coste conservando calidad en cinco semillas",
                "acceptance": "IC unilateral 95% del ratio <0.95, RAM/VRAM <=1.25x",
                "provenance": "known", "change": {key: [champion.get(key, "scalar"), candidate.get(key, "scalar")]
                    for key in candidate if champion.get(key, "scalar") != candidate.get(key, "scalar")}}
    raise RuntimeError("No se encontró propuesta inédita en el espacio conocido")
