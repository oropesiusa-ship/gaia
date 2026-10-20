"""Public-only verification gates. No private keys are generated or loaded."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia import appliance_verify as v
from gaia.bootstrap import Session

FPR = "1234567890ABCDEF1234567890ABCDEF12345678"


def public_listing(fpr=FPR, algorithm="22", curve="ed25519", expiry=""):
    row = ["pub", "-", "255", algorithm, fpr[-16:], "1", expiry, "", "", "", "", "scSC", "", "", "", "", curve]
    return ":".join(row) + "\nfpr:::::::::" + fpr + ":\n"


def signature_status(fpr=FPR, algorithm="22", digest="8", kind="00"):
    return f"[GNUPG:] VALIDSIG {fpr} 2026-10-16 1792108800 0 4 0 {algorithm} {digest} {kind} {fpr}\n"


class TestApplianceVerify(unittest.TestCase):
    def test_public_packet_gate_rejects_secrets_subkeys_and_containers(self):
        for tag in (5, 7, 8, 9, 14, 18):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                v.public_packets(bytes([0xC0 | tag, 0]))
        public = bytes([0xC6, 1, 4, 0xCD, 1, 65])
        self.assertEqual(v.public_packets(public), public)
        armored = b"-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n" + base64.b64encode(public) + b"\n-----END PGP PUBLIC KEY BLOCK-----"
        self.assertEqual(v.public_packets(armored), public)
        for raw in (b"", public + public, b"\xc6\x05x", b"\x99\x00\x10x"):
            with self.assertRaises(ValueError):
                v.public_packets(raw)

    def test_owner_pin_cannot_be_short_key_id_or_changed_primary(self):
        self.assertEqual(v.fingerprint(FPR.lower()), FPR)
        for bad in (FPR[-16:], "G" * 40, ""):
            with self.assertRaises(ValueError):
                v.fingerprint(bad)
        v.public_identity(public_listing(), FPR)
        with self.assertRaises(ValueError):
            v.public_identity(public_listing("0" * 40), FPR)

    def test_wrong_curve_algorithm_expired_or_revoked_key_rejected(self):
        listings = (public_listing(algorithm="1"), public_listing(curve="cv25519"),
                    public_listing(expiry="2"), public_listing().replace("pub:-:", "pub:r:"))
        for listing in listings:
            with self.assertRaises(ValueError):
                v.public_identity(listing, FPR, now=3)

    def test_status_gate_rejects_other_signer_multiple_expired_weak_or_text_sig(self):
        good = signature_status()
        v.valid_signature(good, FPR)
        for bad in ("", good + good, good + "[GNUPG:] EXPKEYSIG example\n", signature_status("0" * 40),
                    signature_status(algorithm="1"), signature_status(digest="2"), signature_status(kind="01")):
            with self.assertRaises(ValueError):
                v.valid_signature(bad, FPR)

    def manifest(self, path):
        return {"schema": "gaia-signed-artifacts-v1", "purpose": "release", "signing_fingerprint": FPR,
                "artifacts": [{"name": path.name, "bytes": path.stat().st_size, "sha256": v.sha256(path)}]}

    def test_authenticated_artifact_tamper_and_lab_release_confusion_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.raw"
            path.write_bytes(b"fixture artifact")
            raw = json.dumps(self.manifest(path)).encode()
            self.assertEqual(v.verify_artifacts(raw, Path(directory), FPR, "release")[0]["name"], path.name)
            with self.assertRaises(ValueError):
                v.verify_artifacts(raw, Path(directory), FPR, "lab")
            path.write_bytes(b"tampered artifact")
            with self.assertRaises(ValueError):
                v.verify_artifacts(raw, Path(directory), FPR, "release")

    def test_escape_symlink_duplicate_empty_and_duplicate_json_fields_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.raw"
            path.write_bytes(b"fixture artifact")
            original = self.manifest(path)
            for name in ("../disk.raw", "/etc/passwd", "a/b", ".."):
                manifest = self.manifest(path)
                manifest["artifacts"][0]["name"] = name
                with self.assertRaises(ValueError):
                    v.verify_artifacts(json.dumps(manifest).encode(), Path(directory), FPR, "release")
            for entries in ([], original["artifacts"] * 2):
                with self.assertRaises(ValueError):
                    v.verify_artifacts(json.dumps({**original, "artifacts": entries}).encode(), Path(directory), FPR, "release")
            raw = json.dumps(original).replace('"purpose": "release"', '"purpose": "lab", "purpose": "release"').encode()
            with self.assertRaises(ValueError):
                v.verify_artifacts(raw, Path(directory), FPR, "release")
            real = path.with_name("real.raw")
            path.rename(real)
            path.symlink_to(real)
            with self.assertRaises(ValueError):
                v.verify_artifacts(json.dumps(original).encode(), Path(directory), FPR, "release")

    def test_no_artifact_consumption_before_cryptographic_and_owner_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public, manifest, signature = [root / name for name in ("public.gpg", "manifest.json", "sig.asc")]
            # Packet-shaped public input is deliberately not a real key.
            public.write_bytes(bytes([0xC6, 1, 4]))
            manifest.write_text("{}")
            signature.write_text("not a signature")
            session = Session(root)
            with patch.object(session, "command", return_value=public_listing("0" * 40)) as command, \
                    patch.object(v, "verify_artifacts") as artifacts:
                with self.assertRaises(ValueError):
                    v.verify(session, public, FPR, manifest, signature, root, "release")
                self.assertEqual(command.call_count, 1)
                artifacts.assert_not_called()
            other = Session(root)
            with patch.object(other, "command", side_effect=[public_listing(), ""]) as command, \
                    patch.object(v, "verify_artifacts") as artifacts:
                with self.assertRaises(ValueError):
                    v.verify(other, public, FPR, manifest, signature, root, "release")
                self.assertEqual(command.call_count, 2)
                artifacts.assert_not_called()

    def test_rejects_secret_packet_before_any_external_command_or_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "not-public.gpg"
            path.write_bytes(b"\xc5\x00")  # packet tag only, no secret material
            session = Session(root)
            with patch.object(session, "command") as command:
                with self.assertRaises(ValueError):
                    v.verify(session, path, FPR, path, path, root, "release")
                command.assert_not_called()
                self.assertFalse((session.directory / "public-only").exists())


if __name__ == "__main__":
    unittest.main()
