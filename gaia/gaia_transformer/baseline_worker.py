"""Baseline de confianza en proceso nuevo. Solo recibe train y contextos privados.

No es todavía el protocolo de candidatos/aislamiento del laboratorio de Fase 2.
"""
import json
from pathlib import Path
import resource
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def run(directory):
    start = time.monotonic()
    request = json.loads((directory / "request.json").read_text())
    limits = request["limits"]
    resource.setrlimit(resource.RLIMIT_CPU, (int(limits["seconds"]) + 10, int(limits["seconds"]) + 12))
    import numpy as np
    import torch
    from gaia.protected import runtime
    from gaia.gaia_transformer.model import ModelConfig
    from gaia.gaia_transformer.trainer import Trainer, configure_cuda, state_digest

    configure_cuda(request["seed"], limits["vram_mb"])
    gpu = torch.cuda.get_device_properties(0)
    if str(gpu.uuid).lower().removeprefix("gpu-") != request["device_uuid"].lower().removeprefix("gpu-"):
        raise RuntimeError("La GPU activa no coincide con el UUID seleccionado")
    if not runtime.arch_supports(torch.cuda.get_arch_list(), torch.cuda.get_device_capability(0)):
        raise RuntimeError("La wheel no cubre los kernels de esta GPU")
    with np.load(directory / "inputs.npz", allow_pickle=False) as inputs:
        if set(inputs.files) != {"train", "contexts"}:
            raise ValueError("Protocolo baseline: solo se permiten train y contexts")
        train, contexts = inputs["train"], inputs["contexts"]
    trainer = Trainer(train, request["seed"], ModelConfig(**request["model"]))
    if any(p.device.type != "cuda" or p.dtype != torch.float32 for p in trainer.model.parameters()):
        raise RuntimeError("Todos los parámetros deben estar en CUDA/fp32")
    torch.cuda.synchronize()
    t_init = time.monotonic() - start

    def guard():
        if time.monotonic() - start > limits["seconds"]:
            raise TimeoutError("Baseline supera el presupuesto de tiempo")
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        if rss > limits["rss_mb"] or torch.cuda.max_memory_reserved() / 2**20 > limits["vram_mb"]:
            raise RuntimeError("Baseline supera presupuesto RSS/VRAM del allocator")

    initial_hash = state_digest(trainer.model)
    snapshots, t_train, t_eval = [], 0.0, 0.0

    def evaluate():
        nonlocal t_eval
        guard()
        torch.cuda.synchronize()
        t0 = time.monotonic()
        logits = trainer.predict_last(contexts)
        torch.cuda.synchronize()
        t_eval += time.monotonic() - t0
        filename = f"logits-{trainer.steps:06d}.npy"
        np.save(directory / filename, logits, allow_pickle=False)
        snapshots.append({"step": trainer.steps, "logits": filename})

    evaluate()
    while trainer.steps < request["steps"]:
        end = min(trainer.steps + request["eval_every"], request["steps"])
        torch.cuda.synchronize()
        t0 = time.monotonic()
        while trainer.steps < end:
            guard()
            trainer.step()
        torch.cuda.synchronize()
        t_train += time.monotonic() - t0
        evaluate()
    guard()
    final_hash = state_digest(trainer.model)
    gradient_hash = trainer.gradient_digest()
    torch.cuda.synchronize()
    guard()
    result = {"status": "ok", "seed": request["seed"], "configuration": trainer.configuration(),
              "parameters": sum(p.numel() for p in trainer.model.parameters()),
              "runtime": runtime.fingerprint(with_torch=True),
              "gpu": {"name": gpu.name, "uuid": str(gpu.uuid),
                      "capability": list(torch.cuda.get_device_capability(0)), "vram_mb": gpu.total_memory // 2**20},
              "policy": {"deterministic": torch.are_deterministic_algorithms_enabled(),
                         "tf32_matmul": torch.backends.cuda.matmul.allow_tf32,
                         "tf32_cudnn": torch.backends.cudnn.allow_tf32,
                         "cudnn_benchmark": torch.backends.cudnn.benchmark,
                         "cudnn_deterministic": torch.backends.cudnn.deterministic},
              "initial_state_sha256": initial_hash, "final_state_sha256": final_hash,
              "final_gradient_sha256": gradient_hash, "train_losses": trainer.losses,
              "snapshots": snapshots,
              "metrics": {"init_seconds": t_init, "train_seconds": t_train, "eval_seconds": t_eval,
                          "wall_seconds": time.monotonic() - start,
                          "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                          "peak_vram_reserved_mb": torch.cuda.max_memory_reserved() / 2**20,
                          "peak_vram_allocated_mb": torch.cuda.max_memory_allocated() / 2**20}}
    (directory / "worker_result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    try:
        run(Path(sys.argv[1]))
    except Exception as exc:
        print(f"GAIA_TRANSFORMER_BASELINE_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
