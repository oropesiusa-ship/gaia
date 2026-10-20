"""Operadores de modificación. Cada uno devuelve (genoma_nuevo, detalle).

prov = 'known'      -> técnica conocida (no cuenta como descubrimiento autónomo)
prov = 'generated'  -> modificación de código generada por GAIA (mutación AST / borrado)
"""
import copy
import math

from . import genome as G
from . import snippets


def _neighbor(choices, cur, rng):
    i = choices.index(cur) if cur in choices else rng.integers(len(choices))
    j = int(min(len(choices) - 1, max(0, i + rng.choice([-2, -1, 1, 2]))))
    return choices[j]


def _hp_choice(name):
    def op(g, rng):
        g = copy.deepcopy(g)
        old = g["hp"][name]
        if rng.random() < 0.7:
            new = _neighbor(G.HP_CHOICES[name], old, rng)
        else:
            new = G.HP_CHOICES[name][rng.integers(len(G.HP_CHOICES[name]))]
        g["hp"][name] = new
        return G.normalize(g), f"{name}: {old} -> {new}"
    return op


def _hp_range(name):
    lo, hi, mode = G.HP_RANGES[name]

    def op(g, rng):
        g = copy.deepcopy(g)
        old = g["hp"][name]
        if mode == "log":
            new = float(min(hi, max(lo, old * math.exp(rng.normal(0, 0.6)))))
        else:
            new = float(min(hi, max(lo, old + rng.normal(0, (hi - lo) * 0.2))))
            if name == "wd" and rng.random() < 0.4:
                new = 0.0
        new = float(f"{new:.4g}")
        g["hp"][name] = new
        return G.normalize(g), f"{name}: {old:.4g} -> {new:.4g}"
    return op


def _slot(name):
    def op(g, rng):
        g = copy.deepcopy(g)
        opts = [o for o in snippets.search_options(name) if o != g["slots"][name]]
        new = opts[rng.integers(len(opts))]
        old = g["slots"][name]
        g["slots"][name] = new
        g["lits"], g["drops"] = {}, []        # las posiciones de código cambian
        return G.normalize(g), f"{name}: {old} -> {new}"
    return op


def op_lit(g, rng):
    base = G._base_source(g)
    lits = G.literals(base)
    pick = lits[rng.integers(len(lits))]
    cur = g["lits"].get(pick["key"], pick["value"])
    new = float(f"{cur * float(rng.choice([0.25, 0.5, 0.8, 1.25, 2.0, 4.0])):.6g}")
    g = copy.deepcopy(g)
    g["lits"][pick["key"]] = new
    line = base.split("\n")[pick["line"] - 1].strip()
    return G.normalize(g), f"constante {pick['value']} -> {new} en `{line[:60]}`"


def op_drop(g, rng):
    base = G._base_source(g)
    avail = [a for a in G.optional_lines(base) if a not in g["drops"]]
    if not avail:
        raise ValueError("nada que eliminar")
    name = avail[rng.integers(len(avail))]
    g = copy.deepcopy(g)
    g["drops"].append(name)
    return G.normalize(g), f"eliminar operación opcional '{name}'"


def op_undrop(g, rng):
    if not g["drops"]:
        raise ValueError("nada que restaurar")
    g = copy.deepcopy(g)
    g["drops"].pop(rng.integers(len(g["drops"])))
    return G.normalize(g), "restaurar operación opcional"


def op_reset_lits(g, rng):
    if not g["lits"]:
        raise ValueError("sin mutaciones")
    g = copy.deepcopy(g)
    key = list(g["lits"])[rng.integers(len(g["lits"]))]
    del g["lits"][key]
    return G.normalize(g), "revertir una constante"


def random_genome(rng):
    g = copy.deepcopy(G.BASELINE)
    for k, ch in G.HP_CHOICES.items():
        g["hp"][k] = ch[rng.integers(len(ch))]
    for k, (lo, hi, mode) in G.HP_RANGES.items():
        v = math.exp(rng.uniform(math.log(lo), math.log(hi))) if mode == "log" else rng.uniform(lo, hi)
        g["hp"][k] = float(f"{v:.4g}")
    for k in snippets.SLOTS:
        names = snippets.search_options(k)
        g["slots"][k] = names[rng.integers(len(names))]
    return G.normalize(g)


