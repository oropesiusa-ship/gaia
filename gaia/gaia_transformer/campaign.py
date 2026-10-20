"""Modo A GaiaTransformer: puertas CUDA, propuestas conocidas y promoción por pares."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gaia.bootstrap import locked, write_json
from gaia.gaia_transformer import benchmark_state, genome as G
from gaia.gaia_transformer.campaign_store import CampaignStore
from gaia.gaia_transformer.lab import benchmark
from gaia.gaia_transformer.lab.calibration import Laboratory, SPEC, reliability, slow_source, valid_trial
from gaia.gaia_transformer.lab.monitor import directory_mb


class Halt(RuntimeError):
    pass


class CampaignLab(Laboratory):
    def __init__(self, *args, deadline, **kwargs):
        super().__init__(*args, **kwargs)
        self.deadline = deadline

    def trial(self, *args, **kwargs):
        if (ROOT / "STOP").exists():
            raise Halt("STOP solicitado")
        if time.monotonic() + self.cfg.get("limits", {}).get("max_experiment_seconds", 20) + 2 >= self.deadline:
            raise Halt("Presupuesto restante insuficiente para otro trial")
        try:
            return super().trial(*args, **kwargs)
        except RuntimeError:
            path = self.directory / f"trial-{self.count:04d}" / "result.json"
            if path.exists() and json.loads(path.read_text()).get("status") == "stopped":
                raise Halt("STOP solicitado durante trial")
            raise


def identity(cfg, frozen, source):
    here = Path(__file__).parent
    files = [here / name for name in ("campaign.py", "campaign_store.py", "genome.py", "benchmark_state.py",
                                      "research.py", "observation.py", "observe_worker.py", "profiling.py", "search_strategy.py")]
    files += list((ROOT / "tests").glob("test_gaia_transformer*.py"))
    strategy_file = ROOT / cfg["workload"]["state_dir"] / "strategy_gpu.json"
    return {"config": cfg, "benchmark": frozen, "champion_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "search_strategy_state": hashlib.sha256(strategy_file.read_bytes()).hexdigest() if strategy_file.exists() else None,
            "campaign_sources": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}


def prepare(lab, frozen, source, output, baseline=None):
    gates = {}

    def gate(name, action):
        result = action()
        gates[name] = result
        write_json(output / "readiness.json", {"status": "PREPARING", "gates": gates})
        if not result["ok"]:
            raise RuntimeError("NOT_READY: " + name + ": " + json.dumps(result))

    def runtime_gate():
        trial = lab.trial(source, 0)
        return {"ok": valid_trial(trial) and all(trial["handshake"]["isolation"].values()),
                "runtime": trial.get("worker_runtime"), "isolation": trial.get("isolation")}

    gate("G0_runtime", runtime_gate)

    def correctness():
        code = ("import sys,unittest;sys.path.insert(0,sys.argv[1]);"
                "s=unittest.TestSuite(unittest.defaultTestLoader.discover(sys.argv[1]+'/tests',pattern=p) "
                "for p in ('test_gaia_transformer_model.py','test_gaia_transformer_data.py','test_gaia_transformer_lab.py'));"
                "r=unittest.TextTestRunner(verbosity=2).run(s);sys.exit(0 if r.wasSuccessful() and not r.skipped else 1)")
        with (output / "correctness.stdout.log").open("w") as stdout, (output / "correctness.stderr.log").open("w") as stderr:
            result = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT)], stdout=stdout, stderr=stderr, timeout=120)
        return {"ok": result.returncode == 0, "returncode": result.returncode, "skips_allowed": False}

    gate("G1_correctness", correctness)
    measurements = [lab.trial(source, 0) for _ in range(5)]
    reliable = reliability(measurements)
    reliable["numerically_reproducible"] = all(trial["curve"] == measurements[0]["curve"] for trial in measurements)
    reliable["ok"] &= reliable["numerically_reproducible"]
    baseline_cost = reliable.get("median_s", 0)
    if baseline is not None and source != baseline:
        refs = [lab.trial(baseline, 0) for _ in range(3)]
        if not all(valid_trial(trial) for trial in refs):
            raise RuntimeError("Referencia baseline dejó de alcanzar calidad")
        baseline_cost = statistics.median(trial["cost_s"] for trial in refs)
    reliable["reference_drift"] = abs(baseline_cost / frozen["reference_cost_s"] - 1)
    reliable["ok"] &= reliable["reference_drift"] <= SPEC["max_drift"]
    gate("G2_reliability", lambda: reliable)
    gate("G3_integrity", lambda: {"ok": benchmark.identity() == frozen["identity"], "hashes": benchmark.identity()})
    null = lab.paired(source, source, SPEC["control_seeds"])
    slow = lab.paired(source, slow_source(source), SPEC["control_seeds"])
    gate("G4_controls", lambda: {"ok": null["decision"].get("pairs") == 5
                                 and null["decision"]["decision"] != "accepted"
                                 and slow["decision"].get("lower95", 0) > SPEC["min_slowdown"],
                                 "null": null["decision"], "slow": slow["decision"]})
    limits = lab.cfg.get("limits", {})
    gate("G5_budget", lambda: {"ok": all(isinstance(limits.get(k, default), (int, float))
                                         and math.isfinite(limits.get(k, default)) and limits.get(k, default) > 0
                                         for k, default in (("max_experiment_seconds", 20), ("max_ram_mb", 3000),
                                                            ("max_vram_mb", 3000), ("max_disk_mb", 500)))
                                 and time.monotonic() < lab.deadline, "limits": limits})
    result = {"status": "READY_FOR_CAMPAIGN", "gates": gates, "created": time.time()}
    write_json(output / "readiness.json", result)
    return result


def compare(lab, champion, candidate, reference):
    current = lab.trial(champion, 0)
    if not valid_trial(current):
        raise RuntimeError("Campeón no alcanza calidad")
    cost = current["cost_s"]
    if cost < SPEC["min_resolvable_s"] or abs(cost / reference - 1) > SPEC["max_drift"]:
        raise RuntimeError("Deriva o saturación: se requiere revisión humana")
    screen = lab.trial(candidate, 0)
    if not valid_trial(screen) or screen["cost_s"] > cost * SPEC["screen_slack"]:
        return {"decision": "rejected", "stage": "screen", "champion": current, "candidate": screen}
    confirmation = lab.paired(champion, candidate, SPEC["confirm_seeds"])
    return {"decision": confirmation["decision"]["decision"], "stage": "confirmation",
            "screen": {"champion": current, "candidate": screen}, "confirmation": confirmation}


def run(args, report):
    cfg = json.loads(Path(args.config).read_text())
    runtime = json.loads(Path(args.bootstrap_report).read_text())["cuda_probes"][0]["runtime"]
    frozen, baseline = benchmark_state.load(ROOT, cfg, runtime)
    store = CampaignStore(ROOT, cfg["workload"]["state_dir"])
    deadline = time.monotonic() + args.minutes * 60
    with locked(store.dir / "calibration.lock"), locked(store.dir / "campaign.lock"):
        if store.current_version() is None:
            store.publish(dict(G.BASE), baseline, {"type": "baseline", "benchmark_sha256": frozen["baseline_sha256"]}, allow_baseline=True)
        recovered, next_id = store.recover()
        store.tmp.mkdir(exist_ok=True)
        # El evaluador usa tempfile.mkdtemp; redirigir su raíz permite recuperar
        # temporales propios incluso si el padre muere sin ejecutar finally.
        tempfile.tempdir = str(store.tmp)
        report.update(recovered=recovered, state_dir=str(store.dir), events=[], promotions=0)
        champion_g, champion = store.load_version()
        from gaia.gaia_transformer.search_strategy import load as load_strategy
        strategy = load_strategy(store.dir, frozen)
        report["strategy"] = strategy
        frozen_identity = identity(cfg, frozen, champion)
        lab = CampaignLab(cfg, runtime, args.output, frozen["identity"], frozen["target_loss"], deadline=deadline)
        write_json(store.dir / "readiness_gpu.json", {"status": "PREPARING", "evidence": str(args.output / "readiness.json")})
        try:
            readiness = prepare(lab, frozen, champion, args.output, baseline)
        except BaseException as exc:
            write_json(store.dir / "readiness_gpu.json", {"status": "NOT_READY", "reason": str(exc),
                                                         "evidence": str(args.output / "readiness.json")})
            raise
        readiness["identity"] = frozen_identity
        write_json(args.output / "readiness.json", readiness)
        write_json(store.dir / "readiness_gpu.json", readiness)
        store.append({"type": "readiness", "evidence": str(args.output / "readiness.json"), "identity": frozen_identity})
        reference = readiness["gates"]["G2_reliability"]["median_s"]
        if args.prepare_only:
            report.update(status="READY_FOR_CAMPAIGN", trials=lab.count)
            return
        for number in range(next_id, next_id + args.max_experiments):
            if store.stop_requested():
                raise Halt("STOP solicitado")
            benchmark_state.load(ROOT, cfg, runtime)
            store.verify_versions()
            if identity(cfg, frozen, champion) != frozen_identity:
                raise RuntimeError("Identidad de campaña cambió")
            if store.disk_mb() + directory_mb(args.output) > cfg.get("limits", {}).get("max_disk_mb", 500):
                raise RuntimeError("Estado GPU supera presupuesto de disco")
            from gaia.gaia_transformer import research
            trigger, completed = research.should_trigger(store.records(), champion, args.research_after)
            if trigger and cfg.get("research", {}).get("enabled", True):
                store.append({"type": "research_trigger", "champion_sha256": research.champion_key(champion),
                              "completed": completed, "after": args.research_after})
                report.setdefault("research_cycles", []).append(research.cycle(
                    store, cfg, runtime, frozen, args.output / f"research-before-{number:05d}",
                    Path(args.bootstrap_report), lab, deadline))
            unlocked = research.unlocked_options(store.records(), champion)
            proposal, operator, hypothesis = G.propose(champion_g, store.records(), number, unlocked=unlocked, strategy=strategy)
            candidate = G.render(proposal)
            experiment_id = f"e{number:05d}"
            event = {"id": experiment_id, "genome": proposal, "operator": operator,
                     "genome_sha256": G.digest(proposal), "hypothesis": hypothesis, "parent": store.current_version()}
            store.append({"type": "start", **event})
            print(f"[GaiaTransformer campaña] {experiment_id}: {hypothesis['change']}", file=sys.stderr, flush=True)
            try:
                result = compare(lab, champion, candidate, reference)
            except Halt:
                raise
            except Exception as exc:
                store.append({"type": "end", **event, "decision": "error", "reason": str(exc)})
                raise
            evidence = {"experiment_id": experiment_id, "parent": event["parent"], "hypothesis": hypothesis,
                        "comparison": result, "readiness": str(args.output / "readiness.json"), "identity": frozen_identity}
            write_json(args.output / f"{experiment_id}.json", evidence)
            version = None
            if identity(cfg, frozen, champion) != frozen_identity:
                raise RuntimeError("Identidad cambió antes de publicar el resultado")
            if result["decision"] == "accepted":
                version = store.publish(proposal, candidate, evidence)
                champion_g, champion = proposal, candidate
                reference = statistics.median(t["cost_s"] for t in result["confirmation"]["candidate"])
                frozen_identity = identity(cfg, frozen, champion)
                report["promotions"] += 1
            store.append({"type": "end", **event, "decision": result["decision"], "version": version,
                          "evidence": str(args.output / f"{experiment_id}.json")})
            report["events"].append({"id": experiment_id, "decision": result["decision"], "version": version,
                                      "comparison": result.get("confirmation", {}).get("decision")})
            print(f"[GaiaTransformer campaña] {experiment_id}: {result['decision']} versión={version}", file=sys.stderr, flush=True)
            write_json(args.output / "result.json", report)
        report.update(status="GPU_CAMPAIGN_COMPLETE", trials=lab.count, champion=store.current_version())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--bootstrap-report", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-experiments", type=int, default=1)
    parser.add_argument("--minutes", type=float, default=15)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--research-after", type=int, default=40, help="experimentos sin mejora entre ciclos de investigación")
    args = parser.parse_args()
    if not 1 <= args.max_experiments <= 1000 or not 1 <= args.minutes <= 60 or not 1 <= args.research_after <= 1000:
        parser.error("max-experiments/research-after 1..1000 y minutes 1..60")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING"}
    try:
        run(args, report)
    except Halt as exc:
        report.update(status="STOPPED", reason=str(exc))
    except BaseException as exc:
        report.update(status="FAILED", reason=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if report.get("status") == "FAILED":
            write_json(args.output / "NEEDS_HUMAN.json", {"reason": report.get("reason"), "result": str(args.output / "result.json")})
        write_json(args.output / "result.json", report)
    print(json.dumps({key: report[key] for key in ("status", "state_dir", "promotions", "recovered") if key in report}
                     | {"result": str(args.output / "result.json")}))


if __name__ == "__main__":
    main()
