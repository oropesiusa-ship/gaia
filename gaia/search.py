"""Historial y estrategias de búsqueda (la parte que aprende a experimentar)."""
import math

import numpy as np

from . import genome as G
from . import mutate

DEFAULT_STRATEGY = {
    "version": 0, "kind": "adaptive", "learn": True,
    "p_global": 0.15, "temp": 0.5, "n_mut_mean": 1.3, "elite_k": 4,
    "ucb_c": 0.5, "prior_n": 2.0, "stagnation_boost": 0.2,
}
STRATEGY_BOUNDS = {"p_global": (0.02, 0.6), "temp": (0.05, 3.0), "n_mut_mean": (1.0, 3.0),
                   "elite_k": (1, 8), "ucb_c": (0.0, 2.0), "prior_n": (0.5, 6.0),
                   "stagnation_boost": (0.0, 0.5)}


def reward(parent_cost, cost, status):
    """Recompensa de un experimento respecto a su padre (log del cociente de coste)."""
    if status in ("invalid", "error", "timeout"):
        return -0.1
    if cost is None:
        return -0.02
    return float(np.clip(math.log(parent_cost / cost), -0.5, 1.5))


class History:
    """Vista del historial que usa la estrategia (idéntica en real y en simulación)."""

    def __init__(self):
        self.items = []         # dicts
        self.seen = set()
        self.op_n, self.op_sum = {}, {}
        self.since_improve = 0
        self.best = math.inf

    def add(self, genome, cost, status, parent_cost, ops):
        h = G.genome_hash(genome)
        self.seen.add(h)
        r = reward(parent_cost, cost, status) if parent_cost else 0.0
        for o in ops:
            self.op_n[o] = self.op_n.get(o, 0) + 1
            self.op_sum[o] = self.op_sum.get(o, 0.0) + r / max(1, len(ops))
        self.items.append({"hash": h, "genome": genome, "cost": cost, "status": status})
        if cost is not None and cost < self.best * 0.995:
            self.best, self.since_improve = cost, 0
        else:
            self.since_improve += 1

    def elites(self, k):
        ok = [i for i in self.items if i["cost"] is not None]
        ok.sort(key=lambda i: i["cost"])
        uniq, out = set(), []
        for i in ok:
            if i["hash"] not in uniq:
                uniq.add(i["hash"])
                out.append(i)
            if len(out) >= k:
                break
        return out


class Strategy:
    def __init__(self, params, rng, op_names=None, random_genome=None):
        self.p = {**DEFAULT_STRATEGY, **params}
        self.rng = rng
        # Optional contracted surface: operator subset and a matching global sampler. Defaults are unchanged.
        self.op_names = op_names
        self.random_genome = random_genome or mutate.random_genome

    def _op_weights(self, hist, names=None):
        # A caller may restrict the operator set (e.g. a contracted surface); default is unchanged.
        names = names if names is not None else self.op_names if self.op_names is not None else mutate.OP_NAMES
        n_tot = sum(hist.op_n.values())
        if not self.p["learn"] or self.p["kind"] == "uniform":
            return np.ones(len(names)) / len(names)
        pn, c = self.p["prior_n"], self.p["ucb_c"]
        sc = []
        for n in names:
            cnt = hist.op_n.get(n, 0)
            mean = (hist.op_sum.get(n, 0.0)) / (cnt + pn)          # prior de recompensa 0
            bonus = c * math.sqrt(math.log(n_tot + 2) / (cnt + 1)) * 0.1
            sc.append(mean + bonus)
        sc = np.array(sc) / max(self.p["temp"], 1e-3) * 5.0
        sc -= sc.max()
        w = np.exp(sc)
        return w / w.sum()

    def propose(self, hist):
        """Devuelve (genoma, ops, parent_hash, parent_cost)."""
        rng = self.rng
        if self.p["kind"] == "random":
            return self.random_genome(rng), ["random_global"], None, None
        pg = self.p["p_global"] + self.p["stagnation_boost"] * min(1.0, hist.since_improve / 30)
        elites = hist.elites(int(self.p["elite_k"]))
        for _ in range(60):
            if not elites or rng.random() < pg:
                g = self.random_genome(rng)
                return g, ["random_global"], None, None
            w = 1.0 / (np.arange(len(elites)) + 1.0)
            par = elites[rng.choice(len(elites), p=w / w.sum())]
            child, ops = par["genome"], []
            if len(elites) > 1 and rng.random() < 0.1 and self.op_names is None:
                other = elites[rng.integers(len(elites))]
                child, ops = mutate.crossover(child, other["genome"], rng), ["crossover"]
            n = 1 + rng.poisson(max(0.0, self.p["n_mut_mean"] - 1.0))
            names = self.op_names if self.op_names is not None else mutate.OP_NAMES
            weights = self._op_weights(hist)
            ok = True
            for _ in range(n):
                name = names[rng.choice(len(weights), p=weights)]
                try:
                    child, _ = mutate.apply(name, child, rng)
                    ops.append(name)
                except (ValueError, IndexError):
                    ok = False
                    break
            if ok and ops and G.genome_hash(child) not in hist.seen:
                return child, ops, par["hash"], par["cost"]
        return self.random_genome(rng), ["random_global"], None, None
