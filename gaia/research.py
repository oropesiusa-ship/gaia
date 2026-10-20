"""Research Engine (Modo B): observar -> diagnosticar -> hipótesis -> experimento -> inferencia -> memoria.

Diferencia con el Search Engine: la búsqueda pregunta «¿qué valor pruebo?»; la investigación pregunta
«¿qué factor limita el progreso y qué experimento lo contrastaría?».

Reglas que NO se saltan:
  * Toda hipótesis se contrasta con el mismo laboratorio (cribado + confirmación pareada + promoción).
    El Research Engine no promueve nada por su cuenta.
  * Una hipótesis de implementación (misma matemática) tiene una cota de Amdahl: si la fase que ataca
    pesa menos que `min_expected_gain`, se descarta SIN gastar un experimento (queda registrada).
  * Lo aprendido se guarda (ledger) y condiciona ciclos posteriores (priors por familia, no repetir
    lo ya refutado en el mismo campeón).
  * Una opción de código solo entra en el espacio de la búsqueda (`unlock`) si su hipótesis es apoyada.
"""
import copy
import json
import math
import os
import shutil
import tempfile
import time
from collections import Counter
from pathlib import Path

import numpy as np

from . import genome as G
from . import snippets
from .protected import evaluator, task, sandbox

OBSERVER = Path(__file__).with_name("observe_worker.py")


# ----------------------------------------------------------------------------- observación
def observe(eng, src, seed=0, batches=None):
    """Perfil por fases del campeón (subproceso aislado) + descomposición del coste."""
    batches = batches or eng.cfg["research"]["profile_batches"]
    spec = eng.bench["tasks"]["main"]
    Xtr, ytr, Xva, _ = task.make_dataset(spec, seed)
    Path(eng.store.tmp).mkdir(parents=True, exist_ok=True)
    wd = tempfile.mkdtemp(dir=eng.store.tmp, prefix="obs_")
    try:
        eng.source_context()
        work, bundle = Path(wd, "work"), Path(wd, "bundle")
        work.mkdir()
        np.savez(os.path.join(wd, "data.npz"), Xtr=Xtr, ytr=ytr, Xva=Xva, k=spec["k"])
        lim = eng.lim
        hashes = sandbox.bundle_files(bundle, OBSERVER, src, Path(wd, "data.npz"))
        with sandbox.launch(bundle, work, hashes, {**lim, "max_experiment_seconds": 120}, evaluator._limiter,
                            arguments=(seed, batches), hidden_paths=(eng.store.stable, eng.root / "gaia")) as session:
            channel = evaluator._Chan(session.proc)
            session.verify(channel, min(120, lim["max_experiment_seconds"] + 10))
            prof = json.loads(channel.recv(120))
            if session.proc.wait(timeout=5) != 0:
                raise RuntimeError("observación fallida en sandbox CPU")
            prof["sandbox_evidence"] = session.evidence
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    # descomposición del coste: coste = t_init + pasos_hasta_objetivo x tiempo_por_paso
    trial = eng.trial(src, eng.bench["tiers"]["screen"][0])
    prof["trial"] = {k: (round(v, 4) if isinstance(v, float) else v)
                     for k, v in trial.items() if k in ("reached", "cost_s", "t_init", "status")}
    if trial.get("reached"):
        steps = (trial["cost_s"] - trial["t_init"]) / (prof["ms_per_step"] / 1e3)
        prof["steps_to_target_est"] = round(steps)
        prof["init_share"] = round(trial["t_init"] / trial["cost_s"], 4)
    prof["eval_resolution_share"] = None
    if trial.get("reached"):
        res_s = eng.bench["eval_every"] * prof["ms_per_step"] / 1e3
        prof["eval_resolution_share"] = round(res_s / trial["cost_s"], 4)
    return prof


# ----------------------------------------------------------------------------- historial/ memoria
def _research_records(eng):
    return [r for r in eng.store.records() if r["type"].startswith("research_")]


def priors(eng):
    """Beta(1,1) por familia con los resultados pasados de investigación -> media de éxito."""
    c = {}
    for r in _research_records(eng):
        if r["type"] == "research_result":
            f = c.setdefault(r["family"], [1.0, 1.0])
            if r["status"] == "supported":
                f[0] += 1
            elif r["status"] in ("refuted", "refuted_screen"):
                f[1] += 1
    return {f: a / (a + b) for f, (a, b) in c.items()}


def tested_here(eng, champion):
    return {r["family"] for r in _research_records(eng)
            if r["type"] == "research_result" and r.get("champion") == champion
            and r["status"] in ("refuted", "refuted_screen", "supported", "inconclusive")}


