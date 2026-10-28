"""Real administrative sandbox probe only; never start a session or campaign."""
import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from tools.stage2_runtime import administrative_sandbox_probe
from tools.stage2_executor import ROOT


class AdministrativeProbeTests(unittest.TestCase):
    def test_unverified_probe_still_blocks_and_drains(self):
        owner = Mock(record_error=None)
        owner.collect.return_value = []
        with patch('gaia.provenance.bwrap_capability', return_value={'verified': False}):
            with self.assertRaisesRegex(ValueError, 'SANDBOX_UNAVAILABLE'):
                administrative_sandbox_probe(owner)
        owner.begin.assert_called_once()
        owner.drain.assert_called_once()

    def test_live_leftover_child_is_not_accepted_as_a_zombie(self):
        owner = Mock(record_error=None)
        owner.collect.return_value = [{'state': 'S'}]
        with patch('gaia.provenance.bwrap_capability', return_value={'verified': True}):
            with self.assertRaisesRegex(RuntimeError, 'LIVE_ADMINISTRATIVE_PROBE_CHILDREN'):
                administrative_sandbox_probe(owner)
        owner.drain.assert_called_once()

    def test_probe_exception_cannot_skip_cleanup(self):
        owner = Mock(record_error=None)
        with patch('gaia.provenance.bwrap_capability', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                administrative_sandbox_probe(owner)
        owner.drain.assert_called_once()

    def test_recording_failure_prevents_probe_without_skipping_cleanup(self):
        owner = Mock(record_error=None)
        owner.record.side_effect = lambda event: setattr(owner, 'record_error', 'fixture-disk-full')
        with patch('gaia.provenance.bwrap_capability') as probe:
            with self.assertRaisesRegex(RuntimeError, 'SUBREAPER_EVIDENCE_FAILED'):
                administrative_sandbox_probe(owner)
        probe.assert_not_called()
        owner.drain.assert_called_once()

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'pidfd_open') and shutil.which('bwrap'),
                         'Linux pidfd/bwrap required for the real administrative probe')
    def test_real_probe_leaves_no_idle_children_in_a_dedicated_process(self):
        script = '''import json
from tools.stage2_children import ChildBoundary
from tools.stage2_runtime import administrative_sandbox_probe
events=[]
with ChildBoundary(events.append) as owner:
    capability=administrative_sandbox_probe(owner)
    empty=owner.kernel_empty()
    idle=not owner.active
    owner.collect()  # The unchanged idle gate must accept the now-empty process.
print(json.dumps({'capability':capability,'kernel_empty':empty,'idle':idle,
                  'restored':not owner.enabled,'events':events}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value['capability']['verified'])
        self.assertTrue(value['kernel_empty'])
        self.assertTrue(value['idle'])
        self.assertTrue(value['restored'])
        self.assertIn('ADMINISTRATIVE_PROBE_END', [row['kind'] for row in value['events']])
