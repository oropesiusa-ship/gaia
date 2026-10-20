"""Fixed known numpy_mlp protocol via the unchanged protected evaluator/bwrap."""
import copy
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time

from ..provenance import digest
from .local import unavailable
from .stability import summarize
from .local import memory, text

PROTOCOL = {"id": "numpy_mlp_observation_v1", "workload": "numpy_mlp", "benchmark_profile": "easy",
            "task": "main", "data_seed": 9000, "init_seed": 9000, "max_batches": 300, "target": 2.0,
            "trainer": "G.render(G.BASELINE)", "purpose": "fixed-batch observation, not cost-to-target certification"}


def _monitor(stop, observed, cpu):
    """Sample descendants; CPU is an explicitly labelled lower bound, not rusage(bwrap)."""
    ticks = os.sysconf("SC_CLK_TCK")
    while not stop.is_set():
        pending = [os.getpid()]
        seen = set()
        rss = 0
        while pending:
            pid = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            for task in Path(f"/proc/{pid}/task").glob("*"):
                pending.extend(int(x) for x in text(task / "children").split())
            if pid == os.getpid():
                continue
            raw = text(f"/proc/{pid}/stat")
            if ") " in raw:
                fields = raw.rsplit(") ", 1)[1].split()
                if len(fields) >= 22:
                    # PID reuse is disambiguated by process start ticks.
                    key = (pid, fields[19])
                    cpu[key] = max(cpu.get(key, 0), (int(fields[11]) + int(fields[12])) / ticks)
                    rss += max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE")
        observed.append({"offset_s": time.perf_counter(), "descendant_rss_bytes": rss,
                         "descendant_cpu_s_lower_bound": sum(cpu.values()),
                         "system_ram_available_bytes": memory().get("MemAvailable")})
        stop.wait(0.01)


def _run(connection, limits):
    # Spawned process owns evaluator and temp files, keeping sampling isolated.
    from .. import genome as G
    from ..protected import benchmark, evaluator
    try:
        with tempfile.TemporaryDirectory(prefix="gaia-observation-") as tmp:
            start = time.process_time()
            observed, cpu = [], {}
            stop = threading.Event()
            monitor = threading.Thread(target=_monitor, args=(stop, observed, cpu), daemon=True)
            t0 = time.perf_counter()
            monitor.start()
            try:
                result = evaluator.run_trial(G.render(G.BASELINE), copy.deepcopy(benchmark.DEFAULT_SPEC),
                                             "main", 9000, 9000, limits["max_experiment_seconds"], limits, tmp,
                                             target=2.0, max_batches=300)
            finally:
                stop.set()
                monitor.join(timeout=1)
            for sample in observed:
                sample["offset_s"] -= t0
            # Allowlist only: no worker paths, exception messages or candidate authority.
            value = {key: result.get(key) for key in ("status", "wall_s", "t_init", "t_train", "t_eval",
                                                     "batches", "final_acc", "peak_rss_mb", "sandbox_validation")}
            value.update(evaluator_cpu_s=time.process_time() - start,
                         descendant_cpu_s_lower_bound=sum(cpu.values()), resource_samples=observed,
                         cpu_measurement_method="sampled_proc_descendants_10ms_lower_bound",
                         success=result["status"] == "ok" and result["sandbox_validation"] is True)
            if not value["success"]:
                value.update(reason="protected_trial_failed", nonfatal=True)
            connection.send(value)
    except Exception as exc:
        connection.send(unavailable("numpy_mlp", type(exc).__name__, "ERROR"))
    finally:
        connection.close()


def collect(cfg, count, cv_threshold, deadline, environment_identity):
    ctx = multiprocessing.get_context("spawn")
    samples = []
    start = time.perf_counter()
    for _ in range(count):
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            break
        receiver, sender = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_run, args=(sender, cfg["limits"]))
        process.start()
        sender.close()
        try:
            if receiver.poll(remaining):
                try:
                    samples.append(receiver.recv())
                except EOFError:
                    samples.append(unavailable("numpy_mlp", "worker_exited", "ERROR"))
            else:
                samples.append(unavailable("numpy_mlp", "observation_deadline", "ERROR"))
        finally:
            if process.is_alive():
                process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join()
            receiver.close()
        if not samples[-1].get("success"):
            break
    good = [s for s in samples if s.get("success")]
    metrics = {key: summarize([s[key] for s in good], cv_threshold)
               for key in ("wall_s", "t_train", "descendant_cpu_s_lower_bound", "evaluator_cpu_s", "peak_rss_mb", "final_acc")}
    return {"status": "AVAILABLE" if len(good) == count else "ERROR", "protocol": PROTOCOL,
            "protocol_hash": digest(PROTOCOL), "environment_identity": environment_identity,
            "requested_samples": count, "samples": samples, "statistics": metrics,
            "success_count": len(good), "duration_s": time.perf_counter() - start,
            "nonfatal": len(good) != count}
