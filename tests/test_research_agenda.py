"""Contracts and deterministic baseline for the experimental 1.2.x research pilot."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from gaia.cognition.research_agenda import (
    BenchmarkObservation,
    deterministic_agenda,
    validate_research_artifact,
)
from gaia.cognition.store import CognitiveStore
from gaia.provenance import canonical_json


ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'docs/local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json'


class ResearchAgendaTests(unittest.TestCase):
    def setUp(self):
        self.raw=SOURCE.read_bytes();self.document=json.loads(self.raw)
        self.source={'id':SOURCE.name,'sha256':hashlib.sha256(self.raw).hexdigest()}

    def test_observation_preserves_exact_failure_references(self):
        observed=BenchmarkObservation.from_bytes(self.raw,SOURCE.name)
        self.assertEqual(observed['source'],self.source)
        issues={(v['task_id'],v['failure_count']):v for v in observed['issues']}
        self.assertIn(('spanish',2),issues);self.assertIn(('reasoning',2),issues)
        self.assertEqual(issues[('spanish',2)]['evidence_refs'][0],
                         {'source':self.source,'pointer':'/baseline/rows/0/objective'})
        self.assertTrue(any(v['task_id']=='fact_update'and v['format_failure_count']==2
                            for v in observed['issues']))

    def test_selector_is_deterministic_complete_and_non_executable(self):
        observed=BenchmarkObservation.from_document(self.document,self.source)
        first=deterministic_agenda(observed);second=deterministic_agenda(observed)
        self.assertEqual(first,second);self.assertEqual(first['authority'],'NONE')
        self.assertEqual(first['decision'],'CONTINUE')
        self.assertEqual(first['agenda'][0]['task_id'],'reasoning')
        hypothesis=first['hypotheses'][0]
        self.assertEqual(set(hypothesis),{'id','problem','evidence_refs','causal_hypothesis',
            'proposed_change','prediction','success_metric','budget','authority_required',
            'uncertainties','stop_conditions'})
        self.assertEqual(hypothesis['authority_required'],'LOCAL_COMPUTE')
        self.assertEqual(first['proposal_authority'],'NONE')
        self.assertFalse(first['experiment']['execute'])
        self.assertEqual(first['experiment']['network_requests'],0)

    def test_persisted_baseline_is_exactly_reproducible(self):
        observed=BenchmarkObservation.from_bytes(self.raw,SOURCE.name)
        expected=canonical_json(deterministic_agenda(observed))+b'\n'
        actual=(ROOT/'docs/local_intelligence_evidence/GAIA_1_2_RESEARCH_AGENDA_BASELINE_V1.json').read_bytes()
        self.assertEqual(actual,expected)

    def test_insufficient_evidence_stops_without_hypothesis(self):
        document=copy.deepcopy(self.document)
        for section in ('baseline','memory'):
            document[section]['rows']=[r for r in document[section]['rows'] if not r.get('objective')]
        observed=BenchmarkObservation.from_document(document,self.source)
        result=deterministic_agenda(observed)
        self.assertEqual(result['decision'],'STOP');self.assertEqual(result['reason'],'INSUFFICIENT_FAILURE_EVIDENCE')
        self.assertEqual(result['hypotheses'],[]);self.assertIsNone(result['experiment'])

    def test_contract_rejects_authority_and_reference_tampering(self):
        result=deterministic_agenda(BenchmarkObservation.from_document(self.document,self.source))
        for mutate in (
            lambda v:v.update(authority='SIDE_EFFECT'),
            lambda v:v['hypotheses'][0]['evidence_refs'][0].update(pointer='/invented'),
            lambda v:v['experiment'].update(execute=True),
            lambda v:v['hypotheses'][0]['budget'].update(max_model_runs=1000),
        ):
            changed=copy.deepcopy(result);mutate(changed)
            with self.subTest(changed=changed),self.assertRaises(ValueError):
                validate_research_artifact(changed,observed=BenchmarkObservation.from_document(self.document,self.source))

    def test_conclusion_can_be_persisted_as_immutable_data(self):
        observed=BenchmarkObservation.from_document(self.document,self.source)
        value=deterministic_agenda(observed)
        with tempfile.TemporaryDirectory() as state:
            store=CognitiveStore(state);record=store.put_research(value,observed)
            self.assertEqual(record['kind'],'RESEARCH_AGENDA')
            self.assertEqual(store.get(record['id'],'RESEARCH_AGENDA'),record)


if __name__=='__main__':unittest.main()
