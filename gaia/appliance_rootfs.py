"""Construye la base Debian de S1 sin sudo ni acceso a dispositivos físicos.

Es un rootfs de construcción, no una appliance terminada ni un medio instalador.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import tarfile
import tempfile

from .appliance_bootstrap import diagnose
from .bootstrap import BootstrapError, Session, locked, verified_download, write_json


PROFILE = {
    "id": "gaia-debian-trixie-amd64-base-v1",
    "stage": "F1/S1 Debian base, not release appliance",
    "suite": "trixie",
    "snapshot": "20261015T000000Z",
    "mirror": "https://snapshot.debian.org/archive/debian/20261015T000000Z/",
    "architecture": "amd64",
    "variant": "minbase",
    "components": ["main"],
    "keyring": "/usr/share/keyrings/debian-archive-keyring.pgp",
    "packages": ["systemd-sysv", "linux-image-amd64", "initramfs-tools", "systemd-boot-efi",
                 "python3-venv", "ca-certificates", "bubblewrap", "nftables", "iproute2",
                 "smartmontools", "e2fsprogs", "dosfstools", "fdisk", "util-linux", "kmod"],
}
PYTHON_SOURCE = {
    "url": "https://www.python.org/ftp/python/3.14.4/Python-3.14.4.tar.xz",
    "sha256": "d923c51303e38e249136fc1bdf3568d56ecb03214efdef48516176d3d7faaef8",
    "hash_source": "https://www.python.org/downloads/release/python-3144/",
}
BUILD_PACKAGES = ["build-essential", "libssl-dev", "zlib1g-dev", "libbz2-dev", "libreadline-dev",
                  "libsqlite3-dev", "libffi-dev", "liblzma-dev", "libncurses-dev", "libgdbm-dev",
                  "uuid-dev", "libzstd-dev"]



def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def build_command(tool, target):
    # Snapshot expiry is ignored for historical metadata, signatures remain
    # mandatory. No hooks, unauthenticated packages or arbitrary profile argv.
    return [tool, "--mode=unshare", "--format=tar", "--variant=" + PROFILE["variant"],
            "--architectures=" + PROFILE["architecture"], "--components=main",
            "--keyring=" + PROFILE["keyring"],
            '--aptopt=Acquire::Check-Valid-Until "false"',
            '--aptopt=Acquire::Languages "none"', '--aptopt=Acquire::Retries "1"',
            "--include=" + ",".join(PROFILE["packages"]),
            PROFILE["suite"], str(target), PROFILE["mirror"]]


def inspect_rootfs(path):
    status = None
    runtime = None
    kernels, initramfs, efi = [], [], []
    with tarfile.open(path, "r|") as archive:
        for member in archive:
            name = member.name.removeprefix("./")
            if name == "opt/gaia/build-runtime.json":
                if runtime is not None or not member.isfile() or member.size > 1024 * 1024:
                    raise ValueError("Informe de runtime inválido")
                runtime = json.load(archive.extractfile(member))
            if name == "var/lib/dpkg/status":
                if status is not None or not member.isfile() or member.size > 32 * 1024 * 1024:
                    raise ValueError("Base dpkg inválida/duplicada")
                status = archive.extractfile(member).read().decode("utf-8")
            if member.isfile() and member.size:
                if name.startswith("boot/vmlinuz-"):
                    kernels.append(name)
                if name.startswith("boot/initrd.img-"):
                    initramfs.append(name)
                if name.startswith("usr/lib/systemd/boot/efi/") and name.endswith((".efi", ".efi.stub")):
                    efi.append(name)
    if status is None:
        raise ValueError("Rootfs sin inventario dpkg")
    packages = {}
    for paragraph in status.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in paragraph.splitlines()
                      if not line.startswith((" ", "\t")) and ": " in line)
        if fields.get("Status") == "install ok installed":
            packages[fields["Package"]] = {key: fields.get(key) for key in ("Version", "Architecture")}
    missing = set(PROFILE["packages"]) - packages.keys()
    if missing or not kernels or not initramfs or not efi:
        raise ValueError(f"Base incompleta: paquetes={sorted(missing)}, kernel={bool(kernels)}, "
                         f"initramfs={bool(initramfs)}, EFI={bool(efi)}")
    result = {"packages": packages, "kernels": sorted(kernels), "initramfs": sorted(initramfs), "efi": sorted(efi)}
    if runtime is not None:
        result["runtime"] = runtime
    return result


def runtime_hooks(session):
    source = verified_download(session, PYTHON_SOURCE)
    script = Path(__file__).with_name("appliance_runtime_build.sh")
    lock = session.root / "requirements/gaia-transformer-cuda-pascal-py314.lock"
    payload = session.directory.resolve() / "gaia-source.tar"
    files = [session.root / "gaia.py"] + sorted(p for p in (session.root / "gaia").rglob("*")
             if p.is_file() and not p.is_symlink() and "__pycache__" not in p.parts)
    with tarfile.open(payload, "w") as archive:
        for path in files:
            archive.add(path, arcname="app/" + path.relative_to(session.root).as_posix(), recursive=False)
    session.report["runtime_inputs"] = {"python_source": PYTHON_SOURCE,
        "script_sha256": sha256(script), "lock_sha256": sha256(lock), "app_tar_sha256": sha256(payload),
        "app_files": {p.relative_to(session.root).as_posix(): sha256(p) for p in files},
        "configure_flags": ["--prefix=/opt/gaia/python", "--with-ensurepip=install", "--disable-test-modules"],
        "make_jobs": 2}
    hooks = ['--customize-hook=mkdir -p "$1/opt/gaia"',
             "--customize-hook=" + shlex.join(["tar-in", str(payload), "/opt/gaia"])]
    for path in (source, script, lock):
        staged = session.directory.resolve() / path.name
        shutil.copyfile(path, staged)
        hooks.append("--customize-hook=" + shlex.join(["copy-in", str(staged), "/tmp"]))
    hooks.append('--customize-hook=chroot "$1" /bin/sh /tmp/appliance_runtime_build.sh')
    return hooks


def check_tmpdir(directory, with_runtime):
    directory = directory.resolve()
    if not directory.is_dir() or not os.access(directory, os.W_OK | os.X_OK):
        raise BootstrapError("appliance-rootfs-tmpdir", "El directorio temporal no existe o no es escribible.",
                             "Elegir un directorio temporal existente con --tmpdir; no se cambian permisos automáticamente.")
    if any(not (p.stat().st_mode & stat.S_IXOTH) for p in (directory, *directory.parents)):
        raise BootstrapError("appliance-rootfs-tmpdir", "Los usuarios mapeados de mmdebstrap no pueden atravesar el directorio temporal.",
                             "Elegir un temporal público de construcción fuera del home privado, sin cambiar permisos del home.")
    required = (16 if with_runtime else 2) * 2**30
    available = shutil.disk_usage(directory).free
    if available < required:
        raise BootstrapError("appliance-rootfs-tmpdir", f"Temporal insuficiente: {available / 2**30:.1f} GiB libres; presupuesto {required / 2**30:.0f} GiB.",
                             "Usar --tmpdir en un filesystem con espacio real, p. ej. /var/tmp; no ampliar ni llenar el tmpfs.")
    return {"path": str(directory), "free_bytes": available, "required_bytes": required}


def select_tmpdir(with_runtime, requested=None):
    if requested is not None:
        return check_tmpdir(requested, with_runtime)
    failures = []
    for candidate in dict.fromkeys((tempfile.gettempdir(), "/var/tmp")):
        try:
            result = check_tmpdir(Path(candidate), with_runtime)
            result["rejected_candidates"] = failures
            return result
        except BootstrapError as exc:
            failures.append({"path": candidate, "reason": str(exc)})
    raise BootstrapError("appliance-rootfs-tmpdir", "No hay temporal adecuado: " + json.dumps(failures),
                         "Elegir --tmpdir con capacidad y permisos adecuados antes de reconstruir.")


def build(session, with_runtime=False, tmpdir=None):
    host = diagnose(session)
    session.report["host"] = host
    if host["missing_packages"] or not host["rootfs_namespace_probe"]["available"]:
        raise BootstrapError("appliance-rootfs-preflight", "Host de construcción no preparado.",
                             "Ejecutar appliance-bootstrap y revisar su informe.")
    if host["rootfs_namespace_probe"]["mode"] != "mmdebstrap-unshare":
        raise BootstrapError("appliance-rootfs-preflight", "Se requiere la vía mmdebstrap sin root comprobada.",
                             "Ejecutar desde el usuario normal; no elevar todo GAIA con sudo.")
    keyring = Path(PROFILE["keyring"])
    if not keyring.is_file():
        raise BootstrapError("appliance-rootfs-keyring", "Falta el keyring de archivo Debian.",
                             "Instalar debian-archive-keyring del repositorio del host, sin omitir firmas.")
    # Conservative workspace budget, not a claimed minimum USB capacity.
    budget_gib = 32 if with_runtime else 8
    if host["disk_free_bytes"] < budget_gib * 2**30:
        raise BootstrapError("appliance-rootfs-space", f"La construcción requiere {budget_gib} GiB de presupuesto libre de trabajo.",
                             "Liberar espacio en el workspace antes de construir.")
    output = session.directory.resolve() / "rootfs.tar"
    temporary = select_tmpdir(with_runtime, tmpdir)
    session.report["build_tmpdir"] = temporary
    command = build_command(host["tools"]["mmdebstrap"], output)
    if with_runtime:
        hooks = runtime_hooks(session)
        command = [arg + "," + ",".join(BUILD_PACKAGES) if arg.startswith("--include=") else arg for arg in command]
        command[1:1] = hooks
    session.report.update(profile=PROFILE, keyring_sha256=sha256(keyring),
                          builder_source_sha256=sha256(Path(__file__)),
                          build_command=command, with_runtime=with_runtime,
                          build_host_versions=host["installed_versions"])
    session.save()
    env = {**os.environ, "TMPDIR": temporary["path"]}
    session.command("appliance-rootfs-build", command, env=env, timeout=1800, live=not with_runtime)
    contents = inspect_rootfs(output)
    if with_runtime and contents.get("runtime", {}).get("status") != "GAIA_RUNTIME_CPU_SMOKE_OK":
        raise ValueError("Falta smoke real del runtime en el rootfs")
    manifest = {"status": "DEBIAN_BASE_ROOTFS_BUILT", "profile": PROFILE,
                "rootfs_sha256": sha256(output), "rootfs_bytes": output.stat().st_size,
                "keyring_sha256": session.report["keyring_sha256"],
                "builder_source_sha256": session.report["builder_source_sha256"],
                "build_host_versions": host["installed_versions"], **contents,
                "pending": ["GAIA runtime and fixed Python dependencies", "NVIDIA profile",
                            "CORE/guardian", "A/B UEFI disk images", "offline policy and recovery",
                            "VM acceptance scenarios and signing for release"],
                "s1_complete": False, "bootable_media": False}
    if with_runtime:
        manifest.update(status="DEBIAN_RUNTIME_ROOTFS_BUILT", runtime_inputs=session.report["runtime_inputs"])
        manifest["pending"] = [item for item in manifest["pending"] if item != "GAIA runtime and fixed Python dependencies"]
        manifest["pending"].append("Remove build-only toolchain from release image")
    write_json(session.directory / "rootfs-manifest.json", manifest)
    session.report["artifact"] = {"path": str(output), "sha256": manifest["rootfs_sha256"],
                                  "manifest": "rootfs-manifest.json"}
    session.finish(manifest["status"])
    return 0


def main(root, args):
    parser = argparse.ArgumentParser(prog="gaia.py appliance-rootfs", description=__doc__)
    parser.add_argument("--with-runtime", action="store_true", help="compila Python 3.14.4 y crea un venv Torch/CUDA fijado dentro del rootfs")
    parser.add_argument("--tmpdir", type=Path, help="temporal existente; por defecto prueba TMPDIR y /var/tmp; runtime exige 16 GiB libres")
    options = parser.parse_args(args)
    session = Session(root)
    session.report["request"] = {"command": "appliance-rootfs", "profile": PROFILE["id"]}
    try:
        with locked(Path(root) / ".gaia/bootstrap.lock"):
            return build(session, with_runtime=options.with_runtime, tmpdir=options.tmpdir)
    except KeyboardInterrupt as exc:
        session.finish("INTERRUPTED", exc)
        return 130
    except Exception as exc:
        session.finish("FAILED", exc)
        return 40
