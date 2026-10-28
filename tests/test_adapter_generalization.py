import copy
import json
import unittest
from pathlib import Path

from gaia.cognition.adapter_generalization import decide, load_protocol, score_response
from gaia.cognition.instruction_adapter import adapt


PROTOCOL = Path('docs/local_intelligence_evidence/GAIA_1_2_ADAPTER_GENERALIZATION_PREREGISTRATION_V1.json')


class AdapterGeneralizationTests(unittest.TestCase):
    def test_preregistered_protocol_is_self_consistent_and_covers_required_risks(self):
        value = load_protocol(PROTOCOL)
        self.assertEqual(value['schema'], 'gaia_adapter_generalization_preregistration_v1')
        self.assertGreaterEqual(len(value['cases']), 18)
        covered = {tag for case in value['cases'] for tag in case['tags']}
        self.assertTrue({
            'SPANISH_MULTIPLICATION', 'OPERATOR_VARIATION', 'WORKING_MULTIPLICATION',
            'LITERAL_JSON', 'EXACT_FORMAT', 'TRANSLATION', 'CASING', 'NEGATION',
            'QUOTED_CONTENT', 'ADVERSARIAL', 'NO_INTERVENTION',
        }.issubset(covered))

    def test_scoring_is_independent_and_adapter_cannot_mutate_expectations(self):
        value = load_protocol(PROTOCOL)
        for case in value['cases']:
            with self.subTest(case=case['id']):
                expected = copy.deepcopy(case['expected'])
                projected = adapt(case['prompt'], 'EXACT_OUTPUT_AND_OPERATOR_V2')
                self.assertEqual(case['expected'], expected)
                targeted = [change for change in projected['changes'] if change != 'LITERAL_OUTPUT_GUARD']
                self.assertEqual(bool(targeted), case['targeted_adapter_intervention'])
                canonical = json.dumps(expected['value'], separators=(',', ':'), ensure_ascii=False) if expected['kind'] == 'JSON' else expected['value']
                self.assertTrue(score_response(case, canonical)['pass'])

    def test_scorer_rejects_semantically_or_format_incorrect_outputs(self):
        value = load_protocol(PROTOCOL)
        by_id = {case['id']: case for case in value['cases']}
        self.assertFalse(score_response(by_id['mul-es-01'], '42.0')['pass'])
        self.assertFalse(score_response(by_id['json-literal-01'], '{"estado": "LISTO"}')['format_pass'])
        self.assertFalse(score_response(by_id['negation-01'], 'PERMITIDO')['pass'])

    def test_decision_requires_every_preregistered_gate(self):
        protocol = load_protocol(PROTOCOL)
        baseline = {'passed': 15, 'format_passed': 13, 'total': 18, 'errors': 0,
                    'median_latency_s': 1.0, 'peak_rss_sum_bytes': 100, 'peak_device_vram_increment_bytes': 100}
        candidate = dict(baseline, passed=17, format_passed=16, median_latency_s=1.05)
        self.assertEqual(decide(protocol, baseline, candidate)['decision'], 'PROMOTE')
        candidate['passed'] = 14
        self.assertEqual(decide(protocol, baseline, candidate)['decision'], 'REJECT_V2')


if __name__ == '__main__':
    unittest.main()
