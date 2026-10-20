"""Guest-only logical DATA corruption/restore exercise on independent VM disk."""
import json
import os
from pathlib import Path
import pwd
import signal
import subprocess
import time

from data_backup import check_tree, digest, restore, snapshot, verify
from guardian import verify_ledger


def run(args):
    return subprocess.check_output(args, text=True, timeout=60)


def exercise():
    cmdline = dict(item.split("=", 1) for item in Path("/proc/cmdline").read_text().split() if "=" in item)
    if os.geteuid() != 0 or cmdline.get("gaia.lab") != "1" or cmdline.get("gaia.scenario") != "data-recovery":
        raise ValueError("DATA recovery exercise requires the explicit lab guest profile")
    devices = json.loads(run(["/usr/bin/lsblk", "--json", "--nodeps", "--bytes", "--output", "PATH,TYPE,SERIAL,SIZE"]))
    matches = [d for d in devices["blockdevices"] if d.get("serial") == "GAIA-LAB-BACKUP"]
    if len(matches) != 1 or matches[0]["type"] != "disk" or matches[0]["size"] != 512 * 1024 * 1024:
        raise ValueError("Independent VM backup device identity mismatch")
    device = Path(matches[0]["path"])
    if not device.is_block_device() or device.stat().st_rdev in {Path(p).stat().st_dev for p in ("/", "/core", "/data")}:
        raise ValueError("Backup must be a separate device")
    backup = Path("/run/gaia-data-backup")
    backup.mkdir(mode=0o700)
    run(["/usr/bin/mount", "-o", "nodev,nosuid,noexec", str(device), str(backup)])
    pid = None
    paused = False
    try:
        os.chown(backup, 0, 0)
        os.chmod(backup, 0o700)
        pid = int(run(["/usr/bin/systemctl", "show", "--property=MainPID", "--value", "gaia-guardian.service"]).strip())
        if pid <= 1:
            raise ValueError("Guardian is not running")
        # The lab has only the already-completed worker and guardian as writers.
        # Pause rather than stop the required service (which would stop the probe).
        os.kill(pid, signal.SIGSTOP)
        paused = True
        for _ in range(100):
            if any(line.startswith("State:") and "T" in line for line in Path(f"/proc/{pid}/status").read_text().splitlines()):
                break
            time.sleep(0.01)
        else:
            raise ValueError("Guardian writer did not pause")
        agent = pwd.getpwnam("gaia")
        guardian = pwd.getpwnam("gaia-guardian")
        roles = {"agent": {"uid": agent.pw_uid, "gids": [agent.pw_gid]},
                 "evidence": {"uid": guardian.pw_uid, "gids": [guardian.pw_gid, agent.pw_gid]}}
        source = Path("/data")
        fixture = source / "agent/recovery-fixture.bin"
        fixture.write_bytes(bytes(range(256)) * 1025)
        os.chown(fixture, agent.pw_uid, agent.pw_gid)
        os.chmod(fixture, 0o600)
        ledger = source / "evidence/ledger.jsonl"
        prefix = verify_ledger(ledger)
        inodes = {name: (source / name).stat().st_ino for name in roles}
        fixture_hash = digest(fixture)
        anchor = snapshot(source, backup, roles)
        expected = verify(backup, anchor, roles)
        check_tree(source, expected)
        # A modified backup must fail before any destination is touched.
        archive = backup / "data.tar"
        original = archive.read_bytes()
        with archive.open("r+b") as stream:
            stream.seek(1024)
            value = stream.read(1)
            stream.seek(1024)
            stream.write(bytes([value[0] ^ 1]))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            restore(backup, source, anchor, roles)
        except ValueError:
            pass
        else:
            raise ValueError("Tampered backup was accepted")
        check_tree(source, expected)
        with archive.open("wb") as stream:
            stream.write(original)
            stream.flush()
            os.fsync(stream.fileno())
        run(["/usr/bin/mount", "-o", "remount,ro", str(backup)])
        for path, damage in ((fixture, b"CORRUPTED AGENT DATA"), (ledger, b'{"incomplete":')):
            with path.open("wb") as stream:
                stream.write(damage)
                stream.flush()
                os.fsync(stream.fileno())
        try:
            check_tree(source, expected)
        except ValueError:
            pass
        else:
            raise ValueError("DATA corruption was not detected")
        try:
            verify_ledger(ledger)
        except (ValueError, KeyError):
            pass
        else:
            raise ValueError("Corrupted evidence was accepted")
        restore(backup, source, anchor, roles)
        if digest(fixture) != fixture_hash or verify_ledger(ledger) != prefix:
            raise ValueError("DATA content or confirmed evidence prefix was not restored")
        if any((source / name).stat().st_ino != inode for name, inode in inodes.items()):
            raise ValueError("Restore replaced a role root inode")
        return {"status": "DATA_RESTORED", "manifest_sha256": anchor, "archive_sha256": digest(archive),
            "fixture_sha256": fixture_hash, "restored_ledger_sequence": prefix[0],
            "independent_backup_device": True, "backup_read_only_during_restore": True,
            "tampered_backup_rejected_before_write": True, "logical_corruption_detected": True}
    finally:
        if paused:
            os.kill(pid, signal.SIGCONT)
        run(["/usr/bin/umount", str(backup)])
