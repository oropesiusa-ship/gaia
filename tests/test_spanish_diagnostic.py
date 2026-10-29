import unittest
from pathlib import Path
from gaia.cognition.research_agenda import BenchmarkObservation
from gaia.cognition.spanish_diagnostic import VARIANTS,augment_observation,score,compare

class SpanishDiagnosticTests(unittest.TestCase):
    def test_variants_preserve_existing_expected_value(self):
        self.assertEqual([v['id']for v in VARIANTS],['CONTROL_JSON','TOKEN_ONLY','ENGLISH_JSON'])
        self.assertTrue(all('azul'in v['prompt']for v in VARIANTS))

    def test_scoring_is_strict(self):
        self.assertTrue(score(VARIANTS[0],'{"color":"azul"}')['pass']);self.assertFalse(score(VARIANTS[0],'{"color":"blue"}')['pass'])
        self.assertTrue(score(VARIANTS[1],'azul')['pass']);self.assertFalse(score(VARIANTS[1],'Azul')['pass'])

    def test_comparison_has_no_promotion_authority(self):
        rows=[{'variant_id':'CONTROL_JSON','score':{'pass':False}},{'variant_id':'TOKEN_ONLY','score':{'pass':True}},
              {'variant_id':'ENGLISH_JSON','score':{'pass':True}}]
        value=compare(rows);self.assertEqual(value['diagnosis'],'SPANISH_INSTRUCTION_INTERACTION_SUPPORTED');self.assertFalse(value['promotion_allowed'])

    def test_english_pass_with_case_only_copy_failure_is_classified_explicitly(self):
        rows=[{'variant_id':'CONTROL_JSON','score':{'pass':False}},{'variant_id':'TOKEN_ONLY','score':{'pass':False}},
              {'variant_id':'ENGLISH_JSON','score':{'pass':True}}]
        self.assertEqual(compare(rows)['diagnosis'],'SPANISH_INSTRUCTION_AND_CASING_INTERACTION_SUPPORTED')

    def test_persisted_v2_diagnostic_augments_spanish_issue_by_hash(self):
        root=Path(__file__).resolve().parents[1];evidence=root/'docs/local_intelligence_evidence'
        observed=BenchmarkObservation.from_bytes((evidence/'GAIA_1_2_MEMORY_QUALITY_V1.json').read_bytes(),'GAIA_1_2_MEMORY_QUALITY_V1.json')
        path=evidence/'GAIA_1_2_SPANISH_DIAGNOSTIC_V2.json';value=augment_observation(observed,path.read_bytes(),path.name)
        issue=next(v for v in value['issues']if v['task_id']=='spanish')
        self.assertEqual(issue['diagnostic_details']['diagnosis'],'SPANISH_INSTRUCTION_AND_CASING_INTERACTION_SUPPORTED')
        self.assertEqual(len(issue['research_evidence_refs']),3)

if __name__=='__main__':unittest.main()
