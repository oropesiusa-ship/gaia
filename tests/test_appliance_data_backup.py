"""DATA restore trust boundaries and exact content/role metadata recovery."""
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from gaia.appliance_vm_payload import data_backup as b


class TestDataBackup(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.backup = self.root / "DATA", self.root / "backup"
        self.source.mkdir()
        self.backup.mkdir()
        self.roles = {name: {"uid": os.getuid(), "gids": [os.getgid()]} for name in ("agent", "evidence")}
        for name in self.roles:
            (self.source / name).mkdir(mode=0o700)
        (self.source / "lost+found").mkdir()
        self.payload = self.source / "agent/payload.bin"
        self.payload.write_bytes(bytes(range(256)))
        self.payload.chmod(0o600)
        (self.source / "evidence/ledger.jsonl").write_text('confirmed evidence\n')

    def snap(self):
        return b.snapshot(self.source, self.backup, self.roles)

    def rewrite(self, record):
        (self.backup / "manifest.json").write_text(json.dumps(record))
        return b.digest(self.backup / "manifest.json")

    def test_restore_exact_content_modes_and_root_inodes(self):
        anchor = self.snap()
        expected = b.verify(self.backup, anchor, self.roles)
        before = {name: (self.source / name).stat().st_ino for name in self.roles}
        self.payload.write_bytes(b"corrupt")
        self.payload.chmod(0o644)
        extra = self.source / "agent/unconfirmed"
        extra.write_text("not in confirmed snapshot")
        with self.assertRaises(ValueError):
            b.check_tree(self.source, expected)
        b.restore(self.backup, self.source, anchor, self.roles)
        self.assertEqual(self.payload.read_bytes(), bytes(range(256)))
        self.assertEqual(self.payload.stat().st_mode & 0o777, 0o600)
        self.assertFalse(extra.exists())
        self.assertEqual(before, {name: (self.source / name).stat().st_ino for name in self.roles})

    def test_tampered_archive_and_manifest_do_not_touch_destination(self):
        anchor = self.snap()
        archive = self.backup / "data.tar"
        original = archive.read_bytes()
        self.payload.write_bytes(b"valuable current data")
        archive.write_bytes(original + b"tamper")
        with self.assertRaises(ValueError):
            b.restore(self.backup, self.source, anchor, self.roles)
        self.assertEqual(self.payload.read_bytes(), b"valuable current data")
        archive.write_bytes(original)
        record = json.loads((self.backup / "manifest.json").read_text())
        record["archive_sha256"] = "0" * 64
        self.rewrite(record)
        with self.assertRaises(ValueError):
            b.restore(self.backup, self.source, anchor, self.roles)
        self.assertEqual(self.payload.read_bytes(), b"valuable current data")

    def test_unsafe_paths_owners_permissions_and_duplicate_rows_rejected(self):
        anchor = self.snap()
        original = json.loads((self.backup / "manifest.json").read_text())
        for field, value in (("name", "../outside"), ("name", "agent/../../outside"),
                             ("uid", os.getuid() + 1), ("gid", os.getgid() + 1), ("mode", 0o4755)):
            record = json.loads(json.dumps(original))
            entry = next(row for row in record["entries"] if row["kind"] == "file")
            entry[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                b.verify(self.backup, self.rewrite(record), self.roles)
        record = json.loads(json.dumps(original))
        record["entries"].append(record["entries"][0])
        with self.assertRaises(ValueError):
            b.verify(self.backup, self.rewrite(record), self.roles)

    def test_no_symlink_or_hardlink_reads_and_budget_before_hash(self):
        escape = self.source / "agent/00-escape"
        escape.symlink_to("/must-not-be-opened")
        with patch.object(b, "digest") as checksum:
            with self.assertRaises(ValueError):
                self.snap()
            checksum.assert_not_called()
        escape.unlink()
        os.link(self.payload, escape)
        with self.assertRaises(ValueError):
            self.snap()
        escape.unlink()
        with patch.object(b, "MAX_BYTES", 4), patch.object(b, "digest") as checksum:
            with self.assertRaises(ValueError):
                self.snap()
            checksum.assert_not_called()
        self.assertFalse((self.backup / "data.tar").exists())

    def test_symlink_destination_does_not_escape(self):
        anchor = self.snap()
        outside = self.root / "outside"
        (self.source / "agent").rename(outside)
        (self.source / "agent").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            b.restore(self.backup, self.source, anchor, self.roles)
        self.assertEqual((outside / "payload.bin").read_bytes(), bytes(range(256)))

    def test_tar_link_device_duplicate_and_missing_members_rejected(self):
        self.snap()
        original = json.loads((self.backup / "manifest.json").read_text())
        for bad_type in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, "duplicate", "missing"):
            record = json.loads(json.dumps(original))
            with tarfile.open(self.backup / "data.tar", "w", format=tarfile.USTAR_FORMAT) as archive:
                for row in record["entries"]:
                    if row["name"] == "agent/payload.bin" and bad_type == "missing":
                        continue
                    info = tarfile.TarInfo(row["name"])
                    info.type = tarfile.DIRTYPE if row["kind"] == "directory" else tarfile.REGTYPE
                    info.uid, info.gid, info.mode, info.mtime, info.size = row["uid"], row["gid"], row["mode"], row["mtime"], row["bytes"]
                    if row["name"] == "agent/payload.bin" and bad_type in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE):
                        info.type, info.size, info.linkname = bad_type, 0, "/outside"
                    raw = (self.source / row["name"]).read_bytes() if info.type == tarfile.REGTYPE else None
                    archive.addfile(info, io.BytesIO(raw) if raw is not None else None)
                    if row["name"] == "agent/payload.bin" and bad_type == "duplicate":
                        archive.addfile(info, io.BytesIO(raw))
            record["archive_sha256"] = b.digest(self.backup / "data.tar")
            with self.subTest(type=bad_type), self.assertRaises(ValueError):
                b.restore(self.backup, self.source, self.rewrite(record), self.roles)
            self.assertEqual(self.payload.read_bytes(), bytes(range(256)))


if __name__ == "__main__":
    unittest.main()
