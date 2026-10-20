import math
import statistics


def t_crit(df, table):
    if df < 1:
        return float("inf")
    return table.get(str(df), 1.7 if df > 9 else 2.0)


def decide(champ, cand, acc):
    """Decisión pareada entre campeón y candidato en las mismas semillas.

    champ/cand: listas de resultados de run_trial (misma longitud, mismo orden de semillas).
    Devuelve dict con 'decision' en {accepted, rejected, deferred, pareto_alternative}.
    """
    n = len(champ)
    c_ok = sum(1 for r in champ if r["reached"])
    k_ok = sum(1 for r in cand if r["reached"])
    out = {"n": n, "champ_reached": c_ok, "cand_reached": k_ok}
    if k_ok < max(c_ok, math.ceil(0.8 * n)):
        return {**out, "decision": "rejected",
                "reason": f"calidad: el candidato alcanza el objetivo en {k_ok}/{n} semillas (campeón {c_ok}/{n})"}
    logs = [math.log(b["cost_s"] / a["cost_s"]) for a, b in zip(champ, cand)
            if a["reached"] and b["reached"]]
    if len(logs) < 3:
        return {**out, "decision": "rejected", "reason": "pocos pares válidos"}
    m = statistics.mean(logs)
    se = statistics.stdev(logs) / math.sqrt(len(logs))
    up = m + t_crit(len(logs) - 1, acc["t_crit_one_sided_95"]) * se
    thr = math.log(1 - acc["min_gain"])
    mem_c = [r["peak_rss_mb"] for r in champ if r["peak_rss_mb"]]
    mem_k = [r["peak_rss_mb"] for r in cand if r["peak_rss_mb"]]
    mem_ratio = (statistics.median(mem_k) / statistics.median(mem_c)) if mem_c and mem_k else None
    out.update(ratio=round(math.exp(m), 4), ratio_upper95=round(math.exp(up), 4),
               mem_ratio=None if mem_ratio is None else round(mem_ratio, 3), pairs=len(logs))
    if up < thr:
        if mem_ratio is not None and mem_ratio > acc["mem_tolerance"]:
            return {**out, "decision": "pareto_alternative",
                    "reason": f"más rápido pero usa {mem_ratio:.2f}x la RAM: alternativa de la frontera de Pareto"}
        return {**out, "decision": "accepted",
                "reason": f"coste {math.exp(m):.3f}x del de referencia (límite sup. IC95% {math.exp(up):.3f} < {1-acc['min_gain']:.2f})"}
    if m < thr:
        return {**out, "decision": "deferred",
                "reason": f"mejora probable ({math.exp(m):.3f}x) pero no concluyente (IC sup. {math.exp(up):.3f})"}
    return {**out, "decision": "rejected",
            "reason": f"sin mejora verificable (coste {math.exp(m):.3f}x, IC sup. {math.exp(up):.3f})"}


def paired_bootstrap(diffs, n=4000, seed=0):
    """IC 90% de la media de diffs por bootstrap (para comparar estrategias)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    d = np.asarray(diffs, dtype=float)
    means = [rng.choice(d, len(d)).mean() for _ in range(n)]
    return float(d.mean()), float(np.percentile(means, 5)), float(np.percentile(means, 95))
