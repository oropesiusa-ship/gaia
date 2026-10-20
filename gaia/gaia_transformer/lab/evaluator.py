"""Padre GPU: tiempos de pared, targets privados, watchdog continuo y limpieza."""
from dataclasses import asdict
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import numpy as np

from gaia.protected import runtime
from . import benchmark, guard, sandbox
from .monitor import LimitExceeded, MonitorError, NVML, Watchdog, terminate


class ProtocolError(RuntimeError):
    pass


class WorkerError(RuntimeError):
    def __init__(self, response):
        self.code = response.get("code", "WORKER_ERROR")
        super().__init__(response.get("reason", "Fallo del worker"))


def limiter(seconds, file_mb):
    parent = os.getpid()

    def apply():
        resource.setrlimit(resource.RLIMIT_CPU, (math.ceil(seconds) + 5, math.ceil(seconds) + 6))
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_mb * 2**20, file_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        ctypes.CDLL(None).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
        if os.getppid() != parent:
            os._exit(130)
    return apply


class Channel:
    def __init__(self, proc, watchdog):
        self.proc, self.watchdog, self.buffer = proc, watchdog, b""

    def recv(self):
        while b"\n" not in self.buffer:
            self.watchdog.check()
            if len(self.buffer) > 65536:
                raise ProtocolError("Respuesta de protocolo demasiado larga")
            ready, _, _ = select.select([self.proc.stdout], [], [], 0.01)
            if ready:
                chunk = os.read(self.proc.stdout.fileno(), 8192)
                if not chunk:
                    raise ProtocolError("EOF del worker antes de completar protocolo")
                self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        if len(line) > 65536:
            raise ProtocolError("Respuesta de protocolo demasiado larga")
        self.watchdog.check(force=True)
        try:
            response = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            raise ProtocolError("Respuesta no es JSON válido") from exc
        if not isinstance(response, dict):
            raise ProtocolError("Respuesta debe ser objeto JSON")
        if response.get("event") == "ERROR":
            raise WorkerError(response)
        return response

    def command(self, command, **values):
        self.watchdog.check()
        self.proc.stdin.write((json.dumps({"command": command, **values}) + "\n").encode())
        self.proc.stdin.flush()
        response = self.recv()
        if response.get("event") != "OK" or response.get("command") != command:
            raise ProtocolError("Acuse de comando incorrecto")
        return response


def validate_runtime(expected):
    actual = runtime.fingerprint(with_torch=False)
    # El padre no inicializa CUDA ni importa Torch: usa la huella del probe validado.
    if {key: value for key, value in actual.items() if key != "torch"} != {
            key: value for key, value in expected.items() if key != "torch"}:
        raise RuntimeError("PARENT_RUNTIME_MISMATCH: entorno distinto al probe CUDA")


