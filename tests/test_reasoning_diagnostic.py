import json
from pathlib import Path
import unittest

from gaia.cognition.reasoning_diagnostic import VARIANTS,SYMBOLIC_VARIANTS,score,compare,augment_observation
from gaia.cognition.research_agenda import BenchmarkObservation


class ReasoningDiagnosticTests(unittest.TestCase):
    def test_variants_change_one_existing_case_without_revealing_answer(self):
        self.assertEqual([v['id']for v in VARIANTS],['CONTROL_JSON','NUMERIC_ONLY','DECOMPOSE_JSON'])
        self.assertTrue(all(v['operation']=='17*23'and v['expected']==391 for v in VARIANTS))
        self.assertNotIn('391',VARIANTS[1]['prompt']);self.assertNotIn('391',VARIANTS[2]['prompt'])

    def test_frozen_scoring_distinguishes_format_and_value(self):
        self.assertTrue(score(VARIANTS[0],'{"resultado":391}')['pass'])
        self.assertEqual(score(VARIANTS[0],'391')['reason'],'STRICT_JSON_EQUAL')
        self.assertTrue(score(VARIANTS[1],'391')['pass'])
        self.assertEqual(score(VARIANTS[1],'0.7391')['reason'],'WRONG_VALUE')

    def test_comparison_is_diagnostic_not_promotional(self):
        rows=[{'variant_id':'CONTROL_JSON','score':{'pass':False}},{'variant_id':'NUMERIC_ONLY','score':{'pass':True}},
              {'variant_id':'DECOMPOSE_JSON','score':{'pass':True}}]
        value=compare(rows)
        self.assertEqual(value['diagnosis'],'FORMAT_OR_INSTRUCTION_INTERACTION_SUPPORTED')
        self.assertEqual(value['authority'],'NONE');self.assertFalse(value['promotion_allowed'])

    def test_symbolic_suite_reuses_same_operation_without_revealing_answer(self):
        self.assertEqual([v['id']for v in SYMBOLIC_VARIANTS],['CONTROL_JSON','SYMBOLIC_JSON','ENGLISH_JSON'])
        self.assertTrue(all(v['expected']==391 and '391'not in v['prompt'] for v in SYMBOLIC_VARIANTS[1:]))

    def test_verified_diagnostic_augments_reasoning_with_new_citable_evidence(self):
        root=Path(__file__).resolve().parents[1];source=root/'docs/local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json'
        diagnostic=root/'docs/local_intelligence_evidence/GAIA_1_2_REASONING_SYMBOLIC_DIAGNOSTIC_V2.json'
        observed=BenchmarkObservation.from_bytes(source.read_bytes(),source.name)
        augmented=augment_observation(observed,diagnostic.read_bytes(),diagnostic.name)
        issue=next(v for v in augmented['issues']if v['task_id']=='reasoning')
        self.assertEqual(issue['diagnostic_details']['diagnosis'],'LANGUAGE_OR_OPERATOR_REPRESENTATION_SUPPORTED')
        self.assertEqual(len(issue['research_evidence_refs']),3);self.assertEqual(len(augmented['valid_evidence_refs']),19)


if __name__=='__main__':unittest.main()
