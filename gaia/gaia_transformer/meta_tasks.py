"""Datos y binding de un estudio separado: no modifica el laboratorio de campaña."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import types

from . import data
from .lab import benchmark, evaluator

TASKS = ("periodic_tune", "counter_holdout")


def generate(task, split):
    if task not in TASKS or split not in ("train", "validation"):
        raise ValueError("Tarea/split de metaestudio desconocidos")
    if task == "periodic_tune":
        return data.generate_split(data.DEFAULT_SPEC, split)
    # Otra ley de continuación: progresión modular de período 16, frente a
    # copiar patrones arbitrarios de períodos 2/4/8 en la tarea de ajuste.
    count, seed, domain = (4096, 5101, "M") if split == "train" else (256, 6203, "N")
    records = []
    for index in range(count):
        raw = hashlib.sha256(f"counter_bytes/v1|{split}|{seed}|{index}".encode()).digest()
        start, increment = raw[0] % 16, (1, 3, 5, 7)[raw[1] % 4]
        body = bytes(data.ALPHABET[(start + increment * position) % 16] for position in range(55))
        records.append(f"{domain}{index:08x}:".encode() + body)
    return b"".join(records)


def manifest(task):
    payload = {"task": task, "generator": "structured_bytes/v1" if task == TASKS[0] else "counter_bytes/v1",
               "context": 64, "splits": {split: hashlib.sha256(generate(task, split)).hexdigest()
                                        for split in ("train", "validation")}}
    return {**payload, "sha256": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()}


@dataclass(frozen=True)
class TaskBenchmark:
    task: str
    cross_entropy = staticmethod(benchmark.cross_entropy)

    def private_data(self, spec):
        if spec.split != "validation":
            raise ValueError("El metaestudio usa su propia tarea holdout, no audit de campaña")
        expected = json.loads(Path(__file__).with_name("meta_tasks_v1.json").read_text())[self.task]
        actual = manifest(self.task)
        if actual != expected:
            raise RuntimeError("META_CORPUS_INTEGRITY: tarea distinta de la fijada")
        train = data.records(generate(self.task, "train"))
        contexts, targets = data.private_validation(generate(self.task, "validation"))
        return train, contexts, targets, actual["sha256"]

    def identity(self):
        here = Path(__file__).parent
        files = [here / name for name in ("meta_tasks.py", "meta_tasks_v1.json", "metastudy.py", "search_strategy.py", "genome.py")]
        identity = benchmark.identity()
        identity.update({str(path.relative_to(here.parents[1])): hashlib.sha256(path.read_bytes()).hexdigest() for path in files})
        identity["metastudy/task"] = manifest(self.task)["sha256"]
        return identity


def evaluator_for(task):
    """Mismo bytecode de run_trial, binding de datos/identidad propio e inmutable.

    No parchea globals del evaluador de producción ni cambia worker, guard,
    sandbox, monitor, criterio de coste o métricas. El resultado pertenece a
    otra identidad experimental y nunca promociona un entrenador de campaña.
    """
    if task not in TASKS:
        raise ValueError("Tarea desconocida")
    scope = dict(evaluator.run_trial.__globals__)
    scope["benchmark"] = TaskBenchmark(task)
    function = types.FunctionType(evaluator.run_trial.__code__, scope, "meta_run_trial", evaluator.run_trial.__defaults__)
    function.__kwdefaults__ = dict(evaluator.run_trial.__kwdefaults__)
    return function
