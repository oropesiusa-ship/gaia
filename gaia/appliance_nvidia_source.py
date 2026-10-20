"""Authenticated NVIDIA 580 compute inputs; no changes to host drivers."""
import functools
import gzip
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.request

from .appliance_nvidia import driver_compatibility
from .appliance_rootfs import PROFILE, select_tmpdir, sha256
from .bootstrap import write_json

# Debian 13's NVIDIA repository starts with post-Pascal branches. The official
# Debian 12 repository retains 580; dependency resolution is done on Debian 13,
# and only explicitly versioned 580 driver packages can come from that source.
REPOSITORY = "https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/"
KEY_FINGERPRINT = "EB693B3035CD5710E231E123A4B469963BF863CC"
COMPUTE = ("nvidia-kernel-dkms", "nvidia-smi", "libcuda1", "libnvidia-ml1")
KERNEL = "6.12.107+deb13-amd64"
KERNEL_VERSION = "6.12.107-1"


def download(session, url, name, limit):
    path = session.directory.resolve() / name
    request = urllib.request.Request(url, headers={"User-Agent": "GAIA-appliance-inputs/1"})
    with urllib.request.urlopen(request, timeout=60) as response, path.open("xb") as stream:
        if not response.url.startswith("https://"):
            raise ValueError("NVIDIA input redirected outside HTTPS")
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError("NVIDIA input exceeds size limit")
            stream.write(chunk)
    session.report.setdefault("downloads", []).append(
        {"url": url, "name": name, "bytes": total, "sha256": sha256(path)})
    session.save()
    return path


def paragraphs(text):
    for block in text.strip().split("\n\n"):
        fields = {}
        last = None
        for line in block.splitlines():
            if line.startswith((" ", "\t")) and last:
                fields[last] += "\n" + line[1:]
            elif ": " in line:
                last, value = line.split(": ", 1)
                if last in fields:
                    raise ValueError("Duplicate package metadata field")
                fields[last] = value
        if fields:
            yield fields


def index_digest(release, name):
    section = re.search(r"^SHA256:\n((?:[ \t]+[^\n]+\n?)+)", release, re.M)
    if not section:
        raise ValueError("Signed Release has no SHA256 section")
    rows = [line.split() for line in section[1].splitlines()]
    matches = [(digest, int(size)) for digest, size, path in rows if path == name]
    if len(matches) != 1 or not re.fullmatch(r"[0-9a-f]{64}", matches[0][0]):
        raise ValueError("Missing/ambiguous signed package index digest")
    return matches[0]


def newest_580(records):
    choices = {r["Version"] for r in records if r.get("Package") == COMPUTE[0]
               and re.fullmatch(r"580\.[0-9.]+-[0-9]+", r.get("Version", ""))}
    if not choices:
        raise ValueError("Official NVIDIA source has no proprietary 580 package")

    def compare(a, b):
        if a == b:
            return 0
        return -1 if subprocess.run(["dpkg", "--compare-versions", a, "lt", b]).returncode == 0 else 1

    return max(choices, key=functools.cmp_to_key(compare))


