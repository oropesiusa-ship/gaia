"""Servidor GPU protegido: INIT/TRAIN/PREDICT/QUIT; jamás recibe targets ni objetivo."""
import importlib.util
import json
import os
from pathlib import Path
import sys


def main():
    directory = Path(sys.argv[1])
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    sys.stdout = open(os.devnull, "w")

    def emit(value):
        proto.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")

    try:
        import numpy as np
        import torch
        from dataclasses import dataclass  # disponible al ejecutar el candidato autónomo

        request = json.loads((directory / "runtime.json").read_text())
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8" or torch.cuda.device_count() != 1:
            raise RuntimeError("CUDA_POLICY: workspace/GPU visible inválidos")
        torch.cuda.set_device(0)
        prop = torch.cuda.get_device_properties(0)
        if str(prop.uuid).lower().removeprefix("gpu-") != request["uuid"].lower().removeprefix("gpu-"):
            raise RuntimeError("GPU_MISMATCH")
        # Se conserva el tope de allocator, pero el padre controla VRAM total con NVML.
        torch.cuda.set_per_process_memory_fraction(min(1.0, request["vram_mb"] * 2**20 / prop.total_memory), 0)
        spec = importlib.util.spec_from_file_location("gaia_runtime", Path(__file__).with_name("runtime.py"))
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        if not runtime.arch_supports(torch.cuda.get_arch_list(), torch.cuda.get_device_capability(0)):
            raise RuntimeError("CUDA_ARCH_MISMATCH")
        with np.load(directory / "inputs.npz", allow_pickle=False) as inputs:
            if set(inputs.files) != {"train", "contexts"}:
                raise RuntimeError("INPUT_FIELDS: solo train/contexts permitidos")
            train, contexts = inputs["train"], inputs["contexts"]
        contexts.setflags(write=False)
        torch.cuda.synchronize()
        isolation = {"parent_hidden": not Path(f"/proc/{request['parent_host_pid']}").exists(),
                     "network_isolated": os.stat("/proc/self/ns/net").st_ino != request["parent_net_inode"],
                     "host_files_hidden": all(not Path(path).exists() for path in request["hidden_files"])}
        if request["isolated"] and not all(isolation.values()):
            raise RuntimeError("SANDBOX_POLICY: aislamiento incompleto")
        emit({"event": "READY", "runtime": runtime.fingerprint(with_torch=True),
              "gpu_uuid": str(prop.uuid), "pid_in_namespace": os.getpid(),
              "input_fields": ["contexts", "train"], "environment_keys": sorted(os.environ), "isolation": isolation})
        candidate = None

        def check_policy():
            if (not torch.are_deterministic_algorithms_enabled() or torch.backends.cuda.matmul.allow_tf32
                    or torch.backends.cudnn.allow_tf32 or torch.backends.cudnn.benchmark
                    or not torch.backends.cudnn.deterministic or torch.cuda.current_device() != 0):
                raise RuntimeError("CUDA_POLICY: el candidato alteró flags protegidos")
            if candidate is not None:
                if not isinstance(candidate.model, torch.nn.Module):
                    raise RuntimeError("MODEL: se requiere candidate.model nn.Module")
                parameters = list(candidate.model.parameters())
                if not parameters or any(p.device.type != "cuda" or p.dtype != torch.float32 for p in parameters):
                    raise RuntimeError("MODEL: parámetros deben estar en CUDA/fp32")
                if any(not torch.isfinite(p).all().item() for p in parameters):
                    raise RuntimeError("MODEL: parámetros no finitos")

        for line in sys.stdin:
            if len(line) > 4096:
                raise RuntimeError("PROTOCOL: petición demasiado larga")
            message = json.loads(line)
            cmd = message["command"]
            torch.cuda.synchronize()
            if cmd == "INIT":
                if candidate is not None:
                    raise RuntimeError("PROTOCOL: INIT duplicado")
                seed = int(message["seed"])
                np.random.seed(seed)
                torch.manual_seed(seed)
                module_spec = importlib.util.spec_from_file_location("gaia_candidate", directory / "candidate.py")
                module = importlib.util.module_from_spec(module_spec)
                sys.modules[module_spec.name] = module  # dataclasses consulta __module__.
                module_spec.loader.exec_module(module)
                candidate = module.Candidate(train.copy(), seed)
            elif cmd == "TRAIN":
                if candidate is None or not 1 <= int(message["steps"]) <= 10000:
                    raise RuntimeError("PROTOCOL: TRAIN inválido")
                candidate.train(int(message["steps"]))
            elif cmd == "PREDICT":
                if candidate is None:
                    raise RuntimeError("PROTOCOL: PREDICT antes de INIT")
                prediction = candidate.predict(contexts.copy())
                if type(prediction) is not np.ndarray or prediction.shape != (len(contexts), 256) or prediction.dtype != np.float32:
                    raise ValueError("PREDICTION: se requiere ndarray float32 N x 256")
                if not np.isfinite(prediction).all():
                    raise ValueError("PREDICTION: logits no finitos")
                np.save(directory / "prediction.npy", prediction, allow_pickle=False)
            elif cmd == "QUIT":
                torch.cuda.synchronize()
                emit({"event": "BYE"})
                return
            else:
                raise RuntimeError("PROTOCOL: comando desconocido")
            check_policy()
            torch.cuda.synchronize()
            emit({"event": "OK", "command": cmd,
                  "allocator_peak_mb": torch.cuda.max_memory_reserved() / 2**20})
    except BaseException as exc:
        code = "CUDA_OOM" if "torch" in locals() and isinstance(exc, torch.OutOfMemoryError) else "WORKER_ERROR"
        emit({"event": "ERROR", "code": code, "reason": f"{type(exc).__name__}: {exc}"[:2000]})
        raise


if __name__ == "__main__":
    main()
