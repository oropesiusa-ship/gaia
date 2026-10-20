"""Guest-only test publisher and health-gated boot counter commitment.

Not exposed to the agent catalogue. Physical installation remains a separate
human-authorized operation; this module accepts explicit VM lab profiles only.
"""
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys


def run(args):
    return subprocess.check_output(args, text=True, timeout=60)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def context(scenario):
    args = dict(p.split("=", 1) for p in Path("/proc/cmdline").read_text().split() if "=" in p)
    if os.geteuid() != 0 or args.get("gaia.lab") != "1" or args.get("gaia.scenario") != scenario:
        raise ValueError("Operation requires the selected privileged lab evaluator")
    return args


def mount_esp():
    esp = Path("/run/gaia-transaction-esp")
    esp.mkdir(mode=0o700)
    device = Path("/dev/disk/by-label/GAIA-ESP")
    if not device.is_block_device():
        raise ValueError("Missing lab ESP")
    run(["/usr/bin/mount", "-o", "nodev,nosuid,noexec,umask=0077", str(device), str(esp)])
    return esp


def flush(path):
    # syncfs provides a filesystem-wide barrier for FAT directory metadata.
    run(["/usr/bin/sync", "-f", str(path)])


def publication_child():
    context("publication-interrupted")
    source = Path("/run/gaia-transaction-esp/EFI/GAIA/gaia-b.efi")
    temporary = source.with_name("gaia-b-next.efi.tmp")
    with source.open("rb") as src, temporary.open("xb") as dst:
        dst.write(src.read(256 * 1024))
        dst.flush()
        os.fsync(dst.fileno())
        print("GAIA_PUBLICATION_PARTIAL_READY", flush=True)
        # The parent intentionally kills the actual writer at this checkpoint.
        sys.stdin.buffer.read(1)
        raise ValueError("Lab publisher must be interrupted at its checkpoint")


def interrupted_publication(sequence):
    context("publication-interrupted")
    esp = mount_esp()
    try:
        stable = esp / "EFI/GAIA/gaia-a.efi"
        candidate = esp / "EFI/GAIA/gaia-b.efi"
        partial = esp / "EFI/GAIA/gaia-b-next.efi.tmp"
        a_hash, b_hash = digest(stable), digest(candidate)
        if sequence == 1:
            process = subprocess.Popen(["/opt/gaia/venv/bin/python", "-I", "/core/boot_transaction.py", "--publication-child"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                readable, _, _ = select.select([process.stdout], [], [], 15)
                if not readable or process.stdout.readline().strip() != b"GAIA_PUBLICATION_PARTIAL_READY":
                    raise ValueError("Publisher did not reach the injection checkpoint")
                process.kill()
                if process.wait(timeout=10) != -signal.SIGKILL:
                    raise ValueError("Publisher was not killed at the checkpoint")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
        elif sequence != 2:
            raise ValueError("Unexpected publication test boot sequence")
        if (not partial.is_file() or partial.stat().st_size != 256 * 1024
                or digest(stable) != a_hash or digest(candidate) != b_hash):
            raise ValueError("Interrupted writer changed an active UKI")
        if any("next" in entry.name for entry in (esp / "loader/entries").glob("*.conf")):
            raise ValueError("Partially published image became selectable")
        flush(esp)
        return {"status": "INTERRUPTED_PUBLICATION_SAFE", "sequence": sequence,
            "writer_sigkill_injected": sequence == 1, "partial_bytes": partial.stat().st_size,
            "active_a_sha256": a_hash, "active_b_sha256": b_hash}
    finally:
        run(["/usr/bin/umount", str(esp)])


def bless_healthy(sequence):
    args = context("health-bless")
    if args["gaia.slot"] != "B":
        raise ValueError("Only the lab candidate B can be blessed")
    esp = mount_esp()
    try:
        entries = esp / "loader/entries"
        counted = list(entries.glob("gaia-b+*.conf"))
        stable = entries / "gaia-b.conf"
        if sequence == 1:
            if len(counted) != 1 or counted[0].name != "gaia-b+2-1.conf" or stable.exists():
                raise ValueError("Unexpected candidate boot counter before health commitment")
            # main probe calls this only after integrity, offline, DATA, catalogue
            # and non-root model checks have all passed for this CPU profile.
            os.replace(counted[0], stable)
            flush(esp)
        elif sequence == 2:
            if counted or not stable.is_file():
                raise ValueError("Healthy candidate was not retained across reboot")
        else:
            raise ValueError("Unexpected health commitment sequence")
        return {"status": "HEALTHY_CANDIDATE_COMMITTED", "sequence": sequence,
                "candidate_entry": stable.name, "profile": "vm-cpu-l0"}
    finally:
        run(["/usr/bin/umount", str(esp)])


if __name__ == "__main__":
    if sys.argv[1:] != ["--publication-child"]:
        raise SystemExit("Internal lab publisher only")
    publication_child()
