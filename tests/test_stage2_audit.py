"""Synthetic final Stage 2 decisions cannot substitute for real campaigns."""
import unittest
from tools.stage2_audit import final_decision, attribution_window


class FullDecisionTests(unittest.TestCase):
    names = ('session1', 'session2', 'window1', 'window2', 'aggregate', 'attribution1',
             'attribution2', 'catalogue_probe', 'catalogue_decisions', 'terminal_replays',
             'frozen_protocol', 'terminal_bytes', 'drift_coverage','retained_scratch','administrative_chain')

    def test_all_required_categories_must_pass(self):
        checks = {name: {'status': 'PASS'} for name in self.names}
        self.assertEqual(final_decision(checks)['status'], 'PASS')
        for name in self.names:
            partial = {key: value for key, value in checks.items() if key != name}
            self.assertEqual(final_decision(partial)['status'], 'BLOCKED')
            failed = {**checks, name: {'status': 'FAIL'}}
            self.assertEqual(final_decision(failed)['status'], 'FAIL')

    def test_environment_gap_is_never_promoted_to_pass(self):
        checks = {name: {'status': 'PASS'} for name in self.names}
        checks['attribution1'] = {'status': 'INCONCLUSIVE_ENVIRONMENT'}
        self.assertEqual(final_decision(checks)['status'], 'INCONCLUSIVE_ENVIRONMENT')
        checks['frozen_protocol'] = {'status': 'FAIL'}
        self.assertEqual(final_decision(checks)['status'], 'FAIL')

    def test_session_endpoint_gaps_cannot_be_hidden_by_dense_middle_samples(self):
        rows = [{'status': 'PASS', 'locks': [], 'clock': {'boot_id': 'fixture', 'monotonic': t},
                 'gpu': {'status': 'PASS'}} for t in (100, 110)]
        value = attribution_window(rows, {'boot_id': 'fixture', 'monotonic': 0},
                                   {'boot_id': 'fixture', 'monotonic': 120})
        self.assertNotEqual(value['status'], 'PASS')
