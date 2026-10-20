"""Supervisión del padre: NVML por PID, /proc y disco; no importa Torch."""
import ctypes as C
import os
from pathlib import Path
import signal
import time


class MonitorError(RuntimeError):
    pass


class LimitExceeded(RuntimeError):
    def __init__(self, resource, observed, limit):
        self.resource, self.observed, self.limit = resource, observed, limit
        super().__init__(f"{resource}: observado {observed:.2f} > límite {limit:.2f}")


class ProcessInfo(C.Structure):
    # ABI NVML ProcessInfo v2/v3: pid, memoria, instancias MIG.
    _fields_ = [("pid", C.c_uint), ("usedGpuMemory", C.c_ulonglong),
                ("gpuInstanceId", C.c_uint), ("computeInstanceId", C.c_uint)]


class NVML:
    def __init__(self, uuid):
        self.lib = C.CDLL("libnvidia-ml.so.1")
        self.lib.nvmlErrorString.restype = C.c_char_p
        self._check(self.lib.nvmlInit_v2())
        self.handle = C.c_void_p()
        try:
            self._check(self.lib.nvmlDeviceGetHandleByUUID(uuid.encode(), C.byref(self.handle)))
            minor = C.c_uint()
            self._check(self.lib.nvmlDeviceGetMinorNumber(self.handle, C.byref(minor)))
            self.minor = minor.value
            self.query = getattr(self.lib, "nvmlDeviceGetComputeRunningProcesses_v3", None)
            if self.query is None:
                self.query = self.lib.nvmlDeviceGetComputeRunningProcesses_v2
            self.processes()  # Fallar antes de iniciar un candidato si no hay telemetría.
        except BaseException:
            self.close()
            raise

    def _check(self, code):
        if code:
            text = self.lib.nvmlErrorString(code).decode(errors="replace")
            raise MonitorError(f"NVML {code}: {text}")

    def processes(self):
        # Reintentos acotados si otro proceso CUDA aparece entre las dos llamadas.
        for _ in range(3):
            count = C.c_uint(0)
            code = self.query(self.handle, C.byref(count), None)
            if code == 0:
                return {}
            if code != 7:  # NVML_ERROR_INSUFFICIENT_SIZE
                self._check(code)
            size = count.value * 2 + 8
            rows = (ProcessInfo * size)()
            count.value = size
            code = self.query(self.handle, C.byref(count), rows)
            if code == 7:
                continue
            self._check(code)
            result = {}
            for row in rows[:count.value]:
                if row.usedGpuMemory == 2**64 - 1:
                    raise MonitorError("NVML no informa memoria por proceso")
                result[row.pid] = row.usedGpuMemory / 2**20
            return result
        raise MonitorError("NVML cambió repetidamente el número de procesos")

    def close(self):
        self.lib.nvmlShutdown()


def descendants(pid):
    found, pending = set(), [pid]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        try:
            text = Path(f"/proc/{current}/task/{current}/children").read_text()
            pending.extend(int(value) for value in text.split())
        except (FileNotFoundError, ProcessLookupError):
            pass
    return found


def rss_mb(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    except (FileNotFoundError, ProcessLookupError):
        return 0.0
    return 0.0


def directory_mb(root):
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in files:
            try:
                total += (Path(directory) / name).lstat().st_size
            except FileNotFoundError:
                pass
    return total / 2**20


class Watchdog:
    def __init__(self, proc, directory, nvml, limits, deadline, stop_file=None):
        self.proc, self.directory, self.nvml = proc, directory, nvml
        self.limits, self.deadline, self.stop_file = limits, deadline, stop_file
        self.last_sample = 0.0
        self.peak_rss_mb = self.peak_vram_mb = self.peak_disk_mb = 0.0
        self.gpu_seen = False
        self.samples = 0
        self.pids = {proc.pid}

    def check(self, force=False):
        now = time.monotonic()
        if self.stop_file and self.stop_file.exists():
            raise InterruptedError("STOP solicitado")
        if now >= self.deadline:
            raise TimeoutError("Presupuesto de pared agotado por el padre")
        if not force and now - self.last_sample < 0.02:
            return
        self.last_sample = now
        self.pids = descendants(self.proc.pid)
        self.peak_rss_mb = max(self.peak_rss_mb, sum(rss_mb(pid) for pid in self.pids))
        gpu = self.nvml.processes()
        self.gpu_seen |= bool(self.pids & gpu.keys())
        self.peak_vram_mb = max(self.peak_vram_mb, sum(gpu.get(pid, 0) for pid in self.pids))
        self.peak_disk_mb = max(self.peak_disk_mb, directory_mb(self.directory))
        self.samples += 1
        for name, value in (("ram_mb", self.peak_rss_mb), ("vram_mb", self.peak_vram_mb), ("disk_mb", self.peak_disk_mb)):
            if value > self.limits[name]:
                raise LimitExceeded(name, value, self.limits[name])

    def metrics(self):
        return {"peak_rss_mb": self.peak_rss_mb, "peak_vram_nvml_mb": self.peak_vram_mb,
                "peak_disk_mb": self.peak_disk_mb, "monitor_samples": self.samples,
                "gpu_process_seen": self.gpu_seen, "sampling_interval_s": 0.02}


def terminate(proc):
    if proc is None or proc.poll() is not None:
        return
    for pid in descendants(proc.pid) - {proc.pid}:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    proc.wait(timeout=10)
