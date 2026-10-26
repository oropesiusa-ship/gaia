import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.archive_backend_scratch import archive, copy_archive, inspect_archive


class ArchiveTests(unittest.TestCase):
    def fixture(self, tmp):
        root = Path(tmp)
        work = root / 'state_local_intelligence/work/inference-x'
        work.mkdir(parents=True)
        (work / 'job.json').write_text('{}')
        return root, work, root / '.gaia/archives/test'

    def test_lossless_archive_preserves_inode_and_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            inode = (work / 'job.json').stat().st_ino
            with patch('tools.archive_backend_scratch.processes', return_value={'scratch_references': [], 'backend_candidates': []}):
                result = archive(root, dest, apply=True)
            p = dest / 'work/inference-x/job.json'
            self.assertEqual(p.stat().st_ino, inode)
            self.assertEqual(p.read_text(), '{}')
            self.assertEqual(result['deleted_files'], 0)
            self.assertTrue(result['empty_operational_work'])
            self.assertEqual(inspect_archive(dest)['status'], 'ARCHIVE_INTACT')
            self.assertTrue((dest / 'original-path-locator.json').exists())
            self.assertTrue((dest / 'manifest-after.json').exists())

    def test_copy_retains_unknown_original_despite_limited_process_visibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            inode = (work / 'job.json').stat().st_ino
            with patch('tools.archive_backend_scratch.processes', return_value={'unreadable_processes': [{'pid': 123}]}):
                result = copy_archive(root, dest, apply=True)
            self.assertEqual(result['status'], 'ARCHIVED_COPY_VERIFIED')
            self.assertEqual((work / 'job.json').stat().st_ino, inode)
            self.assertEqual((work / 'job.json').read_text(), '{}')
            self.assertEqual((dest / 'work/inference-x/job.json').read_text(), '{}')
            self.assertEqual(result['moved_files'], 0)
            self.assertEqual(inspect_archive(dest)['status'], 'ARCHIVE_INTACT')

    def test_live_reference_refuses_without_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            with patch('tools.archive_backend_scratch.processes', return_value={'scratch_references': [{}], 'backend_candidates': []}):
                with self.assertRaisesRegex(ValueError, 'ACTIVE'):
                    archive(root, dest, apply=True)
            self.assertTrue(work.exists())
            self.assertFalse(dest.exists())

    def test_dry_run_no_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            with patch('tools.archive_backend_scratch.processes', return_value={'scratch_references': [], 'backend_candidates': []}):
                self.assertEqual(archive(root, dest)['status'], 'DRY_RUN')
            self.assertTrue(work.exists())
            self.assertFalse(dest.exists())

    def test_traversal_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            with self.assertRaisesRegex(ValueError, 'TRAVERSAL'):
                archive(root, dest / '../../outside', apply=True)
            self.assertTrue(work.exists())

    def test_same_uid_unreadable_process_blocks(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            proc = {'scratch_references': [], 'backend_candidates': [],
                    'unreadable_processes': [{'pid': os.getpid()}]}
            with patch('tools.archive_backend_scratch.processes', return_value=proc):
                with self.assertRaisesRegex(ValueError, 'UNREADABLE'):
                    archive(root, dest, apply=True)
            self.assertTrue(work.exists())

    def test_interrupted_rename_inspection_has_no_automatic_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            with patch('tools.archive_backend_scratch.processes', return_value={'scratch_references': [], 'backend_candidates': []}):
                archive(root, dest, apply=True)
            (dest / 'receipt.json').unlink()
            result = inspect_archive(dest)
            self.assertEqual(result['status'], 'ARCHIVE_INTACT')
            self.assertFalse(result['receipt_present'])
            self.assertFalse(result['automatic_recovery'])

    def test_curated_evidence_and_smoke_reference_unchanged(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            (root / 'docs').mkdir()
            (root / 'docs/cert.json').write_text('{"claim":"PASS"}')
            discovery = root / 'state_local_intelligence/discovery'
            discovery.mkdir()
            (discovery / 'smoke-mistralrs-CPU.json').write_text('{"work":"inference-x"}')
            with patch('tools.archive_backend_scratch.processes', return_value={'scratch_references': [], 'backend_candidates': []}):
                result = archive(root, dest, apply=True)
            self.assertTrue(result['certification_evidence_unchanged'])
            before = json.loads((dest / 'manifest-before.json').read_text())
            after = json.loads((dest / 'manifest-after.json').read_text())
            self.assertEqual(before['preserved_certification_evidence'], after['certification_evidence'])
            self.assertEqual((discovery / 'smoke-mistralrs-CPU.json').read_text(), '{"work":"inference-x"}')

    def test_crash_after_rename_keeps_evidence_inspectable(self):
        from tools import archive_backend_scratch as module
        with tempfile.TemporaryDirectory() as tmp:
            root, work, dest = self.fixture(tmp)
            real_sync = module.sync_directory

            def crash_after_rename(path):
                if Path(path) == dest and (dest / 'work').exists():
                    raise OSError('simulated crash boundary after rename')
                real_sync(path)

            with patch.object(module, 'processes', return_value={'scratch_references': [], 'backend_candidates': []}), \
                 patch.object(module, 'sync_directory', side_effect=crash_after_rename):
                with self.assertRaisesRegex(OSError, 'crash boundary'):
                    archive(root, dest, apply=True)
            self.assertEqual((dest / 'work/inference-x/job.json').read_text(), '{}')
            self.assertEqual(inspect_archive(dest)['status'], 'ARCHIVE_INTACT')
            self.assertFalse((dest / 'receipt.json').exists())
