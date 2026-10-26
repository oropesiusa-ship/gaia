"""Conservative scratch ownership; no age-based cleanup and no backend launch."""
import tempfile
from pathlib import Path
import unittest

from tools.inventory_backend_scratch import snapshot, classify, scratch_gate


class ScratchTests(unittest.TestCase):
    def test_nonempty_unknown_scratch_blocks_without_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'inference-unknown'
            p.mkdir()
            (p / 'job.json').write_text('{}')
            self.assertEqual(scratch_gate(tmp)['status'], 'BLOCKED_PREEXECUTION')
            self.assertTrue((p / 'job.json').exists())
            self.assertFalse(scratch_gate(tmp)['cleanup_performed'])

    def test_owner_absence_is_not_stale_proof(self):
        self.assertEqual(classify('inference-x', {'scratch_references': []}, [])[0], 'UNKNOWN_OWNER')

    def test_reference_is_not_terminal_or_disposable_proof(self):
        self.assertEqual(classify('inference-x', {'scratch_references': []}, [{}])[0], 'UNKNOWN_OWNER')

    def test_live_reference_blocks_cleanup(self):
        proc = {'scratch_references': [{'references': [{'value': '/work/inference-x/job.json'}]}]}
        self.assertEqual(classify('inference-x', proc, [])[0], 'ACTIVE_FOREIGN')

    def test_empty_scratch_gate_is_observation_not_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = scratch_gate(tmp)
            self.assertEqual(result['status'], 'PASS')
            self.assertFalse(result['session_started'])

    def test_symlink_recorded_without_following_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'link').symlink_to('/nonexistent')
            row = next(r for r in snapshot(tmp) if r['path'] == 'link')
            self.assertEqual(row['kind'], 'symlink')
            self.assertNotIn('sha256', row)

    def test_snapshot_records_hash_timestamp_owner_without_content_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'job.json'
            p.write_text('{"pid":123}')
            before = p.read_bytes()
            row = next(r for r in snapshot(tmp) if r['path'] == 'job.json')
            self.assertEqual(row['metadata']['pid'], 123)
            self.assertEqual(len(row['sha256']), 64)
            self.assertIn('ctime_ns', row)
            self.assertIn('uid', row)
            self.assertEqual(p.read_bytes(), before)
