"""Trusted guest evaluator for the VM foundation, not the F1 acceptance suite."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run(args):
    return subprocess.check_output(args, text=True, timeout=90)


def main():
    cmdline = dict(item.split("=", 1) for item in Path("/proc/cmdline").read_text().split() if "=" in item)
    assert cmdline["gaia.lab"] == "1"
    assert hashlib.sha256(Path("/core/SHA256SUMS").read_bytes()).hexdigest() == cmdline["gaia.core"]
    run(["/usr/bin/sha256sum", "--check", "/core/SHA256SUMS"])
    public_trust = None
    if Path("/core/owner-trust.json").is_file():
        from public_trust import custody_check
        public_trust = custody_check()
    mounts = {row.split()[1]: row.split()[3].split(",") for row in Path("/proc/mounts").read_text().splitlines()}
    assert "ro" in mounts["/"] and "ro" in mounts["/core"] and "rw" in mounts["/data"]
    rules = json.loads(run(["/usr/sbin/nft", "--json", "list", "ruleset"]))
    policies = {entry["chain"]["hook"]: entry["chain"]["policy"] for entry in rules["nftables"] if "chain" in entry}
    assert all(policies[hook] == "drop" for hook in ("input", "forward", "output"))
    links = json.loads(run(["/usr/sbin/ip", "-json", "link", "show"]))
    assert any(link["ifname"] != "lo" for link in links), "NIC required to test offline policy"
    assert all("UP" not in link["flags"] for link in links if link["ifname"] != "lo")
    python = "/opt/gaia/venv/bin/python"
    client = '''import socket,json
def request(value):
 with socket.socket(socket.AF_UNIX) as s:
  s.connect("/run/gaia/control.sock"); s.sendall(json.dumps(value).encode()+b"\\n")
  return json.loads(s.makefile("rb").readline(4096))
good=request({"action":"inventory"})
assert good["status"]=="ok"
assert request({"action":"shell","command":"id"})["status"]=="denied"
assert request({"action":"inventory","path":"/etc/shadow"})["status"]=="denied"
try:
 open("/data/evidence/ledger.jsonl","ab")
except PermissionError:
 pass
else:
 raise AssertionError("Agent can modify guardian evidence")
print(json.dumps(good))
'''
    for _ in range(50):
        if Path("/run/gaia/control.sock").exists():
            break
        time.sleep(0.1)
    catalogue = json.loads(run(["/usr/sbin/runuser", "-u", "gaia", "--", python, "-I", "-c", client]))
    namespace = str(os.stat("/proc/self/ns/net").st_ino)
    sandbox = json.loads(run(["/usr/sbin/runuser", "-u", "gaia", "--", "/usr/bin/bwrap",
        "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
        "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/sbin", "/sbin",
        "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
        "--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache",
        "--ro-bind", "/opt/gaia/python", "/opt/gaia/python", "--ro-bind", "/opt/gaia/venv", "/opt/gaia/venv",
        "--ro-bind", "/opt/gaia/app", "/opt/gaia/app", "--ro-bind", "/core", "/core",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        "--bind", "/data/agent", "/data/agent", python, "-I", "/core/worker_smoke.py", namespace]))
    from guardian import verify_ledger
    count, digest = verify_ledger(Path("/data/evidence/ledger.jsonl"))
    assert count == catalogue["sequence"] and digest == catalogue["sha256"]
    recovery = None
    if cmdline.get("gaia.scenario") == "data-recovery":
        from data_recovery import exercise
        recovery = exercise()
        # The resumed guardian must extend the exact restored evidence prefix.
        catalogue = json.loads(run(["/usr/sbin/runuser", "-u", "gaia", "--", python, "-I", "-c", client]))
        count, digest = verify_ledger(Path("/data/evidence/ledger.jsonl"))
        assert count == recovery["restored_ledger_sequence"] + 1 == catalogue["sequence"]
        assert digest == catalogue["sha256"]
    publication = None
    health = None
    if cmdline.get("gaia.scenario") == "publication-interrupted":
        from boot_transaction import interrupted_publication
        publication = interrupted_publication(count)
    if cmdline.get("gaia.scenario") == "health-bless":
        from boot_transaction import bless_healthy
        health = bless_healthy(count)
    if cmdline.get("gaia.scenario") == "health-reject":
        print("GAIA_HEALTH_REJECTED=unblessed-lab-candidate", flush=True)
        raise ValueError("Injected unhealthy candidate must not be blessed")
    usb_boot = None
    if cmdline.get("gaia.scenario") == "usb-smoke":
        disks = json.loads(run(["/usr/bin/lsblk", "--json", "--tree", "--output", "PATH,TYPE,SERIAL,MOUNTPOINTS"]))
        def nodes(row):
            yield row
            for child in row.get("children", []):
                yield from nodes(child)
        roots = [d for d in disks["blockdevices"] if d.get("serial") == "GAIA-LAB-RECOVERY"]
        assert len(roots) == 1 and any("/" in (n.get("mountpoints") or []) for n in nodes(roots[0]))
        assert public_trust and public_trust["status"] == "OWNER_PUBLIC_SIGNATURE_OK"
        usb_boot = {"status": "USB_RECOVERY_BOOT_OK", "device": roots[0]["path"]}
    print("GAIA_VM_RESULT=" + json.dumps({"status": "VM_FOUNDATION_OK", "slot": cmdline["gaia.slot"],
        "profile": "vm-cpu-l0", "sandbox": sandbox, "offline": True,
        "catalogue": "inventory-only", "ledger_sequence": count, "ledger_sha256": digest,
        "data_recovery": recovery, "owner_public_trust": public_trust,
        "publication": publication, "health": health, "usb_boot": usb_boot}), flush=True)


if __name__ == "__main__":
    # -I excludes this script's directory; CORE is an explicit trusted path.
    sys.path.insert(0, "/core")
    main()