# ----------------------------------------------------------------------------- diagnóstico
def search_health(eng, window=40):
    """Diagnóstico de la búsqueda (no un simple contador): ¿explora? ¿aprende? ¿distingue ruido?"""
    ends = [r for r in eng.store.records() if r["type"] == "end" and r.get("genome")][-window:]
    if not ends:
        return {"n": 0}
    regions = Counter(tuple(sorted(r["genome"]["slots"].items())) for r in ends)
    ops = Counter(o for r in ends for o in r.get("ops", []))
    tot = sum(ops.values()) or 1
    ent = -sum(v / tot * math.log(v / tot) for v in ops.values())
    ent_norm = ent / math.log(len(ops)) if len(ops) > 1 else 0.0
    reached = sum(1 for r in ends if (r.get("screen") or {}).get("reached"))
    cal = eng.bench["calibrated"]["main"]
    return {"n": len(ends), "region_repeat": round(1 - len(regions) / len(ends), 3),
            "distinct_regions": len(regions), "op_entropy_norm": round(ent_norm, 3),
            "informative_fraction": round(reached / len(ends), 3),
            "noise_cv": cal["cv"], "min_gain": eng.acc["min_gain"],
            "since_promotion": eng.state["since_promotion"]}


def diagnose(eng, obs):
    """Lista de explicaciones candidatas con evidencia. Cada una: id, claim, evidence, severity."""
    mg = eng.cfg["research"]["min_expected_gain"]
    f = obs["fractions"]
    D = []
    step = obs["ms_per_step"]
    tr = obs.get("trial", {})
    if obs.get("steps_to_target_est"):
        D.append({"id": "cost_decomposition", "severity": 0.3,
                  "claim": f"coste = {obs['init_share']*100:.0f}% init + {obs['steps_to_target_est']} pasos x {step:.3f} ms",
                  "evidence": {"steps": obs["steps_to_target_est"], "ms_per_step": round(step, 4),
                               "init_share": obs["init_share"]}})
    gather_share = f["sampler"] + min(f["loop_gather"], obs["gather_frac_of_step"])
    for key, label in (("fwd_bwd", "propagación"), ("optimizer", "optimizador"), ("clip", "recorte de gradiente")):
        if f[key] >= mg:
            D.append({"id": f"phase_{key}", "severity": round(f[key], 3),
                      "claim": f"la fase {label} ocupa {f[key]*100:.0f}% del paso",
                      "evidence": {"fraction": round(f[key], 3)}})
    if gather_share >= mg:
        D.append({"id": "phase_gather", "severity": round(gather_share, 3),
                  "claim": f"muestreo + indexado (gather) ocupa ~{gather_share*100:.0f}% del paso",
                  "evidence": {"sampler": round(f["sampler"], 3), "gather_micro": round(obs["gather_frac_of_step"], 3)}})
    if obs["matmul_frac_of_step"] >= 0.5:
        D.append({"id": "matmul_bound", "severity": round(obs["matmul_frac_of_step"], 3),
                  "claim": f"el paso está limitado por producto de matrices (~{obs['matmul_frac_of_step']*100:.0f}%): "
                           "solo cambiar precisión, tamaño o algoritmo puede ayudar",
                  "evidence": {"matmul_frac": round(obs["matmul_frac_of_step"], 3)}})
    res = obs.get("eval_resolution_share")
    if res is not None and res >= mg:
        D.append({"id": "resolution_limited", "severity": round(res, 3),
                  "claim": f"la resolución del benchmark (1 evaluación cada {eng.bench['eval_every']} pasos) es "
                           f"{res*100:.0f}% del coste: mejoras menores son indetectables",
                  "evidence": {"resolution_share": res}, "action": "needs_human"})
    h = search_health(eng)
    if h["n"]:
        if 2 * h["noise_cv"] >= h["min_gain"]:
            D.append({"id": "noise_floor", "severity": round(2 * h["noise_cv"], 3), "action": "needs_human",
                      "claim": f"el ruido de medida (CV {h['noise_cv']*100:.1f}%) es comparable a la mejora exigida "
                               f"({h['min_gain']*100:.0f}%)", "evidence": h})
        if h["region_repeat"] >= 0.5:
            D.append({"id": "search_repeats_region", "severity": h["region_repeat"],
                      "claim": f"la búsqueda repite región: solo {h['distinct_regions']} combinaciones de componentes "
                               f"en los últimos {h['n']} experimentos", "evidence": h})
        if h["informative_fraction"] < 0.3:
            D.append({"id": "search_uninformative", "severity": round(1 - h["informative_fraction"], 3),
                      "claim": f"solo {h['informative_fraction']*100:.0f}% de los experimentos alcanzan el objetivo: "
                               "la búsqueda propone casi siempre variantes inservibles", "evidence": h})
    return sorted(D, key=lambda d: -d["severity"])


