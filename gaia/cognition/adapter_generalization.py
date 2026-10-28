"""Frozen scoring contract for independent instruction-adapter evaluation."""
import json
from pathlib import Path

from gaia.provenance import digest


SCHEMA = 'gaia_adapter_generalization_preregistration_v1'
KINDS = ('EXACT', 'JSON')


def load_protocol(path):
    value = json.loads(Path(path).read_bytes())
    sealed = dict(value)
    claimed = sealed.pop('content_sha256', None)
    if value.get('schema') != SCHEMA or claimed != digest(sealed):
        raise ValueError('INVALID_OR_UNSEALED_GENERALIZATION_PROTOCOL')
    cases = value.get('cases')
    if not isinstance(cases, list) or len({case.get('id') for case in cases}) != len(cases):
        raise ValueError('INVALID_GENERALIZATION_CASES')
    for case in cases:
        expected = case.get('expected', {})
        if (set(case) != {'id', 'category', 'tags', 'prompt', 'expected', 'targeted_adapter_intervention'}
                or expected.get('kind') not in KINDS or set(expected) != {'kind', 'value'}):
            raise ValueError('INVALID_GENERALIZATION_CASE')
    return value


def score_response(case, text):
    expected = case['expected']
    if not isinstance(text, str):
        return {'pass': False, 'format_pass': False, 'reason': 'NON_TEXT'}
    if expected['kind'] == 'EXACT':
        passed = text.strip() == expected['value']
        return {'pass': passed, 'format_pass': passed, 'reason': 'EXACT_MATCH'}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return {'pass': False, 'format_pass': False, 'reason': 'MALFORMED_JSON'}
    semantic = parsed == expected['value']
    canonical = json.dumps(expected['value'], separators=(',', ':'), ensure_ascii=False)
    return {'pass': semantic, 'format_pass': semantic and text.strip() == canonical,
            'reason': 'STRICT_JSON_EQUAL_AND_CANONICAL_FORMAT'}


def decide(protocol, baseline, candidate):
    limits = protocol['thresholds']
    baseline_by_id = baseline.get('by_id', {})
    candidate_by_id = candidate.get('by_id', {})
    regressions = sorted(case_id for case_id, result in baseline_by_id.items()
                         if result['pass'] and not candidate_by_id.get(case_id, {}).get('pass'))
    checks = {
        'minimum_accuracy': candidate['passed'] / candidate['total'] >= limits['minimum_accuracy'],
        'minimum_format_rate': candidate['format_passed'] / candidate['total'] >= limits['minimum_format_rate'],
        'maximum_regressions': len(regressions) <= limits['maximum_regressions'],
        'maximum_errors': candidate['errors'] <= limits['maximum_errors'],
        'maximum_median_latency_ratio': candidate['median_latency_s'] <= baseline['median_latency_s'] * limits['maximum_median_latency_ratio'],
        'maximum_rss_ratio': candidate['peak_rss_sum_bytes'] <= baseline['peak_rss_sum_bytes'] * limits['maximum_rss_ratio'],
        'maximum_vram_ratio': candidate['peak_device_vram_increment_bytes'] <= baseline['peak_device_vram_increment_bytes'] * limits['maximum_vram_ratio'],
    }
    return {'decision': 'PROMOTE' if all(checks.values()) else 'REJECT_CANDIDATE', 'checks': checks,
            'regressions': regressions, 'authority': 'NONE'}