def authenticated_inputs(session):
    output = session.directory.resolve()
    key = download(session, REPOSITORY + "3bf863cc.pub", "nvidia-key.asc", 1024 * 1024)
    home = output / "public-only"
    home.mkdir(mode=0o700)
    listing = session.command("nvidia-key-identity", ["gpg", "--batch", "--no-options", "--homedir", str(home),
        "--with-colons", "--show-keys", str(key)])
    fingerprints = [line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:")]
    if fingerprints != [KEY_FINGERPRINT]:
        raise ValueError("NVIDIA archive key fingerprint differs from the pinned identity")
    keyring = output / "nvidia-keyring.gpg"
    session.command("nvidia-key-dearmor", ["gpg", "--batch", "--no-options", "--homedir", str(home),
        "--dearmor", "--output", str(keyring), str(key)])
    signed = download(session, REPOSITORY + "InRelease", "InRelease", 2 * 1024 * 1024)
    release = output / "Release.verified"
    signature = session.command("nvidia-index-signature", ["gpgv", "--homedir", str(home), "--status-fd", "1",
        "--keyring", str(keyring), "--output", str(release), str(signed)])
    if "[GNUPG:] VALIDSIG " + KEY_FINGERPRINT + " " not in signature:
        raise ValueError("NVIDIA InRelease signer mismatch")
    digest, size = index_digest(release.read_text(), "Packages.gz")
    index = download(session, REPOSITORY + "Packages.gz", "Packages.gz", 16 * 1024 * 1024)
    if index.stat().st_size != size or sha256(index) != digest:
        raise ValueError("NVIDIA Packages.gz differs from the signed index")
    with gzip.open(index, "rb") as stream:
        data = stream.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("Uncompressed NVIDIA index exceeds size limit")
    records = list(paragraphs(data.decode()))
    version = newest_580(records)
    selected = {}
    for package in COMPUTE:
        rows = [r for r in records if r.get("Package") == package and r.get("Version") == version
                and r.get("Architecture") == "amd64"]
        if len(rows) != 1:
            raise ValueError("Inconsistent NVIDIA compute package set: " + package)
        row = rows[0]
        relative = PurePosixPath(row["Filename"])
        if relative.is_absolute() or ".." in relative.parts or not re.fullmatch(r"[0-9a-f]{64}", row["SHA256"]):
            raise ValueError("Invalid signed NVIDIA package path/hash")
        selected[package] = {field: row[field] for field in ("Version", "Filename", "SHA256", "Size", "Depends") if field in row}
    catalog = json.loads(Path(__file__).with_name("bootstrap_profiles.json").read_text())
    minimum = next(p["min_driver"] for p in catalog["profiles"] if p["id"] == "gaia-transformer-cuda-pascal")
    if not driver_compatibility(version, minimum)["meets_existing_minimum"]:
        raise ValueError("Official driver is below the existing CUDA gate")
    upstream = version.rsplit("-", 1)[0]
    chips = download(session, "https://download.nvidia.com/XFree86/Linux-x86_64/" + upstream
        + "/README/supportedchips.html", "supportedchips.html", 4 * 1024 * 1024)
    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", chips.read_text(), re.S | re.I)
    support = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r)).strip()
               for r in rows if "GTX 1060 6GB" in r and "1C03" in r.upper()]
    if not support:
        raise ValueError("Selected driver's product list does not confirm GTX 1060 6GB / 1C03")
    profile = {"repository": REPOSITORY, "archive_fingerprint": KEY_FINGERPRINT,
        "driver_version": version, "compute_packages": selected,
        "debian_snapshot": PROFILE["snapshot"], "kernel": KERNEL, "kernel_package_version": KERNEL_VERSION,
        "documented_gpu_support": support, "gpu_tested": False, "module_built": False,
        "evidence_sha256": {name: sha256(output / name) for name in
            ("nvidia-key.asc", "nvidia-keyring.gpg", "InRelease", "Packages.gz", "supportedchips.html")}}
    write_json(output / "official-inputs.json", profile)
    session.report["official_inputs"] = profile
    session.save()
    return profile


