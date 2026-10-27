"""Offline full Stage 2 decision: no campaign execution, repair or claim inference."""
import json
from pathlib import Path

from tools import stage2_executor as ex
from tools.stage2_observer import audit_observer, coverage
from tools.stage2_session2 import audit_second_aggregate
from tools.stage1_coverage import window_coverage
from tools.audit_endurance_session import audit_session
from gaia.autonomy.session import SessionStore
from gaia.autonomy.telemetry import Telemetry
from gaia.autonomy.store import CampaignStore
from gaia.autonomy.lineage import engine_state_dir


def attribution_window(rows, started, stopped):
    result = coverage(rows)
    if not rows:
        return result
    clocks = [started, *[row['clock'] for row in rows]]
    if rows[-1]['clock']['monotonic'] < stopped['monotonic']:
        clocks.append(stopped)
    if (len({clock['boot_id'] for clock in clocks}) != 1
            or any(not 0 <= b['monotonic'] - a['monotonic'] < 20
                   for a, b in zip(clocks, clocks[1:]))):
        result['failures'].append('ATTRIBUTION_SESSION_ENDPOINT_GAP')
    gpu = [row for row in rows if 'gpu' in row]
    if (not gpu or gpu[0]['clock']['monotonic'] - started['monotonic'] >= 60
            or stopped['monotonic'] - gpu[-1]['clock']['monotonic'] >= 60):
        result['failures'].append('GPU_ATTRIBUTION_ENDPOINT_GAP')
    if result['failures']:
        if result['status'] != 'FAIL':
            result['status'] = 'INCONCLUSIVE_ENVIRONMENT'
    return result


def final_decision(checks):
    """Missing evidence never means PASS; environmental gaps are distinguished."""
    required = {'session1', 'session2', 'window1', 'window2', 'aggregate',
                'attribution1', 'attribution2', 'catalogue_probe', 'catalogue_decisions',
                'terminal_replays', 'frozen_protocol', 'terminal_bytes', 'drift_coverage'}
    missing = sorted(required - checks.keys())
    failed = sorted(name for name in required & checks.keys() if checks[name]['status'] != 'PASS')
    environment = any(checks[name]['status'] == 'INCONCLUSIVE_ENVIRONMENT' for name in failed)
    violation = any(checks[name]['status'] == 'FAIL' for name in failed)
    return {'status': 'FAIL' if violation else 'BLOCKED' if missing else 'INCONCLUSIVE_ENVIRONMENT' if environment
            else 'FAIL' if failed else 'PASS', 'missing': missing, 'failed': failed}


def audit_full(root, out, contract, second_result):
    """Re-read both sessions, global budget, attribution and decision traces."""
    root, out = Path(root), Path(out)
    state = Path(contract['state_path'])
    first_result = json.loads((out / 'result-s1.json').read_bytes())
    first = SessionStore(state, first_result['session_id'])
    second = SessionStore(state, second_result['session_id'])
    roots = [out, out.parent / (out.name + '-observer'), state,
             *[root / engine_state_dir(lin) for lin in second.read()['lineages']],
             ex.operational_scratch(contract)]
    if second_result.get('temporary_evidence'):
        roots.append(Path(second_result['temporary_evidence']))
    aggregate = ex.StageBudget(out / 'budget', contract['hash'], roots)
    checks = {'session1': audit_session(root, state, first.identifier, stage='stage2'),
              'session2': audit_session(root, state, second.identifier, stage='stage2'),
              'window1': window_coverage(first), 'window2': window_coverage(second),
              'aggregate': audit_second_aggregate(second, aggregate, first)}
    checks['attribution1'] = audit_observer(out.parent / (out.name + '-observer'), contract['hash'],
        started=first.state_view()['started_clock'], stopped=first.events()[-1]['clock'])
    rows = [row for row in Telemetry(second.root / 'telemetry').samples() if row['kind'] == 'ATTRIBUTION']
    checks['attribution2'] = attribution_window(rows, second.state_view()['started_clock'], second.events()[-1]['clock'])
    before = json.loads((second.root / 'evidence/S2-C3-catalogue-before.json').read_bytes())
    checks['catalogue_probe'] = before['incompatible_probe']
    ids = second.state_view()['campaigns']
    checks['catalogue_decisions'] = json.loads((second.root / 'evidence' /
        f'{ids[-1]}-catalogue-decisions.json').read_bytes()) if len(ids) == 2 else {'status': 'FAIL'}
    boundary = json.loads((out / 'boundary/result.json').read_bytes())
    replays = [*boundary.get('terminal_replays', []), *second_result.get('terminal_replays', [])]
    checks['terminal_replays'] = {'status': 'PASS' if len(replays) == 4 and all(
        row.get('status') == row.get('child_creation_claim') == 'PASS' for row in replays) else 'FAIL'}
    changed = ex.changes(root, state, second.read()['freeze'])
    checks['frozen_protocol'] = {'status': 'PASS' if not changed else 'FAIL', 'changes': changed}
    changed_campaigns = []
    for session in (first, second):
        for cid in session.state_view()['campaigns']:
            saved = json.loads((session.root / 'evidence' / f'{cid}-terminal.json').read_bytes())
            if ex.inventory([CampaignStore(state, cid).root], include_cache=True) != saved['manifest']:
                changed_campaigns.append(cid)
    checks['terminal_bytes'] = {'status': 'FAIL' if changed_campaigns else 'PASS', 'changed': changed_campaigns}
    missing_drift = []
    for name in ('session1', 'session2'):
        for note in checks[name]['notes']:
            if (note.get('pss_coverage') == 'PARTIAL' or note.get('idle_rss_slope') == 'NOT_EXERCISED'
                    or note.get('vram_return_to_baseline') == 'NOT_EXERCISED'):
                missing_drift.append({'session': name, 'note': note})
    checks['drift_coverage'] = {'status': 'INCONCLUSIVE_ENVIRONMENT' if missing_drift else 'PASS',
                              'missing': missing_drift}
    return {**final_decision(checks), 'checks': checks,
            'scope': 'FULL_TWO_SESSION_STAGE2_NOT_A_SOFTWARE_TEST_CLAIM'}