# ----------------------------------------------------------------------------- hipótesis
def _with(g, hp=None, slots=None):
    g = copy.deepcopy(g)
    if hp:
        g["hp"].update(hp)
    if slots:
        g["slots"].update(slots)
        g["lits"], g["drops"] = {}, []
    return G.normalize(g)


def _hyp(hid, family, diag, claim, g, kind, ub, prediction, desc, **chg):
    return {"id": hid, "family": family, "diagnosis": diag, "claim": claim, "kind": kind,
            "upper_bound": None if ub is None else round(ub, 3), "prediction": prediction,
            "falsification": "IC95% superior del cociente pareado >= 0.95, o no alcanza la calidad en alguna semilla",
            "intervention": desc, "genome": _with(g, **chg)}


def generate(eng, obs, diags, champ_g):
    """Convierte diagnósticos en hipótesis contrastables (control = campeón)."""
    mg = eng.cfg["research"]["min_expected_gain"]
    f, s, hp = obs["fractions"], champ_g["slots"], champ_g["hp"]
    ids = {d["id"] for d in diags}
    H = []
    gather = f["sampler"] + min(f["loop_gather"], obs["gather_frac_of_step"])
    if "phase_gather" in ids and s["sampler"] != "shuffled_slices":
        H.append(_hyp("H-gather", "slot.sampler:shuffled_slices", "phase_gather",
                      "Barajar una vez y servir lotes como vistas contiguas elimina el gather en cada paso",
                      champ_g, "algorithmic", gather,
                      f"el mecanismo explica como máximo {gather*100:.0f}% del paso; pasos hasta el objetivo no empeoran",
                      "sampler -> shuffled_slices", slots={"sampler": "shuffled_slices"}))
    if "phase_optimizer" in ids and s["optimizer"] == "adam":
        H.append(_hyp("H-opt-inplace", "slot.optimizer:adam_inplace", "phase_optimizer",
                      "Adam con operaciones in-place evita asignaciones temporales por parámetro y paso",
                      champ_g, "implementation", f["optimizer"],
                      "mismo resultado numérico con menos tiempo de optimizador", "optimizer -> adam_inplace",
                      slots={"optimizer": "adam_inplace"}))
    if "phase_fwd_bwd" in ids and s["backward"] == "naive":
        ub = f["fwd_bwd"] * (1 - (obs["matmul_frac_of_fwd_bwd"] or 1.0))
        H.append(_hyp("H-fused-bwd", "slot.backward:fused", "phase_fwd_bwd",
                      "El softmax/gradiente fusionado reduce el trabajo elemento a elemento (no el matmul)",
                      champ_g, "implementation", ub, f"coste baja como máximo {ub*100:.0f}% del paso",
                      "backward -> fused", slots={"backward": "fused"}))
    if "phase_clip" in ids and hp["clip"] > 0:
        H.append(_hyp("H-no-clip", "hp.clip:0", "phase_clip",
                      "El recorte de gradiente cuesta una norma global por paso y quizá no es necesario",
                      champ_g, "algorithmic", f["clip"], "mismo número de pasos sin recorte", "clip -> 0",
                      hp={"clip": 0.0}))
    if "matmul_bound" in ids and s["dtype"] == "float64":
        H.append(_hyp("H-float32", "slot.dtype:float32", "matmul_bound",
                      "Con matmul dominante, precisión simple casi duplica el rendimiento de BLAS y la memoria",
                      champ_g, "algorithmic", None, "paso ~2x más rápido sin perder la calidad objetivo",
                      "dtype -> float32", slots={"dtype": "float32"}))
    if "matmul_bound" in ids and hp["hidden"] > 16:
        ch = G.HP_CHOICES["hidden"]
        nxt = ch[max(0, ch.index(hp["hidden"]) - 1)] if hp["hidden"] in ch else hp["hidden"]
        if nxt != hp["hidden"]:
            H.append(_hyp("H-narrower", f"hp.hidden:{nxt}", "matmul_bound",
                          "Una red más estrecha reduce el cálculo por paso; puede costar pasos extra",
                          champ_g, "algorithmic", None, "coste total menor si los pasos extra no compensan",
                          f"hidden {hp['hidden']} -> {nxt}", hp={"hidden": nxt}))
    if "cost_decomposition" in ids and obs.get("steps_to_target_est", 0) * obs["ms_per_step"] / 1e3 > 0.5 * (obs["trial"].get("cost_s") or 0):
        for tag, k in (("up", 2.0), ("down", 0.5)):
            nb = int(min(1024, max(16, hp["batch"] * k)))
            lr = float(f"{hp['lr'] * k:.4g}")
            if nb != hp["batch"]:
                H.append(_hyp(f"H-lr-batch-{tag}", f"hp.lr_batch:{tag}", "cost_decomposition",
                              "Los pasos dominan el coste: escalar lr y batch juntos (regla lineal) puede reducir "
                              "pasos o coste por paso", champ_g, "algorithmic", None,
                              "menos pasos hasta el objetivo", f"batch {hp['batch']}->{nb}, lr {hp['lr']}->{lr}",
                              hp={"batch": nb, "lr": lr}))
    if ids & {"search_repeats_region", "search_uninformative"}:
        seen = {G.genome_hash(i["genome"]) for i in eng.hist.items}
        for slot, opts in snippets.SLOTS.items():
            for o in opts:
                if o == s[slot]:
                    continue
                g2 = _with(champ_g, slots={slot: o})
                if G.genome_hash(g2) not in seen:
                    H.append(_hyp(f"H-cover-{slot}-{o}", f"slot.{slot}:{o}", "search_coverage",
                                  f"Cambio de un solo factor ({slot}={o}) nunca evaluado en el contexto del campeón",
                                  champ_g, "algorithmic", None, "sin predicción cuantitativa (cobertura)",
                                  f"{slot} -> {o}", slots={slot: o}))
    # deduplicar por genoma
    uniq, out = set(), []
    for h in H:
        gh = G.genome_hash(h["genome"])
        if gh not in uniq:
            uniq.add(gh)
            out.append(h)
    return out


