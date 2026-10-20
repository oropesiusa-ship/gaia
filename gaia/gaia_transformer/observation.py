"""Fase 6: observación del campeón con benchmark intacto y diagnóstico no promocional."""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np

from gaia.bootstrap import locked, write_json
from gaia.protected import runtime
from gaia.gaia_transformer import benchmark_state, profiling
from gaia.gaia_transformer.campaign_store import CampaignStore
from gaia.gaia_transformer.lab import benchmark, guard, sandbox
from gaia.gaia_transformer.lab.calibration import SPEC, valid_trial
from gaia.gaia_transformer.lab.evaluator import Channel, limiter, run_trial
from gaia.gaia_transformer.lab.monitor import NVML, Watchdog, terminate


def history_records(store):
    result = store.records()
    for record in result:
        if record.get("type") != "end" or "evidence" not in record:
            continue
        path = Path(record["evidence"])
        if path.resolve().is_relative_to((ROOT / ".gaia/reports").resolve()) and path.is_file():
            record["stage"] = json.loads(path.read_text()).get("comparison", {}).get("stage")
    return result


def observe(source, cfg, expected_runtime, steps, store, output):
    guard.check_source(source)
    executable, reason = sandbox.available()
    if not executable:
        raise RuntimeError("SANDBOX_UNAVAILABLE: " + str(reason))
    nvml, proc, watchdog = None, None, None
    limits_cfg = cfg.get("limits", {})
    limits = {"ram_mb": limits_cfg.get("max_ram_mb", 3000), "vram_mb": limits_cfg.get("max_vram_mb", 3000),
              "disk_mb": limits_cfg.get("max_disk_mb", 500), "seconds": limits_cfg.get("max_experiment_seconds", 20)}
    metrics = {"status": "RUNNING"}
    store.tmp.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="gaia-gpu-observe-", dir=store.tmp) as tmp:
            directory = Path(tmp)
            work, bundle = directory / "work", directory / "lab"
            work.mkdir()
            bundle.mkdir()
            (work / "tmp").mkdir()
            (work / "candidate.py").write_text(source)
            train, contexts, _, _ = benchmark.private_data(benchmark.TrialSpec())
            # La observación no usa targets ni calcula calidad; eso pertenece al trial normal.
            np.savez(work / "inputs.npz", train=train, contexts=contexts)
            write_json(work / "runtime.json", {"uuid": cfg["cuda"]["device_uuid"], "vram_mb": limits["vram_mb"],
                                              "seed": 0, "steps": steps, "warmup": 25})
            shutil.copyfile(Path(__file__).with_name("observe_worker.py"), bundle / "worker.py")
            shutil.copyfile(Path(profiling.__file__), bundle / "profiling.py")
            shutil.copyfile(Path(runtime.__file__), bundle / "runtime.py")
            nvml = NVML(cfg["cuda"]["device_uuid"])
            start = time.monotonic()
            try:
                with (output / "observer.stderr.log").open("wb") as stderr:
                    proc = subprocess.Popen(sandbox.command(executable, bundle, work, nvml.minor),
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                            cwd=work, env=sandbox.environment(cfg["cuda"]["device_uuid"], work),
                                            start_new_session=True, preexec_fn=limiter(limits["seconds"], 64))
                watchdog = Watchdog(proc, directory, nvml, limits, start + limits["seconds"], ROOT / "STOP")
                response = Channel(proc, watchdog).recv()
                if response.get("event") != "OBSERVATION" or response.get("runtime") != expected_runtime:
                    raise RuntimeError("Respuesta/runtime del observador inválidos")
                profiling.validate_observation(response)
                policy = response["policy"]
                if not policy["deterministic"] or policy["tf32_matmul"] or policy["tf32_cudnn"] or policy["cudnn_benchmark"]:
                    raise RuntimeError("El observador alteró flags CUDA")
                if proc.wait(timeout=2) != 0 or not watchdog.gpu_seen:
                    raise RuntimeError("Observador sin finalización o telemetría GPU válida")
                metrics.update(status="ok", **watchdog.metrics(), parent_wall_s=time.monotonic() - start,
                               isolation="bwrap", limits=limits)
                write_json(output / "observation.json", response)
                return response
            finally:
                terminate(proc)
                if proc:
                    for pipe in (proc.stdin, proc.stdout):
                        if pipe:
                            pipe.close()
                if watchdog:
                    metrics.update(watchdog.metrics())
                metrics["worker_returncode"] = proc.returncode if proc else None
    except BaseException as exc:
        metrics.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            if nvml:
                nvml.close()
        finally:
            write_json(output / "observer_metrics.json", metrics)


