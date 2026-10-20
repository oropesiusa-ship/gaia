"""Disk format, trust checks and VM result gates; no guest boot in unit tests."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zlib

from gaia import appliance_image as image, appliance_image_build as assembler
from gaia.bootstrap import Session
from gaia.appliance_vm_scenarios import extract_esp, prepare_esp


class TestApplianceImage(unittest.TestCase):
    def test_repeated_esp_preparation_never_reuses_unix_mcopy_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payloads = {"a": b"public EFI fixture A", "b": b"public EFI fixture B"}
            original = {"uki_directory": "EFI/GAIA", "uki_sha256": {
                slot.upper(): assembler.hashlib.sha256(data).hexdigest() for slot, data in payloads.items()}}
            destinations = []
            def command(stage, args, **kwargs):
                if stage.startswith("verify-staged-uki-"):
                    slot = stage[-1]
                    output = Path(args[-1])
                    if output.exists():
                        raise AssertionError("Unix destination exists: mcopy would ask for overwrite")
                    output.write_bytes(payloads[slot])
                    destinations.append(output)
            session = SimpleNamespace(directory=root, command=command)
            for _ in range(2):
                self.assertEqual(prepare_esp(session, {"mcopy": "mcopy"}, original, root / "esp.fat", "normal-A"), original["uki_sha256"])
            self.assertEqual(len(set(destinations)), 4)

    def test_esp_range_exact_with_qemu_absolute_or_normal_dd_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "disk"
            raw = b"prefix".ljust(1024, b"p") + bytes(range(256)) * 8 + b"suffix".ljust(2048, b"s")
            source.write_bytes(raw)
            part = {"start": 2, "sectors": 4, "bytes": 2048}
            target = root / "esp.fat"
            for semantics in ("absolute", "normal"):
                def command(stage, args, **kwargs):
                    options = dict(arg.split("=", 1) for arg in args if "=" in arg)
                    skip, count, bs = int(options["skip"]), int(options["count"]), int(options["bs"])
                    end = (count if semantics == "absolute" else skip + count) * bs
                    Path(options["of"]).write_bytes(source.read_bytes()[skip * bs:end])
                with self.subTest(semantics=semantics):
                    extract_esp(SimpleNamespace(command=command), {"qemu-img": "qemu-img"}, source, target, part)
                    self.assertEqual(target.read_bytes(), raw[1024:3072])

    def test_gpt_primary_backup_checksums_and_partition_bounds(self):
        parts = image.partition_spec(1024)
        sectors = assembler.gpt_layout(parts)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disk.raw"
            assembler.write_gpt(path, parts, sectors)
            with path.open("rb") as stream:
                self.assertEqual(stream.read(512)[510:], b"\x55\xaa")
                primary = stream.read(512)
                entries = stream.read(128 * 128)
                stream.seek((sectors - 1) * 512)
                backup = stream.read(512)
            for raw, lba, other in ((primary, 1, sectors - 1), (backup, sectors - 1, 1)):
                self.assertEqual(raw[:8], b"EFI PART")
                header = bytearray(raw[:92])
                stored = struct.unpack_from("<I", header, 16)[0]
                struct.pack_into("<I", header, 16, 0)
                self.assertEqual(zlib.crc32(header), stored)
                self.assertEqual(struct.unpack_from("<QQ", raw, 24), (lba, other))
                self.assertEqual(struct.unpack_from("<I", raw, 88)[0], zlib.crc32(entries))
            for i, part in enumerate(parts):
                start, end = struct.unpack_from("<QQ", entries, i * 128 + 32)
                self.assertEqual(start, part["start"])
                self.assertEqual(end - start + 1, part["sectors"])
                self.assertLess(end, sectors - 34)

    def test_pe_sections_after_stub_with_alignment_and_nonzero_imagebase(self):
        stub = bytearray(512)
        struct.pack_into("<I", stub, 60, 64)
        stub[64:68] = b"PE\0\0"
        struct.pack_into("<H", stub, 70, 1)
        struct.pack_into("<H", stub, 84, 112)
        struct.pack_into("<H", stub, 88, 0x20B)
        struct.pack_into("<Q", stub, 112, 0x100000)
        struct.pack_into("<I", stub, 120, 0x1000)
        struct.pack_into("<III", stub, 208, 0x1200, 0x2000, 0x1400)
        sections = assembler.uki_sections(stub, [(".linux", 0x12345), (".initrd", 0x23456)])
        self.assertEqual(sections[".linux"], 0x104000)
        self.assertGreaterEqual(sections[".initrd"], sections[".linux"] + 0x12345)
        self.assertEqual(sections[".initrd"] % 0x1000, 0)

    def test_sparse_embedding_does_not_overwrite_partition_neighbors(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = [Path(directory) / name for name in ("source", "target")]
            assembler.new_file(source, 4 * assembler.MIB)
            with source.open("r+b") as stream:
                stream.seek(assembler.MIB)
                stream.write(b"payload")
            assembler.new_file(target, 6 * assembler.MIB)
            with target.open("r+b") as stream:
                stream.write(b"prefix")
                stream.seek(5 * assembler.MIB)
                stream.write(b"suffix")
            assembler.sparse_copy(source, target, assembler.MIB)
            with target.open("rb") as stream:
                self.assertEqual(stream.read(6), b"prefix")
                stream.seek(2 * assembler.MIB)
                self.assertEqual(stream.read(7), b"payload")
                stream.seek(5 * assembler.MIB)
                self.assertEqual(stream.read(6), b"suffix")

    def test_altered_runtime_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "rootfs.tar").write_bytes(b"altered")
            manifest = directory / "rootfs-manifest.json"
            manifest.write_text(json.dumps({"status": "DEBIAN_RUNTIME_ROOTFS_BUILT", "rootfs_bytes": 7, "rootfs_sha256": "0" * 64}))
            with patch.object(image, "inspect_rootfs") as inspect:
                with self.assertRaisesRegex(ValueError, "integrity"):
                    image.verified_source(manifest)
                inspect.assert_not_called()

    def test_fragmented_small_extents_preserve_every_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = [Path(directory) / name for name in ("source", "target")]
            assembler.new_file(source, 4 * assembler.MIB)
            with source.open("r+b") as stream:
                for index, offset in enumerate((0, 8192, 32768, 131072, assembler.MIB + 4096)):
                    stream.seek(offset)
                    stream.write(bytes([index + 1]) * 4096)
            assembler.new_file(target, 6 * assembler.MIB)
            assembler.sparse_copy(source, target, assembler.MIB)
            with target.open("rb") as stream:
                stream.seek(assembler.MIB)
                self.assertEqual(stream.read(4 * assembler.MIB), source.read_bytes())

    def test_no_guest_success_from_qemu_exit_alone_or_duplicate_marker(self):
        good = 'GAIA_VM_RESULT={"status":"VM_FOUNDATION_OK"}\n'
        self.assertEqual(image.vm_result(good)["status"], "VM_FOUNDATION_OK")
        for log in ("Power down", good + good, 'GAIA_VM_RESULT={"status":"failed"}\n'):
            with self.assertRaises(ValueError):
                image.vm_result(log)

    def test_pe_commandline_read_respects_virtual_length_and_bounds(self):
        raw = bytearray(512)
        struct.pack_into("<I", raw, 60, 64)
        raw[64:68] = b"PE\0\0"
        struct.pack_into("<H", raw, 70, 1)
        struct.pack_into("<H", raw, 84, 112)
        struct.pack_into("<H", raw, 88, 0x20B)
        raw[200:208] = b".cmdline"
        struct.pack_into("<I", raw, 208, 7)
        struct.pack_into("<I", raw, 220, 400)
        raw[400:407] = b"slot=A\0"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.efi"
            path.write_bytes(raw)
            self.assertEqual(image.pe_section(path, ".cmdline"), b"slot=A\0")
            struct.pack_into("<I", raw, 208, 4096)
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, "Truncated"):
                image.pe_section(path, ".cmdline")

    def test_namespace_helper_rejects_host_namespace_before_creating_files(self):
        with patch.object(assembler.os, "geteuid", return_value=0), \
                patch.object(assembler.os, "readlink", return_value="same"):
            with self.assertRaisesRegex(ValueError, "namespace"):
                assembler.assemble({"host_user_namespace": "same"})

    def test_serial_decode_preserves_raw_bytes_and_default_strict_json_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(directory)
            args = [sys.executable, "-c", "import os;os.write(1,b'console\\xe2 mixed\\n')"]
            self.assertIn("\ufffd", session.command("serial", args, text_errors="replace"))
            self.assertEqual((session.directory / "00-serial.stdout.log").read_bytes(), b"console\xe2 mixed\n")
            with self.assertRaises(UnicodeDecodeError):
                session.command("strict", args)

    def test_guardian_rejects_rewritten_or_broken_evidence(self):
        path = Path(image.__file__).with_name("appliance_vm_payload") / "guardian.py"
        spec = importlib.util.spec_from_file_location("vm_guardian", path)
        guardian = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guardian)
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "ledger"
            self.assertEqual(guardian.verify_ledger(ledger), (0, "0" * 64))
            row = {"sequence": 1, "previous": "0" * 64, "result": {"cpus": 2}}
            digest = assembler.hashlib.sha256(guardian.canonical(row)).hexdigest()
            row["sha256"] = digest
            ledger.write_bytes(guardian.canonical(row) + b"\n")
            self.assertEqual(guardian.verify_ledger(ledger), (1, digest))
            row["result"]["cpus"] = 3
            ledger.write_bytes(guardian.canonical(row) + b"\n")
            with self.assertRaisesRegex(ValueError, "hash"):
                guardian.verify_ledger(ledger)


if __name__ == "__main__":
    unittest.main()
