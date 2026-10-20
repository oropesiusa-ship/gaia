"""Evaluador independiente.

- El PADRE mide todos los tiempos (reloj de pared alrededor de cada petición).
- El PADRE conoce las etiquetas de validación; el candidato nunca las ve.
- bwrap obligatorio, sin red, bundle RO, /work privado y RLIMIT adicionales.
"""
import json
import os
import resource
import select
import shutil
import subprocess
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

import numpy as np

from . import guard, runtime, task, sandbox

WORKER = Path(__file__).with_name("worker.py")
RAPL = Path("/sys/class/powercap/intel-rapl:0/energy_uj")


def _energy():
    try:
        return int(RAPL.read_text())
    except Exception:       # noqa: BLE001
        return None


class _Chan:
    def __init__(self, proc):
        self.p = proc
        self.buf = b""

    def send(self, line):
        self.p.stdin.write((line + "\n").encode())
        self.p.stdin.flush()

    def recv(self, timeout):
        end = time.perf_counter() + timeout
        fd = self.p.stdout.fileno()
        while b"\n" not in self.buf:
            left = end - time.perf_counter()
            if left <= 0:
                raise TimeoutError("el candidato no responde")
            r, _, _ = select.select([fd], [], [], left)
            if not r:
                continue
            chunk = os.read(fd, 4096)
            if not chunk:
                raise EOFError("el proceso candidato terminó")
            self.buf += chunk
            if len(self.buf) > 65536:
                raise RuntimeError("worker protocol exceeds 64 KiB")
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode(errors="replace")


def _torch_mode():
    return os.environ.get("GAIA_FP_TORCH") == "1"