def select(eng, hyps, champion):
    """Poda por cota de Amdahl, memoria y prior; devuelve (a_probar, descartadas)."""
    mg = eng.cfg["research"]["min_expected_gain"]
    pri, done = priors(eng), tested_here(eng, champion)
    keep, drop = [], []
    for h in hyps:
        if h["family"] in done:
            drop.append((h, "ya contrastada con este campeón"))
        elif h["kind"] == "implementation" and h["upper_bound"] is not None and h["upper_bound"] < mg:
            drop.append((h, f"cota de Amdahl {h['upper_bound']*100:.1f}% < mejora mínima {mg*100:.0f}%: "
                            "no puede ser detectable"))
        else:
            ub = h["upper_bound"] if h["upper_bound"] is not None else mg
            h["score"] = round(pri.get(h["family"], 0.5) * ub * (1.0 if h["kind"] == "implementation" else 0.6), 4)
            keep.append(h)
    keep.sort(key=lambda h: -h["score"])
    return keep[:eng.cfg["research"]["max_hypotheses"]], drop + [(h, "fuera del cupo del ciclo") for h in keep[eng.cfg["research"]["max_hypotheses"]:]]


# ----------------------------------------------------------------------------- inferencia
def infer(decision, end, h=None):
    """Hipótesis -> veredicto a partir del registro final del laboratorio."""
    c, sc = end.get("confirm"), end.get("screen") or {}
    if decision == "accepted":
        why = f"promovida: coste {c['ratio']}x (IC95% sup. {c['ratio_upper95']})"
        ub = (h or {}).get("upper_bound")
        if ub is not None and (1 - c["ratio"]) > ub * 1.5:
            why += (f". SORPRESA: la ganancia observada ({(1-c['ratio'])*100:.0f}%) supera la cota mecanística "
                    f"({ub*100:.0f}%): el modelo causal es incompleto (efecto en pasos o en caché)")
        return "supported", why
    if decision == "pareto_alternative":
        return "inconclusive", "más rápida pero con más RAM (alternativa Pareto)"
    if decision == "deferred":
        return "inconclusive", f"mejora probable pero no concluyente (ratio {c['ratio']}, IC sup. {c['ratio_upper95']})"
    if c and c.get("ratio") is not None:
        return "refuted", f"confirmación: coste {c['ratio']}x (IC95% sup. {c['ratio_upper95']}) sin mejora verificable"
    if sc.get("reached"):
        return "refuted_screen", end["reason"]
    return "inconclusive", "la variante no cumple calidad/ejecución: no contrasta el mecanismo (" + end["reason"][:80] + ")"