def run(args, report, already_locked=False):
    cfg = json.loads(Path(args.config).read_text())
    expected_runtime = json.loads(Path(args.bootstrap_report).read_text())["cuda_probes"][0]["runtime"]
    frozen, _ = benchmark_state.load(ROOT, cfg, expected_runtime)
    store = CampaignStore(ROOT, cfg["workload"]["state_dir"])
    with (nullcontext() if already_locked else locked(store.dir / "calibration.lock")), \
            (nullcontext() if already_locked else locked(store.dir / "campaign.lock")):
        store.verify_versions()
        if store.current_version() is None:
            raise RuntimeError("No hay campeón de campaña: ejecutar gaia-transformer-prepare antes de observar")
        version = store.current_version()
        genome, source = store.load_version()
        source_hash = hashlib.sha256(source.encode()).hexdigest()
        identities = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in [Path(__file__), Path(profiling.__file__), Path(__file__).with_name("observe_worker.py")]}
        report.update(champion=version, genome=genome, candidate_sha256=source_hash,
                      observer_sha256=identities, baseline_sha256=frozen["baseline_sha256"],
                      benchmark_sha256=hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest(),
                      promotion_evidence=False, champion_changed=False, benchmark_changed=False, ledger_event="observation")
        store.tmp.mkdir(exist_ok=True)
        tempfile.tempdir = str(store.tmp)
        trial = run_trial(source, cfg, expected_runtime, args.output / "reference_trial",
                          benchmark.TrialSpec(seed=0, steps=SPEC["max_steps"], eval_every=SPEC["eval_every"],
                                              target_loss=frozen["target_loss"]), expected_identity=frozen["identity"],
                          require_sandbox=True, stop_file=ROOT / "STOP")
        if not valid_trial(trial):
            raise RuntimeError("Trial normal inválido: " + str(trial.get("error")))
        report["reference_trial"] = trial
        observation = observe(source, cfg, expected_runtime, args.steps, store, args.output)
        report["matches_reference_at_same_step"] = profiling.reference_parity(observation, trial)
        campaign_noise = None
        readiness_path = store.dir / "readiness_gpu.json"
        if readiness_path.exists():
            readiness = json.loads(readiness_path.read_text())
            if readiness.get("identity", {}).get("champion_sha256") == source_hash:
                measurement = readiness.get("gates", {}).get("G2_reliability", {})
                if measurement.get("ok") and "cv" in measurement:
                    campaign_noise = {"cv": measurement["cv"], "costs": measurement["costs"],
                                      "created": readiness["created"], "source": str(readiness_path),
                                      "historical": True}
        diagnosis = profiling.diagnose(observation, trial, history_records(store), SPEC["min_gain"], campaign_noise)
        # La observación no valida un coste de promoción; no altera benchmark, campeón ni recompensa.
        benchmark_state.load(ROOT, cfg, expected_runtime)
        store.verify_versions()
        if store.current_version() != version or hashlib.sha256(store.load_version()[1].encode()).hexdigest() != source_hash:
            raise RuntimeError("El campeón cambió mientras se observaba")
        report.update(status="GPU_OBSERVATION_READY", diagnosis=diagnosis,
                      observation=str(args.output / "observation.json"))
        write_json(args.output / "result.json", report)
        store.append({"type": "observation", "champion": version, "candidate_sha256": source_hash,
                      "evidence": str(args.output / "result.json"), "diagnosis": diagnosis})
        print(f"[observación] fase dominante: {diagnosis['claims'][0]['phase']}; "
              f"sobrecarga instrumentación: {diagnosis['instrumentation_overhead_ratio']:.2f}x", file=sys.stderr, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--bootstrap-report", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--steps", type=int, default=100)
    args = parser.parse_args()
    if not 10 <= args.steps <= 300:
        parser.error("steps debe ser 10..300")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING"}
    try:
        run(args, report)
    except BaseException as exc:
        report.update(status="FAILED", reason=f"{type(exc).__name__}: {exc}")
        write_json(args.output / "NEEDS_HUMAN.json", {"reason": report["reason"]})
        raise
    finally:
        write_json(args.output / "result.json", report)
        lines = ["# Observación GaiaTransformer", "", "```json", json.dumps(report, indent=2, ensure_ascii=False), "```", ""]
        (args.output / "REPORT.md").write_text("\n".join(lines))
    print(json.dumps({"status": report["status"], "champion": report["champion"], "result": str(args.output / "result.json")}))


if __name__ == "__main__":
    main()
