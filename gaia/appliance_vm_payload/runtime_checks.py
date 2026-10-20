"""Fixed eager CPU readiness check; no device tuning or model training."""
import os
import sys
import subprocess


def cpu_smoke():
    import bz2, ctypes, curses, dbm.gnu, lzma, readline, sqlite3, ssl, uuid, zlib
    from compression import zstd
    import numpy as np
    import torch
    if os.geteuid() == 0 or sys.version_info[:3] != (3, 14, 4):
        raise ValueError("Runtime must be the pinned non-root Python")
    dependencies = subprocess.check_output([sys.executable, "-I", "-m", "pip", "--isolated", "check"], text=True, timeout=30)
    links = subprocess.check_output(["/usr/bin/ldd", "/opt/gaia/python/bin/python3.14"], text=True, timeout=30)
    if "not found" in links:
        raise ValueError("Cleaned interpreter is missing a shared library")
    if np.__version__ != "2.3.5" or torch.__version__ != "2.14.0+cu126":
        raise ValueError("Runtime dependency version changed")
    sys.path.insert(0, "/opt/gaia/app")
    from gaia.gaia_transformer.model import GaiaTransformer
    torch.set_num_threads(1)
    torch.manual_seed(7)
    with torch.no_grad():
        model = GaiaTransformer().eval()
        tokens = torch.randint(256, (2, 16))
        logits, loss = model(tokens, tokens)
    if list(logits.shape) != [2, 16, 256] or not torch.isfinite(logits).all() or not torch.isfinite(loss):
        raise ValueError("Non-root causal CPU smoke failed")
    return {"status": "PINNED_RUNTIME_CPU_OK", "python": sys.version.split()[0], "uid": os.geteuid(),
            "torch": torch.__version__, "numpy": np.__version__, "cuda_runtime": torch.version.cuda,
            "openssl": ssl.OPENSSL_VERSION, "gpu_tested": False,
            "pip_check": dependencies.strip(), "interpreter_ldd": links}


def cuda_smoke(expected_driver):
    import torch
    driver = subprocess.check_output(["/usr/bin/nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                                     text=True, timeout=30).strip().splitlines()
    if driver != [expected_driver] or not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise ValueError("The physical CUDA profile requires one GPU and its exact fixed driver")
    capability = torch.cuda.get_device_capability(0)
    if capability not in ((6, 0), (6, 1), (6, 2)) or torch.cuda.get_device_properties(0).total_memory < 2 * 1024**3:
        raise ValueError("Physical CUDA profile requires a supported Pascal GPU")
    from gaia.gaia_transformer.model import GaiaTransformer
    torch.manual_seed(7)
    with torch.no_grad():
        model = GaiaTransformer().eval().cuda()
        tokens = torch.randint(256, (2, 16), device="cuda")
        logits, loss = model(tokens, tokens)
        torch.cuda.synchronize()
        if list(logits.shape) != [2, 16, 256] or not torch.isfinite(logits).all() or not torch.isfinite(loss):
            raise ValueError("Physical non-root CUDA GaiaTransformer smoke failed")
    return {"status": "PINNED_RUNTIME_CUDA_OK", "driver": driver[0], "gpu_tested": True,
            "name": torch.cuda.get_device_name(0), "capability": list(capability), "uid": os.geteuid()}
