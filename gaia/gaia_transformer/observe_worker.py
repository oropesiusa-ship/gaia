"""Observador de confianza en sandbox: tres entrenamientos normales y uno instrumentado."""
import ast
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import types


def main():
    directory = Path(sys.argv[1])
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    sys.stdout = open(os.devnull, "w")
    try:
        start = time.perf_counter()
        import numpy as np
        import torch
        request = json.loads((directory / "runtime.json").read_text())
        profiling_spec = importlib.util.spec_from_file_location("profiling", Path(__file__).with_name("profiling.py"))
        profiling = importlib.util.module_from_spec(profiling_spec)
        profiling_spec.loader.exec_module(profiling)
        spec = importlib.util.spec_from_file_location("runtime", Path(__file__).with_name("runtime.py"))
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        if torch.cuda.device_count() != 1 or os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
            raise RuntimeError("CUDA policy inválida")
        torch.cuda.set_device(0)
        gpu = torch.cuda.get_device_properties(0)
        if str(gpu.uuid).lower().removeprefix("gpu-") != request["uuid"].lower().removeprefix("gpu-"):
            raise RuntimeError("UUID GPU distinto")
        if not runtime.arch_supports(torch.cuda.get_arch_list(), torch.cuda.get_device_capability(0)):
            raise RuntimeError("Wheel sin arquitectura compatible")
        torch.cuda.set_per_process_memory_fraction(min(1., request["vram_mb"] * 2**20 / gpu.total_memory), 0)
        with np.load(directory / "inputs.npz", allow_pickle=False) as inputs:
            if set(inputs.files) != {"train", "contexts"}:
                raise ValueError("Inputs de observación inválidos")
            train, contexts = inputs["train"], inputs["contexts"]
        source = (directory / "candidate.py").read_text()
        phases = {}
        active = False

        @contextmanager
        def measure(name):
            if not active:
                yield
                return
            torch.cuda.synchronize()
            first, last = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            first.record()
            before = time.perf_counter()
            yield
            last.record()
            torch.cuda.synchronize()
            wall = time.perf_counter() - before
            item = phases.setdefault(name, {"count": 0, "wall_s": 0., "cuda_stream_ms": 0.})
            item["count"] += 1
            item["wall_s"] += wall
            item["cuda_stream_ms"] += first.elapsed_time(last)

        def signature(candidate, predictions):
            state, gradients = hashlib.sha256(), hashlib.sha256()
            for key, value in sorted(candidate.model.state_dict().items()):
                state.update(key.encode())
                state.update(value.detach().cpu().contiguous().numpy().tobytes())
            for key, value in sorted(candidate.model.named_parameters()):
                if value.grad is not None:
                    gradients.update(key.encode())
                    gradients.update(value.grad.detach().cpu().contiguous().numpy().tobytes())
            return {"state": state.hexdigest(), "gradients": gradients.hexdigest(),
                    "losses": hashlib.sha256(np.asarray(candidate.losses, dtype=np.float64).tobytes()).hexdigest(),
                    "logits": hashlib.sha256(predictions.tobytes()).hexdigest()}

        def fresh(instrumented, index):
            nonlocal active, phases
            active = False
            torch.manual_seed(request["seed"])
            np.random.seed(request["seed"])
            module = types.ModuleType(f"gaia_observer_candidate_{index}")
            module.gaia_observe_phase = measure
            sys.modules[module.__name__] = module
            candidate = None
            try:
                torch.cuda.synchronize()
                before = time.perf_counter()
                exec(compile(profiling.instrument(source) if instrumented else source, "<observed-candidate>", "exec"), module.__dict__)
                candidate = module.Candidate(train.copy(), request["seed"])
                if any(p.device.type != "cuda" or p.dtype != torch.float32 for p in candidate.model.parameters()):
                    raise RuntimeError("Observador requiere modelo CUDA/fp32")
                torch.cuda.synchronize()
                init_s = time.perf_counter() - before
                before = time.perf_counter()
                candidate.train(request["warmup"])
                torch.cuda.synchronize()
                warmup_s = time.perf_counter() - before
                phases = {}
                active = instrumented
                torch.cuda.synchronize()
                before = time.perf_counter()
                candidate.train(request["steps"])
                torch.cuda.synchronize()
                train_s = time.perf_counter() - before
                active = False
                before = time.perf_counter()
                predictions = candidate.predict(contexts.copy())
                torch.cuda.synchronize()
                eval_s = time.perf_counter() - before
                if predictions.shape != (len(contexts), 256) or not np.isfinite(predictions).all():
                    raise ValueError("Predicciones de observación inválidas")
                return {"init_s": init_s, "warmup_s": warmup_s, "train_s": train_s, "eval_s": eval_s,
                        "signature": signature(candidate, predictions), "phases": dict(phases),
                        "allocator_peak_mb": torch.cuda.max_memory_reserved() / 2**20,
                        "parameters": sum(p.numel() for p in candidate.model.parameters())}
            finally:
                del candidate
                sys.modules.pop(module.__name__, None)
                import gc
                gc.collect()
                torch.cuda.empty_cache()

        torch.cuda.synchronize()
        startup = time.perf_counter() - start
        runs = [fresh(False, index) for index in range(3)]
        wrapped = fresh(True, 3)
        result = {"event": "OBSERVATION", "steps": request["steps"], "warmup": request["warmup"],
                  "seed": request["seed"], "startup_s": startup, "plain_runs": runs, "instrumented": wrapped,
                  "replicates": "tres entrenamientos frescos dentro del mismo proceso observador",
                  "timing_semantics": "pared sincronizada por fase; eventos CUDA miden intervalo de stream, no suma pura de kernels",
                  "runtime": runtime.fingerprint(with_torch=True),
                  "parity": all(run["signature"] == wrapped["signature"] for run in runs),
                  "policy": {"deterministic": torch.are_deterministic_algorithms_enabled(),
                             "tf32_matmul": torch.backends.cuda.matmul.allow_tf32,
                             "tf32_cudnn": torch.backends.cudnn.allow_tf32, "cudnn_benchmark": torch.backends.cudnn.benchmark},
                  "input_fields": ["contexts", "train"], "wall_s": time.perf_counter() - start}
        profiling.validate_observation(result)
        proto.write(json.dumps(result, allow_nan=False) + "\n")
    except BaseException as exc:
        proto.write(json.dumps({"event": "ERROR", "reason": f"{type(exc).__name__}: {exc}"}) + "\n")
        raise


if __name__ == "__main__":
    main()
