"""Read-only cross-session Stage 2 reconciliation; never admits a campaign.

This is distinct from ChildBoundary (Linux process containment). A successful
inspection is evidence only, not permission to start session 2. The S1 executor
and its original evidence remain untouched.
"""
import json
import copy
from pathlib import Path

from tools import stage2_executor as ex
from tools.stage2_runtime import audit_aggregate
from tools.audit_endurance_session import audit_session
from tools.stage1_coverage import window_coverage
from gaia.autonomy.lineage import engine_state_dir
from gaia.autonomy.session import SessionStore


def boundary_admission(contract, root, state):
    """Allow only the documented first NumPy benchmark creation after S1.

    Initial admission compares whole freezes. Cross-session inspection must
    still reject every other change, while accepting the benchmark that the
    first campaign creates (gaia.autonomy.freeze.changes uses this same rule).
    """
    check = ex.admission(contract, root, state)
    current = copy.deepcopy(check['freeze'])
    expected = contract['freeze']
    for lineage, previous in expected['lineages'].items():
        if previous['benchmark_hash'] is None:
            current['lineages'][lineage]['benchmark_hash'] = None
    current.pop('hash', None)
    original = {k: v for k, v in expected.items() if k != 'hash'}
    if current == original:
        check['reasons'] = [r for r in check['reasons'] if r != 'FROZEN_PROTOCOL_CHANGED']
    check['status'] = 'PASS' if not check['reasons'] else 'BLOCKED_PREEXECUTION'
    return check


def verify_manifest(expected, actual, manifest_path):
    """S1 writes its manifest last; only that file is outside its own snapshot."""
    if not isinstance(expected, dict) or not expected:
        raise ValueError('MISSING_S1_MANIFEST')
    observed = {p: h for p, h in actual.items() if p != str(manifest_path)}
    if observed != expected:
        raise ValueError('S1_MANIFEST_CHANGED')


def inspect_boundary(root, contract_path):
    """Reconcile persisted S1 evidence without repairs, locks or terminal replay.

    Replays need a dedicated process owner to prove zero ephemeral children and
    are deliberately not performed here. Even PASS leaves execution prohibited.
    """
    root = Path(root).resolve()
    contract_path = ex.safe_out(root, Path(contract_path)).resolve()
    out = contract_path.parent
    result = {'status': 'BLOCKED_PREEXECUTION', 'execution_prohibited': True,
              'terminal_replays': 'NOT_EXERCISED', 'failures': []}
    before = None
    roots = None
    try:
        contract = ex.validate_contract(json.loads(contract_path.read_bytes()))
        state = Path(contract['state_path'])
        if state != out / 'state':
            raise ValueError('CANONICAL_STAGE2_STATE_REQUIRED')
        roots = [out, state, *[root / engine_state_dir(lin)
                              for lin in contract['lineages']],
                 ex.operational_scratch(contract)]
        before = ex.inventory(roots, include_cache=True)
        result['owned_manifest'] = before
        manifest_path = out / 'manifest-s1.json'
        verify_manifest(json.loads(manifest_path.read_bytes()), before, manifest_path)
        observed = json.loads((out / 'result-s1.json').read_bytes())
        if observed.get('status') != 'S1_OBSERVED':
            raise ValueError('S1_NOT_OBSERVED')
        if observed.get('subreaper', {}).get('status') != 'PASS':
            raise ValueError('S1_PROCESS_CONTAINMENT_UNPROVEN')
        aggregate = ex.StageBudget(out / 'budget', contract['hash'], roots)
        view = aggregate.view()
        sid = observed['session_id']
        if view['sessions'] != [sid]:
            raise ValueError('EXPECTED_EXACTLY_ONE_COMPLETED_SESSION')
        store = SessionStore(state, sid)
        checks = {'admission': boundary_admission(contract, root, state),
                  'reconciliation': ex.reconcile(store, roots, root=root),
                  'aggregate': audit_aggregate(store, aggregate),
                  'session_audit': audit_session(root, state, sid, stage='stage2'),
                  'coverage': window_coverage(store)}
        result['checks'] = checks
        result['session_id'] = sid
        result['aggregate_snapshot'] = view
        result['failures'].extend(name for name, check in checks.items()
                                  if check.get('status') != 'PASS')
        if not result['failures']:
            result['status'] = 'PASS'
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['failures'].append(str(exc))
    finally:
        if before is not None:
            try:
                if ex.inventory(roots, include_cache=True) != before:
                    result['failures'].append('BOUNDARY_INSPECTION_WROTE_OR_STATE_CHANGED')
            except (OSError, ValueError) as exc:
                result['failures'].append(str(exc))
        if result['failures']:
            result['status'] = 'BLOCKED_PREEXECUTION'
    return result
