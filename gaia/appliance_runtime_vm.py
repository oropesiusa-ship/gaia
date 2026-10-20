"""Internal host runner: verify persistent readiness then stop only its QEMU."""
import argparse
import json
from pathlib import Path
import re
import socket
import subprocess
import time


def readiness(text):
    # A console line is streamed in fragments; inner JSON objects can close
    # before the complete outer record has arrived. Never parse a partial line.
    values = []
    for line in text.splitlines(keepends=True):
        if not line.endswith("\n"):
            continue
        match = re.search(r"GAIA_RUNTIME_READY=(\{[^\r\n]*\})", line)
        if match:
            values.append(json.loads(match[1]))
    if len(values) > 1:
        raise ValueError("Ambiguous runtime readiness")
    return values[0] if values else None


def run(spec):
    serial, errors = Path(spec["serial"]), Path(spec["errors"])
    qmp = Path(spec["qmp"])
    started = time.monotonic()
    result = None
    with serial.open("xb") as output, errors.open("xb") as stderr:
        proc = subprocess.Popen(spec["command"], stdout=output, stderr=stderr, stdin=subprocess.DEVNULL)
        try:
            while time.monotonic() - started < 180:
                if proc.poll() is not None:
                    raise ValueError("Runtime VM powered off/exited before readiness")
                text = serial.read_text(errors="replace")
                result = readiness(text)
                if result is not None:
                    if (result.get("status") != "GAIA_RUNTIME_READY" or result.get("authority") != "L0"
                            or result["runtime"]["uid"] == 0 or result["runtime"]["status"] != "PINNED_RUNTIME_CPU_OK"
                            or result["owner_public_trust"]["status"] != "OWNER_PUBLIC_SIGNATURE_OK"):
                        raise ValueError("Persistent runtime did not pass readiness gates")
                    break
                time.sleep(0.2)
            else:
                raise ValueError("Persistent runtime readiness deadline exceeded")
            # Prove the normal service remains alive rather than auto-poweroff.
            time.sleep(10)
            if proc.poll() is not None:
                raise ValueError("Runtime did not stay active after readiness")
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(5)
                connection.connect(str(qmp))
                stream = connection.makefile("rwb", buffering=0)
                json.loads(stream.readline())
                for index, execute in enumerate(("qmp_capabilities", "quit")):
                    stream.write(json.dumps({"execute": execute, "id": index}).encode() + b"\n")
                    while True:
                        response = json.loads(stream.readline())
                        if response.get("id") == index:
                            if "error" in response:
                                raise ValueError("QMP rejected controlled test shutdown")
                            break
                stream.close()
            proc.wait(timeout=15)
            result["persistent_after_ready_seconds"] = 10
            result["test_shutdown"] = "host QMP quit after committed readiness; not a physical power-loss qualification"
            print(json.dumps(result), flush=True)
            return result
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", type=Path)
    options = parser.parse_args()
    run(json.loads(options.spec.read_text()))
