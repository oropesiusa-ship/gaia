"""Puertas G0-G5: una sola batería automática antes de una campaña.

READY solo si TODAS pasan. Si algo cambia después (runtime, config, archivos protegidos), `run` se niega.
Nunca se relajan reglas retrospectivamente: un cambio crítico exige nueva baseline/estado.
`prepare --refreeze` solo repite las puertas bajo la misma identidad certificada.
"""
import json
import math
import statistics
import time
import uuid
from pathlib import Path

import numpy as np

from . import genome as G
from . import integrity, snippets, stats, provenance, manifest, ledger
from .protected import runtime, evaluator
from .store import atomic_write, sha256

def runtime_fp():
    """Huella del padre con el MISMO criterio que usa el worker (torch incluido en modo torch)."""
    return runtime.fingerprint(with_torch=evaluator._torch_mode())


def config_hash(cfg):
    return provenance.digest(provenance.experimental_config(cfg))


def identity(eng):
    root = eng.root
    fp = runtime_fp()
    return {"runtime": runtime.digest(fp), "runtime_detail": fp, "config": config_hash(eng.cfg),
            "protected": {str(f.relative_to(root)): sha256(f)
                          for f in integrity.protected_files(root, eng.store.dir)},
            "snippets": sha256(root / "gaia" / "snippets.py"),
            "sandbox": "bwrap CPU: user/pid/net/ipc/uts, read-only bundle, private work/tmp, RLIMIT",
            "champion_at_freeze": eng.store.current_version()}


def _gate(ok, **detail):
    return {"ok": bool(ok), **detail}


# ----------------------------------------------------------------------------------- G0
def g0_runtime(eng, src):
    requirements = provenance.prerequisites(eng)
    reasons = []
    if requirements["state_schema"] != "MVP_CPU_V1":
        reasons.append("STATE_SCHEMA_INVALID")
    if not requirements["source"].get("ok") or not requirements["source"].get("integrity"):
        reasons.append("SOURCE_INTEGRITY_FAILED")
    if not (requirements.get("environment") or {}).get("ok"):
        reasons.append("ENVIRONMENT_MISMATCH")
    recovery = requirements.get("publication_recovery") or {}
    if (recovery.get("status") != "READY" or recovery.get("pointer_temporaries") or
            any(not row["never_published"] for row in recovery.get("staging", []))):
        reasons.append("RECOVERY_REQUIRED")
    if not requirements["bwrap"]["verified"]:
        reasons.append("SANDBOX_UNAVAILABLE")
    if reasons or not requirements["ok"]:
        return _gate(False, reason_codes=reasons or ["ENVIRONMENT_MISMATCH"], requirements_errors=requirements["reasons"],
                     cpu_sandbox_status="NOT_VERIFIED")
    try:
        # Infrastructure probe only: no benchmark/quality comparison before G0.
        r = evaluator.check_correctness(src, limits=eng.lim, include_evidence=True)
    except Exception as exc:
        r = getattr(exc, "trial_result", {"status": "error", "error": str(exc)})
    pfp = runtime.digest(runtime_fp())
    smoke = provenance.bwrap_capability()
    environment = requirements["environment"]
    verified = r.get("sandbox") is True and r.get("sandbox_validation") is True and r.get("promotable") is True
    ok = r["status"] == "ok" and r.get("worker_fp") == pfp and smoke["verified"] and verified and environment["ok"]
    extra = {}
    if evaluator._torch_mode():                          # workload con torch/CUDA
        t = runtime_fp().get("torch") or {}
        arch_ok = bool(t.get("cuda_available")) and runtime.arch_supports(t.get("arch_list"), t.get("capability", [0, 0]))
        extra = {"torch": t.get("version"), "arch_list": t.get("arch_list"), "gpu_capability": t.get("capability"),
                 "arch_covers_gpu": arch_ok}
        ok = ok and arch_ok
    return _gate(ok, parent=pfp, worker=r.get("worker_fp"), status=r["status"], error=r["error"][:200], **extra,
                  sandbox_required=True, bwrap_status="BWRAP_AVAILABLE" if smoke["verified"] else "SANDBOX_UNAVAILABLE",
                  cpu_sandbox_status="CPU_SANDBOX_VERIFIED" if verified else "SANDBOX_UNAVAILABLE",
                  sandbox_evidence=r.get("sandbox_evidence"), sandbox_reason=r.get("reason"),
                  manifest_checks=environment["checks"], manifest_errors=environment["errors"],
                  reason_codes=[] if ok else ["SANDBOX_UNAVAILABLE"])


