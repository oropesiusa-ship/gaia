"""Smoke test de plataforma (Fase 0.1), no entrenador ni evaluador de campaña.

Ejecutable bajo python -I: solo usa stdlib hasta que se fijan los flags CUDA.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import sys
import time


def probe():
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
        raise RuntimeError("CUBLAS_WORKSPACE_CONFIG debe fijarse antes de importar torch")
    import numpy as np
    import torch

    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA no disponible en el runtime instalado")
    if torch.cuda.device_count() != 1:
        raise RuntimeError("El probe requiere exactamente una GPU visible")
    torch.cuda.set_device(0)
    prop = torch.cuda.get_device_properties(0)
    spec = importlib.util.spec_from_file_location("gaia_runtime", Path(__file__).parent / "protected/runtime.py")
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    if not runtime.arch_supports(torch.cuda.get_arch_list(), torch.cuda.get_device_capability(0)):
        raise RuntimeError("La wheel de Torch no contiene un cubin compatible con la GPU")
    max_vram = int(os.environ["GAIA_PROBE_VRAM_MB"])
    max_rss = int(os.environ["GAIA_PROBE_RSS_MB"])
    torch.cuda.set_per_process_memory_fraction(min(1.0, max_vram * 2**20 / prop.total_memory), 0)

    def sample(seed):
        torch.manual_seed(seed)
        np.random.seed(seed)
        x = torch.randn(32, 64, device="cuda", dtype=torch.float32)
        weight = torch.randn(64, 64, device="cuda", dtype=torch.float32, requires_grad=True)
        target = torch.randint(0, 64, (32,), device="cuda")
        hashes, losses = [], []
        for _ in range(3):
            logits = torch.nn.functional.gelu(torch.nn.functional.layer_norm(x @ weight, (64,)))
            loss = torch.nn.functional.cross_entropy(logits, target)
            loss.backward()
            if not torch.isfinite(loss).item() or not torch.isfinite(weight.grad).all().item():
                raise RuntimeError("Loss o gradientes CUDA no finitos")
            hashes.append(hashlib.sha256(weight.grad.detach().cpu().numpy().tobytes()).hexdigest())
            losses.append(loss.item())
            with torch.no_grad():
                weight.add_(weight.grad, alpha=-0.05)
            weight.grad = None
        torch.cuda.synchronize()
        return {"output": hashlib.sha256(logits.detach().cpu().numpy().tobytes()).hexdigest(),
                "gradients": hashes, "losses": losses}

    torch.cuda.synchronize()
    start = time.monotonic()
    a, b = sample(123), sample(123)
    other = sample(124)
    torch.cuda.synchronize()
    if a != b or a["output"] == other["output"]:
        raise RuntimeError("El smoke test no reproduce semillas iguales o no distingue semillas diferentes")
    peak_vram = torch.cuda.max_memory_reserved(0) / 2**20
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    if peak_vram > max_vram or peak_rss > max_rss:
        raise RuntimeError(f"Presupuesto excedido: VRAM={peak_vram:.1f} MiB, RSS={peak_rss:.1f} MiB")
    return {"runtime": runtime.fingerprint(with_torch=True),
            "gpu": {"name": prop.name, "uuid": str(prop.uuid), "vram_mb": prop.total_memory // 2**20,
                    "capability": list(torch.cuda.get_device_capability(0)),
                    "arch_list": list(torch.cuda.get_arch_list())},
            "policy": {"deterministic": torch.are_deterministic_algorithms_enabled(),
                       "cublas_workspace_config": os.environ["CUBLAS_WORKSPACE_CONFIG"],
                       "tf32_matmul": torch.backends.cuda.matmul.allow_tf32,
                       "tf32_cudnn": torch.backends.cudnn.allow_tf32,
                       "cudnn_benchmark": torch.backends.cudnn.benchmark,
                       "cudnn_deterministic": torch.backends.cudnn.deterministic,
                       "dtype": "float32", "visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES")},
            "determinism": a, "different_seed_output": other["output"],
            "metrics": {"smoke_seconds": time.monotonic() - start, "peak_vram_reserved_mb": peak_vram,
                        "peak_rss_mb": peak_rss}, "status": "ok"}


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), sort_keys=True))
    except Exception as exc:
        print(f"CUDA_PROBE_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
