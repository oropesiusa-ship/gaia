import unittest
from gaia.cognition.spanish_diagnostic import VARIANTS,score,compare

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

if __name__=='__main__':unittest.main()