def g1_candidate(eng, genome, source):
    from .protected import guard
    try:
        if (not isinstance(genome, dict) or set(genome) != set(G.BASELINE) or
                set(genome["hp"]) != set(G.HP_DEFAULT) or set(genome["slots"]) != set(G.BASELINE["slots"])):
            return _gate(False, reason_codes=["INVALID_GENOME"])
        rendered = G.render(genome)
    except guard.GuardError as exc:
        return _gate(False, reason_codes=["GUARD_REJECTED"], error=str(exc))
    except (ValueError, KeyError, TypeError, SyntaxError) as exc:
        return _gate(False, reason_codes=["INVALID_GENOME"], error=str(exc))
    if source != rendered:
        return _gate(False, reason_codes=["SOURCE_RENDER_MISMATCH"])
    try:
        guard.check_source(source)
        import ast
        if any(isinstance(node, ast.Constant) and isinstance(node.value, str) and Path(node.value).is_absolute()
               for node in ast.walk(ast.parse(source))):
            return _gate(False, reason_codes=["GUARD_REJECTED"], error="Absolute candidate paths are forbidden")
        # Retain existing numerical checks for the permitted implementation
        # slots. Candidate-specific smoke uses its actual precision/parameters.
        correctness = g1_correctness()
        if not correctness["ok"]:
            return _gate(False, reason_codes=["INVALID_GENOME"], correctness=correctness)
        trial = eng.trial(source, eng.bench["tiers"]["screen"][0], target=2.0,
                          max_batches=eng.bench["eval_every"])
        ok = trial["status"] == "ok" and trial.get("sandbox_validation") is True and trial.get("promotable") is True
        return _gate(ok, reason_codes=[] if ok else ["CANDIDATE_LOAD_FAILED"],
                     trainer_hash=__import__("hashlib").sha256(source.encode()).hexdigest(),
                     genome_hash=provenance.digest(genome), trial_evidence=[trial])
    except guard.GuardError as exc:
        return _gate(False, reason_codes=["GUARD_REJECTED"], error=str(exc))
    except (OSError, RuntimeError, ValueError) as exc:
        return _gate(False, reason_codes=["CANDIDATE_LOAD_FAILED"], error=str(exc))


# ----------------------------------------------------------------------------------- G1
def _grad_check(src, tol=1e-5):
    """Analytic vs finite differences, executed inside the mandatory sandbox."""
    return evaluator.check_correctness(src)["gradient_error"]


def g1_correctness():
    from .protected import guard
    bad = {}
    for slot_act in snippets.SLOTS["act"]:
        for bw in snippets.SLOTS["backward"]:
            g = G.new_genome(slots={"act": slot_act, "backward": bw})
            if slot_act == "relu":       # relu no es derivable en 0; los puntos aleatorios no caen ahí
                pass
            err = _grad_check(G.render(g))
            if err > 1e-4:
                bad[f"{slot_act}/{bw}"] = err
    blocked = 0
    for evil in ("import os", "x = open('f')", "eval('1')", "import subprocess"):
        try:
            guard.check_source(evil)
        except guard.GuardError:
            blocked += 1
    rng = np.random.default_rng(1)
    for _ in range(60):
        G.render(__import__("gaia.mutate", fromlist=["x"]).random_genome(rng))
    # cada muestreador devuelve índices/trozos válidos
    for name in snippets.SLOTS["sampler"]:
        result = evaluator.check_correctness(G.render(G.new_genome(slots={"sampler": name})))
        if not result["sampler_valid"]:
            bad[f"sampler/{name}"] = "tamaño de lote incorrecto"
    return _gate(not bad and blocked == 4, gradient_errors=bad, guard_blocked=f"{blocked}/4",
                 options_checked=sum(len(v) for v in snippets.SLOTS.values()))