# ----------------------------------------------------------------------------- ciclo
def cycle(eng, deadline=None, max_experiments=None):
    """Un ciclo completo de investigación. Devuelve resumen (incluye 'improved' y 'text')."""
    st, log = eng.state, eng.log
    if max_experiments is not None and max_experiments <= 0:
        return {"improved": False, "results": [], "diagnoses": [], "text": "Presupuesto agotado", "pruned": []}
    champion = eng.store.current_version()
    champ_g, champ_src = eng.store.load_version()
    log(f"== INVESTIGACIÓN (Modo B) sobre {champion}: observar, diagnosticar, formular hipótesis ==")
    obs = observe(eng, champ_src)
    diags = diagnose(eng, obs)
    eng.store.append({"type": "research_diagnosis", "champion": champion, "observation": obs, "diagnoses": diags})
    for d in diags:
        log(f"   diagnóstico [{d['id']}] {d['claim']}")
    hyps = generate(eng, obs, diags, champ_g)
    todo, dropped = select(eng, hyps, champion)
    for h, why in dropped:
        log(f"   descartada {h['id']}: {why}")
        eng.store.append({"type": "research_hypothesis", "champion": champion, "status": "pruned",
                          "reason": why, **{k: h[k] for k in ("id", "family", "claim", "kind", "upper_bound")}})
    results, improved = [], False
    for h in todo:
        if max_experiments is not None and len(results) >= max_experiments:
            break
        if eng.store.stop_requested() or (deadline and time.monotonic() >= deadline):
            break
        log(f"   hipótesis {h['id']} ({h['kind']}, cota {h['upper_bound']}): {h['claim']}")
        eng.store.append({"type": "research_hypothesis", "champion": champion, "status": "testing",
                          **{k: h[k] for k in ("id", "family", "claim", "kind", "upper_bound", "prediction",
                                               "falsification", "intervention", "diagnosis")}})
        hyp_meta = {"limitation": h["diagnosis"], "component": h["intervention"], "rationale": h["claim"],
                    "expected": h["prediction"], "regression_risk": "ver criterio de falsación",
                    "origin": "research", "research_id": h["id"]}
        decision = eng.experiment(proposal=(h["genome"], [f"research:{h['family']}"], None, None),
                                  research=hyp_meta)
        end = eng.last_end
        decision = "accepted" if decision == "improved" else decision
        status, why = infer(decision, end, h)
        eng.store.append({"type": "research_result", "id": h["id"], "family": h["family"], "champion": champion,
                          "status": status, "evidence": why, "experiment": end.get("id"), "kind": h["kind"]})
        log(f"      -> {status.upper()}: {why}")
        results.append({"id": h["id"], "status": status, "why": why, "family": h["family"]})
        if status == "supported":
            for slot, opt in h["genome"]["slots"].items():
                if (slot, opt) in snippets.RESEARCH_ONLY:
                    st.setdefault("unlocked", []).append([slot, opt])
                    snippets.set_unlocked(st["unlocked"])
                    eng.store.append({"type": "research_unlock", "option": [slot, opt], "hypothesis": h["id"]})
                    log(f"      la opción {slot}={opt} entra en el espacio de la búsqueda")
            improved = True
            break                       # el campeón cambió: las demás hipótesis eran sobre el anterior
    text = summarize(obs, diags, results, dropped, improved)
    st["research_summary"] = text
    eng.store.save_state(st)
    return {"improved": improved, "results": results, "diagnoses": diags, "text": text,
            "pruned": [(h["id"], why) for h, why in dropped]}


def summarize(obs, diags, results, dropped, improved):
    L = ["Investigación autónoma (Modo B):"]
    L += [f"- diagnóstico {d['id']}: {d['claim']}" for d in diags[:6]]
    L += [f"- {r['id']}: {r['status']} ({r['why']})" for r in results]
    L += [f"- {h['id']} no contrastada: {why}" for h, why in dropped[:6]]
    if not improved:
        human = [d for d in diags if d.get("action") == "needs_human"]
        if human:
            L.append("Conclusión: el límite parece estar en el INSTRUMENTO (" + "; ".join(d["id"] for d in human) +
                     "), no en el optimizador: hace falta decisión humana sobre el benchmark.")
        elif all(r["status"] in ("refuted", "refuted_screen") for r in results) and results:
            L.append("Conclusión: las palancas de implementación contrastadas fueron refutadas; el margen restante "
                     "está en cambios algorítmicos o en ampliar el espacio de componentes.")
        else:
            L.append("Conclusión: evidencia insuficiente; ver las hipótesis inconclusas.")
    return "\n".join(L)
