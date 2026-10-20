"""Retire identified disposable VM artifacts with dependency and use checks.

Only files produced by local completed reports are eligible. Never removes
directories, logs, manifests, keys, corpora, checkpoints, or retained references.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from .appliance_rootfs import sha256
from .bootstrap import Session, locked


def created_by_report(path, report, root):
    for step in report.get("steps", []):
        args = step.get("command", [])
        if not args:
            continue
        name = Path(args[0]).name
        if name == "qemu-img" and len(args) > 1 and args[1] == "dd":
            if any(value == "of=" + str(path) for value in args):
                return True
        if name == "qemu-img" and len(args) > 1 and args[1] == "create":
            index = 2
            while index < len(args):
                if args[index] in ("-f", "-F", "-b", "-o"):
                    index += 2
                elif args[index] in ("-q", "-u"):
                    index += 1
                else:
                    output = Path(args[index])
                    if not output.is_absolute():
                        output = root / output
                    if output.resolve() == path.resolve():
                        return True
                    break
    return False


def idle(path):
    result = subprocess.run(["/usr/bin/fuser", str(path)], text=True, capture_output=True)
    return result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip()


def eligible(path, reports_root, protected):
    if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(reports_root)
            or path.stat().st_uid != os.getuid() or (path.stat().st_dev, path.stat().st_ino) in protected):
        return False
    report_path = path.parent / "report.json"
    if not report_path.is_file():
        return False
    record = json.loads(report_path.read_text())
    if record.get("status") == "running" or not record.get("finished"):
        return False
    return path.stat().st_mtime <= record["finished"] + 2 and idle(path)


def dependency_order(bases, children, can_remove):
    """Children before bases; preserve any base with a non-disposable dependent."""
    order, blocked = [], set()
    def visit(path, visiting):
        if path in visiting:
            raise ValueError("Cycle in VM backing graph")
        if path in order:
            return True
        if not can_remove(path):
            blocked.add(path)
            return False
        okay = True
        for child in children.get(path, []):
            okay = visit(child, visiting | {path}) and okay
        if okay:
            order.append(path)
        else:
            blocked.add(path)
        return okay
    for base in bases:
        visit(base, set())
    return order, blocked


def cleanup(session, policy, apply=False):
    root = session.root.resolve()
    reports = root / ".gaia/reports"
    keep = [root / value for value in policy["preserve"]]
    protected = {(p.stat().st_dev, p.stat().st_ino) for p in keep if p.is_file()}
    bases, expected, reasons = [], {}, {}
    for value in policy["retire_base_images"]:
        path = root / value
        if not path.resolve().is_relative_to(reports) or path.name != "disk.raw":
            raise ValueError("Only local superseded disk.raw fixtures can be retired")
        if not path.exists():
            continue
        manifest = json.loads((path.parent / "image-manifest.json").read_text())
        if manifest.get("release_image") or manifest.get("signed"):
            raise ValueError("Refusing to retire a release/signed base")
        bases.append(path)
        expected[path] = manifest["disk_sha256"]
        reasons[path] = "Superseded disposable lab base, owner retention policy"
    children, graph = {}, []
    for path in reports.glob("*/*.qcow2"):
        if path.is_symlink() or not path.is_file():
            raise ValueError("Unknown VM link in backing graph")
        result = subprocess.run(["/usr/bin/qemu-img", "info", "--output=json", str(path)],
                                check=True, text=True, capture_output=True, timeout=30)
        info = json.loads(result.stdout)
        backing = info.get("full-backing-filename") or info.get("backing-filename")
        graph.append({"path": str(path.relative_to(root)), "format": info.get("format"),
                      "virtual_size": info.get("virtual-size"), "backing": backing})
        if backing:
            parent = Path(backing)
            if not parent.is_absolute():
                parent = path.parent / parent
            children.setdefault(parent.resolve(), []).append(path)
    def disposable(path):
        if not eligible(path, reports, protected):
            return False
        if path in bases:
            return True
        report = json.loads((path.parent / "report.json").read_text())
        return path.suffix == ".qcow2" and created_by_report(path, report, root)
    order, blocked = dependency_order(bases, children, disposable)
    for path in order:
        reasons.setdefault(path, "Completed disposable overlay dependent on retired base")
    cache = root / policy["bundle_cache"]
    if not cache.resolve().is_relative_to(reports) or cache.name != "bundle.ext4":
        raise ValueError("Only a local regenerable bundle.ext4 cache is eligible")
    if cache.exists() and eligible(cache, reports, protected):
        record = json.loads((cache.parent / "report.json").read_text())
        expected[cache] = record["bundle_disk_sha256"]
        reasons[cache] = "Regenerable read-only bundle cache; signed source retained"
        order.append(cache)
    if policy.get("retire_esp_staging"):
        for path in sorted(reports.glob("*/*.fat")):
            if eligible(path, reports, protected):
                record = json.loads((path.parent / "report.json").read_text())
                if created_by_report(path, record, root):
                    order.append(path)
                    reasons[path] = "Completed ESP staging fixture; hashes/logs retained"
    plan = []
    for path in dict.fromkeys(order):
        digest = sha256(path)
        if path in expected and digest != expected[path]:
            raise ValueError("Artifact changed relative to recorded hash: " + str(path))
        info = path.stat()
        plan.append({"path": str(path.relative_to(root)), "sha256": digest,
            "bytes": info.st_size, "allocated_bytes": info.st_blocks * 512, "reason": reasons[path]})
    session.report.update(cleanup_policy=policy, backing_graph=graph, plan=plan, blocked=[str(p.relative_to(root)) for p in sorted(blocked)],
        before_free_bytes=shutil.disk_usage(root).free, apply=apply, removed=[])
    session.save()
    if apply:
        for entry in plan:
            path = root / entry["path"]
            if not eligible(path, reports, protected) or sha256(path) != entry["sha256"]:
                raise ValueError("Artifact changed/became busy during cleanup")
            path.unlink()
            session.report["removed"].append(entry)
            session.save()
    session.report["after_free_bytes"] = shutil.disk_usage(root).free
    session.finish("DISPOSABLE_ARTIFACTS_CLEANED" if apply else "DISPOSABLE_CLEANUP_PLANNED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    session = Session(root)
    session.report["request"] = {"command": "appliance-artifact-cleanup"}
    try:
        with locked(root / ".gaia/bootstrap.lock"):
            cleanup(session, json.loads(args.policy.read_text()), args.apply)
        return 0
    except Exception as exc:
        session.finish("STOPPED", exc)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