# ----------------------------------------------------------------------------------- G2
def g2_reliability(eng, src):
    rc = eng.cfg["readiness"]
    seed = eng.bench["tiers"]["screen"][0]
    rs = [eng.trial(src, seed) for _ in range(rc["reliability_runs"])]
    if any(r["status"] != "ok" or r.get("sandbox_validation") is not True or r.get("promotable") is not True
           or not isinstance(r.get("peak_rss_mb"), (float, int)) or not 0 < r["peak_rss_mb"] <= eng.lim["max_ram_mb"] for r in rs):
        return _gate(False, reason_codes=["BASELINE_QUALITY_FAILED"], trial_evidence=rs)
    reached = sum(r["reached"] for r in rs)
    costs = [r["cost_s"] for r in rs if r["reached"]]
    if reached < len(rs) or len(costs) < 3:
        return _gate(False, reached=f"{reached}/{len(rs)}", reason_codes=["BASELINE_QUALITY_FAILED"], trial_evidence=rs)
    if any(type(cost) not in (float, int) or not math.isfinite(cost) or cost <= 0 for cost in costs):
        return _gate(False, reason_codes=["BASELINE_UNSTABLE"], trial_evidence=rs)
    cv = statistics.pstdev(costs) / statistics.mean(costs)
    med = statistics.median(costs)
    half = len(costs) // 2
    drift = abs(statistics.median(costs[half:]) / statistics.median(costs[:half]) - 1)
    warm = costs[0] / med
    ok = cv <= rc["max_cv"] and warm <= rc["max_warmup_ratio"] and drift <= eng.cfg["stop"]["drift_tolerance"]
    reasons = []
    if cv > rc["max_cv"] or warm > rc["max_warmup_ratio"]:
        reasons.append("BASELINE_UNSTABLE")
    if drift > eng.cfg["stop"]["drift_tolerance"]:
        reasons.append("BASELINE_DRIFT")
    return _gate(ok, reached=f"{reached}/{len(rs)}", cv=round(cv, 4), warmup_ratio=round(warm, 3),
                  drift=round(drift, 3), median_s=round(med, 4), costs=[round(c, 4) for c in costs],
                  reason_codes=reasons, trial_evidence=rs)


# ----------------------------------------------------------------------------------- G3
def g3_integrity(eng):
    bad = integrity.verify(eng.root, eng.store.dir)
    from .ledger import verify_ledger
    chain = verify_ledger(eng.store)
    from .ledger import current_from_records
    current_matches = chain["ok"] and current_from_records(chain["records"]) == eng.store.current_version()
    cur = eng.store.current_version()
    ok_ver = cur in eng.store.versions() and all((eng.store.stable / v / "evidence.json").exists()
                                                  for v in eng.store.versions())
    environment = manifest.validate_manifest(eng)
    recovery = eng.store.recover_publications(eng)
    reasons = []
    if not chain["ok"]:
        reasons.append("LEDGER_INVALID")
    if not environment["ok"]:
        reasons.append("MANIFEST_INVALID")
    if not ok_ver or bad:
        reasons.append("VERSION_INTEGRITY_FAILED")
    if not current_matches or recovery["status"] != "READY":
        reasons.append("LINEAGE_INVALID")
    return _gate(not reasons, reason_codes=reasons, tampered=bad, ledger_schema=chain["schema"],
                 ledger_chain=chain["chain"], ledger_evidence_refs=chain["evidence_refs"],
                 ledger_version_refs=chain["version_refs"], ledger_errors=chain["errors"],
                 ledger_status=chain["code"], ledger_current_matches=current_matches, versions=eng.store.versions(),
                 manifest_errors=environment["errors"], recovery=recovery)


