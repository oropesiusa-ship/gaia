"""Pruebas del laboratorio GPU: baseline, repetición, protocolo y fallos deliberados."""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from gaia.gaia_transformer.lab import benchmark
from gaia.gaia_transformer.lab.candidate import baseline_source
from gaia.gaia_transformer.lab.evaluator import run_trial


def cases(source, cfg, runtime, smoke=False):
    yield "baseline", source, cfg, runtime, benchmark.TrialSpec(), "ok", None
    if smoke:
        return
    yield "repeat", source, cfg, runtime, benchmark.TrialSpec(), "ok", None
    yield "private_target", source, cfg, runtime, benchmark.TrialSpec(target_loss=3.0), "ok", None
    yield "bad_import", source + "\nimport os\n", cfg, runtime, benchmark.TrialSpec(), "invalid", None
    variants = {
        "bad_shape": ("predict(self, contexts)", "return np.zeros((len(contexts),255),dtype=np.float32)", "worker_error"),
        "nonfinite": ("predict(self, contexts)", "return np.full((len(contexts),256),np.nan,dtype=np.float32)", "worker_error"),
        "crash": ("train(self, steps)", "raise RuntimeError('deliberate candidate failure')", "worker_error"),
        "cuda_oom": ("train(self, steps)", "self.extra = torch.empty(2**30,device='cuda',dtype=torch.float32)", "cuda_oom"),
        "policy": ("train(self, steps)", "torch.use_deterministic_algorithms(False)", "worker_error"),
        "timeout": ("train(self, steps)", "while True: pass", "timeout"),
        "stdout": ("train(self, steps)", "print('not a protocol response'); super().train(steps)", "ok"),
    }
    for name, (signature, body, expected) in variants.items():
        config = copy.deepcopy(cfg)
        if name == "timeout":
            config["limits"]["max_experiment_seconds"] = 6
        variant = source + f"\nclass Candidate(Candidate):\n    def {signature}:\n        {body}\n"
        yield name, variant, config, runtime, benchmark.TrialSpec(steps=25), expected, None
    for name, key, value in (("rss_limit", "max_ram_mb", 64), ("vram_limit", "max_vram_mb", 1),
                              ("disk_limit", "max_disk_mb", 0.001)):
        config = copy.deepcopy(cfg)
        config["limits"][key] = value
        yield name, source, config, runtime, benchmark.TrialSpec(), "resource_limit", None
    altered = copy.deepcopy(runtime)
    altered["torch"]["version"] = "deliberately_wrong"
    yield "runtime_mismatch", source, cfg, altered, benchmark.TrialSpec(), "protocol_error", None
    yield "integrity_mismatch", source, cfg, runtime, benchmark.TrialSpec(), "error", {"changed": "identity"}
    yield "stop", source, cfg, runtime, benchmark.TrialSpec(), "stopped", None


def verify(name, result, completed):
    if not result["temporary_files_removed"]:
        raise RuntimeError("Limpieza incompleta: " + name)
    if name == "baseline":
        if result["final_loss"] >= result["curve"][0]["loss"]:
            raise RuntimeError("La baseline no redujo pérdida privada")
        if result["isolation"]["mode"] != "bwrap" or not all(result["handshake"]["isolation"].values()):
            raise RuntimeError("No hay aislamiento verificable de red/procesos/archivos")
        if not result["gpu_process_seen"] or result["peak_vram_nvml_mb"] < result["allocator_peak_mb"]:
            raise RuntimeError("Telemetría de VRAM incompleta")
    if name == "repeat" and result["curve"] != completed["baseline"]["curve"]:
        raise RuntimeError("El laboratorio no reproduce los logits/pérdidas de la baseline")
    if name == "private_target":
        if not result["reached"] or result["steps"] != 50:
            raise RuntimeError("El objetivo privado no requirió dos logros sucesivos")
        if result["cost_s"] != sum(result[key] for key in ("t_init_s", "t_train_s", "t_eval_s", "t_metric_s")):
            raise RuntimeError("El coste excluye trabajo necesario de confirmación/evaluación")
    resources = {"rss_limit": "ram_mb", "vram_limit": "vram_mb", "disk_limit": "disk_mb"}
    if name in resources and result.get("resource") != resources[name]:
        raise RuntimeError("Se detectó un límite distinto al que se pretendía probar: " + name)
    if name == "timeout" and result["stage"] != "train":
        raise RuntimeError("El timeout no llegó al candidato de entrenamiento")
    if result["status"] != "ok" and (result["valid"] or result["cost_s"] is not None):
        raise RuntimeError("Fallo marcado como resultado válido: " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--bootstrap-report", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cfg = json.loads(Path(args.config).read_text())
    runtime = json.loads(Path(args.bootstrap_report).read_text())["cuda_probes"][0]["runtime"]
    source, protected = baseline_source(), benchmark.identity()
    report = {"status": "RUNNING", "campaign_initialized": False, "calibrated": False,
              "protected_sha256": protected, "cases": {}}
    try:
        for name, candidate, config, expected_runtime, spec, expected, identity_override in cases(source, cfg, runtime, args.baseline_only):
            print(f"[GPU lab] {name}: esperado={expected}", file=sys.stderr, flush=True)
            stop = args.output / "test_STOP" if name == "stop" else ROOT / "STOP"
            if name == "stop":
                stop.write_text("test stop\n")
            result = run_trial(candidate, config, expected_runtime, args.output / name, spec,
                               expected_identity=identity_override if identity_override is not None else protected,
                               require_sandbox=True, stop_file=stop)
            report["cases"][name] = result
            (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
            if result["status"] != expected:
                raise RuntimeError(f"{name}: esperado {expected}, recibido {result['status']}: {result['error']}")
            verify(name, result, report["cases"])
        report["status"] = "GPU_TRIAL_READY" if args.baseline_only else "GPU_LAB_READY"
    except BaseException as exc:
        report.update(status="FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "cases": len(report["cases"]), "result": str(args.output / "result.json")}))


if __name__ == "__main__":
    main()
