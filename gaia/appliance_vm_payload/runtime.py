"""Persistent L0 runtime candidate; readiness does not enable L2 actions."""
import json
import os
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, "/core")
from public_trust import custody_check
from runtime_checks import cpu_smoke, cuda_smoke


def main():
    process = Path("/proc/self/status").read_text()
    if "NoNewPrivs:\t1" not in process or "CapEff:\t0000000000000000" not in process:
        raise ValueError("Runtime privilege boundaries missing")
    proof = custody_check()
    smoke = cpu_smoke()
    profile = json.loads(Path("/core/runtime-profile.json").read_text())
    if profile["execution_profile"] == "cuda":
        smoke["gpu"] = cuda_smoke(profile["driver"])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        for attempt in range(50):
            try:
                connection.connect("/run/gaia/control.sock")
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if attempt == 49:
                    raise
                time.sleep(0.1)
        connection.sendall(b'{"action":"inventory"}\n')
        result = json.loads(connection.makefile("rb").readline(4096))
    if result.get("status") != "ok":
        raise ValueError("Guardian did not accept L0 inventory")
    cmdline = dict(part.split("=", 1) for part in Path("/proc/cmdline").read_text().split() if "=" in part)
    status = {"status": "GAIA_RUNTIME_READY", "profile": profile["name"], "authority": "L0",
              "slot": cmdline["gaia.slot"],
              "inventory": result["inventory"], "ledger_sequence": result["sequence"],
              "owner_public_trust": proof, "runtime": smoke, "private_key_used": False}
    target = Path("/data/agent/runtime-status.json")
    temporary = target.with_suffix(".json.tmp")
    with temporary.open("w") as stream:
        json.dump(status, stream)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    print("GAIA_RUNTIME_READY=" + json.dumps(status), flush=True)
    # Stay alive offline; there is no automatic package installation or privilege
    # escalation. Host Lab benchmark/experiments remain separate phase gates.
    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()