# ----------------------------------------------------------------------------------- G4
def g4_controls(eng, src):
    """Control nulo (campeón vs sí mismo: no debe 'ganar') y control de sensibilidad (una variante
    deliberadamente más lenta debe medirse más lenta)."""
    n = eng.cfg["readiness"]["control_pairs"]
    seeds = [4000 + i for i in range(n)]
    slow = src.replace("            idx = self.next_idx()\n",
                       "            idx = self.next_idx()\n" + "            _w = self.X[idx] @ self.W[0]\n" * 6)
    if slow == src:
        return _gate(False, reason_codes=["EVALUATOR_CONTROL_FAILED"], reason="no se pudo construir la variante lenta de control")

    def paired(a_src, b_src):
        A, B = [], []
        for i, s in enumerate(seeds):
            order = ("a", "b") if i % 2 == 0 else ("b", "a")
            for w in order:
                (A if w == "a" else B).append(eng.trial(a_src if w == "a" else b_src, s))
        return A, B
    A, B = paired(src, src)
    null_trials = A + B
    null = stats.decide(A, B, eng.acc)
    A, B = paired(src, slow)
    sens = stats.decide(A, B, eng.acc)
    trials = null_trials + A + B
    quality = stats.decide(A, [{**r, "reached": False, "cost_s": None} for r in B], eng.acc)
    valid = all(r["status"] == "ok" and r["reached"] and r.get("sandbox_validation") is True for r in trials)
    ok = valid and null["decision"] != "accepted" and sens["decision"] != "accepted" and (sens.get("ratio") or 0) > 1.02 and quality["decision"] == "rejected"
    reasons = [] if ok else ["EVALUATOR_CONTROL_FAILED" if null["decision"] == "accepted" or not valid else "BENCHMARK_DISCRIMINATION_FAILED"]
    return _gate(ok, null={k: null.get(k) for k in ("decision", "ratio", "ratio_upper95")},
                  slowdown={k: sens.get(k) for k in ("decision", "ratio", "ratio_upper95")}, quality_control=quality,
                  reason_codes=reasons, trial_evidence=trials)


# ----------------------------------------------------------------------------------- G5
def g5_budget(eng):
    lim, st = eng.lim, eng.cfg["stop"]
    positive = all(type(lim.get(k)) in (int, float) and math.isfinite(lim[k]) and lim[k] > 0
                   for k in ("max_total_minutes", "max_experiments", "max_experiment_seconds", "max_ram_mb", "max_disk_mb", "worker_threads"))
    positive &= type(eng.acc["confirm_seeds"]) is int and eng.acc["confirm_seeds"] >= 3 and st["plateau_experiments"] > 0
    invocation = getattr(eng, "invocation", {})
    positive &= (0 < invocation.get("minutes", lim["max_total_minutes"]) <= lim["max_total_minutes"] and
                 0 < invocation.get("max_experiments", lim["max_experiments"]) <= lim["max_experiments"] and
                 invocation.get("meta", eng.cfg["meta"]["enabled"]) == eng.cfg["meta"]["enabled"])
    host = manifest.host_identity(eng.root, eng.store.dir)
    ram = all(host["capabilities"][k] >= lim["max_ram_mb"] for k in ("effective_memory_mb", "available_ram_mb"))
    remaining = lim["max_disk_mb"] - eng.store.disk_mb()
    disk = remaining > 0 and host["information"]["state_free_mb"] >= remaining
    reasons = ([] if positive else ["BUDGET_INVALID"]) + ([] if ram else ["RESOURCE_BUDGET_FAILED"]) + ([] if disk else ["DISK_BUDGET_FAILED"])
    return _gate(not reasons, reason_codes=reasons, config_hash=config_hash(eng.cfg), minutes=lim["max_total_minutes"],
                 max_experiments=lim["max_experiments"], memory=host["capabilities"], disk_remaining_mb=remaining,
                 active_limits_verified_by="G0 real sandbox handshake", required_pairs=eng.acc["confirm_seeds"])


# ----------------------------------------------------------------------------------- orquestación
GATE_NAMES = ("G0_runtime", "G1_correctness", "G2_reliability", "G3_integrity", "G4_controls", "G5_budget")
GATE_LABELS = {"G0": "Identity & infrastructure", "G1": "Candidate structure", "G2": "Baseline health",
               "G3": "Integrity", "G4": "Evaluator controls", "G5": "Budget & capacity"}
REPORT_SCHEMA = "mvp_cpu_gates_v1"


