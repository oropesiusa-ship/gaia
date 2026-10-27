"""Synthetic boundary tests; no sessions, inference or experiments are run."""
import tempfile
import unittest
import copy
from pathlib import Path
from unittest.mock import patch

from tools.stage2_boundary import boundary_admission, inspect_boundary, verify_manifest


class BoundaryManifestTests(unittest.TestCase):
    def test_first_benchmark_creation_is_not_protocol_drift(self):
        frozen = {'hash': 'old', 'commit': 'same',
                  'lineages': {'fixture': {'benchmark_hash': None}}}
        current = copy.deepcopy(frozen)
        current['hash'] = 'new'
        current['lineages']['fixture']['benchmark_hash'] = 'created'
        check = {'freeze': current, 'reasons': ['FROZEN_PROTOCOL_CHANGED']}
        with patch('tools.stage2_boundary.ex.admission', return_value=check):
            result = boundary_admission({'freeze': frozen}, None, None)
        self.assertEqual(result['status'], 'PASS')

    def test_other_drift_and_unrelated_gates_remain_blocking(self):
        frozen = {'hash': 'old', 'commit': 'same',
                  'lineages': {'fixture': {'benchmark_hash': 'fixed'}}}
        for key in ('commit', 'benchmark'):
            current = copy.deepcopy(frozen)
            if key == 'commit':
                current['commit'] = 'different'
            else:
                current['lineages']['fixture']['benchmark_hash'] = 'changed'
            check = {'freeze': current,
                     'reasons': ['FROZEN_PROTOCOL_CHANGED', 'HOST_MEMORY_RESERVE']}
            with patch('tools.stage2_boundary.ex.admission', return_value=check):
                result = boundary_admission({'freeze': frozen}, None, None)
            self.assertEqual(result['status'], 'BLOCKED_PREEXECUTION')
            self.assertIn('FROZEN_PROTOCOL_CHANGED', result['reasons'])
            self.assertIn('HOST_MEMORY_RESERVE', result['reasons'])

    def test_benchmark_creation_does_not_clear_an_unrelated_gate(self):
        frozen = {'hash': 'old', 'lineages': {'fixture': {'benchmark_hash': None}}}
        current = {'hash': 'new', 'lineages': {'fixture': {'benchmark_hash': 'created'}}}
        check = {'freeze': current,
                 'reasons': ['FROZEN_PROTOCOL_CHANGED', 'HOST_MEMORY_RESERVE']}
        with patch('tools.stage2_boundary.ex.admission', return_value=check):
            result = boundary_admission({'freeze': frozen}, None, None)
        self.assertEqual(result['status'], 'BLOCKED_PREEXECUTION')
        self.assertEqual(result['reasons'], ['HOST_MEMORY_RESERVE'])

    def test_manifest_itself_is_the_only_allowed_addition(self):
        verify_manifest({'a': 'hash'}, {'a': 'hash', 'manifest': 'own'}, Path('manifest'))

    def test_modified_missing_and_added_files_are_rejected(self):
        for actual in ({'a': 'changed'}, {}, {'a': 'hash', 'extra': 'hash'}):
            with self.subTest(actual=actual):
                with self.assertRaisesRegex(ValueError, 'S1_MANIFEST_CHANGED'):
                    verify_manifest({'a': 'hash'}, actual, Path('manifest'))

    def test_empty_or_invalid_manifest_is_rejected(self):
        for expected in ({}, [], None):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, 'MISSING_S1_MANIFEST'):
                    verify_manifest(expected, {}, Path('manifest'))

    def test_missing_contract_fails_closed_without_creating_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = inspect_boundary(root, root / '.gaia/stage2/new/contract.json')
            self.assertEqual(result['status'], 'BLOCKED_PREEXECUTION')
            self.assertTrue(result['execution_prohibited'])
            self.assertEqual(list(root.iterdir()), [])
