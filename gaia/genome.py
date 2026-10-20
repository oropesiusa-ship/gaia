"""Genoma = hiperparámetros + elección de componentes + mutaciones de código.

El genoma se renderiza a un `trainer.py` autocontenido que se ejecuta SIEMPRE
en el proceso aislado del evaluador.
"""
import ast
import copy
import hashlib
import json
import re

from . import snippets
from .protected import guard

HP_DEFAULT = {
    "hidden": 64, "depth": 2, "lr": 0.05, "batch": 64,
    "momentum": 0.9, "beta1": 0.9, "beta2": 0.999,
    "wd": 0.0, "sched": "const", "warm": 0, "horizon": 1000,
    "init_scale": 1.0, "clip": 0.0,
}

HP_CHOICES = {
    "hidden": [16, 32, 48, 64, 96, 128, 192, 256],
    "depth": [1, 2, 3],
    "batch": [16, 32, 64, 128, 256, 512, 1024],
    "momentum": [0.0, 0.5, 0.8, 0.9, 0.95, 0.99],
    "beta1": [0.8, 0.9, 0.95],
    "beta2": [0.9, 0.99, 0.999],
    "sched": ["const", "cosine"],
    "warm": [0, 20, 50, 100],
    "horizon": [200, 400, 800, 1500, 3000],
    "clip": [0.0, 0.5, 1.0, 5.0],
}
HP_RANGES = {"lr": (1e-4, 1.5, "log"), "wd": (0.0, 1e-2, "lin"),
             "init_scale": (0.3, 2.0, "lin")}

# Qué hiperparámetros afectan realmente según los componentes elegidos.
def active_hps(g):
    s = g["slots"]
    act = {"hidden", "depth", "lr", "batch", "sched", "warm", "init_scale", "clip", "wd"}
    if s["optimizer"] == "momentum":
        act.add("momentum")
    if s["optimizer"] in ("adam", "adam_inplace"):
        act |= {"beta1", "beta2"}
    if g["hp"]["sched"] == "cosine":
        act.add("horizon")
    return act


BASELINE = {
    "hp": dict(HP_DEFAULT),
    "slots": {"dtype": "float64", "act": "relu", "sampler": "randint",
              "backward": "naive", "optimizer": "sgd"},
    "lits": {}, "drops": [],
}


def new_genome(hp=None, slots=None):
    g = copy.deepcopy(BASELINE)
    if hp:
        g["hp"].update(hp)
    if slots:
        g["slots"].update(slots)
    return normalize(g)


def normalize(g):
    """Fija a su valor por defecto lo que no influye, para no duplicar genomas."""
    g = copy.deepcopy(g)
    act = active_hps(g)
    for k, v in HP_DEFAULT.items():
        if k not in act:
            g["hp"][k] = v
    g["drops"] = sorted(set(g.get("drops", [])))
    g["lits"] = {k: g["lits"][k] for k in sorted(g.get("lits", {}))}
    return g


def genome_hash(g):
    core = {k: g[k] for k in ("hp", "slots", "lits", "drops")}
    return hashlib.sha1(json.dumps(core, sort_keys=True).encode()).hexdigest()[:12]


def _base_source(g):
    s = g["slots"]
    src = snippets.TEMPLATE
    for name in ("act", "sampler", "backward", "optimizer"):
        src = src.replace(f"__SLOT_{name}__", snippets.SLOTS[name][s[name]].rstrip("\n"))
    src = src.replace("__HP__", repr(dict(g["hp"])))
    return src.replace("__DTYPE__", s["dtype"])


def literals(base_src):
    """Constantes float mutables (fuera de HP). Clave 'línea:columna'."""
    tree = ast.parse(base_src)
    hp_line = next(n.lineno for n in tree.body if isinstance(n, ast.Assign)
                   and getattr(n.targets[0], "id", "") == "HP")
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, float) \
                and n.value != 0.0 and n.lineno != hp_line:
            out.append((n.lineno, n.col_offset, n.end_col_offset, n.value))
    out.sort()
    return [{"key": f"{l}:{c}", "line": l, "col": c, "end": e, "value": v}
            for l, c, e, v in out]


def optional_lines(base_src):
    return sorted(set(re.findall(r"# @opt:(\w+)", base_src)))


def render(g):
    """Devuelve el código fuente del entrenador. Lanza ValueError si es inválido."""
    base = _base_source(g)
    lines = base.split("\n")
    if g["lits"]:
        lits = {l["key"]: l for l in literals(base)}
        edits = []
        for key, val in g["lits"].items():
            if key not in lits:
                raise ValueError(f"literal inexistente {key}")
            edits.append((lits[key], float(val)))
        for l, val in sorted(edits, key=lambda e: (-e[0]["line"], -e[0]["col"])):
            ln = lines[l["line"] - 1]
            lines[l["line"] - 1] = ln[:l["col"]] + repr(val) + ln[l["end"]:]
    avail = optional_lines(base)
    for name in g["drops"]:
        if name not in avail:
            raise ValueError(f"línea opcional inexistente {name}")
        for i, ln in enumerate(lines):
            if f"# @opt:{name}" in ln:
                indent = ln[:len(ln) - len(ln.lstrip())]
                lines[i] = indent + "pass"
    src = "\n".join(lines)
    guard.check_source(src)       # lanza guard.GuardError (subclase de ValueError)
    compile(src, "<genome>", "exec")
    return src


def describe(g):
    sl = g["slots"]
    parts = [f"{sl['optimizer']}/{sl['act']}/{sl['dtype']}/{sl['backward']}/{sl['sampler']}",
             f"h{g['hp']['hidden']}x{g['hp']['depth']}", f"b{g['hp']['batch']}",
             f"lr{g['hp']['lr']:.4g}"]
    if g["lits"]:
        parts.append(f"lits={len(g['lits'])}")
    if g["drops"]:
        parts.append("drop=" + ",".join(g["drops"]))
    return " ".join(parts)


def diff(a, b):
    """Diferencias entre dos genomas: lista de (campo, antes, después, procedencia)."""
    out = []
    for k in a["hp"]:
        if a["hp"][k] != b["hp"][k]:
            out.append((f"hp.{k}", a["hp"][k], b["hp"][k], "known"))
    for k in a["slots"]:
        if a["slots"][k] != b["slots"][k]:
            out.append((f"slot.{k}", a["slots"][k], b["slots"][k], "known"))
    for k in sorted(set(a["lits"]) | set(b["lits"])):
        if a["lits"].get(k) != b["lits"].get(k):
            out.append((f"lit@{k}", a["lits"].get(k), b["lits"].get(k), "generated"))
    for k in sorted(set(a["drops"]) ^ set(b["drops"])):
        out.append((f"drop.{k}", k in a["drops"], k in b["drops"], "generated"))
    return out


def provenance(a, b):
    """'known' | 'generated' | 'mixed' según TODO lo que difiere del campeón."""
    kinds = {d[3] for d in diff(a, b)}
    return "mixed" if len(kinds) == 2 else (kinds.pop() if kinds else "known")
