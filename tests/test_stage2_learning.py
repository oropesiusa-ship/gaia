"""Synthetic catalogue contracts only; not real Stage 2 evidence."""
import unittest
import tempfile
import json
from pathlib import Path
from gaia.autonomy.catalog import BINDING
from gaia.autonomy.lineage import engine_state_dir
from tools.stage2_learning import assess_catalogue, surface_probe, decision_coverage, native_probe_reference


class Stage2LearningTests(unittest.TestCase):
    def binding(self, surface='numpy_mlp'):
        return {**dict.fromkeys(BINDING, 'fixture'), 'surface': surface}

    def test_c3_reports_factual_cross_surface_difference_without_execution(self):
        reference = {'record_hash': 'fixture', 'binding': self.binding()}
        value = assess_catalogue([reference], self.binding('local_inference'), role='S2-C3')
        self.assertEqual(value['incompatibility_claim'], 'OBSERVED')
        self.assertEqual(value['eligible_record_hashes'], [])
        self.assertFalse(value['assessments'][0]['executable_effect'])
        self.assertIn('surface', value['assessments'][0]['applicability']['differing'])

    def test_c4_exact_match_is_eligible_not_claimed_as_reused(self):
        reference = {'record_hash': 'fixture', 'binding': self.binding()}
        value = assess_catalogue([reference], self.binding(), role='S2-C4')
        self.assertEqual(value['eligible_record_hashes'], ['fixture'])
        self.assertEqual(value['reuse_claim'], 'NOT_EXERCISED')
        self.assertTrue(value['execution_prohibited'])

    def test_empty_catalogue_does_not_manufacture_claims(self):
        value = assess_catalogue([], self.binding('local_inference'), role='S2-C3')
        self.assertEqual(value['incompatibility_claim'], 'NOT_EXERCISED')
        self.assertIsNotNone(value['empty_reason'])

    def test_incomplete_bindings_and_wrong_surface_fail_closed(self):
        with self.assertRaises(ValueError):
            assess_catalogue([], {}, role='S2-C3')
        with self.assertRaises(ValueError):
            assess_catalogue([], self.binding(), role='S2-C3')
        with self.assertRaises(ValueError):
            assess_catalogue([{'record_hash': 'fixture', 'binding': {}}],
                             self.binding(), role='S2-C4')

    def test_native_binding_probe_is_not_an_accepted_experiment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lineage = {'lineage_id': 'al' + '1' * 24, 'surface': 'numpy_mlp',
                       'objective': 'fixture', 'source_identity_hash': 'fixture'}
            native = root / engine_state_dir(lineage['lineage_id'])
            stable = native / 'stable/v0000'
            stable.mkdir(parents=True)
            (native / 'stable/CURRENT').write_text('v0000')
            (stable / 'manifest.json').write_text(json.dumps({'environment_hash': 'fixture'}))
            (stable / 'genome.json').write_text(json.dumps({'fixture': True}))
            probe = native_probe_reference(root, lineage)
            self.assertEqual(probe['acceptance_claim'], 'NONE')
            self.assertEqual(probe['reuse_claim'], 'NONE')
            self.assertEqual(probe['binding']['reference_version'], 'v0000')
            (native / 'stable/CURRENT').write_text('../../outside')
            with self.assertRaisesRegex(ValueError, 'INVALID_NATIVE_CHAMPION_VERSION'):
                native_probe_reference(root, lineage)

    def test_same_surface_difference_is_not_cross_surface_evidence(self):
        reference = {'record_hash': 'fixture',
                     'binding': {**self.binding('local_inference'), 'objective': 'different'}}
        value = assess_catalogue([reference], self.binding('local_inference'), role='S2-C3')
        self.assertEqual(value['incompatibility_claim'], 'NOT_EXERCISED')

    def test_factual_surface_probe_does_not_invent_environment_identity(self):
        lineage = {'surface': 'local_inference', 'lineage_id': 'fixture', 'hash': 'fixture'}
        reference = {'record_hash': 'fixture', 'binding': self.binding()}
        value = surface_probe([reference], lineage)
        self.assertEqual(value['status'], 'PASS')
        self.assertEqual(value['full_binding_assessment'], 'NOT_CLAIMED')
        self.assertEqual(value['references'][0]['differing'], ['surface'])
        self.assertFalse(value['references'][0]['executable_effect'])
        self.assertEqual(surface_probe([], lineage)['status'], 'NOT_EXERCISED')

    def test_probe_refuses_missing_factual_lineage(self):
        with self.assertRaises(ValueError):
            surface_probe([], {'surface': 'local_inference'})

    def reference(self):
        return {'record_hash': 'record', 'experiment_id': 'original', 'candidate_hash': 'candidate',
                'binding': self.binding()}

    def test_actual_linked_materialization_is_reuse(self):
        executed = [{'experiment_id': 'consumer', 'proposed_change': {'class': 'REPLICATION',
            'reference': {'source_experiments': ['original'], 'claim': {'configuration_hash': 'candidate'},
                          'learning_id': 'learning', 'hash': 'learning-hash'}}}]
        value = decision_coverage([self.reference()], self.binding(), executed)
        self.assertEqual(value['status'], 'PASS')
        self.assertEqual(value['decisions'][0]['decision'], 'REUSED')
        self.assertEqual(value['reuse_claim'], 'OBSERVED')

    def test_non_reference_plan_records_explicit_non_applicability(self):
        executed = [{'experiment_id': 'consumer', 'proposed_change': {'class': 'EXPLORATION'}}]
        value = decision_coverage([self.reference()], self.binding(), executed)
        self.assertEqual(value['status'], 'PASS')
        self.assertEqual(value['decisions'][0]['decision'], 'REJECTED')
        self.assertEqual(value['reuse_claim'], 'NOT_EXERCISED')

    def test_incompatible_actual_reuse_is_a_failure_not_a_rejection(self):
        reference = self.reference()
        reference['binding']['reference_version'] = 'obsolete'
        executed = [{'experiment_id': 'consumer', 'proposed_change': {'class': 'REPLICATION',
            'reference': {'source_experiments': ['original'], 'claim': {'configuration_hash': 'candidate'},
                          'learning_id': 'learning', 'hash': 'learning-hash'}}}]
        value = decision_coverage([reference], self.binding(), executed)
        self.assertEqual(value['status'], 'FAIL')
        self.assertEqual(value['decisions'][0]['decision'], 'FORBIDDEN_REUSE')

    def test_missing_required_reference_never_manufactures_rejection(self):
        executed = [{'experiment_id': 'consumer', 'proposed_change': {'class': 'REPLICATION'}}]
        value = decision_coverage([self.reference()], self.binding(), executed)
        self.assertEqual(value['status'], 'FAIL')
        self.assertEqual(value['decisions'][0]['decision'], 'UNASSESSED')

    def test_missing_cross_surface_environment_cannot_become_exact(self):
        reference = self.reference()
        reference['binding'] = {'surface': 'local_inference'}
        value = decision_coverage([reference], self.binding(), [])
        self.assertEqual(value['status'], 'PASS')
        self.assertEqual(value['decisions'][0]['reason'], 'INCOMPATIBLE_SURFACE_NO_REUSE')
        self.assertEqual(value['decisions'][0]['assessment']['applicability']['status'], 'UNASSESSED')
