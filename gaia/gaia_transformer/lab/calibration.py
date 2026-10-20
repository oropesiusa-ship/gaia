"""Fase 3: benchmark congelado, controles y comparación sin búsqueda autónoma."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gaia.bootstrap import locked, write_json
from gaia.gaia_transformer.lab import benchmark
from gaia.gaia_transformer.lab.candidate import baseline_source
from gaia.gaia_transformer.lab.evaluator import run_trial

# Fijado ANTES de medir. Cambiarlo requiere otra identidad y nueva calibración.
SPEC = {
    "version": "gaia_transformer_benchmark/v1", "reference_steps": 100, "max_steps": 300,
    "eval_every": 25, "hits_needed": 2, "quality_tolerance": 0.05,
    "calibration_seeds": [9000, 9001, 9002, 9003, 9004],
    "confirm_seeds": [1000, 1001, 1002, 1003, 1004],
    "audit_seeds": [5000, 5001, 5002, 5003, 5004, 5005],
    "control_seeds": [4000, 4001, 4002, 4003, 4004], "screen_seed": 0,
    "min_gain": 0.05, "memory_tolerance": 1.25, "screen_slack": 1.3,
    "max_cv": 0.20, "max_warmup_ratio": 1.35, "max_drift": 0.35,
    "min_resolvable_s": 0.06, "min_slowdown": 1.02,
}


def valid_trial(trial):
    return (trial.get("status") == "ok" and trial.get("valid") is True and trial.get("reached") is True
            and isinstance(trial.get("cost_s"), (int, float)) and math.isfinite(trial["cost_s"])
            and trial["cost_s"] > 0 and all(isinstance(trial.get(key), (int, float))
                and math.isfinite(trial[key]) and trial[key] > 0
                for key in ("peak_rss_mb", "peak_vram_nvml_mb")))


def decide(champion, candidate, seeds, spec=SPEC):
    """Todos los pares deben ser válidos, alcanzar calidad y conservar orden/semilla."""
    if (len(seeds) != 5 or len(set(seeds)) != 5 or len(champion) != 5 or len(candidate) != 5
            or any(not valid_trial(t) or t["spec"]["seed"] != seed
                   for group in (champion, candidate) for t, seed in zip(group, seeds))):
        return {"decision": "rejected", "reason": "Se requieren cinco pares íntegros con calidad en todas las semillas"}
    logs = [math.log(b["cost_s"] / a["cost_s"]) for a, b in zip(champion, candidate)]
    mean = statistics.mean(logs)
    margin = 2.132 * statistics.stdev(logs) / math.sqrt(5)  # t unilateral 95%, df=4
    ram = statistics.median(t["peak_rss_mb"] for t in candidate) / statistics.median(t["peak_rss_mb"] for t in champion)
    vram = statistics.median(t["peak_vram_nvml_mb"] for t in candidate) / statistics.median(t["peak_vram_nvml_mb"] for t in champion)
    outcome = {"ratio": math.exp(mean), "upper95": math.exp(mean + margin),
               "lower95": math.exp(mean - margin), "ram_ratio": ram, "vram_ratio": vram, "pairs": 5}
    if outcome["upper95"] < 1 - spec["min_gain"]:
        decision = "accepted" if max(ram, vram) <= spec["memory_tolerance"] else "pareto_alternative"
    else:
        decision = "deferred" if outcome["ratio"] < 1 - spec["min_gain"] else "rejected"
    return {**outcome, "decision": decision}


def reliability(trials, spec=SPEC):
    if len(trials) != 5 or not all(valid_trial(t) for t in trials):
        return {"ok": False, "reason": "La baseline no alcanza calidad 5/5"}
    costs = [t["cost_s"] for t in trials]
    median = statistics.median(costs)
    cv = statistics.pstdev(costs) / statistics.mean(costs)
    drift = abs(statistics.median(costs[2:]) / statistics.median(costs[:2]) - 1)
    warmup = costs[0] / median
    return {"ok": cv <= spec["max_cv"] and drift <= spec["max_drift"]
            and warmup <= spec["max_warmup_ratio"] and median >= spec["min_resolvable_s"],
            "median_s": median, "cv": cv, "drift": drift, "warmup_ratio": warmup, "costs": costs}


class Laboratory:
    def __init__(self, cfg, runtime, directory, identity, target=None):
        self.cfg, self.runtime, self.directory, self.identity, self.target = cfg, runtime, directory, identity, target
        self.count = 0

    def trial(self, source, seed, split="validation", reference=False):
        self.count += 1
        path = self.directory / f"trial-{self.count:04d}"
        spec = benchmark.TrialSpec(seed=seed, steps=SPEC["reference_steps"] if reference else SPEC["max_steps"],
                                   eval_every=SPEC["eval_every"], split=split,
                                   target_loss=None if reference else self.target)
        result = run_trial(source, self.cfg, self.runtime, path, spec,
                           expected_identity=self.identity, require_sandbox=True, stop_file=ROOT / "STOP")
        print(f"[benchmark] {path.name} seed={seed} {split}: {result['status']} "
              f"loss={result.get('final_loss')} reached={result['reached']}", file=sys.stderr, flush=True)
        if result["status"] != "ok":
            raise RuntimeError(f"Trial inválido: {path}: {result['error']}")
        return result

    def paired(self, a, b, seeds, split="validation"):
        champion, candidate = [], []
        for index, seed in enumerate(seeds):
            pair = {}
            for key in (("a", "b") if index % 2 == 0 else ("b", "a")):
                pair[key] = self.trial(a if key == "a" else b, seed, split)
            champion.append(pair["a"])
            candidate.append(pair["b"])
        return {"decision": decide(champion, candidate, seeds), "champion": champion, "candidate": candidate,
                "seeds": seeds, "split": split}


def compare_candidate(lab, champion, candidate):
    """Cribado barato y cinco pares; devuelve evidencia, no cambia el campeón."""
    before = lab.trial(champion, SPEC["screen_seed"])
    screen = lab.trial(candidate, SPEC["screen_seed"])
    if not valid_trial(before):
        raise RuntimeError("El campeón no es fiable durante el cribado")
    if not valid_trial(screen) or screen["cost_s"] > before["cost_s"] * SPEC["screen_slack"]:
        return {"decision": "rejected", "stage": "screen", "champion": before, "candidate": screen}
    confirmation = lab.paired(champion, candidate, SPEC["confirm_seeds"])
    return {"decision": confirmation["decision"]["decision"], "stage": "confirmation",
            "screen": {"champion": before, "candidate": screen}, "confirmation": confirmation}


def audit(lab, baseline, champion):
    """Semillas nunca usadas para seleccionar, en validación y dominio audit reservado."""
    result = {}
    for split in ("validation", "audit"):
        pairs = []
        for index, seed in enumerate(SPEC["audit_seeds"]):
            pair = {}
            for key in (("baseline", "champion") if index % 2 == 0 else ("champion", "baseline")):
                pair[key] = lab.trial(baseline if key == "baseline" else champion, seed, split)
            pairs.append(pair)
        result[split] = {"pairs": pairs, "all_quality": all(valid_trial(t) for p in pairs for t in p.values()),
                         "ratios": [p["champion"]["cost_s"] / p["baseline"]["cost_s"]
                                    for p in pairs if all(valid_trial(t) for t in p.values())]}
    return result


def slow_source(source):
    return source + "\nclass Candidate(Candidate):\n    def train(self, steps):\n" \
        "        for _ in range(steps):\n            self.step()\n" \
        "            for _ in range(20):\n                self.predict_last(self.data[:32,:-1].cpu().numpy().astype(np.uint8))\n"


def run(args, report):
    cfg = json.loads(Path(args.config).read_text())
    runtime = json.loads(Path(args.bootstrap_report).read_text())["cuda_probes"][0]["runtime"]
    source, identity = baseline_source(), benchmark.identity()
    state = ROOT / cfg["workload"]["state_dir"]
    state.mkdir(exist_ok=True)
    with locked(state / "calibration.lock"):
        if (state / "benchmark.json").exists():
            raise RuntimeError("Ya existe benchmark congelado; conservarlo y usar nueva identidad para recalibrar")
        lab = Laboratory(cfg, runtime, args.output, identity)
        report.update(spec=SPEC, protected_sha256=identity, runtime=runtime, config=cfg, state_dir=str(state),
                      baseline_sha256=hashlib.sha256(source.encode()).hexdigest())
        reference = [lab.trial(source, seed, reference=True) for seed in SPEC["calibration_seeds"]]
        # Objetivo conservador explícito: peor baseline de calibración + tolerancia fija.
        target = max(t["final_loss"] for t in reference) + SPEC["quality_tolerance"]
        lab.target = target
        report.update(reference=reference, target_loss=target)
        write_json(args.output / "result.json", report)
        report["calibration_quality"] = [lab.trial(source, seed) for seed in SPEC["calibration_seeds"]]
        if not all(valid_trial(t) for t in report["calibration_quality"]):
            raise RuntimeError("La baseline no alcanza el objetivo en todas las semillas de calibración")
        report["reliability"] = reliability([lab.trial(source, SPEC["screen_seed"]) for _ in range(5)])
        if not report["reliability"]["ok"]:
            raise RuntimeError("Baseline inestable, deriva o benchmark saturado: revisar entorno sin relajar umbrales")
        report["null_control"] = lab.paired(source, source, SPEC["control_seeds"])
        null = report["null_control"]["decision"]
        if null.get("pairs") != 5 or null["decision"] == "accepted":
            raise RuntimeError("Control nulo inválido o falso positivo")
        report["slow_control"] = lab.paired(source, slow_source(source), SPEC["control_seeds"])
        slow = report["slow_control"]["decision"]
        if slow.get("lower95", 0) <= SPEC["min_slowdown"]:
            raise RuntimeError("El control lento no es inequívocamente más lento")
        report["confirmation_null"] = compare_candidate(lab, source, source)
        if report["confirmation_null"]["decision"] == "accepted":
            raise RuntimeError("La confirmación promovió un candidato idéntico")
        report["audit"] = audit(lab, source, source)
        if not all(group["all_quality"] for group in report["audit"].values()):
            raise RuntimeError("Baseline no alcanza calidad en semillas/dominio de auditoría")
        if identity != benchmark.identity():
            raise RuntimeError("Integridad del laboratorio cambió durante calibración")
        report.update(status="GPU_BENCHMARK_READY", trials=lab.count, promotions=0, campaign_ready=False)
        frozen = {"spec": SPEC, "target_loss": target, "identity": identity, "runtime": runtime,
                  "config": cfg, "baseline_sha256": report["baseline_sha256"],
                  "reference_cost_s": report["reliability"]["median_s"], "evidence": str(args.output / "result.json")}
        # Escribir solo tras todos los controles. No se crea stable/CURRENT ni promoción.
        write_json(state / "baseline.json", {"source": source, "sha256": frozen["baseline_sha256"]})
        write_json(state / "benchmark.json", frozen)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--bootstrap-report", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING"}
    try:
        run(args, report)
    except BaseException as exc:
        report.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        write_json(args.output / "result.json", report)
    print(json.dumps({"status": report["status"], "result": str(args.output / "result.json"),
                      "trials": report["trials"], "target_loss": report["target_loss"]}))


if __name__ == "__main__":
    main()
