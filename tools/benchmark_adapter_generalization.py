#!/usr/bin/env python3
"""Run the sealed adapter generalization A/B against the selected local backend."""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gaia.cognition.adapter_generalization import decide, load_protocol, score_response
from gaia.cognition.conversation import ConversationStore
from gaia.cognition.instruction_adapter import adapt
from gaia.local_intelligence.primary import PrimaryLocalIntelligenceBackend


def run_arm(protocol, policy, state_dir, intelligence_state):
    store = ConversationStore(state_dir)
    backend = PrimaryLocalIntelligenceBackend(intelligence_state, context=protocol['controls']['context_tokens'])
    backend.load()
    rows = []
    try:
        for case in protocol['cases']:
            projected = adapt(case['prompt'], policy)
            conversation = store.create('adapter generalization ' + case['id'], 'adapter-generalization-' + policy.lower())
            started = time.perf_counter()
            result = store.respond(conversation['id'], projected['prompt'], backend,
                                   maximum=protocol['controls']['context_tokens'],
                                   max_tokens=protocol['controls']['max_output_tokens'], memory=True)
            elapsed = time.perf_counter() - started
            text = result.get('assistant_turn', {}).get('payload', {}).get('content')
            rows.append({'id': case['id'], 'category': case['category'], 'status': result['status'],
                         'original_prompt': case['prompt'], 'projected_prompt': projected['prompt'],
                         'prompt_changes': projected['changes'], 'response': text,
                         'score': score_response(case, text), 'latency_s': elapsed,
                         'input_tokens': result['projection']['input_tokens']})
    finally:
        telemetry = backend.unload()
    by_id = {row['id']: row['score'] for row in rows}
    return {'policy': policy, 'rows': rows, 'by_id': by_id, 'total': len(rows),
            'passed': sum(row['score']['pass'] for row in rows),
            'format_passed': sum(row['score']['format_pass'] for row in rows),
            'errors': sum(row['status'] != 'OK' for row in rows),
            'median_latency_s': statistics.median(row['latency_s'] for row in rows),
            'peak_rss_sum_bytes': telemetry['peak_rss_sum_bytes'],
            'peak_device_vram_increment_bytes': telemetry['peak_device_vram_increment_bytes'],
            'runtime_returncode': telemetry['runtime_returncode']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--intelligence-state', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    protocol = load_protocol(args.protocol)
    baseline = run_arm(protocol, 'ORIGINAL', args.state_root / 'baseline', args.intelligence_state)
    candidate = run_arm(protocol, protocol['candidate'], args.state_root / 'candidate', args.intelligence_state)
    result = {'schema': 'gaia_adapter_generalization_evaluation_v1',
              'protocol_content_sha256': protocol['content_sha256'], 'authority': 'NONE',
              'baseline': baseline, 'candidate': candidate,
              'result': decide(protocol, baseline, candidate)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + '\n')
    print(json.dumps({'output': str(args.output), 'baseline': baseline['passed'],
                      'candidate': candidate['passed'], **result['result']}, indent=2))


if __name__ == '__main__':
    main()
