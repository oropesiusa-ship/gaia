"""Human-terminal provisioning of the two explicitly authorized custody USBs.

Creates LUKS2/ext4 only. Never generates keys, reads passphrases or opens an
existing LUKS volume. Exact local identities live in ignored .gaia/ configuration.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
TOOLS = {
    "sudo": "/usr/bin/sudo", "lsblk": "/usr/bin/lsblk",
    "cryptsetup": "/usr/sbin/cryptsetup", "wipefs": "/usr/sbin/wipefs",
    "mkfs": "/usr/sbin/mkfs.ext4", "mount": "/usr/bin/mount", "umount": "/usr/bin/umount",
    "e2fsck": "/usr/sbin/e2fsck",
    "chown": "/usr/bin/chown", "chmod": "/usr/bin/chmod", "sync": "/usr/bin/sync",
    "udevadm": "/usr/bin/udevadm",
}
ROLES = {
    "primary": ("gaia-signing-primary", "GAIA-SIGNING-PRIMARY", "GAIA-KEY-PRIMARY"),
    "backup": ("gaia-signing-backup", "GAIA-SIGNING-BACKUP", "GAIA-KEY-BACKUP"),
}


def inventory():
    # With PATH but no NAME column, lsblk JSON is flat unless --tree is explicit.
    # descendants() must see mounted partitions before any destructive command.
    raw = subprocess.check_output([TOOLS["lsblk"], "--json", "--tree", "--bytes", "--output",
        "PATH,TYPE,TRAN,MODEL,SERIAL,SIZE,RO,FSTYPE,LABEL,MOUNTPOINTS"], text=True)
    return json.loads(raw)["blockdevices"]


def descendants(node):
    yield node
    for child in node.get("children", []):
        yield from descendants(child)


def match_target(expected, devices):
    matches = [d for d in devices if d.get("serial") == expected["serial"]]
    if len(matches) != 1:
        raise ValueError("USB ausente o identidad ambigua; no se usa etiqueta ni /dev/sdX como alternativa")
    device = matches[0]
    if (device.get("type") != "disk" or device.get("tran") != "usb" or device.get("ro")
            or device.get("size") != expected["bytes"] or device.get("model", "").strip() != expected["model"]):
        raise ValueError("No coincide tipo/conexión/capacidad/modelo del USB autorizado")
    for child in descendants(device):
        if child.get("fstype") == "crypto_LUKS" or child.get("type") in ("crypt", "lvm", "raid1", "raid0"):
            raise ValueError("Existe cifrado/mapper: se protege lo ya preparado; no se reformatea")
        for mount in child.get("mountpoints") or []:
            if mount and (ROOT.is_relative_to(Path(mount)) or Path.home().is_relative_to(Path(mount))
                          or mount in ("/", "/boot", "/boot/efi", "/usr", "/var", "/home")):
                raise ValueError("USB contiene un filesystem esencial o el proyecto: operación rechazada")
    by_id = Path(expected["by_id"])
    if not str(by_id).startswith("/dev/disk/by-id/usb-") or not by_id.is_block_device():
        raise ValueError("No existe la ruta estable USB autorizada")
    if str(by_id.resolve()) != device["path"]:
        raise ValueError("Ruta by-id e identidad de lsblk no coinciden")
    return device


def root_command(args, check=True):
    # No capture_output/stdin redirection: sudo and cryptsetup own the terminal.
    return subprocess.run([TOOLS["sudo"], "--", *map(str, args)], check=check)


def prepare(role, expected):
    device = match_target(expected, inventory())
    mapper, luks_label, fs_label = ROLES[role]
    if Path("/dev/mapper", mapper).exists():
        raise ValueError("Nombre de mapper ya ocupado; no se cierra un volumen ajeno")
    print(f"\n{role}: {device['path']} — {device['model']} — {device['size']} bytes — serie {device['serial']}", flush=True)
    print("cryptsetup solicitará confirmación y contraseña LUKS directamente. No se generará ninguna clave GPG.", flush=True)
    # Detect on-disk LUKS even when the unprivileged udev cache is stale.
    result = root_command([TOOLS["cryptsetup"], "isLuks", expected["by_id"]], check=False)
    if result.returncode == 0:
        raise ValueError("El USB ya es LUKS: se conserva; no se reformatea")
    if result.returncode != 1:
        raise ValueError("No se pudo comprobar con certeza si el USB ya es LUKS")
    for child in reversed(list(descendants(device))):
        if any(child.get("mountpoints") or []):
            root_command([TOOLS["umount"], "--", child["path"]])
    device = match_target(expected, inventory())
    if any(any(child.get("mountpoints") or []) for child in descendants(device)):
        raise ValueError("Quedan montajes en el USB; no se borra")
    root_command([TOOLS["wipefs"], "--all", expected["by_id"]])
    root_command([TOOLS["udevadm"], "settle"])
    match_target(expected, inventory())
    root_command([TOOLS["cryptsetup"], "luksFormat", "--type", "luks2", "--pbkdf", "argon2id",
                  "--label", luks_label, expected["by_id"]])
    opened = False
    mounted = False
    mountpoint = tempfile.mkdtemp(prefix="gaia-empty-key-usb-")
    try:
        # This is only the LUKS container created immediately above. An
        # existing encrypted container is never opened by this procedure.
        root_command([TOOLS["cryptsetup"], "open", expected["by_id"], mapper])
        opened = True
        mapped = "/dev/mapper/" + mapper
        root_command([TOOLS["mkfs"], "-L", fs_label, mapped])
        root_command([TOOLS["e2fsck"], "-f", "-n", mapped])
        root_command([TOOLS["mount"], "-o", "nodev,nosuid,noexec", mapped, mountpoint])
        mounted = True
        root_command([TOOLS["chown"], f"{os.getuid()}:{os.getgid()}", mountpoint])
        root_command([TOOLS["chmod"], "0700", mountpoint])
        info = Path(mountpoint).stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o777 != 0o700:
            raise ValueError("No se pudieron establecer los permisos de custodia")
        root_command([TOOLS["sync"], "-f", mountpoint])
        root_command([TOOLS["umount"], mountpoint])
        mounted = False
        root_command([TOOLS["cryptsetup"], "close", mapper])
        opened = False
    finally:
        if mounted:
            # Never recursively delete a still-mounted filesystem, even when a
            # root command fails or the human cancels the operation.
            cleanup = root_command([TOOLS["umount"], mountpoint], check=False)
            if cleanup.returncode:
                raise RuntimeError("No se pudo desmontar; se conserva el montaje en " + mountpoint)
        if opened:
            root_command([TOOLS["cryptsetup"], "close", mapper], check=False)
        shutil.rmtree(mountpoint)
    # Metadata only, no unlocking or reading custody content.
    root_command([TOOLS["cryptsetup"], "isLuks", expected["by_id"]])
    if Path("/dev/mapper", mapper).exists():
        raise ValueError("El mapper sigue abierto; revisar antes de retirar el USB")
    print(f"{role}: LUKS2 + ext4 preparados, raíz accesible solo al propietario y volumen cerrado.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("both", "primary", "backup"), default="both")
    parser.add_argument("--check-only", action="store_true", help="solo identidad; sin sudo, formateo ni montaje")
    args = parser.parse_args()
    state = {"status": "running", "prepared": [], "private_keys_generated": False}
    report = ROOT / ".gaia/signing-usb-preparation.json"
    lock = None
    try:
        lock = (ROOT / ".gaia/signing-usb-preparation.lock").open("a")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        expected = json.loads((ROOT / ".gaia/signing-usb-targets.json").read_text())
        if set(expected) != set(ROLES) or expected["primary"]["serial"] == expected["backup"]["serial"]:
            raise ValueError("Configuración local de identidades inválida")
        roles = list(ROLES) if args.role == "both" else [args.role]
        state["roles_requested"] = roles
        devices = inventory()
        for role in roles:
            device = match_target(expected[role], devices)
            print(f"Identidad {role} correcta: {device['path']}, serie …{device['serial'][-4:]}, {device['size']} bytes.")
        if args.check_only:
            return 0
        if os.geteuid() == 0:
            raise ValueError("Ejecutar como usuario normal; solo las herramientas concretas reciben sudo")
        if not all(os.isatty(fd) for fd in (0, 1, 2)):
            raise ValueError("Se necesita terminal local para sudo y las contraseñas LUKS; no se leen por el agente")
        missing = [path for path in TOOLS.values() if not os.access(path, os.X_OK)]
        if missing:
            raise ValueError("Herramientas ausentes: " + ", ".join(missing))
        subprocess.run([TOOLS["sudo"], "-v"], check=True)
        for role in roles:
            prepare(role, expected[role])
            state["prepared"].append(role)
            report.write_text(json.dumps(state, indent=2) + "\n")
        state["status"] = "CUSTODY_USB_PREPARED"
        report.write_text(json.dumps(state, indent=2) + "\n")
        print("Preparación completa. Los USB procesados quedan cerrados. Continúa con la generación humana de la clave.")
        return 0
    except BlockingIOError:
        print("PARADA: otra preparación USB está activa.", file=sys.stderr)
        return 10
    except (Exception, KeyboardInterrupt) as exc:
        state.update(status="STOPPED", reason=str(exc))
        report.write_text(json.dumps(state, indent=2) + "\n")
        print("PARADA: " + str(exc), file=sys.stderr)
        return 10
    finally:
        if lock is not None:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
