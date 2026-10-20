"""Vista mínima bwrap: runtime RO, /work privado, GPU elegida, sin red ni padre."""
import os
from pathlib import Path
import shutil
import subprocess
import sys


def available():
    executable = shutil.which("bwrap")
    if not executable:
        return None, "bwrap no instalado"
    try:
        result = subprocess.run([executable, "--unshare-user", "--unshare-pid", "--unshare-net",
                                 "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev", "/usr/bin/true"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return executable, None
        return None, result.stderr[-2000:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)


def command(executable, bundle, work, minor):
    if not executable:
        return [sys.executable, "-I", str(bundle / "worker.py"), str(work)]
    args = [executable, "--die-with-parent", "--new-session", "--unshare-user", "--unshare-pid",
            "--unshare-net", "--unshare-ipc", "--unshare-uts", "--cap-drop", "ALL"]
    for path in ("/usr", "/lib", "/lib64", "/sys"):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    if Path("/etc/ld.so.cache").exists():
        args += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
    args += ["--proc", "/proc", "--dev", "/dev"]
    for path in (f"/dev/nvidia{minor}", "/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools"):
        if Path(path).exists():
            args += ["--dev-bind", path, path]
    args += ["--ro-bind", str(Path(sys.prefix)), str(Path(sys.prefix)),
             "--ro-bind", str(bundle), "/lab", "--bind", str(work), "/work",
             "--bind", str(work / "tmp"), "/tmp", "--chdir", "/work",
             sys.executable, "-I", "/lab/worker.py", "/work"]
    return args


def environment(uuid, work, isolated=True):
    home = "/work" if isolated else str(work)
    return {"PATH": "/usr/bin:/bin", "HOME": home, "TMPDIR": home + "/tmp", "PYTHONHASHSEED": "0",
            "CUDA_VISIBLE_DEVICES": uuid, "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUBLAS_WORKSPACE_CONFIG": ":4096:8",
            "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
