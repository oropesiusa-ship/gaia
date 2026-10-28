"""Synthetic attribution, no measured Stage 2 session."""
import os
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch
from tools.stage2_observer import lock_holders, coverage, observed_first, snapshot_descendants


class AttributionTests(unittest.TestCase):
    def test_single_snapshot_closes_late_worker_ancestry(self):
        table = {
            10: (1, 10, 10, 100, 3, 'stage2 runtime', 'S', 1000),
            11: (10, 11, 11, 100, 3, 'autonomy-run campaign', 'S', 1100),
            12: (11, 12, 12, 100, 3, '/usr/bin/bwrap worker', 'S', 1200),
            13: (12, 12, 12, 100, 3, '/lab/worker.py', 'R', 1300),
            99: (1, 99, 99, 100, 3, 'foreign worker', 'S', 9900),
        }
        with patch('tools.stage2_observer.proc_info', side_effect=lambda pid: table.get(pid)):
            rows = snapshot_descendants(table, 10)
        self.assertEqual({row['pid'] for row in rows}, {10, 11, 12, 13})

    def test_lock_owner_is_tied_to_device_inode_pid_and_start(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.lock'
            path.touch()
            stat = path.stat()
            text = f'1: FLOCK ADVISORY WRITE 123 {os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}:{stat.st_ino} 0 EOF'
            table = {123: (0, 0, 0, 0, 0, 'fixture', 'S', 456)}
            row = lock_holders([path], text, table, {123: 456})[0]['holders'][0]
            self.assertEqual((row['ownership'], row['start_time']), ('OWNED', 456))
            self.assertEqual(lock_holders([path], text, table, {})[0]['holders'][0]['ownership'], 'FOREIGN')
            self.assertEqual(lock_holders([path], text, {}, {})[0]['holders'][0]['ownership'], 'UNKNOWN')
            self.assertEqual(lock_holders([path], text, table, {123: 999})[0]['holders'][0]['ownership'], 'FOREIGN')

    def rows(self):
        return [{'clock': {'boot_id': 'fixture', 'monotonic': i * 10}, 'status': 'PASS',
                 'observer': {'pid': 1, 'start_time': 1, 'rss_bytes': 100, 'pss_bytes': 50, 'fds': 2},
                 'locks': [], **({'gpu': {'status': 'PASS'}} if i % 3 == 0 else {})}
                for i in range(7)]

    def test_complete_coverage(self):
        self.assertEqual(coverage(self.rows())['status'], 'PASS')

    def test_gap_missing_sensor_and_foreign_owner_fail_closed(self):
        for mutation in ('gap', 'sensor', 'foreign'):
            rows = self.rows()
            if mutation == 'gap':
                rows[1]['clock']['monotonic'] = 30
            elif mutation == 'sensor':
                rows[0]['gpu']['status'] = 'INCONCLUSIVE_ENVIRONMENT'
            else:
                rows[1]['status'] = 'INCONCLUSIVE_ENVIRONMENT'
            self.assertNotEqual(coverage(rows)['status'], 'PASS')

    def test_lock_inode_replacement_is_not_accepted_as_continuity(self):
        rows = self.rows()
        rows[0]['locks'] = [{'path': 'fixture', 'identity': [0, 1, 2]}]
        rows[1]['locks'] = [{'path': 'fixture', 'identity': [0, 1, 3]}]
        self.assertNotEqual(coverage(rows)['status'], 'PASS')

    def test_external_observer_launch_and_final_archival_without_a_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'attempt'
            out.mkdir()
            class Process:
                pid = 123
                returncode = None
                def poll(self):
                    return self.returncode
                def wait(self, timeout=None):
                    self.returncode = 0
                    return 0
            process = Process()
            def launch(*args, **kwargs):
                kwargs['stdout'].write(json.dumps({'status': 'S1_OBSERVED'}))
                return process
            rows = self.rows()
            rows[1]['gpu'] = {'status': 'PASS'}
            with patch('tools.stage2_observer.subprocess.Popen', side_effect=launch), \
                    patch('tools.stage2_observer.sample', side_effect=[rows[0], rows[1]]):
                value = observed_first(root, out / 'contract.json',
                    {'state_path': str(out / 'state'), 'lineages': [], 'hash': 'fixture'})
            self.assertEqual(value['status'], 'S1_OBSERVED')
            archive = root / 'attempt-observer'
            self.assertTrue((archive / 'manifest.json').is_file())
            self.assertEqual(json.loads((archive / 'result.json').read_text())['status'], 'PASS')

    def test_observer_checks_its_own_memory_and_fd_growth(self):
        for key, value in (('rss_bytes', 128 * 2**20), ('fds', 100)):
            rows = self.rows()
            rows[-1]['observer'][key] = value
            self.assertEqual(coverage(rows)['status'], 'FAIL')
