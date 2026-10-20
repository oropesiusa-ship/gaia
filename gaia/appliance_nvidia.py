"""Resolve the physical Pascal profile in an isolated, signed Debian snapshot.

This command only resolves packages; it never installs a driver on the host,
attaches a GPU, writes physical media or changes the accepted CPU candidate.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil

from .appliance_rootfs import PROFILE, select_tmpdir, sha256
from .bootstrap import Session, locked, write_json

PACKAGES = ("nvidia-driver", "nvidia-kernel-dkms", "nvidia-smi", "linux-headers-amd64")
COMPONENTS = ("main", "contrib", "non-free", "non-free-firmware")
EVIDENCE = ("nvidia-policy.txt", "nvidia-metadata.txt", "nvidia-simulation.txt")


def driver_compatibility(version, minimum):
    def numeric(value):
        match = re.fullmatch(r"(?:[0-9]+:)?([0-9]+(?:\.[0-9]+)+)(?:[-+~].*)?", value)
        if not match:
            raise ValueError("Invalid NVIDIA driver version: " + value)
        return tuple(int(part) for part in match[1].split("."))
    selected, required = numeric(version), numeric(minimum)
    width = max(len(selected), len(required))
    meets_minimum = selected + (0,) * (width - len(selected)) >= required + (0,) * (width - len(required))
    return {"selected_driver": version, "minimum_driver": minimum,
            "meets_existing_minimum": meets_minimum, "gpu_tested": False,
            "profile_accepted": False}


def assess_profile(profile):
    catalog_path = Path(__file__).with_name("bootstrap_profiles.json")
    catalog = json.loads(catalog_path.read_text())
    contract = next(p for p in catalog["profiles"] if p["id"] == "gaia-transformer-cuda-pascal")
    compatibility = driver_compatibility(profile["packages"]["nvidia-driver"], contract["min_driver"])
    profile.update(compatibility=compatibility, contract=contract["contract"],
                   contract_catalog_sha256=sha256(catalog_path))
    if not compatibility["meets_existing_minimum"]:
        profile["status"] = "NVIDIA_PROFILE_BLOCKED_DRIVER_MINIMUM"
    return profile


def assess_reports(session, reports):
    assessed = []
    for report in reports:
        directory = report.resolve(strict=True)
        if not directory.is_relative_to((session.root / ".gaia/reports").resolve()):
            raise ValueError("Assessment requires a local report directory")
        profile = json.loads((directory / "nvidia-profile.json").read_text())
        if profile["snapshot"] != PROFILE["snapshot"] or set(profile["evidence_sha256"]) != set(EVIDENCE):
            raise ValueError("Snapshot/evidence set differs")
        for name in EVIDENCE:
            path = directory / name
            if path.is_symlink() or sha256(path) != profile["evidence_sha256"][name]:
                raise ValueError("Resolution evidence changed: " + name)
        if candidates((directory / "nvidia-policy.txt").read_text()) != profile["packages"]:
            raise ValueError("Profile differs from the resolved APT policy")
        profile["resolution_report"] = str(directory)
        assessed.append(assess_profile(profile))
    session.report.update(assessed_profiles=assessed, host_driver_modified=False,
        physical_media_written=False, gpu_tested=False)
    compatible = all(p["compatibility"]["meets_existing_minimum"] for p in assessed)
    session.finish("NVIDIA_SNAPSHOT_RESOLVED" if compatible else "NVIDIA_PROFILE_BLOCKED_DRIVER_MINIMUM")
    return compatible


def candidates(text):
    result = {}
    current = None
    for line in text.splitlines():
        if line and not line[0].isspace() and line.endswith(":"):
            current = line[:-1]
        elif current and line.strip().startswith("Candidate:"):
            value = line.split(":", 1)[1].strip()
            if value != "(none)":
                result[current] = value
    if set(result) != set(PACKAGES):
        raise ValueError("Snapshot has no complete proprietary NVIDIA/kernel-header profile: " + repr(result))
    return result


def probe(session, backports=False):
    if os.geteuid() == 0:
        raise ValueError("Run as the normal user; the probe uses mmdebstrap unshare")
    tool = shutil.which("mmdebstrap")
    if not tool:
        raise ValueError("mmdebstrap missing")
    temporary = select_tmpdir(False)
    output = session.directory.resolve()
    # apt's signature verification stays enabled. No packages from the host's
    # distribution participate in candidate selection.
    target = " -o APT::Default-Release=trixie-backports" if backports else ""
    script = ("set -eu; apt-cache" + target + " policy " + shlex.join(PACKAGES) + " > /tmp/nvidia-policy.txt; "
              "apt-cache show nvidia-driver nvidia-kernel-dkms > /tmp/nvidia-metadata.txt; "
              "apt-get" + target + " --simulate --no-install-recommends install " + shlex.join(PACKAGES)
              + " > /tmp/nvidia-simulation.txt")
    hooks = ["--customize-hook=" + shlex.join(["chroot", "$1", "/bin/sh", "-ec", script])]
    # $1 is the controlled mmdebstrap staging root, expanded by its hook shell.
    hooks[0] = hooks[0].replace("'$1'", '"$1"')
    for name in ("nvidia-policy.txt", "nvidia-metadata.txt", "nvidia-simulation.txt"):
        hooks.append("--customize-hook=" + shlex.join(["copy-out", "/tmp/" + name, str(output)]))
    command = [tool, "--mode=unshare", "--format=null", "--variant=minbase",
        "--architectures=amd64", "--components=" + ",".join(COMPONENTS),
        "--keyring=" + PROFILE["keyring"], '--aptopt=Acquire::Check-Valid-Until "false"',
        '--aptopt=Acquire::Languages "none"', '--aptopt=Acquire::Retries "1"',
        "--include=ca-certificates", *hooks, PROFILE["suite"], "/dev/null"]
    if backports:
        command += ["deb " + PROFILE["mirror"] + " " + suite + " " + " ".join(COMPONENTS)
                    for suite in (PROFILE["suite"], "trixie-backports")]
    else:
        command.append(PROFILE["mirror"])
    session.report.update(request={"command": "appliance-nvidia", "probe": True},
        snapshot=PROFILE["snapshot"], components=list(COMPONENTS), backports=backports, build_tmpdir=temporary,
        host_driver_modified=False, physical_media_written=False, gpu_tested=False)
    session.save()
    session.command("nvidia-snapshot-resolution", command,
                    env={**os.environ, "TMPDIR": temporary["path"]}, timeout=1200)
    versions = candidates((output / "nvidia-policy.txt").read_text())
    simulation = (output / "nvidia-simulation.txt").read_text()
    if re.search(r"^Inst nvidia-open-kernel-dkms ", simulation, re.M) or not re.search(r"^Inst nvidia-kernel-dkms ", simulation, re.M):
        raise ValueError("Pascal must use the proprietary kernel module, not NVIDIA open modules")
    profile = {"status": "NVIDIA_SNAPSHOT_RESOLVED", "snapshot": PROFILE["snapshot"],
        "mirror": PROFILE["mirror"], "components": list(COMPONENTS), "backports": backports, "packages": versions,
        "gpu_family": "Pascal", "kernel_module": "proprietary", "gpu_tested": False,
        "pending": ["verify GTX 1060 support in selected driver", "build module for exact slot kernel",
                    "construct physical runtime and installer", "real CUDA/GaiaTransformer acceptance"],
        "evidence_sha256": {name: sha256(output / name) for name in
            ("nvidia-policy.txt", "nvidia-metadata.txt", "nvidia-simulation.txt")}}
    assess_profile(profile)
    write_json(output / "nvidia-profile.json", profile)
    session.report.update(nvidia_profile=profile)
    session.finish(profile["status"])
    return profile["compatibility"]["meets_existing_minimum"]


def main(root, args):
    parser = argparse.ArgumentParser(prog="gaia.py appliance-nvidia", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--probe", action="store_true",
                        help="resolve and simulate the proprietary profile inside the pinned Debian snapshot")
    group.add_argument("--assess-report", type=Path, action="append",
                       help="assess existing hashed resolution evidence without repeating the APT probe")
    group.add_argument("--official", action="store_true", help="verify and resolve official proprietary NVIDIA 580 compute inputs")
    group.add_argument("--build-modules", type=Path, help="compile and verify modules from a verified official-inputs report")
    group.add_argument("--build-runtime", type=Path, help="integrate verified official inputs into a new runtime rootfs")
    parser.add_argument("--runtime-manifest", type=Path, help="parent runtime manifest for --build-runtime")
    parser.add_argument("--modules-report", type=Path, help="verified module build for --build-runtime")
    parser.add_argument("--backports", action="store_true", help="also resolve the same dated trixie-backports snapshot")
    options = parser.parse_args(args)
    if options.backports and not options.probe:
        parser.error("--backports requires --probe")
    if bool(options.runtime_manifest) != bool(options.build_runtime):
        parser.error("--build-runtime and --runtime-manifest must be used together")
    if bool(options.modules_report) != bool(options.build_runtime):
        parser.error("--build-runtime requires --modules-report")
    session = Session(root)
    try:
        with locked(Path(root) / ".gaia/bootstrap.lock"):
            if options.build_runtime:
                from .appliance_nvidia_source import build_runtime
                build_runtime(session, options.build_runtime, options.runtime_manifest, options.modules_report)
                return 0
            if options.build_modules:
                from .appliance_nvidia_source import build_modules
                build_modules(session, options.build_modules)
                return 0
            if options.official:
                from .appliance_nvidia_source import probe_official
                probe_official(session)
                return 0
            compatible = (assess_reports(session, options.assess_report) if options.assess_report
                          else probe(session, options.backports))
        return 0 if compatible else 20
    except KeyboardInterrupt as exc:
        session.finish("INTERRUPTED", exc)
        return 130
    except Exception as exc:
        session.finish("FAILED", exc)
        return 40
