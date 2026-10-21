"""Qualification-specific bwrap boundary; stable CPU evolution sandbox is untouched."""
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys


def command(runtime_dir, work, argv, *, model=None, gpu=False, worker=None, support=None):
    args = ["bwrap", "--die-with-parent", "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc", "--unshare-uts", "--cap-drop", "ALL"]
    for path in ("/usr", "/lib", "/lib64"):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    if Path('/etc/ld.so.cache').exists():
        args += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
    args += ["--proc", "/proc", "--remount-ro", "/proc", "--dev", "/dev"]
    if gpu:
        for path in ("/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-uvm", "/dev/nvidia-uvm-tools", "/dev/dri/renderD128"):
            if Path(path).exists():
                args += ["--dev-bind", path, path]
    args += ["--tmpfs", "/tmp", "--ro-bind", str(Path(runtime_dir).resolve()), "/runtime", "--bind", str(Path(work).resolve()), "/work", "--chdir", "/work"]
    if model:
        args += ["--dir", "/models", "--ro-bind", str(Path(model).resolve()), "/models/model.gguf"]
    if worker:
        args += ["--ro-bind", str(Path(worker).resolve()), "/worker.py"]
    if support:
        args += ["--ro-bind", str(Path(support).resolve()), "/support"]
    args += ["--remount-ro", "/", *argv]
    return args


def limits(ram_bytes, seconds):
    def apply():
        os.setsid()
        resource.setrlimit(resource.RLIMIT_AS, (ram_bytes, ram_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 2))
        # Official self-contained runtimes extract bounded shared objects into
        # private /tmp; the artifact/extraction budgets are enforced separately.
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 2**20, 1024 * 2**20))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def run(runtime_dir, work, argv, budget, *, timeout=30, model=None, gpu=False, worker=None):
    cmd = command(runtime_dir, work, argv, model=model, gpu=gpu, worker=worker)
    env = {"PATH": "/usr/bin:/bin", "HOME": "/work", "TMPDIR": "/tmp", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
           "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "NO_PROXY": "*", "OMP_NUM_THREADS": str(budget["threads"])}
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                               preexec_fn=limits(budget["worker_ram_bytes"], int(timeout) + 5))
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        return {"status": "TIMEOUT", "returncode": process.returncode, "stdout": stdout.decode(errors="replace")[:100000], "stderr": stderr.decode(errors="replace")[-10000:]}
    return {"status": "OK" if process.returncode == 0 else "FAILED", "returncode": process.returncode,
            "stdout": stdout.decode(errors="replace")[:100000], "stderr": stderr.decode(errors="replace")[-10000:]}
