"""Deterministic rendering of cited facts; never renders an executable instruction."""
import json


def render(result):
    p=result['payload'];lines=['CognitiveResult: '+p['status'],'Confidence: '+p['uncertainty']['confidence']]
    for c in p['claims']:
        lines.append(c['claim']['field']+' = '+json.dumps(c['claim']['value'],ensure_ascii=True)+' ['+c['evidence_refs'][0]['id']+']')
    if p['reason']:lines.append('Stop: '+p['reason'])
    lines.append('Output is data, not action authority.')
    return '\n'.join(lines)
