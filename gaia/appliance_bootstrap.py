"""Preparación interactiva del host de construcción; solo biblioteca estándar.

No construye imágenes ni escribe discos físicos. Solo apt-get recibe privilegios.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time

from .bootstrap import BootstrapError, Session, _read, locked


PACKAGES = {
    "mmdebstrap": ("mmdebstrap",),
    "qemu-system-x86": ("qemu-system-x86_64",),
    "qemu-utils": ("qemu-img", "qemu-io"),
    "ovmf": (),
    "uidmap": ("newuidmap", "newgidmap"),
    "smartmontools": ("smartctl",),
    "mtools": ("mformat", "mcopy", "mmd", "mren", "mdir"),
    "dosfstools": ("mkfs.vfat",),
    "e2fsprogs": ("mkfs.ext4", "e2fsck", "debugfs"),
    "binutils": ("objcopy",),
    "fdisk": ("sfdisk",),
}
REASONS = {
    "mmdebstrap": "construcción del rootfs Debian",
    "qemu-system-x86": "arranque y recuperación en VM x86_64",
    "qemu-utils": "imágenes de disco virtuales",
    "ovmf": "firmware UEFI para las VM",
    "uidmap": "mapeos de usuario para construcción sin root",
    "smartmontools": "diagnóstico SMART previo a instalación física",
    "mtools": "preparación de imágenes FAT sin montarlas",
    "dosfstools": "creación de sistemas FAT para imágenes UEFI",
    "e2fsprogs": "construcción y verificación ext4 sobre archivos de imagen",
    "binutils": "ensamblado de UKI UEFI desde kernel/initramfs fijados",
    "fdisk": "verificación de la tabla GPT de discos virtuales",
}
FIRMWARE_PAIRS = (
    ("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
    ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"),
)


def os_release():
    result = {}
    for line in (_read("/etc/os-release") or "").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            result[key] = " ".join(shlex.split(value))
    return result


def diagnose(session):
    release = os_release()
    if platform.system() != "Linux" or release.get("ID") not in ("debian", "ubuntu"):
        raise BootstrapError("appliance-host", "Host admitido: Debian/Ubuntu Linux.",
                             "Usar un host de construcción Debian/Ubuntu; no se cambia de gestor automáticamente.")
    if platform.machine() not in ("x86_64", "amd64"):
        raise BootstrapError("appliance-host", "El perfil inicial de construcción requiere x86_64.",
                             "Usar el host x86_64 acordado para F1.")
    query = ["/usr/bin/dpkg-query", "-W", "-f=${binary:Package}\t${Status}\t${Version}\n", *PACKAGES]
    try:
        raw = session.command("appliance-packages", query, timeout=30)
    except BootstrapError:
        step = session.report["steps"][-1]
        if step.get("returncode") != 1:  # dpkg-query: some requested packages are absent.
            raise
        raw = (session.directory / step["stdout"]).read_text()
    installed = {}
    for line in raw.splitlines():
        fields = line.split("\t")
        if len(fields) == 3 and fields[1].split()[-2:] == ["ok", "installed"]:
            installed[fields[0].split(":")[0]] = fields[2]
    search_path = os.pathsep.join((os.defpath, "/usr/sbin", "/sbin"))
    tools = {name: shutil.which(name, path=search_path) for names in PACKAGES.values() for name in names}
    firmware = next(([code, variables] for code, variables in FIRMWARE_PAIRS
                     if all(os.access(p, os.R_OK) for p in (code, variables))), None)
    missing = [package for package, names in PACKAGES.items()
               if package not in installed or any(not tools[name] for name in names)
               or (package == "ovmf" and not firmware)]
    namespace = {"available": False, "mode": "root" if os.geteuid() == 0 else "unshare"}
    unshare = shutil.which("unshare", path=search_path)
    if unshare:
        try:
            flags = [] if os.geteuid() == 0 else ["--user", "--map-root-user"]
            session.command("appliance-userns", [unshare, *flags, "--mount", "true"], timeout=10)
            namespace["available"] = True
        except BootstrapError as exc:
            namespace["reason"] = str(exc)
    else:
        namespace["reason"] = "unshare no disponible"
    # Ubuntu may grant userns to mmdebstrap's AppArmor profile while denying the
    # generic unshare executable. Test the builder's own mapped-user namespace
    # and a mount namespace, rather than requiring a global policy change.
    mmdebstrap = tools["mmdebstrap"]
    if mmdebstrap and unshare and os.geteuid() != 0:
        generic = dict(namespace)
        namespace = {"available": False, "mode": "mmdebstrap-unshare", "generic_probe": generic}
        try:
            session.command("appliance-mmdebstrap-userns", [mmdebstrap, "--unshare-helper", unshare,
                            "--mount", "/usr/bin/true"], timeout=30)
            namespace["available"] = True
        except BootstrapError as exc:
            namespace["reason"] = str(exc)
    # Metadata only, no serial/WWN/hostname or foreign-volume contents in reports.
    media = {"devices": [], "status": "unavailable"}
    lsblk = shutil.which("lsblk", path=search_path)
    if lsblk:
        try:
            raw_media = session.command("appliance-media-inventory", [lsblk, "--json", "--bytes", "--nodeps",
                                        "--output", "TYPE,TRAN,MODEL,SIZE,RO"], timeout=10)
            media = {"devices": json.loads(raw_media)["blockdevices"], "status": "observed"}
        except (BootstrapError, ValueError, KeyError) as exc:
            media["reason"] = str(exc)
    return {"os": {key: release.get(key) for key in ("ID", "VERSION_ID", "PRETTY_NAME")},
            "architecture": platform.machine(), "disk_free_bytes": shutil.disk_usage(session.root).free,
            "installed_versions": installed, "tools": tools, "ovmf": firmware,
            "missing_packages": missing, "kvm_access_rw": os.access("/dev/kvm", os.R_OK | os.W_OK),
            "uefi_detected": Path("/sys/firmware/efi").is_dir(), "media_inventory": media,
            "rootfs_namespace_probe": namespace}


def installation_commands(packages):
    if not packages or any(p not in PACKAGES for p in packages):
        raise ValueError("Solo se instalan paquetes del catálogo del host appliance")
    prefix = [] if os.geteuid() == 0 else ["/usr/bin/sudo", "--"]
    return [prefix + ["/usr/bin/apt-get", "update", "--error-on=any"],
            prefix + ["/usr/bin/apt-get", "install", "--no-install-recommends", "--no-remove", "--yes", *packages]]


def terminal_command(session, command):
    # Inherit the terminal directly: neither password nor terminal output is piped
    # into GAIA. The JSON records only fixed argv, duration and process exit status.
    step = {"stage": "appliance-host-install", "command": command, "io": "inherited-terminal"}
    session.report["steps"].append(step)
    session.save()
    start = time.monotonic()
    try:
        result = subprocess.run(command, cwd="/", check=False)
        step["returncode"] = result.returncode
        if result.returncode:
            raise BootstrapError("appliance-host-install", f"apt/sudo terminó con código {result.returncode}.",
                                 "Revisar la salida del terminal y reejecutar appliance-bootstrap; no se ocultan instalaciones parciales.")
    except KeyboardInterrupt:
        step["interrupted"] = True
        raise
    finally:
        step["seconds"] = round(time.monotonic() - start, 2)
        session.save()


def run(session, preflight=False):
    before = diagnose(session)
    session.report["before"] = before
    print(f"Host {before['os']['ID']} {before['architecture']}; "
          f"espacio libre {before['disk_free_bytes'] / 2**30:.1f} GiB; "
          f"KVM {'accesible' if before['kvm_access_rw'] else 'no accesible'}.")
    if not before["rootfs_namespace_probe"]["available"]:
        print("El probe de namespaces para construir rootfs está bloqueado; se registra como requisito pendiente.")
    missing = before["missing_packages"]
    if missing:
        commands = installation_commands(missing)
        session.report["proposed_commands"] = commands
        for package in missing:
            print(f"  {package}: {REASONS[package]}")
        for command in commands:
            print("  " + shlex.join(command))
        if preflight:
            session.finish("APPLIANCE_HOST_PACKAGES_MISSING")
            return 10
        if not (sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty()):
            session.report["next_action"] = "Ejecutar python3 gaia.py appliance-bootstrap en una terminal interactiva."
            print(session.report["next_action"])
            session.finish("NEEDS_INTERACTIVE_TERMINAL")
            return 10
        print("Se instalarán herramientas en el host actual. La appliance llevará su propio runtime fijado.")
        print("sudo solicitará la contraseña directamente en tu terminal; GAIA no la recibe.")
        answer = input("¿Instalar los paquetes mostrados? [s/N]: ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            session.finish("CANCELLED")
            return 130
        session.report["installation_confirmed"] = True
        session.save()
        for command in commands:
            terminal_command(session, command)
        after = diagnose(session)
    else:
        after = before
    session.report["after"] = after
    if after["missing_packages"]:
        raise BootstrapError("appliance-host-check", "Siguen faltando herramientas/firmware tras apt.",
                             "Consultar after.missing_packages y reparar la instalación; no se marca como preparada.")
    for stage, command in (("appliance-mmdebstrap-version", [after["tools"]["mmdebstrap"], "--version"]),
                           ("appliance-qemu-version", [after["tools"]["qemu-system-x86_64"], "--version"]),
                           ("appliance-qemu-img-version", [after["tools"]["qemu-img"], "--version"])):
        session.command(stage, command, timeout=30)
    session.report["host_tools_ready"] = True
    session.report["next_action"] = "Continuar implementación y ensayos S1; no hay constructor de imagen invocado por este comando."
    if not after["rootfs_namespace_probe"]["available"]:
        session.report["next_action"] = "Herramientas listas; definir ejecución delimitada del constructor privilegiado o resolver la vía rootless antes de construir."
        print(session.report["next_action"])
        session.finish("APPLIANCE_HOST_TOOLS_READY_ROOTFS_BLOCKED")
        return 10
    session.finish("APPLIANCE_HOST_READY")
    return 0


def main(root, args):
    parser = argparse.ArgumentParser(prog=f"{Path(sys.argv[0]).name} appliance-bootstrap", description=__doc__)
    parser.add_argument("--preflight", action="store_true", help="solo diagnóstico e informe; no instala ni pide contraseña")
    options = parser.parse_args(args)
    session = Session(root)
    session.report.update(request={"command": "appliance-bootstrap", "preflight": options.preflight},
                          scope="build-host-only", installation_confirmed=False)
    try:
        with locked(Path(root) / ".gaia/bootstrap.lock"):
            return run(session, preflight=options.preflight)
    except (KeyboardInterrupt, EOFError) as exc:
        session.finish("INTERRUPTED", exc)
        return 130
    except Exception as exc:
        session.finish("FAILED", exc)
        return 40
