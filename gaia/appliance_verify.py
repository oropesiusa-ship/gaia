"""Verify signed artifact bundles using an owner-pinned public Ed25519 key only.

No private-key generation, signing, keyserver access or implicit trust enrollment.
Cryptographic verification does not close S1 or authorize physical installation.
"""
import argparse
import base64
import json
from pathlib import Path
import re
import shutil
import time

from .appliance_rootfs import sha256
from .bootstrap import BootstrapError, Session, locked


def fingerprint(value):
    value = value.replace(" ", "").upper()
    if not re.fullmatch(r"[0-9A-F]{40}", value):
        raise ValueError("Se requiere huella OpenPGP v4 completa (40 hex), confirmada por el propietario")
    return value


def public_packets(raw):
    """Gate packet types before handing material to GnuPG or writing any logs.

    This is not a cryptographic parser: GnuPG validates the key and gpgv validates
    the signature. Secret, compressed and encrypted containers are not accepted.
    """
    if raw.startswith(b"-----BEGIN"):
        lines = raw.strip().splitlines()
        if lines[0] != b"-----BEGIN PGP PUBLIC KEY BLOCK-----" or lines[-1] != b"-----END PGP PUBLIC KEY BLOCK-----":
            raise ValueError("Solo se acepta un bloque PUBLIC KEY OpenPGP")
        blank = lines.index(b"")
        raw = base64.b64decode(b"".join(line for line in lines[blank + 1:-1] if not line.startswith(b"=")), validate=True)
    position, primaries = 0, 0
    while position < len(raw):
        header = raw[position]
        position += 1
        if not header & 0x80:
            raise ValueError("Cabecera OpenPGP inválida")
        if header & 0x40:
            tag = header & 63
            if position >= len(raw):
                raise ValueError("Longitud OpenPGP truncada")
            first = raw[position]
            position += 1
            if first < 192:
                size = first
            elif first < 224:
                if position >= len(raw):
                    raise ValueError("Longitud OpenPGP truncada")
                size = (first - 192) * 256 + raw[position] + 192
                position += 1
            elif first == 255:
                if position + 4 > len(raw):
                    raise ValueError("Longitud OpenPGP truncada")
                size = int.from_bytes(raw[position:position + 4], "big")
                position += 4
            else:
                raise ValueError("Longitudes parciales no admitidas en la clave pública")
        else:
            tag = (header >> 2) & 15
            length_type = header & 3
            if length_type == 3:
                raise ValueError("Longitud OpenPGP indeterminada no admitida")
            width = (1, 2, 4)[length_type]
            if position + width > len(raw):
                raise ValueError("Longitud OpenPGP truncada")
            size = int.from_bytes(raw[position:position + width], "big")
            position += width
        if tag not in (2, 6, 13, 17):
            raise ValueError("Solo clave primaria pública: material secreto/subclaves/contenedores rechazados")
        primaries += tag == 6
        if position + size > len(raw):
            raise ValueError("Paquete OpenPGP truncado")
        position += size
    if primaries != 1:
        raise ValueError("Se requiere exactamente una clave primaria pública")
    return raw


def public_identity(listing, expected, now=None):
    rows = [line.split(":") for line in listing.splitlines()]
    public = [row for row in rows if row[0] == "pub"]
    fingerprints = [row[9] for row in rows if row[0] == "fpr" and len(row) > 9]
    if len(public) != 1 or fingerprints != [expected] or any(row[0] in ("sec", "ssb", "sub") for row in rows):
        raise ValueError("Identidad pública distinta de la huella fijada o clave ambigua")
    row = public[0]
    if len(row) < 17 or row[3] != "22" or "ed25519" not in row[14:] or "s" not in row[11].lower():
        raise ValueError("Se requiere la clave primaria Ed25519 OpenPGP de firma")
    if row[1] in ("r", "e", "d", "i") or row[6] and int(row[6]) <= (now if now is not None else time.time()):
        raise ValueError("Clave revocada, caducada, deshabilitada o inválida")


def valid_signature(status, expected):
    records = [line[len("[GNUPG:] "):].split() for line in status.splitlines() if line.startswith("[GNUPG:] ")]
    rejected = {"BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG", "KEYREVOKED", "KEYEXPIRED",
                "SIGEXPIRED", "NO_PUBKEY", "NODATA", "FAILURE", "BADARMOR"}
    valid = [row for row in records if row and row[0] == "VALIDSIG"]
    if any(row and row[0] in rejected for row in records) or len(valid) != 1:
        raise ValueError("Firma ausente, inválida, múltiple, revocada o caducada")
    row = valid[0]
    if (len(row) != 11 or row[1] != expected or row[10] != expected or row[7] != "22"
            or row[8] not in ("8", "9", "10") or row[9] != "00"):
        raise ValueError("Firmante, algoritmo o clase de firma no permitidos")


