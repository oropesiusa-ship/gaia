"""Niveles 4-5: mejorar y verificar el propio mecanismo de búsqueda.

Se compara cada estrategia en un 'paisaje' congelado: el coste medido de cada genoma
se guarda en caché, de modo que todas las estrategias se enfrentan a los mismos
valores y cada simulación es barata. La unidad de comparación es la semilla de búsqueda
(pareada entre estrategias). Para evaluar sin sobreajuste, `prove` usa una TAREA
DISTINTA (`audit`) y semillas que `tune` nunca vio.
"""
import json
import math
import statistics
import time
from pathlib import Path

import numpy as np

from . import genome as G
from . import search, stats
from .protected import evaluator
from .store import atomic_write


class Landscape:
    def __init__(self, store, bench, lim, task, data_seed=0):
        self.store, self.bench, self.lim, self.task = store, bench, lim, task
        self.seed = data_seed
        self.path = store.dir / "meta" / f"landscape_{task}_{data_seed}.jsonl"
        self.path.parent.mkdir(exist_ok=True)
        self.cache = {}
        if self.path.exists():
            for ln in self.path.read_text().splitlines():
                try:
                    r = json.loads(ln)
                    self.cache[r["h"]] = (r["cost"], r["status"])
                except json.JSONDecodeError:
                    pass
        cal = bench["calibrated"][task]
        self.base_cost = cal["ref_cost_s"]
        self.cap = self.base_cost * 1.5
        self.fresh_evals = 0
        self.fresh_seconds = 0.0

    def eval(self, g):
        h = G.genome_hash(g)
        if h in self.cache:
            return self.cache[h]
        t = time.perf_counter()
        try:
            src = G.render(g)
            r = evaluator.run_trial(src, self.bench, self.task, self.seed, self.seed, self.cap,
                                    self.lim, self.store.tmp)
            res = (r["cost_s"] if r["reached"] else None, r["status"])
        except ValueError:
            res = (None, "invalid")
        self.fresh_evals += 1
        self.fresh_seconds += time.perf_counter() - t
        self.cache[h] = res
        with self.path.open("a") as f:
            f.write(json.dumps({"h": h, "cost": res[0], "status": res[1]}) + "\n")
        return res


def simulate(params, landscape, budget, seed):
    rng = np.random.default_rng(seed)
    base = G.new_genome()
    hist = search.History()
    hist.add(base, landscape.base_cost, "ok", None, [])
    strat = search.Strategy(params, rng)
    best, traj = landscape.base_cost, []
    for _ in range(budget):
        g, ops, _, pc = strat.propose(hist)
        cost, status = landscape.eval(g)
        hist.add(g, cost, status, pc, ops)
        if cost is not None and cost < best:
            best = cost
        traj.append(best)
    lg = [math.log(b / landscape.base_cost) for b in traj]
    return {"auc": statistics.mean(lg), "final": lg[-1],
            "evals_to_20pct": next((i + 1 for i, b in enumerate(traj)
                                    if b <= 0.8 * landscape.base_cost), budget + 1)}


def compare(pa, pb, landscape, budget, seeds):
    """Diferencias pareadas (b - a) del AUC log-coste; negativo = b es mejor."""
    ra = [simulate(pa, landscape, budget, s) for s in seeds]
    rb = [simulate(pb, landscape, budget, s) for s in seeds]
    d = [b["auc"] - a["auc"] for a, b in zip(ra, rb)]
    m, lo, hi = stats.paired_bootstrap(d)
    return {"mean_auc_diff": round(m, 4), "ci90": [round(lo, 4), round(hi, 4)],
            "auc_a": round(statistics.mean(r["auc"] for r in ra), 4),
            "auc_b": round(statistics.mean(r["auc"] for r in rb), 4),
            "final_a": round(statistics.mean(r["final"] for r in ra), 4),
            "final_b": round(statistics.mean(r["final"] for r in rb), 4),
            "evals20_a": round(statistics.mean(r["evals_to_20pct"] for r in ra), 1),
            "evals20_b": round(statistics.mean(r["evals_to_20pct"] for r in rb), 1),
            "n_seeds": len(seeds)}