def run_trial(source, cfg, expected_runtime, output, spec=benchmark.TrialSpec(), *,
              expected_identity=None, require_sandbox=True, stop_file=None):
    """Un trial sin selección/promoción. Solo status=ok es resultado válido."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = {"status": "running", "valid": False, "error": None, "stage": "preflight",
              "candidate_sha256": hashlib.sha256(source.encode()).hexdigest(), "spec": asdict(spec),
              "target_calibrated": False, "reached": False, "steps": 0, "curve": [],
              "t_init_s": 0.0, "t_train_s": 0.0, "t_eval_s": 0.0, "t_metric_s": 0.0, "cost_s": None}
    proc = telemetry = watchdog = None
    wall_start = time.monotonic()
    trial_root = None
    try:
        guard.check_source(source)
        validate_runtime(expected_runtime)
        protected = benchmark.identity()
        result["protected_sha256"] = protected
        if expected_identity is not None and protected != expected_identity:
            raise RuntimeError("LAB_INTEGRITY: laboratorio distinto a su identidad esperada")
        limits_cfg = cfg.get("limits", {})
        limits = {"ram_mb": limits_cfg.get("max_ram_mb", 3000), "vram_mb": limits_cfg.get("max_vram_mb", 3000),
                  "disk_mb": limits_cfg.get("max_disk_mb", 500), "seconds": limits_cfg.get("max_experiment_seconds", 20)}
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in limits.values()):
            raise ValueError("Límites GPU deben ser finitos y positivos")
        result["limits"] = limits
        executable, reason = sandbox.available()
        if require_sandbox and not executable:
            raise RuntimeError("SANDBOX_UNAVAILABLE: " + str(reason))
        result["isolation"] = {"mode": "bwrap" if executable else "process_only", "reason": reason,
                               "network_namespace": bool(executable), "pid_namespace": bool(executable)}
        try:
            telemetry = NVML(cfg["cuda"]["device_uuid"])
        except (OSError, AttributeError) as exc:
            raise MonitorError("NVML no disponible: " + str(exc)) from exc
        train, contexts, targets, corpus_hash = benchmark.private_data(spec)
        result["corpus_sha256"] = corpus_hash
        trial_root = Path(tempfile.mkdtemp(prefix="gaia-gpu-"))
        work, bundle = trial_root / "work", trial_root / "lab"
        work.mkdir()
        bundle.mkdir()
        (work / "tmp").mkdir()
        (work / "candidate.py").write_text(source)
        np.savez(work / "inputs.npz", train=train, contexts=contexts)
        request = {"uuid": cfg["cuda"]["device_uuid"], "vram_mb": limits["vram_mb"],
                   "isolated": bool(executable), "parent_host_pid": os.getpid(),
                   "parent_net_inode": os.stat("/proc/self/ns/net").st_ino,
                   "hidden_files": [str(Path(__file__).resolve().parents[1] / "data.py"), str(output)]}
        (work / "runtime.json").write_text(json.dumps(request))
        shutil.copyfile(Path(__file__).with_name("worker.py"), bundle / "worker.py")
        shutil.copyfile(Path(runtime.__file__), bundle / "runtime.py")
        result["stage"] = "startup"
        clock = time.monotonic()
        with (trial_root / "stderr.log").open("wb") as stderr:
            proc = subprocess.Popen(sandbox.command(executable, bundle, work, telemetry.minor),
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                    cwd=work, env=sandbox.environment(cfg["cuda"]["device_uuid"], work, bool(executable)),
                                    start_new_session=True, preexec_fn=limiter(limits["seconds"], 64))
        result["supervisor_pid"] = proc.pid
        watchdog = Watchdog(proc, trial_root, telemetry, limits, clock + limits["seconds"], stop_file)
        channel = Channel(proc, watchdog)
        ready = channel.recv()
        result["handshake"] = ready
        if ready.get("event") != "READY" or ready.get("runtime") != expected_runtime:
            raise ProtocolError("WORKER_RUNTIME_MISMATCH o READY inválido: " +
                                json.dumps(runtime.diff(expected_runtime, ready.get("runtime", {})))[:2000])
        if ready.get("input_fields") != ["contexts", "train"]:
            raise ProtocolError("Campos de datos del worker inválidos")
        result["stage"] = "init"
        channel.command("INIT", seed=spec.seed)
        result["t_init_s"] = time.monotonic() - clock
        result["worker_runtime"] = ready["runtime"]
        hits = 0

        def evaluate():
            nonlocal hits
            result["stage"] = "eval"
            t0 = time.monotonic()
            response = channel.command("PREDICT")
            result["t_eval_s"] += time.monotonic() - t0
            result["allocator_peak_mb"] = max(result.get("allocator_peak_mb", 0), response["allocator_peak_mb"])
            t0 = time.monotonic()
            path = work / "prediction.npy"
            if path.is_symlink() or path.stat().st_size > contexts.shape[0] * 256 * 4 + 4096:
                raise ProtocolError("Archivo de logits inválido o demasiado grande")
            logits = np.load(path, allow_pickle=False)
            loss = benchmark.cross_entropy(logits, targets)
            result["t_metric_s"] += time.monotonic() - t0
            result["curve"].append({"step": result["steps"], "loss": loss,
                                    "logits_sha256": hashlib.sha256(logits.tobytes()).hexdigest()})
            result["final_loss"] = loss
            if spec.target_loss is not None:
                hits = hits + 1 if loss <= spec.target_loss else 0
                result["reached"] = hits >= spec.hits_needed
            watchdog.check(force=True)

        evaluate()
        while result["steps"] < spec.steps and not result["reached"]:
            n = min(spec.eval_every, spec.steps - result["steps"])
            result["stage"] = "train"
            t0 = time.monotonic()
            channel.command("TRAIN", steps=n)
            result["t_train_s"] += time.monotonic() - t0
            result["steps"] += n
            evaluate()
        if not watchdog.gpu_seen:
            raise MonitorError("NVML no observó el PID CUDA del worker")
        result["stage"] = "quit"
        proc.stdin.write(b'{"command":"QUIT"}\n')
        proc.stdin.flush()
        if channel.recv().get("event") != "BYE":
            raise ProtocolError("Cierre de protocolo inválido")
        if proc.wait(timeout=2) != 0:
            raise ProtocolError("Worker terminó con error tras QUIT")
        if protected != benchmark.identity():
            raise RuntimeError("LAB_INTEGRITY: laboratorio modificado durante trial")
        result.update(status="ok", valid=True, stage="complete")
        result["cost_s"] = sum(result[key] for key in ("t_init_s", "t_train_s", "t_eval_s", "t_metric_s"))
    except guard.GuardError as exc:
        result.update(status="invalid", error=str(exc))
    except LimitExceeded as exc:
        result.update(status="resource_limit", error=str(exc), resource=exc.resource)
    except MonitorError as exc:
        result.update(status="monitor_error", error=str(exc))
    except TimeoutError as exc:
        result.update(status="timeout", error=str(exc))
    except (KeyboardInterrupt, InterruptedError) as exc:
        result.update(status="stopped", error=str(exc))
    except WorkerError as exc:
        result.update(status="cuda_oom" if exc.code == "CUDA_OOM" else "worker_error", error=str(exc))
    except ProtocolError as exc:
        result.update(status="protocol_error", error=str(exc))
    except Exception as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            terminate(proc)
        except Exception as exc:
            result.update(status="cleanup_error", valid=False, error=str(exc))
        if watchdog:
            result.update(watchdog.metrics())
        if proc is not None:
            result["worker_returncode"] = proc.returncode
            for pipe in (proc.stdin, proc.stdout):
                if pipe:
                    pipe.close()
        if telemetry:
            try:
                telemetry.close()
            except Exception as exc:
                result.update(status="cleanup_error", valid=False, error=str(exc))
        if trial_root:
            stderr_path = trial_root / "stderr.log"
            if stderr_path.exists():
                shutil.copyfile(stderr_path, output / "stderr.log")
                with stderr_path.open("rb") as stream:
                    stream.seek(max(0, stderr_path.stat().st_size - 8192))
                    result["stderr_excerpt"] = stream.read().decode(errors="replace")
            shutil.rmtree(trial_root)
        result["wall_s"] = time.monotonic() - wall_start
        result["temporary_files_removed"] = trial_root is None or not trial_root.exists()
        if result["status"] != "ok":
            result.update(valid=False, cost_s=None)
        (output / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result
