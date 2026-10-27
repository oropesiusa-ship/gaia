"""Synthetic claim gates cannot certify a real recovery."""
import copy
import tempfile
import unittest
from pathlib import Path
from tools.stage2_protocol import recovery_claim_gate, verify_recovery


class RecoveryGateTests(unittest.TestCase):
    def claims(self):
        seal = {'status': 'PASS', 'outcome': 'PASS', 'identity': {'hash': 'fixture'}}
        result = {'status': 'PASS', 'outcome': 'PASS', 'survivors': [], 'rollback_count': 1,
                  'native_ledger': {'ok': True},
                  'reference': {'reason': 'AFTER_ROLLBACK', 'status': 'MEASURED'}}
        return seal, result, {'injection': {'injected': True}}, {'hash': 'fixture'}

    def test_complete_claims_only_pass_the_claim_gate(self):
        self.assertEqual(recovery_claim_gate(*self.claims()), [])

    def test_unexercised_and_simulated_results_cannot_pass(self):
        for outcome in ('NOT_EXERCISED', 'NOT_EXERCISED_ROLLBACK', 'FAIL', 'UNIT_FIXTURE'):
            seal, result, fault, identity = self.claims()
            seal['outcome'] = result['outcome'] = outcome
            self.assertTrue(recovery_claim_gate(seal, result, fault, identity))

    def test_each_required_claim_blocks_independently(self):
        for index, key, value in ((0, 'identity', {}), (1, 'survivors', [123]),
                                  (1, 'native_ledger', {}), (1, 'rollback_count', 0),
                                  (1, 'reference', {}), (2, 'injection', {})):
            args = list(copy.deepcopy(self.claims()))
            args[index][key] = value
            self.assertTrue(recovery_claim_gate(*args))

    def test_missing_recovery_state_blocks_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = verify_recovery(root, root / 'state_endurance_stage1_recovery_new', root / 'evidence')
            self.assertEqual(value['status'], 'BLOCKED_PREEXECUTION')
            self.assertEqual(list(root.iterdir()), [])
