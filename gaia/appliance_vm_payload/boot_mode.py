"""Root selects a fixed service; no command string or agent-supplied operation."""
import os
from pathlib import Path
import subprocess

args = dict(p.split("=", 1) for p in Path("/proc/cmdline").read_text().split() if "=" in p)
if os.geteuid() != 0:
    raise SystemExit("Boot dispatcher requires the init service")
mode = args.get("gaia.mode", "runtime")
if mode == "vm-test" and args.get("gaia.lab") == "1":
    service = "gaia-vm-probe.service"
elif mode == "runtime":
    service = "gaia-runtime.service"
else:
    raise SystemExit("Unknown boot mode")
subprocess.run(["/usr/bin/systemctl", "--no-block", "start", service], check=True)
