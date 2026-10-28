"""Synthetic claim gates cannot certify a real recovery."""
import copy
import tempfile
import unittest
from pathlib import Path
from tools.stage2_protocol import recovery_claim_gate, verify_recovery, master_recovery_claim_gate, resume_sequence_gate


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

    def resume_claims(self):
        seal, result, fault, identity = self.claims()
        seal.update(status='FAIL', outcome='NOT_EXERCISED_ROLLBACK')
        result.update(status='FAIL', outcome='NOT_EXERCISED_ROLLBACK', rollback_count=0,
                      lineage_blocked=False, native_version='v0001',
                      reference={'reason': 'POST_PROMOTION', 'status': 'MEASURED', 'version': 'v0001'})
        return seal, result, fault, identity

    def test_master_recovery_does_not_claim_unexercised_rollback(self):
        args = self.resume_claims()
        self.assertTrue(recovery_claim_gate(*args))  # Original strict gate is unchanged.
        mode, failures = master_recovery_claim_gate(*args)
        self.assertEqual(mode, 'RESUME_VERIFICATION')
        self.assertEqual(failures, [])  # Claims only; journals/gates/replay still required.

    def test_resume_still_rejects_missing_fault_reference_or_integrity(self):
        for index, key, value in ((2, 'injection', {}), (1, 'reference', {}),
                                  (1, 'lineage_blocked', True), (1, 'native_ledger', {}),
                                  (1, 'survivors', [123]), (0, 'identity', {})):
            args = list(copy.deepcopy(self.resume_claims()))
            args[index][key] = value
            self.assertTrue(master_recovery_claim_gate(*args)[1])

    def test_resumption_requires_exact_normal_journal_sequence(self):
        clock = {'boot_id': 'fixture', 'monotonic': 1}
        events = [{'kind': kind, 'payload': {'campaign_id': 'fixture', **payload},
                   'clock': {'boot_id': 'fixture', 'monotonic': index + 2}}
                  for index, (kind, payload) in enumerate([
                      ('CHILD_EXITED', {'returncode': -9}),
                      ('CAMPAIGN_RELAUNCHED', {'reason': 'RESUMES_AT_VERIFYING'}),
                      ('CHILD_EXITED', {'returncode': 0})])]
        self.assertEqual(resume_sequence_gate(events, 'fixture', clock), 3)
        for invalid in (events[:2], list(reversed(events)), events + events):
            with self.assertRaises(ValueError):
                resume_sequence_gate(invalid, 'fixture', clock)