def regular_bytes(path, limit):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Se requiere archivo regular acotado, sin symlink: " + str(path))
    return path.read_bytes()


def unique_fields(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Campo JSON duplicado: " + name)
        result[name] = value
    return result


def verify_artifacts(manifest_bytes, directory, expected, purpose):
    manifest = json.loads(manifest_bytes, object_pairs_hook=unique_fields)
    if (manifest.get("schema") != "gaia-signed-artifacts-v1" or manifest.get("purpose") != purpose
            or manifest.get("signing_fingerprint") != expected):
        raise ValueError("Esquema, propósito o identidad del manifiesto no coinciden")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 128:
        raise ValueError("Se requiere lista no vacía y acotada de artefactos")
    seen, verified = set(), []
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Directorio de artefactos inválido")
    for entry in artifacts:
        name, size, digest = entry["name"], entry["bytes"], entry["sha256"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name) or name in seen:
            raise ValueError("Nombre de artefacto inseguro o duplicado")
        seen.add(name)
        if type(size) is not int or size < 0 or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Tamaño/hash inválidos")
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size or sha256(path) != digest:
            raise ValueError("Integridad de artefacto incorrecta: " + name)
        verified.append({"name": name, "bytes": size, "sha256": digest})
    return verified


def verify(session, public_key, expected, manifest, signature, directory, purpose, finish_report=True):
    expected = fingerprint(expected)
    # Inputs are snapshots: verify and consume precisely the signed bytes, even
    # if the supplied manifest path is changed during a long artifact check.
    raw_key = public_packets(regular_bytes(public_key, 1024 * 1024))
    raw_manifest = regular_bytes(manifest, 4 * 1024 * 1024)
    raw_signature = regular_bytes(signature, 1024 * 1024)
    tools = {name: shutil.which(name) for name in ("gpg", "gpgv")}
    if not all(tools.values()):
        raise BootstrapError("appliance-verify-tools", "Faltan gpg/gpgv", "Instalarlos en el entorno de verificación.")
    home = session.directory.resolve() / "public-only"
    home.mkdir(mode=0o700)
    keyring, staged_manifest, staged_signature = (home / name for name in ("public.gpg", "manifest.json", "manifest.asc"))
    keyring.write_bytes(raw_key)
    staged_manifest.write_bytes(raw_manifest)
    staged_signature.write_bytes(raw_signature)
    session.report.update(expected_fingerprint=expected, purpose=purpose, private_key_used=False,
        public_key_sha256=sha256(keyring), manifest_sha256=sha256(staged_manifest), signature_sha256=sha256(staged_signature))
    session.save()
    listing = session.command("public-identity", [tools["gpg"], "--batch", "--no-options", "--homedir", str(home),
        "--no-auto-key-retrieve", "--no-auto-check-trustdb", "--with-colons", "--show-keys", str(keyring)], timeout=30)
    public_identity(listing, expected)
    status = session.command("detached-signature", [tools["gpgv"], "--homedir", str(home), "--status-fd", "1",
        "--keyring", str(keyring), "--", str(staged_signature), str(staged_manifest)], timeout=30)
    valid_signature(status, expected)
    session.report["verified_artifacts"] = verify_artifacts(raw_manifest, directory, expected, purpose)
    session.report.update(s1_complete=False, installation_authorized=False)
    if finish_report:
        session.finish("SIGNED_ARTIFACTS_VERIFIED")
    else:
        session.save()


def main(root, args):
    parser = argparse.ArgumentParser(prog="gaia.py appliance-verify", description=__doc__)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--fingerprint", required=True, help="huella completa confirmada fuera del medio recibido")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--purpose", choices=("release", "lab"), default="release")
    options = parser.parse_args(args)
    session = Session(root)
    session.report["request"] = {"command": "appliance-verify"}
    try:
        with locked(Path(root) / ".gaia/bootstrap.lock"):
            verify(session, options.public_key, options.fingerprint, options.manifest, options.signature,
                   options.artifacts_dir, options.purpose)
        return 0
    except KeyboardInterrupt as exc:
        session.finish("INTERRUPTED", exc)
        return 130
    except Exception as exc:
        session.finish("FAILED", exc)
        return 40
