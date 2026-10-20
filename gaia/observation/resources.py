"""Resource samples with explicit process/system scopes and interval CPU counters."""
import os
import resource
import sys
import time

from .host import filesystem
from .local import memory, text
from .stability import summarize


def snapshot(root, start_wall, start_cpu, previous=None):
    now, cpu = time.perf_counter(), time.process_time()
    mem = memory()
    status = {key: int(rest.split()[0]) * 1024
              for line in text("/proc/self/status").splitlines() if ":" in line
              for key, rest in [line.split(":", 1)] if key in ("VmRSS", "VmHWM")}
    line = text("/proc/stat").splitlines()
    ticks = [int(x) for x in line[0].split()[1:9]] if line and line[0].startswith("cpu ") else []
    total, idle = sum(ticks), sum(ticks[i] for i in (3, 4)) if len(ticks) > 4 else 0
    delta = total - previous[0] if previous else 0
    used = 100 * (1 - (idle - previous[1]) / delta) if delta > 0 else None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    storage = filesystem(root)
    value = {"wall_s": now - start_wall, "process_cpu_s": cpu - start_cpu,
             "process_rss_bytes": status.get("VmRSS"), "process_lifetime_peak_rss_bytes": status.get("VmHWM", peak),
             "system_ram_available_bytes": mem.get("MemAvailable"), "swap_available_bytes": mem.get("SwapFree"),
             "system_cpu_utilization_percent": used, "filesystem_free_bytes": storage["free_bytes"],
             "filesystem_available_bytes": storage["available_bytes"],
             "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None}
    return value, (total, idle)


def collect(root, count, interval_ms, cv_threshold, deadline):
    start, cpu = time.perf_counter(), time.process_time()
    samples, previous = [], None
    for index in range(count):
        if time.perf_counter() >= deadline:
            break
        if index:
            time.sleep(min(interval_ms / 1000, max(0, deadline - time.perf_counter())))
        sample, previous = snapshot(root, start, cpu, previous)
        if samples:
            elapsed = sample["wall_s"] - samples[-1]["wall_s"]
            sample["process_cpu_utilization_percent"] = 100 * (sample["process_cpu_s"] - samples[-1]["process_cpu_s"]) / elapsed if elapsed else None
        else:
            sample["process_cpu_utilization_percent"] = None
        samples.append(sample)
    metrics = {key: summarize([s[key] for s in samples], cv_threshold)
               for key in samples[0] if key != "load_average"} if samples else {}
    return {"status": "AVAILABLE" if samples else "UNAVAILABLE", "samples": samples,
            "statistics": metrics, "scope": "observer process and host; not workload process",
            "duration_s": time.perf_counter() - start}
