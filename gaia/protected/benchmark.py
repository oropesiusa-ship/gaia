"""Especificación congelada del benchmark y calibración de la línea base."""
import copy
import json
import statistics

from . import evaluator

DEFAULT_SPEC = {
    "tasks": {
        "main":  {"d": 48, "teacher_hidden": 64, "k": 8, "teacher_gain": 2.0, "noise": 0.3,
                  "teacher_seed": 7, "data_salt": 11, "n_train": 20000, "n_val": 5000},
        # Variante distinta de la tarea: solo para auditorías (nunca para seleccionar).
        "audit": {"d": 56, "teacher_hidden": 80, "k": 8, "teacher_gain": 2.0, "noise": 0.3,
                  "teacher_seed": 99, "data_salt": 23, "n_train": 20000, "n_val": 5000},
    },
    "tiers": {"screen": [0], "confirm": [1000, 1001, 1002, 1003, 1004],
              "audit": [5000, 5001, 5002, 5003, 5004, 5005],
              "calibration": [9000, 9001, 9002, 9003, 9004]},
    "eval_every": 50, "hits_needed": 2, "max_batches": 12000,
    "ref_batches": 3000, "tolerance": 0.005,
    "calibrated": {},
}

# Perfil duro: línea base de varios segundos; tarda mucho más en saturarse que DEFAULT_SPEC (fácil).
HARD_SPEC = copy.deepcopy(DEFAULT_SPEC)
HARD_SPEC["tasks"]["main"].update(d=96, teacher_hidden=192, k=16, noise=0.05, n_train=40000, n_val=8000)
HARD_SPEC["tasks"]["audit"].update(d=104, teacher_hidden=208, k=16, noise=0.05, n_train=40000, n_val=8000)
HARD_SPEC.update(ref_batches=12000, max_batches=60000)
PROFILES = {"easy": DEFAULT_SPEC, "hard": HARD_SPEC}


def calibrate(baseline_source, task_name, bench, limits, tmp_root, log=print):
    """Fija el objetivo de calidad desde la línea base y mide su variabilidad."""
    b = copy.deepcopy(bench)
    accs = []
    for s in b["tiers"]["calibration"]:
        r = evaluator.run_trial(baseline_source, b, task_name, s, s, 1e9, limits, tmp_root,
                                target=2.0, max_batches=b["ref_batches"])
        if r["status"] != "ok":
            raise RuntimeError(f"la línea base falla en calibración: {r['error']}")
        accs.append(r["final_acc"])
    q_ref = statistics.median(accs)
    target = round(q_ref - b["tolerance"], 4)
    cap = limits["max_experiment_seconds"]
    for _ in range(4):
        b["calibrated"][task_name] = {"target": target}
        ok = []
        for s in b["tiers"]["calibration"]:
            r = evaluator.run_trial(baseline_source, b, task_name, s, s, cap, limits, tmp_root)
            ok.append(r["reached"])
        if all(ok):
            break
        target = round(target - 0.005, 4)
    else:
        raise RuntimeError("la línea base no alcanza el objetivo de forma fiable")
    costs = []
    for _ in range(5):
        r = evaluator.run_trial(baseline_source, b, task_name, b["tiers"]["screen"][0],
                                b["tiers"]["screen"][0], cap, limits, tmp_root)
        if not r["reached"]:
            raise RuntimeError("la línea base no alcanza el objetivo en la semilla de cribado")
        costs.append(r["cost_s"])
    med = statistics.median(costs)
    cv = statistics.pstdev(costs) / statistics.mean(costs)
    b["calibrated"][task_name] = {
        "target": target, "q_ref": round(q_ref, 4), "ref_cost_s": round(med, 4),
        "cv": round(cv, 4), "ref_costs": [round(c, 4) for c in costs]}
    log(f"[calibración {task_name}] objetivo={target} (calidad ref {q_ref:.4f}); "
        f"coste base={med:.3f}s, variabilidad (CV)={cv*100:.1f}%")
    return b