def probe_official(session):
    if os.geteuid() == 0:
        raise ValueError("Use the normal user; source resolution runs in mmdebstrap unshare")
    profile = authenticated_inputs(session)
    output = session.directory.resolve()
    version = profile["driver_version"]
    pin = output / "nvidia-580.pref"
    pin.write_text("Package: *\nPin: origin developer.download.nvidia.com\nPin-Priority: -1\n\n"
        "Package: nvidia-* libnvidia-* libcuda1 libcuda1-* firmware-nvidia-* cuda-drivers*\n"
        "Pin: version 580.*\nPin-Priority: 1001\n")
    requested = [package + "=" + version for package in COMPUTE] + [
        "linux-image-" + KERNEL + "=" + KERNEL_VERSION, "linux-headers-" + KERNEL + "=" + KERNEL_VERSION]
    script = ("set -eu; apt-cache policy " + shlex.join(COMPUTE) + " > /tmp/official-policy.txt; "
        "apt-get --simulate --no-install-recommends install " + shlex.join(requested)
        + " > /tmp/official-simulation.txt; apt-get --yes --download-only --no-install-recommends install "
        + shlex.join(requested) + " > /tmp/official-downloads.txt")
    hooks = ['--setup-hook=mkdir -p "$1/usr/share/keyrings" "$1/etc/apt/preferences.d"',
        "--setup-hook=" + shlex.join(["copy-in", str(output / "nvidia-keyring.gpg"), "/usr/share/keyrings"]),
        "--setup-hook=" + shlex.join(["copy-in", str(pin), "/etc/apt/preferences.d"]),
        '--customize-hook=chroot "$1" /bin/sh -ec ' + shlex.quote(script)]
    for name in ("official-policy.txt", "official-simulation.txt", "official-downloads.txt"):
        hooks.append("--customize-hook=" + shlex.join(["copy-out", "/tmp/" + name, str(output)]))
    hooks.append("--customize-hook=" + shlex.join(["copy-out", "/var/cache/apt/archives", str(output)]))
    temporary = select_tmpdir(False)
    command = [shutil.which("mmdebstrap"), "--mode=unshare", "--format=null", "--variant=minbase",
        "--architectures=amd64", "--include=ca-certificates",
        '--aptopt=Acquire::Check-Valid-Until "false"', '--aptopt=Acquire::Languages "none"',
        *hooks, PROFILE["suite"], "/dev/null",
        "deb " + PROFILE["mirror"] + " " + PROFILE["suite"] + " main contrib non-free non-free-firmware",
        "deb " + REPOSITORY + " /"]
    session.report.update(request={"command": "appliance-nvidia", "official": True},
        host_driver_modified=False, physical_media_written=False, gpu_tested=False)
    # mmdebstrap's initial APT process runs outside the target chroot as _apt.
    # It cannot traverse a private home; --keyring is scalar, not additive.
    # Give only the public Debian+NVIDIA packets a traversable temporary path.
    with tempfile.TemporaryDirectory(prefix="gaia-nvidia-public-", dir=temporary["path"]) as keys:
        os.chmod(keys, 0o755)
        combined = Path(keys) / "archives.gpg"
        combined.write_bytes(Path(PROFILE["keyring"]).read_bytes() + (output / "nvidia-keyring.gpg").read_bytes())
        combined.chmod(0o644)
        command.insert(1, "--keyring=" + str(combined))
        session.report["temporary_public_keyring_sha256"] = sha256(combined)
        session.command("official-nvidia-resolution", command,
                        env={**os.environ, "TMPDIR": temporary["path"]}, timeout=1200)
    simulation = (output / "official-simulation.txt").read_text()
    if re.search(r"^Inst (?:nvidia-open|cuda-toolkit|cuda-compat)", simulation, re.M):
        raise ValueError("Resolution selected an unwanted open module/toolkit/compatibility runtime")
    artifacts = []
    for path in sorted((output / "archives").glob("*.deb")):
        info = subprocess.check_output(["dpkg-deb", "-f", str(path), "Package", "Version", "Architecture"], text=True)
        fields = dict(line.split(": ", 1) for line in info.splitlines() if ": " in line)
        artifacts.append({"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size, **fields})
    for package, metadata in profile["compute_packages"].items():
        matches = [row for row in artifacts if row.get("Package") == package]
        if len(matches) != 1 or matches[0]["sha256"] != metadata["SHA256"]:
            raise ValueError("Downloaded NVIDIA compute package differs from authenticated metadata: " + package)
    profile.update(status="NVIDIA_OFFICIAL_COMPUTE_INPUTS_VERIFIED", downloaded_packages=artifacts,
        resolution_evidence_sha256={name: sha256(output / name) for name in
            ("official-policy.txt", "official-simulation.txt", "official-downloads.txt")})
    write_json(output / "official-inputs.json", profile)
    session.report["official_inputs"] = profile
    session.finish(profile["status"])


def build_modules(session, source):
    if os.geteuid() == 0:
        raise ValueError("Module build requires mmdebstrap mapped root, not host root")
    source = source.resolve(strict=True)
    if not source.is_relative_to((session.root / ".gaia/reports").resolve()):
        raise ValueError("Module inputs must be a local verified report")
    profile = json.loads((source / "official-inputs.json").read_text())
    if (profile.get("status") != "NVIDIA_OFFICIAL_COMPUTE_INPUTS_VERIFIED"
            or profile["driver_version"] != "580.178.04-1" or profile["kernel"] != KERNEL):
        raise ValueError("Unexpected/unverified module profile")
    for row in profile["downloaded_packages"]:
        path = source / "archives" / row["name"]
        if Path(row["name"]).name != row["name"] or path.is_symlink() or sha256(path) != row["sha256"]:
            raise ValueError("Cached package changed")
    script = Path(__file__).with_name("appliance_nvidia_build.sh").resolve()
    temporary = select_tmpdir(True)
    if shutil.disk_usage(temporary["path"]).free < 8 * 1024**3:
        raise ValueError("Insufficient module build storage")
    output = session.directory.resolve()
    hooks = ['--customize-hook=mkdir -p "$1/tmp/nvidia-debs"',
        "--customize-hook=" + shlex.join(["copy-in", str(source / "archives") + "/.", "/tmp/nvidia-debs"]),
        "--customize-hook=" + shlex.join(["copy-in", str(script), "/tmp"]),
        '--customize-hook=chroot "$1" /bin/sh /tmp/appliance_nvidia_build.sh',
        "--customize-hook=" + shlex.join(["copy-out", "/tmp/nvidia-modules.tar", str(output)])]
    command = [shutil.which("mmdebstrap"), "--mode=unshare", "--format=null", "--variant=minbase",
        "--architectures=amd64", "--keyring=" + PROFILE["keyring"],
        '--aptopt=Acquire::Check-Valid-Until "false"', '--aptopt=Acquire::Languages "none"',
        *hooks, PROFILE["suite"], "/dev/null", PROFILE["mirror"]]
    session.report.update(request={"command": "appliance-nvidia", "build_modules": str(source)},
        driver_version=profile["driver_version"], kernel=KERNEL, input_manifest_sha256=sha256(source / "official-inputs.json"),
        build_script_sha256=sha256(script), host_driver_modified=False, gpu_tested=False,
        physical_media_written=False, build_tmpdir=temporary)
    session.save()
    session.command("nvidia-module-build", command,
                    env={**os.environ, "TMPDIR": temporary["path"]}, timeout=1800)
    archive = output / "nvidia-modules.tar"
    import tarfile
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        names = {m.name.removeprefix("./"): m for m in members if m.isfile()}
        for module in ("nvidia", "nvidia_modeset", "nvidia_drm", "nvidia_uvm"):
            info = tar.extractfile(names[module + ".modinfo"]).read().decode()
            if "580.178.04" not in info or KERNEL not in info or (module == "nvidia" and "NVIDIA" not in info):
                raise ValueError("Module metadata verification failed")
    session.report.update(module_built=True, module_archive_sha256=sha256(archive),
        module_archive_bytes=archive.stat().st_size,
        pending=["integrate modules and driver libraries into runtime rootfs", "real GPU loading and CUDA validation",
                 "physical installer and medium", "S0/S2-S4"])
    session.finish("NVIDIA_KERNEL_MODULES_BUILT")


def build_runtime(session, source, runtime_manifest, modules_report):
    from .appliance_image import verified_source
    from .appliance_rootfs import inspect_rootfs
    if os.geteuid() == 0:
        raise ValueError("Use mapped-root build, not host root")
    source = source.resolve(strict=True)
    profile = json.loads((source / "official-inputs.json").read_text())
    if profile.get("status") != "NVIDIA_OFFICIAL_COMPUTE_INPUTS_VERIFIED" or profile["kernel"] != KERNEL:
        raise ValueError("Runtime requires the verified official profile")
    for row in profile["downloaded_packages"]:
        path = source / "archives" / row["name"]
        if Path(row["name"]).name != row["name"] or path.is_symlink() or sha256(path) != row["sha256"]:
            raise ValueError("Runtime package input changed")
    rootfs, previous = verified_source(runtime_manifest)
    temporary = select_tmpdir(True)
    required = 3 * previous["rootfs_bytes"] + 8 * 1024**3
    if shutil.disk_usage(temporary["path"]).free < required or shutil.disk_usage(session.root).free < required:
        raise ValueError("Insufficient workspace for immutable NVIDIA runtime: " + str(required))
    output = session.directory.resolve()
    modules_report = modules_report.resolve(strict=True)
    modules = json.loads((modules_report / "report.json").read_text())
    archive = modules_report / "nvidia-modules.tar"
    if (modules.get("status") != "NVIDIA_KERNEL_MODULES_BUILT" or modules["kernel"] != KERNEL
            or sha256(archive) != modules["module_archive_sha256"]):
        raise ValueError("Prebuilt module identity mismatch")
    script = Path(__file__).with_name("appliance_nvidia_integrate.sh").resolve()
    hooks = ['--customize-hook=mkdir -p "$1/tmp/runtime-tree"',
        "--customize-hook=" + shlex.join(["copy-in", str(rootfs), "/tmp"]),
        '--customize-hook=tar --extract --file "$1/tmp/rootfs.tar" --directory "$1/tmp/runtime-tree" --numeric-owner --same-owner --anchored --exclude="./dev/*" --exclude="dev/*"',
        '--customize-hook=mkdir -p "$1/tmp/runtime-tree/tmp/nvidia-debs"',
        "--customize-hook=" + shlex.join(["copy-in", str(source / "archives") + "/.", "/tmp/runtime-tree/tmp/nvidia-debs"]),
        "--customize-hook=" + shlex.join(["copy-in", str(script), "/tmp/runtime-tree/tmp"]),
        "--customize-hook=" + shlex.join(["copy-in", str(archive), "/tmp/runtime-tree/tmp"]),
        '--customize-hook=chroot "$1/tmp/runtime-tree" /bin/sh /tmp/appliance_nvidia_integrate.sh',
        '--customize-hook=rm -rf "$1/tmp/runtime-tree/tmp/nvidia-debs" "$1/tmp/runtime-tree/tmp/module-output" "$1/tmp/runtime-tree/tmp/nvidia-modules.tar"',
        '--customize-hook=tar --create --file "$1/tmp/nvidia-rootfs.tar" --directory "$1/tmp/runtime-tree" --numeric-owner .',
        "--customize-hook=" + shlex.join(["copy-out", "/tmp/nvidia-rootfs.tar", str(output)]),
        "--customize-hook=" + shlex.join(["copy-out", "/tmp/runtime-tree/opt/gaia/build-nvidia.json", str(output)])]
    command = [shutil.which("mmdebstrap"), "--mode=unshare", "--format=null", "--variant=minbase",
        "--architectures=amd64", "--keyring=" + PROFILE["keyring"],
        '--aptopt=Acquire::Check-Valid-Until "false"', '--aptopt=Acquire::Languages "none"',
        *hooks, PROFILE["suite"], "/dev/null", PROFILE["mirror"]]
    session.report.update(request={"command": "appliance-nvidia", "build_runtime": str(source)},
        parent_runtime_manifest=str(runtime_manifest.resolve()), parent_runtime_sha256=previous["rootfs_sha256"],
        official_inputs_sha256=sha256(source / "official-inputs.json"), build_script_sha256=sha256(script),
        prebuilt_modules_sha256=sha256(archive),
        required_workspace_bytes=required, host_driver_modified=False, physical_media_written=False, gpu_tested=False)
    session.command("nvidia-runtime-build", command,
                    env={**os.environ, "TMPDIR": temporary["path"]}, timeout=2400)
    artifact = output / "nvidia-rootfs.tar"
    artifact.rename(output / "rootfs.tar")
    artifact = output / "rootfs.tar"
    contents = inspect_rootfs(artifact)
    manifest = {**previous, **contents, "status": "DEBIAN_RUNTIME_ROOTFS_BUILT",
        "rootfs_sha256": sha256(artifact), "rootfs_bytes": artifact.stat().st_size,
        "nvidia": json.loads((output / "build-nvidia.json").read_text()),
        "nvidia_inputs_manifest_sha256": sha256(source / "official-inputs.json"),
        "parent_runtime_sha256": previous["rootfs_sha256"], "gpu_tested": False,
        "pending": ["physical CUDA runtime and installer", "remove build-only packages after module build",
                    "VM acceptance for resulting image", "real GPU and S0/S2-S4"]}
    write_json(output / "rootfs-manifest.json", manifest)
    session.report.update(artifact={"path": str(artifact), "sha256": manifest["rootfs_sha256"]},
                          nvidia=manifest["nvidia"])
    session.finish("NVIDIA_RUNTIME_ROOTFS_BUILT")
