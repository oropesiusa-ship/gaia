#!/usr/bin/env python3
"""GAIA — núcleo de automejora computacional verificable.

  python gaia.py run                 # lo hace todo solo; para al primer avance verificado,
                                     # al necesitar ayuda humana, o al agotar presupuesto
  python gaia.py run --keep-going    # no para en la primera mejora
  python gaia.py prepare | research | status | report | audit | meta | prove | stop | resume | rollback | selftest
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from gaia.bootstrap import dispatch
    args = sys.argv[1:]
    result = dispatch(ROOT, args)
    sys.argv[1:] = args
    if result is not None:
        sys.exit(result)

def make(args=None):
    return engine.Engine(ROOT, config.load(ROOT))


def cmd_run(a):
    if a.skip_gate or a.force:
        print("CAMPAIGN GATES: BLOCKED — --skip-gate/--force are not allowed for CPU MVP certification")
        return 30
    if (ROOT / "NEEDS_HUMAN.md").exists() and not a.force:
        print((ROOT / "NEEDS_HUMAN.md").read_text())
        print("Resuelve el problema, borra NEEDS_HUMAN.md y vuelve a ejecutar. --force no omite gates MVP.")
        return engine.EXIT["needs_human"]
    try:
        eng = make()
    except ValueError as exc:
        print("CAMPAIGN GATES: BLOCKED — " + str(exc))
        return 30
    until = "budget" if a.keep_going else "improvement"
    out = eng.run(until=until, minutes=a.minutes, max_experiments=a.max_experiments,
                  meta=False if a.no_meta else None)
    msg = {"improved": "Parada: mejora verificada. Revisa `python gaia.py report`.",
           "budget": "Parada: presupuesto de tiempo/experimentos agotado.",
           "stopped": "Parada manual (archivo STOP). Bórralo para reanudar: `python gaia.py resume`.",
            "needs_human": "Parada: campaña bloqueada; revisa las causas indicadas y NEEDS_HUMAN.md si existe."}[out]
    print("\n" + msg)
    if (eng.store.dir / "benchmark.json").exists() and (eng.store.dir / "state.json").exists():
        report.write(eng)
    return engine.EXIT[out]


def cmd_prepare(a):
    eng = make()
    out = readiness.prepare(eng, refreeze=a.refreeze, initialize_mvp=a.initialize_mvp)
    print_requirements(out)
    print(f"\n==> {out['status']}")
    if out.get("reason"):
        print(out["reason"])
    for n, g in out.get("gates", {}).items():
        print(f"  {n}: {'PASS' if g['ok'] else 'FAIL'}")
    return 0 if out["status"] == "READY_FOR_CAMPAIGN" else 30


def print_requirements(out):
    req = out.get("requirements", {})
    source, bwrap = req.get("source", {}), req.get("bwrap", {})
    for label, value in (("Source snapshot", source.get("snapshot")),
                         ("Source manifest", source.get("manifest")),
                         ("Source integrity", source.get("integrity")),
                         ("bwrap available", bwrap.get("available")),
                         ("bwrap verified", bwrap.get("verified"))):
        print(f"{label}: {'PASS' if value else 'FAIL'}")
    environment = req.get("environment") or {}
    for label, key in (("Manifest", "manifest"), ("Environment identity", "environment"),
                       ("Runtime identity", "runtime"), ("Config identity", "config"),
                       ("Sandbox policy", "sandbox_policy")):
        print(f"{label}: {'PASS' if environment.get('checks', {}).get(key) else 'FAIL'}")
    print("State schema:", req.get("state_schema", "UNKNOWN"))
    # G3 contains the verified chain diagnostics when gates ran.
    ledger_gate = out.get("gates", {}).get("G3_integrity", {})
    for label, key in (("Ledger schema", "ledger_schema"), ("Ledger chain", "ledger_chain"),
                       ("Ledger evidence refs", "ledger_evidence_refs"), ("Ledger version refs", "ledger_version_refs")):
        print(f"{label}: {'PASS' if ledger_gate.get(key) else 'FAIL'}")
    print("CPU sandbox:", out.get("gates", {}).get("G0_runtime", {}).get("cpu_sandbox_status", "NOT_VERIFIED"))
    print("Campaign readiness:", "READY" if out["status"] == "READY_FOR_CAMPAIGN" else "BLOCKED")
    for reason in req.get("reasons", []):
        print("  -", reason)


def cmd_research(a):
    res = make().research_now()
    print("\n" + res["text"])
    return 0


def cmd_status(a):
    eng = make()
    if not (eng.store.dir / "benchmark.json").exists():
        print("Sin inicializar. Ejecuta `python gaia.py run`.")
        return 0
    eng._load()
    st = eng.state
    c = eng.bench["calibrated"]["main"]
    print(f"Versión estable: {eng.store.current_version()} · versiones: {eng.store.versions()}")
    print(f"Experimentos: {st['n_experiments']} · sin mejora desde hace: {st['since_promotion']} · "
          f"búsqueda: {st['search_seconds']/60:.1f} min")
    print(f"Línea base: {c['ref_cost_s']} s (CV {c['cv']*100:.1f}%) · objetivo de calidad {c['target']}")
    print(f"Estrategia de búsqueda: v{st['strategy'].get('version', 0)} {st['strategy']}")
    print(f"Disco: {eng.store.disk_mb():.1f} MB · STOP: {eng.store.stop_requested()} · "
          f"NEEDS_HUMAN: {(ROOT / 'NEEDS_HUMAN.md').exists()}")
    return 0


def cmd_report(a):
    print(report.write(make()))
    return 0


def cmd_audit(a):
    eng = make()
    require_cpu_mvp(eng)
    eng.init()
    out = report.audit(eng)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    report.write(eng)
    return 0


def cmd_meta(a):
    eng = make()
    require_cpu_mvp(eng)
    eng.init()
    eng._load()
    eng.store.lock()
    try:
        print(engine_meta(eng, a.rounds))
    finally:
        eng.store.unlock()
    return 0


def engine_meta(eng, rounds):
    from gaia import meta
    res = meta.tune(eng, rounds=rounds)
    eng.store.save_state(eng.state)
    return res


def cmd_prove(a):
    from gaia import meta
    eng = make()
    require_cpu_mvp(eng)
    eng.init()
    eng._load()
    eng.store.lock()
    try:
        out = meta.prove(eng, budget=a.budget, n_seeds=a.seeds)
    finally:
        eng.store.unlock()
    print(json.dumps(out, indent=1, ensure_ascii=False))
    report.write(eng)
    return 0


def cmd_stop(a):
    (ROOT / "STOP").write_text("stop\n")
    print("STOP creado: GAIA se detendrá antes del siguiente experimento.")
    return 0


def cmd_resume(a):
    (ROOT / "STOP").unlink(missing_ok=True)
    print("STOP eliminado.")
    return 0


def cmd_rollback(a):
    eng = make()
    result = eng.rollback(a.to, a.reason)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "COMPLETED" else 30


def cmd_certify_pipeline(a):
    from gaia import certification
    result = certification.run(ROOT)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["pipeline_certified"] else 30


def cmd_verify_autonomous_mvp(a):
    from gaia import autonomous_mvp
    result = autonomous_mvp.run(ROOT)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["autonomous_self_improvement_certified"] else 30


def require_cpu_mvp(eng):
    from gaia import provenance
    req = provenance.prerequisites(eng)
    if not req["ok"]:
        raise ValueError("MVP operation blocked: " + "; ".join(req["reasons"]))


def cmd_selftest(a):
    import unittest
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.epilog = "Arranque automático: bootstrap | doctor | appliance-bootstrap | appliance-rootfs | appliance-image | appliance-verify | appliance-recovery | gaia-transformer-baseline | gaia-transformer-lab | gaia-transformer-benchmark | gaia-transformer-prepare | gaia-transformer-run | gaia-transformer-observe | gaia-transformer-research | gaia-transformer-meta. --no-bootstrap delante del comando usa el runtime/estado manual."
    sub = p.add_subparsers(dest="cmd", required=True)
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help", "plan-experiments", "experiment-strategies", "experiment-strategy", "strategy-metrics"):
        from gaia.experiment_strategy.cli import register as register_meta_strategy
        register_meta_strategy(sub, ROOT)
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help", "learn-experiments", "learning-records", "learning-record", "knowledge", "knowledge-item", "query-knowledge"):
        from gaia.learning.cli import register as register_learning
        register_learning(sub, ROOT)
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help", "prioritize", "priorities", "priority"):
        from gaia.prioritization.cli import register as register_priority
        register_priority(sub, ROOT)
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help", "diagnose", "diagnoses", "diagnosis"):
        from gaia.diagnosis.cli import register as register_diagnosis
        register_diagnosis(sub, ROOT)
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help", "observe", "observations", "observation", "compare-observations"):
        from gaia.observation.cli import register
        register(sub, ROOT)
    sub.add_parser("certify-pipeline", help="Prueba A aislada/controlada; NO certifica automejora autónoma").set_defaults(f=cmd_certify_pipeline)
    sub.add_parser("verify-autonomous-mvp", help="Prueba B: UNA campaña Engine.run normal y verificación, sin seleccionar candidatas").set_defaults(f=cmd_verify_autonomous_mvp)
    r = sub.add_parser("run")
    r.add_argument("--keep-going", action="store_true", help="no parar en la primera mejora")
    r.add_argument("--minutes", type=float, help="tiempo máximo de esta ejecución")
    r.add_argument("--max-experiments", type=int)
    r.add_argument("--no-meta", action="store_true", help="desactiva la metaoptimización")
    r.add_argument("--skip-gate", action="store_true", help="rechazado en CPU MVP: no permite omitir G0-G5")
    r.add_argument("--force", action="store_true", help="rechazado en CPU MVP: no permite forzar campaña/promoción")
    r.set_defaults(f=cmd_run)
    for n, f in (("status", cmd_status), ("report", cmd_report), ("audit", cmd_audit),
                  ("stop", cmd_stop), ("resume", cmd_resume),
                 ("selftest", cmd_selftest)):
        sub.add_parser(n).set_defaults(f=f)
    pp = sub.add_parser("prepare")
    pp.add_argument("--refreeze", action="store_true", help="vuelve a congelar la identidad (queda registrado)")
    pp.add_argument("--initialize-mvp", action="store_true", help="crea explícitamente baseline MVP en estado nuevo vacío")
    pp.set_defaults(f=cmd_prepare)
    rb = sub.add_parser("rollback", help="rollback explícito a un ancestro certificado")
    rb.add_argument("--to", required=True, help="versión ancestro explícita vNNNN")
    rb.add_argument("--reason", required=True, help="motivo no vacío del operador")
    rb.set_defaults(f=cmd_rollback)
    sub.add_parser("research").set_defaults(f=cmd_research)
    m = sub.add_parser("meta")
    m.add_argument("--rounds", type=int, default=3)
    m.set_defaults(f=cmd_meta)
    pr = sub.add_parser("prove")
    pr.add_argument("--budget", type=int)
    pr.add_argument("--seeds", type=int, default=12)
    pr.set_defaults(f=cmd_prove)
    a = p.parse_args()
    if any(getattr(a, name, False) for name in ("observation_command", "diagnosis_command", "priority_command", "learning_command", "meta_strategy_command")):
        sys.exit(a.f(a) or 0)
    # El help y el bootstrap funcionan incluso sin NumPy en el Python de arranque.
    global config, engine, readiness, report
    from gaia import config, engine, readiness, report
    try:
        sys.exit(a.f(a) or 0)
    except KeyboardInterrupt:
        print("\nInterrumpido. El estado persistente permite reanudar con `python gaia.py run`.")
        sys.exit(130)


if __name__ == "__main__":
    main()