def _uniform(name, result, started):
    value = {"gate": name[:2], "status": "PASS" if result["ok"] else "FAIL", "ok": bool(result["ok"]),
             "started_at": started, "finished_at": manifest.timestamp(),
             "checks": [{"name": key, "passed": value} for key, value in result.items() if type(value) is bool],
             "reason_codes": result.get("reason_codes", [] if result["ok"] else [name[:2] + "_VALIDATION_FAILED"]),
             "details": {k: v for k, v in result.items() if k not in ("ok", "reason_codes", "sandbox_evidence", "trial_evidence")}}
    value["evidence_hash"] = provenance.digest(value)
    return value


def run_gates(eng, initialize_mvp=False, *, genome=None, source=None):
    with eng.store.exclusive():
        return _run_gates(eng, initialize_mvp=initialize_mvp, genome=genome, source=source)


def _run_gates(eng, initialize_mvp=False, *, genome=None, source=None):
    schema = provenance.state_schema(eng.store.dir)
    if schema == "NEW" and initialize_mvp:
        eng.init(initialize_mvp=True)
    elif schema != "MVP_CPU_V1":
        raise ValueError("STATE_SCHEMA_INVALID: explicit new baseline required; legacy is read-only")
    try:
        baseline_g, src = eng.store.load_version()
    except (OSError, ValueError, TypeError):
        baseline_g, src = G.new_genome(), ""
    genome = baseline_g if genome is None else genome
    if source is None:
        try:
            source = G.render(genome)
        except (ValueError, TypeError, KeyError):
            source = ""
    campaign_id = str(uuid.uuid4())
    directory = eng.store.dir / "campaigns" / campaign_id
    started = manifest.timestamp()
    gates = {}
    evidence = {**provenance.purpose_metadata(eng.cfg)}
    blocked = False
    for name, fn in (("G0_runtime", lambda: g0_runtime(eng, src)), ("G1_correctness", lambda: g1_candidate(eng, genome, source)),
                      ("G2_reliability", lambda: g2_reliability(eng, src)), ("G3_integrity", lambda: g3_integrity(eng)),
                      ("G4_controls", lambda: g4_controls(eng, src)), ("G5_budget", lambda: g5_budget(eng))):
        gate_started = manifest.timestamp()
        try:
            if name == "G1_correctness" and not blocked:
                # Load only an uninitialized Engine. Re-loading here on each
                # candidate would reset its search RNG/history, changing search
                # semantics even though gates must only observe/validate.
                if eng.bench is None or not eng.state or eng.rng is None:
                    eng._load()
            result = _gate(False, reason_codes=["PRIOR_GATE_FAILED"]) if blocked else fn()
        except Exception as e:      # noqa: BLE001
            code = {"G0": "ENVIRONMENT_MISMATCH", "G1": "CANDIDATE_LOAD_FAILED", "G2": "BASELINE_QUALITY_FAILED",
                    "G3": "VERSION_INTEGRITY_FAILED", "G4": "EVALUATOR_CONTROL_FAILED", "G5": "BUDGET_INVALID"}[name[:2]]
            result = _gate(False, reason_codes=[code], exception=repr(e)[:300])
        gates[name] = _uniform(name, result, gate_started)
        evidence[name] = {key: result[key] for key in ("sandbox_evidence", "trial_evidence") if key in result}
        if evidence[name]:
            gates[name]["details"]["trial_evidence_hash"] = provenance.digest(evidence[name])
            gates[name]["evidence_hash"] = provenance.digest({k: v for k, v in gates[name].items() if k != "evidence_hash"})
        eng.log(f"{name[:2]} {GATE_LABELS[name[:2]]}: {gates[name]['status']} " + ", ".join(gates[name]["reason_codes"]))
        blocked |= not result["ok"]
    status = "READY_FOR_CAMPAIGN" if len(gates) == 6 and all(g["ok"] for g in gates.values()) else "NOT_READY"
    try:
        baseline = manifest._document(eng.store.stable / "v0000/manifest.json")
    except (OSError, ValueError, KeyError, TypeError):
        baseline = {"manifest_hash": None, "environment_hash": None, "config_hash": None, "effective_config": None}
    proposal_context = getattr(eng, "_proposal_context", None) or {}
    if proposal_context.get("proposal_genome_hash") != provenance.digest(genome):
        proposal_context = {}
    report = {"report_schema": REPORT_SCHEMA, "campaign_id": campaign_id, "current": eng.store.current_version(),
              **provenance.purpose_metadata(eng.cfg),
              **proposal_context,
              "baseline_manifest_hash": baseline["manifest_hash"], "environment_hash": baseline["environment_hash"],
              "effective_config_hash": baseline["config_hash"], "effective_config": baseline["effective_config"],
              "invocation": getattr(eng, "invocation", {}),
              "candidate_genome_hash": provenance.digest(genome), "candidate_trainer_hash": __import__("hashlib").sha256(source.encode()).hexdigest(),
              "started_at": started, "finished_at": manifest.timestamp(), "gates": gates,
              "overall": "PASS" if status == "READY_FOR_CAMPAIGN" else "FAIL",
              "evidence_hash": provenance.digest(evidence)}
    report["gate_report_hash"] = provenance.digest(report)
    manifest.write_manifest(directory / "evidence.json", evidence)
    manifest.write_manifest(directory / "gates.json", report)
    context = {"campaign_id": campaign_id, "gate_report_hash": report["gate_report_hash"],
               "gate_report_path": str((directory / "gates.json").relative_to(eng.store.dir)),
               "overall_gates_passed": report["overall"] == "PASS"}
    eng.log("CAMPAIGN GATES: " + ("PASS" if context["overall_gates_passed"] else "BLOCKED"))
    return {"status": status, "gates": gates, "identity": identity(eng) if status == "READY_FOR_CAMPAIGN" else {}, "created": time.time(), **context}


