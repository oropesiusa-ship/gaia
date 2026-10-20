"""Unprivileged hardware/OS facts; no hostnames, accounts or network identifiers."""
import os
from pathlib import Path
import platform

from .local import existing_parent, memory, text


def filesystem(path):
    path = existing_parent(path)
    stat = os.statvfs(path)
    best, kind = -1, None
    for line in text("/proc/self/mountinfo").splitlines():
        fields = line.split()
        if "-" not in fields or len(fields) < 6:
            continue
        mount = fields[4].replace("\\040", " ")
        if path.is_relative_to(mount) and len(mount) > best:
            best, kind = len(mount), fields[fields.index("-") + 1]
    return {"type": kind, "total_bytes": stat.f_blocks * stat.f_frsize,
            "free_bytes": stat.f_bfree * stat.f_frsize,
            "available_bytes": stat.f_bavail * stat.f_frsize}


def collect(root, state):
    blocks = []
    for block in text("/proc/cpuinfo").split("\n\n"):
        fields = {key.strip(): val.strip() for line in block.splitlines() if ":" in line
                  for key, val in [line.split(":", 1)]}
        if fields:
            blocks.append(fields)
    cpu = blocks[0] if blocks else {}
    cores = {(b["physical id"], b["core id"]) for b in blocks if "physical id" in b and "core id" in b}
    flags = [set(b.get("flags", b.get("Features", "")).split()) for b in blocks]
    caches = []
    for directory in sorted(Path("/sys/devices/system/cpu/cpu0/cache").glob("index*")):
        caches.append({key: text(directory / key) or None
                       for key in ("level", "type", "size", "coherency_line_size", "shared_cpu_list")})
    frequency = {key: text(Path("/sys/devices/system/cpu/cpu0/cpufreq") / key) or None
                 for key in ("cpuinfo_min_freq", "cpuinfo_max_freq", "base_frequency")}
    mem = memory()
    try:
        distro = platform.freedesktop_os_release()
    except OSError:
        distro = {}
    source, storage = filesystem(root), filesystem(state)
    return {
        "cpu": {"vendor": cpu.get("vendor_id", cpu.get("CPU implementer")),
                "model": cpu.get("model name", cpu.get("Hardware")), "architecture": platform.machine(),
                "physical_cores": len(cores) or None, "logical_cores": os.cpu_count(),
                "effective_cpus": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                "instruction_flags": sorted(set.intersection(*flags)) if flags else [],
                "flags_scope": "intersection_of_visible_processors", "caches_cpu0": caches,
                "frequency_khz": frequency},
        "ram": {"total_bytes": mem.get("MemTotal"), "page_size_bytes": os.sysconf("SC_PAGE_SIZE"),
                "swap_total_bytes": mem.get("SwapTotal")},
        "storage": {"source": {k: v for k, v in source.items() if k in ("type", "total_bytes")},
                    "state": {k: v for k, v in storage.items() if k in ("type", "total_bytes")},
                    "source_state_same_filesystem": os.stat(existing_parent(root)).st_dev == os.stat(existing_parent(state)).st_dev,
                    "source_archive_same_filesystem": os.stat(existing_parent(root)).st_dev == os.stat(existing_parent(Path(root) / "archives")).st_dev},
        "os": {"system": platform.system(), "kernel": platform.release(), "architecture": platform.machine(),
               "distro": {k: distro[k] for k in ("ID", "VERSION_ID") if k in distro},
               "libc": list(platform.libc_ver())}}