def mutate_strategy(p, rng):
    q = dict(p)
    keys = list(search.STRATEGY_BOUNDS)
    for k in rng.choice(keys, size=int(rng.integers(1, 3)), replace=False):
        lo, hi = search.STRATEGY_BOUNDS[k]
        v = q[k] * math.exp(rng.normal(0, 0.5)) if k != "stagnation_boost" else q[k] + rng.normal(0, 0.1)
        v = min(hi, max(lo, v))
        q[k] = int(round(v)) if k == "elite_k" else float(f"{v:.3g}")
    if rng.random() < 0.1:
        q["learn"] = not q["learn"]
    return q


def tune(engine, rounds=3, seeds=None, budget=None):
    """Nivel 4: GAIA propone variantes de su estrategia y adopta una solo si gana por pares."""
    cfg = engine.cfg["meta"]
    budget = budget or cfg["budget"]
    n_seeds = cfg["seeds"]
    st = engine.state
    ls = Landscape(engine.store, engine.bench, engine.lim, "main")
    rng = np.random.default_rng(st["n_experiments"] + 101)
    cur = dict(st["strategy"])
    seeds = seeds or list(range(100, 100 + n_seeds))     # semillas de ajuste (prove usa otras)
    log = []
    for r in range(rounds):
        if engine.store.stop_requested():
            break
        cand = mutate_strategy(cur, rng)
        cmp = compare(cur, cand, ls, budget, seeds)
        adopt = cmp["mean_auc_diff"] < 0 and cmp["ci90"][1] < 0
        rec = {"type": "meta", "from_version": cur.get("version", 0), "candidate": cand,
               "comparison": cmp, "adopted": adopt, "fresh_evals": ls.fresh_evals,
               "fresh_seconds": round(ls.fresh_seconds, 1)}
        engine.store.append(rec)
        if adopt:
            cand["version"] = cur.get("version", 0) + 1
            cur = cand
            st["strategy"] = cur
            engine.store.save_state(st)
        log.append("adoptada" if adopt else "descartada")
    engine.state["search_seconds"] += ls.fresh_seconds
    return f"{log} (evaluaciones nuevas del paisaje: {ls.fresh_evals}, {ls.fresh_seconds:.0f}s)"


def prove(engine, budget=None, n_seeds=12):
    """Nivel 5: ¿la estrategia actual encuentra mejores soluciones que la v0 y que el azar,
    en una tarea que el ajuste nunca vio y con semillas nuevas?"""
    budget = budget or engine.cfg["meta"]["budget"]
    ls = Landscape(engine.store, engine.bench, engine.lim, "audit")
    seeds = list(range(5000, 5000 + n_seeds))
    cur = dict(engine.state["strategy"])
    v0 = dict(search.DEFAULT_STRATEGY)
    rnd = {**v0, "kind": "random", "learn": False}
    uni = {**v0, "kind": "uniform", "learn": False}
    out = {"budget": budget, "task": "audit (distinta de la usada para ajustar)",
           "current_version": cur.get("version", 0), "comparisons": {}}
    out["comparisons"]["actual_vs_v0"] = compare(v0, cur, ls, budget, seeds)
    out["comparisons"]["v0_adaptativa_vs_aleatoria"] = compare(rnd, v0, ls, budget, seeds)
    out["comparisons"]["v0_adaptativa_vs_mutacion_uniforme"] = compare(uni, v0, ls, budget, seeds)
    out["fresh_evals"], out["fresh_seconds"] = ls.fresh_evals, round(ls.fresh_seconds, 1)
    atomic_write(engine.store.dir / "meta" / "prove_latest.json", json.dumps(out, indent=1))
    return out