# nombre: (función, familia, procedencia, meta de hipótesis)
OPS = {}


def _reg(name, fn, family, prov, limitation, component, rationale, risk):
    OPS[name] = {"fn": fn, "family": family, "prov": prov, "limitation": limitation,
                 "component": component, "rationale": rationale, "risk": risk}


for n, lim, why in [
    ("hidden", "cálculo innecesario o capacidad insuficiente", "menos/más unidades cambia coste por paso y pasos hasta el objetivo"),
    ("depth", "profundidad no óptima", "menos capas reduce cálculo; más capas puede acelerar el aprendizaje"),
    ("batch", "tamaño de lote no óptimo", "lotes mayores amortizan sobrecarga de Python; menores dan más actualizaciones"),
    ("momentum", "optimización lenta", "más inercia puede reducir pasos hasta el objetivo"),
    ("beta1", "optimización lenta", "ajustar el promedio de gradiente de Adam"),
    ("beta2", "optimización inestable", "ajustar el promedio de varianza de Adam"),
    ("sched", "tasa de aprendizaje constante", "decaimiento coseno estabiliza el final"),
    ("warm", "inestabilidad inicial", "calentamiento permite una tasa mayor"),
    ("horizon", "horizonte del schedule", "alinear el decaimiento con los pasos necesarios"),
    ("clip", "gradientes grandes", "recorte permite tasas mayores"),
]:
    _reg(n, _hp_choice(n), "hp", "known", lim, f"hp.{n}", why, "puede empeorar la calidad final")
for n, lim, why in [
    ("lr", "tasa de aprendizaje no óptima", "la tasa decide los pasos hasta el objetivo"),
    ("wd", "regularización innecesaria", "wd=0 evita trabajo por parámetro"),
    ("init_scale", "inicialización no óptima", "escala de pesos inicial afecta la velocidad de arranque"),
]:
    _reg(n, _hp_range(n), "hp", "known", lim, f"hp.{n}", why, "puede divergir")
for n, lim, why in [
    ("dtype", "precisión numérica costosa", "float32 reduce ancho de banda y acelera BLAS"),
    ("act", "activación costosa o lenta de aprender", "otra activación cambia coste y convergencia"),
    ("sampler", "muestreo ineficiente", "permutar por épocas evita indexado aleatorio repetido"),
    ("backward", "operaciones redundantes en retropropagación", "versión fusionada in-place evita asignaciones"),
    ("optimizer", "algoritmo de optimización ineficiente", "otro optimizador cambia pasos hasta el objetivo"),
]:
    _reg(n, _slot(n), "slot", "known", lim, f"slot.{n}", why, "puede cambiar la calidad alcanzada")
_reg("lit", op_lit, "code", "generated", "constante numérica del código no óptima", "código (AST)",
     "perturbar un literal puede revelar un valor mejor", "alta probabilidad de empeorar o romper")
_reg("drop", op_drop, "code", "generated", "operaciones redundantes", "código (AST)",
     "eliminar una operación opcional (p.ej. pérdida no usada) reduce trabajo", "puede alterar el resultado")
_reg("undrop", op_undrop, "code", "generated", "eliminación perjudicial previa", "código (AST)",
     "restaurar una operación eliminada", "ninguno relevante")
_reg("reset_lit", op_reset_lits, "code", "generated", "mutación de constante perjudicial", "código (AST)",
     "revertir una constante a su valor original", "ninguno relevante")

OP_NAMES = list(OPS)


def apply(name, g, rng):
    return OPS[name]["fn"](g, rng)


def crossover(a, b, rng):
    child = copy.deepcopy(a)
    for k in G.HP_DEFAULT:
        if rng.random() < 0.5:
            child["hp"][k] = b["hp"][k]
    for k in child["slots"]:
        if rng.random() < 0.5:
            child["slots"][k] = b["slots"][k]
    if child["slots"] != a["slots"]:
        child["lits"], child["drops"] = {}, []
    return G.normalize(child)
