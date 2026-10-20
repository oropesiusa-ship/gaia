"""G0 — huella del runtime. Solo biblioteca estándar (+ numpy/torch si existen).

El padre y el worker calculan la MISMA huella; si difiere, el trial no vale
(p. ej. el worker `-I` cargando otro site-packages / otro PyTorch que el padre).
"""
import hashlib
import json
import os
import platform
import sys


def fingerprint(with_torch=False):
    fp = {
        "python": sys.version.split()[0],
        "executable": os.path.realpath(sys.executable),
        "prefix": os.path.realpath(sys.prefix),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }
    try:
        import numpy
        fp["numpy"] = numpy.__version__
        fp["numpy_file"] = os.path.realpath(numpy.__file__)
    except ImportError:
        fp["numpy"] = None
    fp["torch"] = None
    if with_torch:
        try:
            import torch
            t = {"version": torch.__version__, "cuda": torch.version.cuda,
                 "file": os.path.realpath(torch.__file__), "cuda_available": torch.cuda.is_available()}
            if t["cuda_available"]:
                t["arch_list"] = list(torch.cuda.get_arch_list())
                t["device"] = torch.cuda.get_device_name(0)
                t["capability"] = list(torch.cuda.get_device_capability(0))
            fp["torch"] = t
        except Exception as e:      # noqa: BLE001
            fp["torch"] = {"error": repr(e)[:200]}
    return fp


def digest(fp):
    return hashlib.sha256(json.dumps(fp, sort_keys=True).encode()).hexdigest()[:16]


def diff(a, b):
    return {k: (a.get(k), b.get(k)) for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def arch_supports(arch_list, capability):
    """¿Algún binario (sm_XY) de la lista corre en una GPU con esa capability? Regla de cubin:
    misma versión mayor y menor <= la de la GPU (sm_60 sirve para 6.1; sm_75 NO sirve para 6.1)."""
    cc = capability[0] * 10 + capability[1]
    for a in arch_list or []:
        if a.startswith("sm_") and a[3:].isdigit():
            n = int(a[3:])
            if n // 10 == cc // 10 and n <= cc:
                return True
    return False
