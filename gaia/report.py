import json
import statistics
from collections import Counter

from . import engine as E
from . import stats
from .store import atomic_write


def audit(eng):
    """Campeón vs línea base en semillas de AUDITORÍA (nunca usadas para seleccionar),
    en la tarea principal y en la tarea distinta 'audit'."""
    eng._load()
    _, champ_src = eng.store.load_version()
    _, base_src = eng.store.load_version("v0000")
    out = {"champion": eng.store.current_version(), "tasks": {}}
    for task in ("main", "audit"):
        base, champ = [], []
        for i, s in enumerate(eng.bench["tiers"]["audit"]):
            order = ("champ", "base") if i % 2 == 0 else ("base", "champ")
            for who in order:
                r = eng.trial(champ_src if who == "champ" else base_src, s, task=task,
                              cap=eng.lim["max_experiment_seconds"])
                (champ if who == "champ" else base).append(r)
        v = stats.decide(base, champ, eng.acc)
        v["baseline_median_s"] = round(statistics.median(r["cost_s"] for r in base if r["reached"]), 4) \
            if any(r["reached"] for r in base) else None
        v["champion_median_s"] = round(statistics.median(r["cost_s"] for r in champ if r["reached"]), 4) \
            if any(r["reached"] for r in champ) else None
        out["tasks"][task] = v
    atomic_write(eng.store.dir / "audit_latest.json", json.dumps(out, indent=1))
    return out


def pareto(points):
    keep = []
    for p in points:
        if not any(q[0] <= p[0] and q[1] <= p[1] and (q[0] < p[0] or q[1] < p[1]) for q in points):
            keep.append(p)
    return sorted(set(keep))