def _limiter(ram_mb, cpu_s, as_limit=True):
    """as_limit=False para torch/CUDA: reserva mucho más espacio virtual que RAM real y RLIMIT_AS
    impediría hasta `import torch`. La RAM se vigila entonces por pico RSS (ver run_trial)."""
    def f():
        if as_limit:
            resource.setrlimit(resource.RLIMIT_AS, (ram_mb * 2**20, ram_mb * 2**20))
        resource.setrlimit(resource.RLIMIT_CPU, (int(cpu_s), int(cpu_s) + 2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 2**20, 64 * 2**20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.setsid()
    return f


def _peak_rss_mb(pid):
    try:
        for ln in Path(f"/proc/{pid}/status").read_text().splitlines():
            if ln.startswith("VmHWM:"):
                return int(ln.split()[1]) / 1024.0
    except Exception:       # noqa: BLE001
        pass
    return None


def run_trial(source, bench, task_name, data_seed, init_seed, cap_s, limits, tmp_root,
              target=None, max_batches=None, curve=False, check_only=False):
    """Ejecuta un candidato y devuelve un dict de métricas medidas por el padre."""
    spec = bench["tasks"][task_name]
    cal = bench["calibrated"].get(task_name, {})
    target = target if target is not None else cal.get("target", 2.0)
    max_batches = max_batches or bench["max_batches"]
    every, need = bench["eval_every"], bench["hits_needed"]
    res = {"status": "ok", "error": "", "reached": False, "cost_s": None, "t_init": 0.0,
           "t_train": 0.0, "t_eval": 0.0, "batches": 0, "final_acc": None,
           "peak_rss_mb": None, "energy_j": None, "wall_s": 0.0, "curve": [],
           "sandbox": False, "sandbox_backend": "bwrap", "sandbox_validation": False,
           "promotable": False, "reason": None, "sandbox_evidence": {}}
    t_wall = time.perf_counter()
    try:
        guard.check_source(source)
    except guard.GuardError as e:
        res.update(status="invalid", error=str(e))
        return res
    Xtr, ytr, Xva, yva = task.make_dataset(spec, data_seed)
    Path(tmp_root).mkdir(parents=True, exist_ok=True)
    trial_root = Path(tempfile.mkdtemp(dir=tmp_root, prefix="trial_"))
    wd = trial_root / "work"
    wd.mkdir()
    running = None
    stack = ExitStack()
    try:
        np.savez(trial_root / "data.npz", Xtr=Xtr, ytr=ytr, Xva=Xva, k=spec["k"])
        bundle = trial_root / "bundle"
        hashes = sandbox.bundle_files(bundle, WORKER, source, trial_root / "data.npz")
        hidden = [Path(__file__).resolve(), Path(tmp_root).resolve().parent / "stable",
                  Path(tmp_root).resolve().parent / "provenance"]
        if Path(tmp_root).name == "tmp":
            hidden.append(Path(tmp_root).resolve().parent)
        session = sandbox.launch(bundle, wd, hashes, limits, _limiter, hidden_paths=hidden)
        # ExitStack owns launch even if protocol validation or a trial fails.
        running = stack.enter_context(session)
        proc = running.proc
        ch = _Chan(proc)
        slack = limits["max_experiment_seconds"] + 10
        res["sandbox_evidence"] = running.evidence
        running.verify(ch, slack)
        res.update(sandbox=True, sandbox_validation=True)
        ready = ch.recv(slack)
        if not ready.startswith("READY"):
            raise RuntimeError(ready)
        wfp = json.loads(ready[6:])
        pfp = runtime.fingerprint(with_torch=False)
        res["worker_fp"] = runtime.digest(wfp)
        if wfp != pfp:
            raise RuntimeError("WORKER_RUNTIME_MISMATCH " + json.dumps(runtime.diff(pfp, wfp))[:400])
        if check_only:
            ch.send("CHECK")
            reply = ch.recv(slack)
            if not reply.startswith("CHECKED "):
                raise RuntimeError("Invalid correctness reply: " + reply[:300])
            res["correctness"] = json.loads(reply[len("CHECKED "):])
            ch.send("QUIT")
            if ch.recv(slack) != "BYE" or proc.wait(timeout=5) != 0:
                raise RuntimeError("Correctness worker did not exit cleanly")
            res["promotable"] = True
            return res
        t0 = time.perf_counter()
        ch.send(f"INIT {int(init_seed)}")
        r = ch.recv(slack)
        res["t_init"] = time.perf_counter() - t0
        if r != "OK":
            raise RuntimeError(r)
        hits, first_t, done = 0, None, 0
        while True:
            e0 = _energy()
            t0 = time.perf_counter()
            ch.send(f"STEPS {every}")
            r = ch.recv(slack)
            dt = time.perf_counter() - t0
            e1 = _energy()
            if e0 is not None and e1 is not None and e1 >= e0:
                res["energy_j"] = (res["energy_j"] or 0.0) + (e1 - e0) / 1e6
            if r != "OK":
                raise RuntimeError(r)
            res["t_train"] += dt
            done += every
            t0 = time.perf_counter()
            ch.send("PRED")
            r = ch.recv(slack)
            res["t_eval"] += time.perf_counter() - t0
            if r != "OK":
                raise RuntimeError(r)
            pred_path = wd / "pred.npy"
            if pred_path.is_symlink() or pred_path.stat().st_size > len(yva) * 8 + 4096:
                raise ValueError("Invalid prediction file")
            pred = np.load(pred_path, allow_pickle=False)
            if pred.shape != (len(yva),) or not np.issubdtype(pred.dtype, np.integer):
                raise ValueError("predict() debe devolver un vector de clases enteras")
            acc = float((pred == yva).mean())
            res["final_acc"] = acc
            if curve:
                res["curve"].append([round(res["t_train"], 4), done, round(acc, 4)])
            if acc >= target:
                hits += 1
                if hits == 1:
                    first_t = res["t_train"]
                if hits >= need:
                    res["reached"] = True
                    res["cost_s"] = res["t_init"] + first_t
                    break
            else:
                hits = 0
                first_t = None
            if res["t_train"] > cap_s or done >= max_batches:
                break
        res["batches"] = done
        res["peak_rss_mb"] = _peak_rss_mb(running.evidence["worker_host_pid"])
        ch.send("QUIT")
        if ch.recv(slack) != "BYE" or proc.wait(timeout=5) != 0:
            raise RuntimeError("Worker did not exit cleanly")
        res["promotable"] = True
    except sandbox.SandboxError as e:
        stderr = (trial_root / "stderr.txt").read_text(errors="replace")[-500:] if (trial_root / "stderr.txt").exists() else ""
        res.update(status="invalid", reason=e.code, error=str(e) + (" | " + stderr if stderr else ""), promotable=False,
                   sandbox_validation=False, reached=False, cost_s=None)
    except (TimeoutError, subprocess.TimeoutExpired) as e:
        res.update(status="timeout", error=str(e))
    except OSError as e:
        if not res["sandbox_validation"]:
            res.update(status="invalid", reason="SANDBOX_UNAVAILABLE", error=str(e))
        else:
            res.update(status="error", error=str(e))
    except (EOFError, RuntimeError, ValueError) as e:
        msg = str(e)
        try:
            msg += " | " + (trial_root / "stderr.txt").read_text()[-300:].replace("\n", " ")
        except Exception:   # noqa: BLE001
            pass
        res.update(status="error", error=msg[:500])
    finally:
        try:
            stack.close()
        except (OSError, subprocess.TimeoutExpired) as e:
            res.update(status="error", reason="SANDBOX_VIOLATION", sandbox_validation=False,
                       error="sandbox cleanup: " + str(e))
        if res["status"] != "ok":
            res.update(promotable=False, reached=False, cost_s=None)
        shutil.rmtree(trial_root, ignore_errors=True)
        res["wall_s"] = time.perf_counter() - t_wall
    return res


def check_correctness(source, limits=None, include_evidence=False):
    """Same G1 numerical/sampler checks, now executed by the sandbox worker."""
    spec = {"d": 6, "teacher_hidden": 8, "k": 3, "teacher_gain": 2.0, "noise": 0.3,
            "teacher_seed": 7, "data_salt": 11, "n_train": 100, "n_val": 30}
    bench = {"tasks": {"main": spec}, "calibrated": {}, "max_batches": 1,
             "eval_every": 1, "hits_needed": 1}
    limits = limits or {"max_ram_mb": 3000, "max_experiment_seconds": 20, "worker_threads": 1}
    with tempfile.TemporaryDirectory(prefix="gaia-correctness-") as tmp:
        result = run_trial(source, bench, "main", 0, 0, 20, limits, tmp, check_only=True)
    if result["status"] != "ok" or not result["sandbox_validation"]:
        raise RuntimeError("CPU correctness sandbox failed: " + result["error"])
    return result if include_evidence else result["correctness"]
