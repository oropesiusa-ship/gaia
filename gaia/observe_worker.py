"""Observación del campeón (Modo B). Subproceso aislado; NO mide coste de referencia.

Perfila por fases envolviendo las funciones del entrenador con temporizadores y reparte
el tiempo medido SIN envoltorios (para no atribuir la sobrecarga de los temporizadores).
Salida: una línea JSON por el descriptor original de stdout.
"""
import importlib.util
import json
import os
import sys
import time

import numpy as np


def main():
    wd, seed, nb = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    helper = importlib.util.spec_from_file_location("cpu_sandbox", os.path.join(os.path.dirname(__file__), "sandbox.py"))
    isolation = importlib.util.module_from_spec(helper)
    helper.loader.exec_module(isolation)
    isolation.worker_handshake()
    out = os.fdopen(os.dup(1), "w")
    sys.stdout = open(os.devnull, "w")
    with np.load("/lab/data.npz", allow_pickle=False) as d:
        Xtr, ytr, Xva, k = d["Xtr"], d["ytr"], d["Xva"], int(d["k"])
    spec = importlib.util.spec_from_file_location("cand", "/lab/trainer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    pc = time.perf_counter

    def fresh():
        t = mod.Trainer(Xtr, ytr, k, seed)
        t.train(50)                       # calentamiento
        return t

    # 1) tiempo total sin envoltorios (mejor de 3)
    totals = []
    for _ in range(3):
        t = fresh()
        t0 = pc()
        t.train(nb)
        totals.append(pc() - t0)
    t_total = min(totals)

    # 2) reparto por fases con envoltorios
    acc = {"sampler": 0.0, "fwd_bwd": 0.0, "optimizer": 0.0, "clip": 0.0, "sched": 0.0}

    def wrap(fn, key):
        def w(*a, **kw):
            t0 = pc()
            r = fn(*a, **kw)
            acc[key] += pc() - t0
            return r
        return w
    t = fresh()
    mod.forward_backward = wrap(mod.forward_backward, "fwd_bwd")
    mod.clip_grads = wrap(mod.clip_grads, "clip")
    mod.lr_at = wrap(mod.lr_at, "sched")
    t.next_idx = wrap(t.next_idx, "sampler")
    t.opt.step = wrap(t.opt.step, "optimizer")
    acc = {k_: 0.0 for k_ in acc}
    t0 = pc()
    t.train(nb)
    t_wrapped = pc() - t0
    other = max(0.0, t_wrapped - sum(acc.values()))
    frac = {k_: v / t_wrapped for k_, v in acc.items()}
    frac["loop_gather"] = other / t_wrapped          # indexado X[idx], y[idx], bucle de Python

    # 3) microbenchmarks: matmul puro y gather
    HP = mod.HP
    B = HP["batch"]
    xb = np.ascontiguousarray(Xtr[:B], dtype=t.X.dtype)
    mm = 0.0
    h = xb
    reps = 200
    for W in t.W:
        t0 = pc()
        for _ in range(reps):
            h @ W
        fwd = (pc() - t0) / reps
        mm += 3.0 * fwd                                # fwd + 2 matmuls de retropropagación
        h = np.zeros((B, W.shape[1]), dtype=W.dtype)
    idx = np.random.default_rng(0).integers(0, len(t.X), B)
    t0 = pc()
    for _ in range(2000):
        t.X[idx]
        t.y[idx]
    gather = (pc() - t0) / 2000
    t0 = pc()
    for _ in range(3):
        t.predict(Xva)
    t_pred = (pc() - t0) / 3
    step = t_total / nb
    fb = acc["fwd_bwd"] / nb * (t_total / t_wrapped)
    out.write(json.dumps({
        "ms_per_step": step * 1e3, "fractions": frac,
        "matmul_frac_of_step": min(1.0, mm / step),
        "matmul_frac_of_fwd_bwd": min(1.0, mm / fb) if fb > 0 else None,
        "gather_frac_of_step": min(1.0, gather / step),
        "predict_ms": t_pred * 1e3, "timer_overhead_ratio": t_wrapped / t_total,
        "hp": {k_: HP[k_] for k_ in ("hidden", "depth", "batch", "lr", "clip", "wd")},
        "dtype": str(t.W[0].dtype), "n_params": int(sum(w.size for w in t.W + t.b)),
    }) + "\n")
    out.flush()
    out.close()
    sys.stdout.close()


try:
    main()
except BaseException as e:   # noqa: BLE001
    sys.stderr.write(repr(e)[:300])
    sys.exit(1)
