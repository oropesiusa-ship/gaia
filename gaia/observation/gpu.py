"""Optional passive GPU discovery. Never imports Torch or starts a GPU workload."""
import csv
import ctypes.util
from pathlib import Path
import shutil

from .local import command, text


def collect():
    devices = []
    for path in sorted(Path("/sys/class/drm").glob("card[0-9]*/device")):
        if not path.name == "device":
            continue
        device = {"vendor_id": text(path / "vendor"), "device_id": text(path / "device")}
        if device not in devices:
            devices.append(device)
    binary = shutil.which("nvidia-smi")
    rows = command([binary, "--query-gpu=name,memory.total,memory.free,driver_version,compute_cap",
                    "--format=csv,noheader,nounits"], timeout=3) if binary else None
    nvidia = []
    if rows:
        for row in csv.reader(rows.splitlines()):
            if len(row) != 5:
                continue
            name, total, free, driver, compute = [x.strip() for x in row]
            nvidia.append({"vendor": "NVIDIA", "model": name,
                           "vram_total_bytes": int(float(total) * 2**20) if total.replace(".", "", 1).isdigit() else None,
                           "vram_available_bytes": int(float(free) * 2**20) if free.replace(".", "", 1).isdigit() else None,
                           "driver": driver, "compute_capability": compute})
    return {"status": "AVAILABLE" if nvidia or devices else "UNAVAILABLE",
            "device_count": len(nvidia) if nvidia else len(devices), "devices": nvidia or devices,
            "usable_gpu": True if nvidia else None if devices else False,
            "cuda_runtime_detected": bool(ctypes.util.find_library("cudart")),
            "nvml": "AVAILABLE" if ctypes.util.find_library("nvidia-ml") else "UNAVAILABLE",
            "nvidia_metrics": "AVAILABLE" if nvidia else "UNAVAILABLE",
            "torch_cuda_available": "UNKNOWN", "framework_probe": "not_executed",
            "campaign_status": "FROZEN"}
