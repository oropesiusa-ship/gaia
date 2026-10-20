"""Public OpenPGP checks inside Debian using its native apt verifier (sqv)."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_signature(manifest, signature):
    config = json.loads(Path("/core/owner-trust.json").read_text())
    key = Path("/core/owner-public.pgp")
    if file_hash(key) != config["public_key_sha256"]:
        raise ValueError("Pinned public key content changed")
    result = subprocess.run(["/usr/bin/sqv", "--keyring", str(key), "--signature-file", str(signature), str(manifest)],
        text=True, capture_output=True, timeout=30,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "HOME": "/run"})
    if result.returncode:
        raise ValueError("Public signature rejected by sqv: " + result.stderr)
    fingerprints = [line.strip().upper() for line in result.stdout.splitlines() if line.strip()]
    if fingerprints != [config["fingerprint"]]:
        raise ValueError("Unexpected signature identity or ambiguous signature")
    return config["fingerprint"]


def custody_check():
    config = json.loads(Path("/core/owner-trust.json").read_text())
    manifest, signature = Path("/core/owner-proof.json"), Path("/core/owner-proof.asc")
    if file_hash(manifest) != config["proof_manifest_sha256"]:
        raise ValueError("Custody proof differs from pinned public challenge")
    identity = verify_signature(manifest, signature)
    record = json.loads(manifest.read_text())
    if record["purpose"] != "lab" or record["signing_fingerprint"] != identity:
        raise ValueError("Incorrect custody proof context")
    return {"status": "OWNER_PUBLIC_SIGNATURE_OK", "fingerprint": identity, "backend": "sqv", "private_key_used": False}