def build(eng):
    st = eng.store
    recs = st.records()
    ends = [r for r in recs if r["type"] == "end" and r.get("genome")]
    init = next((r for r in recs if r["type"] == "init"), None)
    L = ["# Informe de GAIA\n"]
    if not init:
        return "# Informe de GAIA\n\nAún no hay datos. Ejecuta `python gaia.py run`.\n"
    cal = init["calibrated"]["main"]
    L.append(f"**Línea base** (v0000): coste hasta objetivo **{cal['ref_cost_s']} s** "
             f"(calidad objetivo {cal['target']}; variabilidad entre repeticiones CV={cal['cv']*100:.1f}%).\n")
    dec = Counter(r["decision"] for r in ends)
    L.append(f"**Experimentos:** {len(ends)} · " + ", ".join(f"{k}: {v}" for k, v in dec.most_common()))
    abortados = sum(1 for r in recs if r["type"] == "end" and r["decision"] == "aborted")
    if abortados:
        L.append(f"· abortados por interrupción (no válidos): {abortados}")
    tot = sum(r.get("search_cost_s", 0) for r in ends)
    L.append(f"\n**Coste total de búsqueda:** {tot:.0f} s ({tot/60:.1f} min).\n")

    L.append("## Mejoras verificadas (versiones estables)\n")
    vs = st.versions()
    if len(vs) == 1:
        L.append("Ninguna todavía. La línea base sigue siendo el campeón.\n")
    for v in vs[1:]:
        ev = json.loads((st.stable / v / "evidence.json").read_text())
        c = ev["confirm"]
        L.append(f"- **{v}** · coste {c['ratio']:.3f}x del anterior (IC95% sup. {c['ratio_upper95']:.3f}, "
                 f"{c['pairs']} pares) · RAM {c.get('mem_ratio')}x · procedencia **{ev['provenance']}** · "
                 f"{ev['hypothesis']['detail']} · cambios vs anterior: "
                 + ", ".join(f"{d[0]}" for d in ev.get("diff_vs_champion", [])) +
                 f" · tras {ev['experiments_since_last_promotion']} experimentos")
    L.append("\n> Procedencia `known`: técnica conocida elegida por la búsqueda; NO es un descubrimiento "
             "autónomo. Solo `generated` (mutaciones de código propias) podría serlo, y únicamente si la "
             "auditoría la confirma.\n")
    try:
        a = json.loads((st.dir / "audit_latest.json").read_text())
        L.append("## Auditoría independiente (semillas nunca usadas para seleccionar)\n")
        for t, v in a["tasks"].items():
            L.append(f"- tarea `{t}`: línea base {v.get('baseline_median_s')} s → {a['champion']} "
                     f"{v.get('champion_median_s')} s · cociente {v.get('ratio')} · decisión **{v['decision']}** "
                     f"({v['reason']})")
        L.append("")
    except FileNotFoundError:
        L.append("## Auditoría\n\nNo ejecutada. Usa `python gaia.py audit` antes de afirmar nada.\n")

    pts = []
    for r in ends:
        s = r["screen"]
        if s.get("reached") and s.get("peak_rss_mb"):
            pts.append((round(s["cost_s"], 3), round(s["peak_rss_mb"], 1)))
    L.append("## Frontera de Pareto (tiempo hasta objetivo, RAM máx.), cribado\n")
    for p in pareto(pts)[:8]:
        L.append(f"- {p[0]} s · {p[1]} MB")
    L.append("")

    L.append("## Qué operadores funcionan (aprendizaje del historial)\n")
    ops = {}
    for r in ends:
        for o in r.get("ops", []):
            d = ops.setdefault(o, [0, 0, 0])
            d[0] += 1
            d[1] += r["decision"] in ("accepted", "deferred", "pareto_alternative")
            d[2] += bool(r["screen"].get("reached"))
    L.append("| operador | intentos | alcanzan objetivo | llegan a confirmación o mejor |\n|---|---|---|---|")
    for o, (n, a_, b_) in sorted(ops.items(), key=lambda x: -x[1][0]):
        L.append(f"| {o} | {n} | {b_} | {a_} |")
    metas = [r for r in recs if r["type"] == "meta"]
    L.append(f"\n## Metaoptimización (Nivel 4)\n\nEstrategia actual: v{eng.state.get('strategy', {}).get('version', 0)} "
             f"· {len(metas)} variantes evaluadas, {sum(m['adopted'] for m in metas)} adoptadas.\n")
    try:
        p = json.loads((st.dir / "meta" / "prove_latest.json").read_text())
        L.append("## Verificación de la mejora recursiva (Nivel 5)\n")
        for k, c in p["comparisons"].items():
            verdict = "MEJORA" if c["ci90"][1] < 0 else ("EMPEORA" if c["ci90"][0] > 0 else "SIN DIFERENCIA CONCLUYENTE")
            L.append(f"- {k}: Δ AUC log-coste {c['mean_auc_diff']} IC90% {c['ci90']} → **{verdict}** "
                     f"(evals hasta -20%: {c['evals20_a']} → {c['evals20_b']}; {c['n_seeds']} semillas)")
    except FileNotFoundError:
        L.append("## Nivel 5\n\nNo verificado. Usa `python gaia.py prove`.\n")
    L.append("\n## Límites conocidos\n\n- Tarea sintética en CPU (NumPy); no demuestra nada sobre LLM ni GPU.\n"
             "- El MVP CPU actual exige bwrap con handshake y RLIMIT; los históricos previos no acreditan ese aislamiento.\n"
             "- Energía solo si el sistema expone RAPL; si no, no se mide.\n"
             "- El paisaje de metaoptimización congela mediciones de tiempo (con ruido); por eso la verificación "
             "usa una tarea distinta.\n")
    rr = [r for r in eng.store.records() if r["type"] == "research_result"]
    if rr:
        L += ["", "## Investigación autónoma (Modo B)", "",
              f"Hipótesis contrastadas: {len(rr)} · apoyadas {sum(r['status'] == 'supported' for r in rr)} · "
              f"refutadas {sum(r['status'].startswith('refuted') for r in rr)} · "
              f"inconclusas {sum(r['status'] == 'inconclusive' for r in rr)}", "",
              "| hipótesis | familia | campeón | veredicto | evidencia |", "|---|---|---|---|---|"]
        L += [f"| {r['id']} | {r['family']} | {r['champion']} | {r['status']} | {r['evidence'][:90]} |" for r in rr]
        pr = [r for r in eng.store.records() if r["type"] == "research_hypothesis" and r.get("status") == "pruned"]
        if pr:
            L += ["", f"Descartadas sin gastar experimento (cota de Amdahl, memoria o cupo): {len(pr)}"]
    return "\n".join(L)


def write(eng):
    eng._load()
    text = build(eng)
    atomic_write(eng.root / "REPORT.md", text)
    return text