def validate_report(eng, reference, *, genome_hash=None, trainer_hash=None, parent=None, compare_current=True):
    result = {"ok": False, "errors": []}
    try:
        path = manifest._state_path(eng.store.dir, reference["gate_report_path"])
        report = json.loads(path.read_bytes())
        identifier = str(uuid.UUID(report["campaign_id"]))
        if identifier != report["campaign_id"] or path != eng.store.dir / "campaigns" / identifier / "gates.json":
            raise ValueError("GATE_REPORT_INVALID: campaign path/UUID")
        if report["report_schema"] != REPORT_SCHEMA or report["gate_report_hash"] != provenance.digest({k: v for k, v in report.items() if k != "gate_report_hash"}):
            raise ValueError("GATE_REPORT_INVALID: report hash/schema mismatch")
        if (report["gate_report_hash"] != reference["gate_report_hash"] or report["campaign_id"] != reference["campaign_id"] or
                reference["overall_gates_passed"] is not True or report["overall"] != "PASS" or
                set(report["gates"]) != set(GATE_NAMES)):
            raise ValueError("GATE_REPORT_INVALID: report/experiment binding or overall failure")
        for name in GATE_NAMES:
            gate = report["gates"][name]
            if (gate["gate"] != name[:2] or gate["status"] != "PASS" or gate["ok"] is not True or
                    not gate["checks"] or any(check["passed"] is not True for check in gate["checks"]) or
                    gate["evidence_hash"] != provenance.digest({k: v for k, v in gate.items() if k != "evidence_hash"})):
                raise ValueError("GATE_REPORT_INVALID: " + name)
        evidence_path = manifest._state_path(eng.store.dir, str(path.with_name("evidence.json").relative_to(eng.store.dir)))
        evidence = json.loads(evidence_path.read_bytes())
        if provenance.digest(evidence) != report["evidence_hash"]:
            raise ValueError("GATE_REPORT_INVALID: gate evidence changed")
        for name in GATE_NAMES:
            item = evidence[name]
            if item and report["gates"][name]["details"]["trial_evidence_hash"] != provenance.digest(item):
                raise ValueError("GATE_REPORT_INVALID: gate trial evidence mismatch")
        baseline = manifest._document(eng.store.stable / "v0000/manifest.json")
        if any(report.get(k) != v or evidence.get(k) != v for k, v in provenance.purpose_metadata(baseline).items()):
            raise ValueError("GATE_REPORT_INVALID: certification origin mismatch")
        if (report["baseline_manifest_hash"] != baseline["manifest_hash"] or report["environment_hash"] != baseline["environment_hash"] or
                report["effective_config_hash"] != baseline["config_hash"] or report["effective_config"] != baseline["effective_config"]):
            raise ValueError("ENVIRONMENT_MISMATCH: gate report baseline/config")
        if genome_hash is not None and report["candidate_genome_hash"] != genome_hash:
            raise ValueError("GATE_REPORT_INVALID: candidate genome")
        if trainer_hash is not None and report["candidate_trainer_hash"] != trainer_hash:
            raise ValueError("GATE_REPORT_INVALID: candidate trainer")
        if parent is not None and report["current"] != parent:
            raise ValueError("GATE_REPORT_INVALID: parent")
        if compare_current:
            checked = manifest.validate_manifest(eng)
            if (not checked["ok"] or eng.store.current_version() != report["current"] or
                    report["invocation"] != getattr(eng, "invocation", {})):
                raise ValueError("ENVIRONMENT_MISMATCH: current environment/parent differs from gates")
        result.update(ok=True, report=report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["errors"].append(str(exc))
    return result


def pre_promotion(eng, genome, source, provided):
    from . import publication
    if list(eng.store.dir.glob(".rollback-intent-*")):
        raise ValueError("PRE_PROMOTION_FAILED: rollback intent appeared")
    if list(eng.store.stable.glob(".staging-*")) or list(eng.store.stable.glob(".CURRENT-*")):
        raise ValueError("PRE_PROMOTION_FAILED: pending staging/pointer transaction requires inspection")
    try:
        champion = eng.store.load_version()[1]
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("PRE_PROMOTION_FAILED: CURRENT invalid") from exc
    g0, g3 = g0_runtime(eng, champion), g3_integrity(eng)
    if not g0["ok"] or not g3["ok"]:
        raise ValueError("PRE_PROMOTION_FAILED: G0/G3 critical validation")
    baseline, experiment, execution, _ = publication.validate_candidate(eng, genome, source, provided, _preparing=True)
    chain = ledger.verify_ledger(eng.store)
    critical = {"G0": _uniform("G0_runtime", g0, manifest.timestamp()),
                "G3": _uniform("G3_integrity", g3, manifest.timestamp())}
    report = {"pre_promotion_schema": "mvp_cpu_pre_promotion_v1", "status": "PASS", "timestamp": manifest.timestamp(),
              **provenance.purpose_metadata(eng.cfg),
              "experiment_manifest_hash": experiment["manifest_hash"], "experiment_evidence_hash": execution["evidence_hash"],
              "gate_report_hash": experiment["gate_report_hash"], "campaign_id": experiment["campaign_id"],
              "environment_hash": baseline["environment_hash"], "parent": experiment["parent_version"],
              "candidate_trainer_hash": experiment["candidate_trainer_hash"], "candidate_genome_hash": experiment["candidate_genome_hash"],
              "ledger_head": chain["last_hash"], "ledger_sequence": len(chain["records"]),
              "critical_checks": critical, "critical_checks_hash": provenance.digest(critical)}
    report["validation_hash"] = provenance.digest(report)
    path = manifest._state_path(eng.store.dir, provided["experiment_manifest_path"]).with_name("pre_promotion.json")
    if path.exists():
        path = path.with_name("pre_promotion-" + uuid.uuid4().hex + ".json")
    manifest.write_manifest(path, report)
    return {"pre_promotion_path": str(path.relative_to(eng.store.dir)), "pre_promotion_hash": report["validation_hash"]}


def validate_pre_promotion(eng, provided, experiment, execution, *, compare_current=True):
    path = manifest._state_path(eng.store.dir, provided["pre_promotion_path"])
    doc = json.loads(path.read_bytes())
    if any(doc.get(k) != v for k, v in provenance.purpose_metadata(experiment).items()):
        raise ValueError("PRE_PROMOTION_FAILED: certification origin mismatch")
    if (doc["pre_promotion_schema"] != "mvp_cpu_pre_promotion_v1" or doc["status"] != "PASS" or
            doc["validation_hash"] != provided["pre_promotion_hash"] or
            doc["validation_hash"] != provenance.digest({k: v for k, v in doc.items() if k != "validation_hash"})):
        raise ValueError("PRE_PROMOTION_FAILED: invalid pre-promotion report")
    for field in ("experiment_manifest_hash", "environment_hash", "candidate_trainer_hash", "candidate_genome_hash"):
        expected = experiment["manifest_hash"] if field == "experiment_manifest_hash" else experiment[field]
        if doc[field] != expected:
            raise ValueError("PRE_PROMOTION_FAILED: " + field)
    if (doc["experiment_evidence_hash"] != execution["evidence_hash"] or doc["gate_report_hash"] != experiment["gate_report_hash"] or
            doc["campaign_id"] != experiment["campaign_id"] or doc["parent"] != experiment["parent_version"]):
        raise ValueError("PRE_PROMOTION_FAILED: evidence/campaign/parent")
    critical = doc["critical_checks"]
    if set(critical) != {"G0", "G3"} or provenance.digest(critical) != doc["critical_checks_hash"]:
        raise ValueError("PRE_PROMOTION_FAILED: critical checks hash")
    for gate in critical.values():
        if gate["status"] != "PASS" or gate["ok"] is not True or gate["evidence_hash"] != provenance.digest({k: v for k, v in gate.items() if k != "evidence_hash"}):
            raise ValueError("PRE_PROMOTION_FAILED: critical gate not PASS")
    if compare_current:
        chain = ledger.verify_ledger(eng.store)
        if not chain["ok"] or chain["last_hash"] != doc["ledger_head"] or len(chain["records"]) != doc["ledger_sequence"]:
            raise ValueError("PRE_PROMOTION_FAILED: ledger changed after final validation")
    return doc


def path(eng):
    return eng.store.dir / "readiness.json"


def prepare(eng, refreeze=False, initialize_mvp=False):
    requirements = provenance.prerequisites(eng, initialize=initialize_mvp)
    if not requirements["ok"]:
        return {"status": "NOT_READY", "reason": "; ".join(requirements["reasons"]),
                "requirements": requirements, "gates": {}}
    p = path(eng)
    if p.exists() and not refreeze:
        old = json.loads(p.read_text())
        cur = check_identity(eng, old)
        if not cur:
            return {**old, "requirements": requirements}
        return {"status": "NOT_READY", "reason": "la identidad congelada ya no coincide: " + "; ".join(cur) +
                " (un cambio crítico requiere una baseline/estado nuevo; --refreeze no actualiza manifiestos)",
                "requirements": requirements, "gates": old["gates"]}
    try:
        out = run_gates(eng, initialize_mvp=initialize_mvp)
    except (RuntimeError, ValueError, OSError) as exc:
        return {"status": "NOT_READY", "reason": str(exc), "requirements": provenance.prerequisites(eng),
                "gates": {"CPU_initialization": {"ok": False, "error": str(exc)}}}
    out["requirements"] = provenance.prerequisites(eng)
    if not out["requirements"]["ok"]:
        out["status"] = "NOT_READY"
        out["reason"] = "; ".join(out["requirements"]["reasons"])
    if p.exists() and refreeze:
        eng.store.append({"type": "human_intervention", "what": "refreeze de identidad experimental"})
    if out["status"] == "READY_FOR_CAMPAIGN":
        atomic_write(p, json.dumps(out, indent=1))
        eng.store.append({"type": "identity", "status": out["status"], "identity": out["identity"]})
    else:
        atomic_write(eng.store.dir / "readiness_failed.json", json.dumps(out, indent=1))
    return out


def check_identity(eng, frozen=None):
    """Lista de diferencias entre la identidad congelada y la actual (vacía = coincide)."""
    frozen = frozen or json.loads(path(eng).read_text())
    requirements = provenance.prerequisites(eng)
    d = list(requirements["reasons"])
    previous = (frozen.get("requirements", {}).get("environment") or {}).get("identity")
    current = (requirements.get("environment") or {}).get("identity")
    if previous != current:
        d.append("ENVIRONMENT_MISMATCH: cached readiness belongs to another manifest/environment")
    return d
