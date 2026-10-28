import unittest
from gaia.cognition.instruction_adapter import adapt

class InstructionAdapterTests(unittest.TestCase):
    def test_original_is_identity(self):
        self.assertEqual(adapt('Calcula 17 por 23.','ORIGINAL'),{'prompt':'Calcula 17 por 23.','changes':[]})

    def test_experimental_policy_adds_literal_guard_and_symbolic_multiplication(self):
        value=adapt('Calcula 17 por 23. Responde JSON.','LITERAL_AND_OPERATOR_V1')
        self.assertIn('17 * 23',value['prompt']);self.assertIn('without translating',value['prompt'])
        self.assertEqual(value['changes'],['LITERAL_OUTPUT_GUARD','SPANISH_MULTIPLICATION_RESTATEMENT'])

    def test_policy_never_rewrites_original_text_or_grants_authority(self):
        original='Responde únicamente con {"color":"azul"}.';value=adapt(original,'LITERAL_AND_OPERATOR_V1')
        self.assertTrue(value['prompt'].startswith(original));self.assertNotIn('tool',value['prompt'].lower())

    def test_v2_normalizes_only_exact_json_wrapper_and_preserves_literal(self):
        value=adapt('Responde únicamente con el JSON {"color":"azul"}.','EXACT_OUTPUT_AND_OPERATOR_V2')
        self.assertIn('{"color":"azul"}',value['prompt']);self.assertTrue(value['prompt'].startswith('Return exactly this JSON'))
        self.assertIn('EXACT_JSON_WRAPPER_NORMALIZED',value['changes'])

    def test_v3_has_no_global_guard_and_only_targets_supported_patterns(self):
        untouched='Escribe exactamente: CASO_NUEVO'
        self.assertEqual(adapt(untouched,'TARGETED_EXACT_AND_OPERATOR_V3'),{'prompt':untouched,'changes':[]})
        multiplied=adapt('Calcula 19 por 4.','TARGETED_EXACT_AND_OPERATOR_V3')
        self.assertIn('19 * 4',multiplied['prompt'])
        literal=adapt('Responde únicamente con el JSON {"tono":"verde"}.','TARGETED_EXACT_AND_OPERATOR_V3')
        self.assertTrue(literal['prompt'].startswith('Return exactly this JSON'))

if __name__=='__main__':unittest.main()
