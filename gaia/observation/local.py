"""Bounded local reads and commands. Errors never persist arbitrary stderr/paths."""
from pathlib import Path
import subprocess


def text(path):
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def command(args, timeout=2):
    try:
        # Child collectors receive an allowlist, never the user's environment.
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/nonexistent"}
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def unavailable(collector, reason="local_interface_unavailable", status="UNAVAILABLE"):
    return {"status": status, "collector": collector, "reason": reason, "nonfatal": True}


def existing_parent(path):
    path = Path(path).resolve()
    while not path.exists():
        path = path.parent
    return path


def memory():
    wanted = {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}
    return {key: int(rest.split()[0]) * 1024
            for line in text("/proc/meminfo").splitlines() if ":" in line
            for key, rest in [line.split(":", 1)] if key in wanted}
