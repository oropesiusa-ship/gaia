"""L0 VM foundation: fixed inventory operation and guardian-only evidence.

Not an L2 action catalogue or a production authorization service.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import struct


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def verify_ledger(path):
    previous = "0" * 64
    count = 0
    if path.exists():
        if path.stat().st_size > 256 * 1024:
            raise ValueError("Evidence budget exhausted")
        for line in path.read_bytes().splitlines():
            row = json.loads(line)
            digest = row.pop("sha256")
            if row["sequence"] != count + 1 or row["previous"] != previous:
                raise ValueError("Invalid evidence prefix")
            if hashlib.sha256(canonical(row)).hexdigest() != digest:
                raise ValueError("Invalid evidence hash")
            count += 1
            previous = digest
    return count, previous


def serve():
    agent = pwd.getpwnam("gaia").pw_uid
    ledger = Path("/data/evidence/ledger.jsonl")
    count, previous = verify_ledger(ledger)
    boot_requests = 0
    endpoint = Path("/run/gaia/control.sock")
    endpoint.unlink(missing_ok=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(endpoint))
        os.chmod(endpoint, 0o660)
        server.listen(4)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(2)
                try:
                    _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    raw = connection.makefile("rb").readline(4097)
                    request = json.loads(raw)
                    if uid != agent or len(raw) > 4096 or request != {"action": "inventory"}:
                        raise ValueError("Operation not in L0 catalogue")
                    if boot_requests >= 8 or ledger.exists() and ledger.stat().st_size > 250 * 1024:
                        raise ValueError("Evidence budget exhausted")
                    memory = int(Path("/proc/meminfo").read_text().splitlines()[0].split()[1])
                    profile_file = Path("/core/runtime-profile.json")
                    profile = json.loads(profile_file.read_text())["name"] if profile_file.is_file() else "vm-cpu-l0"
                    result = {"cpus": os.cpu_count(), "memory_kib": memory, "profile": profile}
                    row = {"sequence": count + 1, "previous": previous, "action": "inventory", "result": result}
                    digest = hashlib.sha256(canonical(row)).hexdigest()
                    row["sha256"] = digest
                    with ledger.open("ab") as stream:
                        stream.write(canonical(row) + b"\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    directory = os.open(ledger.parent, os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
                    count += 1
                    boot_requests += 1
                    previous = digest
                    response = {"status": "ok", "sequence": count, "sha256": digest, "inventory": result}
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    response = {"status": "denied", "reason": str(exc)}
                connection.sendall(canonical(response) + b"\n")


if __name__ == "__main__":
    serve()
