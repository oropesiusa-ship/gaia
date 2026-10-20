"""Verificación de baseline: métricas privadas en el padre, sin búsqueda ni Store."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
from gaia.gaia_transformer import data

MODEL = {"dim": 64, "layers": 2, "heads": 2, "context": 64, "dropout": 0.0}


def cross_entropy(logits, targets):
    if (logits.shape != (len(targets), 256) or logits.dtype != np.float32
            or targets.ndim != 1 or len(targets) == 0 or targets.dtype != np.uint8 or not np.isfinite(logits).all()):
        raise ValueError("Logits privados inválidos: se requiere float32 N x 256 finito")
    values = logits.astype(np.float64)
    values -= values.max(axis=1, keepdims=True)
    return float(np.mean(np.log(np.exp(values).sum(axis=1)) - values[np.arange(len(targets)), targets]))


def write_inputs(directory, training_records, contexts):
    if training_records.shape[1] != 65 or contexts.shape[1] != 64:
        raise ValueError("El worker solo recibe registros train completos y contextos sin targets")
    np.savez(directory / "inputs.npz", train=training_records, contexts=contexts)


def check_training(worker, evaluations):
    losses = worker["train_losses"]
    window = min(10, len(losses) // 2)
    if window == 0 or not np.isfinite(losses).all() or not np.isfinite([e["loss"] for e in evaluations]).all():
        raise RuntimeError("Pérdidas train insuficientes/no finitas")
    initial, final = float(np.mean(losses[:window])), float(np.mean(losses[-window:]))
    if final >= initial or evaluations[-1]["loss"] >= evaluations[0]["loss"]:
        raise RuntimeError("La baseline no reduce simultáneamente pérdida train y validación privada")
    return {"train_first_mean": initial, "train_last_mean": final,
            "validation_initial": evaluations[0]["loss"], "validation_final": evaluations[-1]["loss"]}


def validate_repetitions(trials, repeats):
    first = trials[0]
    for trial in trials[1:repeats]:
        for key in ("runtime", "gpu", "policy", "configuration", "deterministic_result"):
            if trial[key] != first[key]:
                raise RuntimeError("La baseline no se reproduce entre procesos: " + key)
    other = trials[-1]
    if other["deterministic_result"]["final_state_sha256"] == first["deterministic_result"]["final_state_sha256"]:
        raise RuntimeError("Otra semilla produce exactamente los mismos pesos: revisar seeding")


def run_trial(output, index, seed, steps, cfg, train, contexts, targets, expected_runtime):
    print(f"[GaiaTransformer] trial {index}: seed={seed}, pasos={steps}", file=sys.stderr, flush=True)
    worker_script = Path(__file__).with_name("baseline_worker.py")
    with tempfile.TemporaryDirectory(prefix=f"trial-{index}-", dir=output) as tmp:
        directory = Path(tmp)
        write_inputs(directory, train, contexts)
        request = {"seed": seed, "steps": steps, "eval_every": 25, "model": MODEL,
                   "device_uuid": cfg["cuda"]["device_uuid"],
                   "limits": {"seconds": cfg.get("limits", {}).get("max_experiment_seconds", 20),
                              "rss_mb": cfg["limits"]["max_ram_mb"], "vram_mb": cfg["limits"]["max_vram_mb"]}}
        (directory / "request.json").write_text(json.dumps(request))
        env = {key: os.environ[key] for key in (
            "PATH", "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER", "CUBLAS_WORKSPACE_CONFIG",
            "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS") if key in os.environ}
        env.update(HOME=str(directory), PYTHONHASHSEED="0")
        with (output / f"trial-{index}.stdout.log").open("w") as stdout, (output / f"trial-{index}.stderr.log").open("w") as stderr:
            proc = subprocess.Popen([sys.executable, "-I", str(worker_script), str(directory)],
                                    cwd=directory, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                rc = proc.wait(timeout=request["limits"]["seconds"] + 10)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
                raise
        if rc:
            raise RuntimeError(f"Trial {index} terminó con {rc}; revisar trial-{index}.stderr.log")
        worker = json.loads((directory / "worker_result.json").read_text())
        # Persistir el resultado antes de las comprobaciones para conservar evidencia en un rechazo.
        (output / f"trial-{index}.worker.json").write_text(json.dumps(worker, indent=2) + "\n")
        if worker["runtime"] != expected_runtime:
            raise RuntimeError("El runtime del worker no coincide con la plataforma CUDA validada")
        evaluations = []
        for snapshot in worker.pop("snapshots"):
            logits = np.load(directory / snapshot["logits"], allow_pickle=False)
            evaluations.append({"step": snapshot["step"], "loss": cross_entropy(logits, targets),
                                "logits_sha256": hashlib.sha256(logits.tobytes()).hexdigest()})
        improvement = check_training(worker, evaluations)
        deterministic = {k: worker.pop(k) for k in (
            "initial_state_sha256", "final_state_sha256", "final_gradient_sha256", "train_losses")}
        deterministic["evaluations"] = evaluations
        worker.update(deterministic_result=deterministic, improvement=improvement)
        (output / f"trial-{index}.json").write_text(json.dumps(worker, indent=2) + "\n")
        print(f"[GaiaTransformer] train {improvement['train_first_mean']:.4f} -> {improvement['train_last_mean']:.4f}; "
              f"validación {improvement['validation_initial']:.4f} -> {improvement['validation_final']:.4f}",
              file=sys.stderr, flush=True)
        return worker


def run(args, report):
    cfg = json.loads(Path(args.config).read_text())
    if cfg["workload"]["id"] != "gaia_transformer_cuda" or cfg["workload"]["contract"] != "gaia_transformer_cuda/v1.1":
        raise ValueError("Configuración GaiaTransformer/CUDA v1.1 requerida")
    frozen = json.loads(Path(__file__).with_name("corpus_v1.json").read_text())
    corpus = data.manifest()
    if corpus != frozen:
        raise RuntimeError("El corpus generado no coincide con su especificación/digest congelados")
    report.update(corpus=corpus, model=MODEL, seed=args.seed, steps=args.steps, repeats=args.repeats,
                  contract=cfg["workload"]["contract"], config=cfg,
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted(Path(__file__).parent.glob("*.py"))}, trials=[])
    (args.output / "corpus.json").write_text(json.dumps(corpus, indent=2) + "\n")
    train = data.records(data.generate_split(data.DEFAULT_SPEC, "train"))
    contexts, targets = data.private_validation(data.generate_split(data.DEFAULT_SPEC, "validation"))
    expected_runtime = json.loads(Path(args.bootstrap_report).read_text())["cuda_probes"][0]["runtime"]
    for index, seed in enumerate([args.seed] * args.repeats + [args.seed + 1]):
        trial = run_trial(args.output, index, seed, args.steps, cfg, train, contexts, targets, expected_runtime)
        report["trials"].append(trial)
        (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    validate_repetitions(report["trials"], args.repeats)
    report.update(status="GAIA_TRANSFORMER_BASELINE_READY", reproducible=True, private_validation=True,
                  campaign_initialized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--bootstrap-report", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--seed", type=int, default=9000)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING"}
    try:
        if not 20 <= args.steps <= 10000 or not 2 <= args.repeats <= 5 or not 0 <= args.seed < 2**31 - 1:
            raise ValueError("steps debe ser 20..10000, repeats 2..5 y seed 0..2**31-2")
        run(args, report)
    except BaseException as exc:
        report.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "result": str(args.output / "result.json"),
                      "corpus_sha256": report["corpus"]["sha256"], "trials": len(report["trials"])}))


if __name__ == "__main__":
    main()
