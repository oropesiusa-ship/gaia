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
from gaia.autonomy.supervisor import alive


def retained_scratch(contract,state,session_ids):
    """Read-only proof of retained terminal work; never clean or adopt it."""
    scratch=ex.operational_scratch(contract)
    before=ex.inventory([scratch],include_cache=True)
    groups={};known=set();journals=[]
    for sid in session_ids:
        store=SessionStore(state,sid);view=store.state_view()
        if view['running']or not view['stopped']or len(view['finished'])!=len(view['campaigns']):
            raise ValueError('SCRATCH_SESSION_NOT_TERMINAL')
        journal=store.root/'evidence'/'scratch-lifecycle.jsonl'
        if journal.with_name(journal.name+'.pending').exists():raise ValueError('SCRATCH_JOURNAL_UNRESOLVED')
        if not journal.exists():continue
        ex.inventory([journal],include_cache=True)
        data=journal.read_bytes();journals.append({'path':str(journal),'sha256':ex.sha(journal)})
        if data and not data.endswith(b'\n'):raise ValueError('SCRATCH_JOURNAL_PARTIAL_ROW')
        for line in data.splitlines():
            row=json.loads(line);work=Path(row['work'])
            if (work.parent!=scratch or not work.name.startswith('inference-')
                    or row['scratch_root']!=str(scratch)or row['scratch_identity']!=contract['plan']['scratch_identity']
                    or row['session_id']!=sid or row['campaign_id']not in view['campaigns']):
                raise ValueError('SCRATCH_OWNER_BINDING_MISMATCH')
            groups.setdefault(str(work),[]).append(row)
    if {str(path)for path in scratch.iterdir()}!=set(groups):raise ValueError('UNEXPLAINED_RETAINED_SCRATCH')
    for work,rows in groups.items():
        created=[row for row in rows if row['event']=='CREATED']
        if (len(created)!=1 or [row['event']for row in rows]!=
                ['CREATE_INTENT','CREATED','LAUNCH_INTENT','CHILD','LOADED','RELEASED','UNLOADED']
                or rows[-1]['event']!='UNLOADED'or rows[-1].get('state')!='TERMINAL_RETAINED_SUCCESS'
                or any(row['event']in('LOAD_FAILED','UNLOAD_FAILED','RELEASE_FAILED')or
                       str(row.get('state','')).startswith('UNRESOLVED')for row in rows)):
            raise ValueError('SCRATCH_NOT_SUCCESSFULLY_TERMINAL')
        marker=json.loads((Path(work)/'stage2-owner.json').read_bytes())
        if marker!=created[0]:raise ValueError('SCRATCH_OWNER_RECEIPT_CHANGED')
        expected=created[0]
        if ex.sha(Path(work)/'job.json')!=expected['job_hash']:raise ValueError('SCRATCH_JOB_CHANGED')
        for row in rows:
            if any(row[key]!=expected[key]for key in ('owner','session_id','campaign_id','job_hash','stack_hash')):
                raise ValueError('SCRATCH_LIFECYCLE_BINDING_CHANGED')
            if row['owner']['boot_id']!=contract['boot_id']:raise ValueError('SCRATCH_BOOT_MISMATCH')
            if alive(row['owner']['pid'],row['owner']['start_time']):raise ValueError('SCRATCH_OWNER_STILL_ALIVE')
            if row['event']=='CHILD':
                child=row['child']
                if child['boot_id']!=contract['boot_id']or alive(child['pid'],child['start_time']):
                    raise ValueError('SCRATCH_CHILD_STILL_ALIVE_OR_BOOT_CHANGED')
        if not any(row['event']=='CHILD'for row in rows)or not any(row['event']=='LOADED'for row in rows):
            raise ValueError('SCRATCH_EXECUTION_RECEIPTS_MISSING')
        known.add(work)
    if before!=ex.inventory([scratch],include_cache=True):raise ValueError('SCRATCH_CHANGED_DURING_INSPECTION')
    return {'status':'PASS','retained_directories':len(known),'journals':journals,'manifest':before,'read_only':True}


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
    if 'OPERATIONAL_BACKEND_SCRATCH_BUSY'in check['reasons']:
        try:
            out=Path(contract['state_path']).parent
            observed=json.loads((out/'result-s1.json').read_bytes())
            if observed['status']!='S1_OBSERVED':raise ValueError('S1_NOT_OBSERVED')
            check['retained_scratch']=retained_scratch(contract,state,[observed['session_id']])
            check['reasons']=[reason for reason in check['reasons']if reason!='OPERATIONAL_BACKEND_SCRATCH_BUSY']
        except (OSError,ValueError,KeyError,TypeError)as exc:
            check['reasons'].append('RETAINED_SCRATCH_UNVERIFIED:'+str(exc))
    check['status'] = 'PASS' if not check['reasons'] else 'BLOCKED_PREEXECUTION'
    return check


def verify_manifest(expected, actual, manifest_path, additional=None):
    """S1 writes its manifest last; only that file is outside its own snapshot."""
    if not isinstance(expected, dict) or not expected:
        raise ValueError('MISSING_S1_MANIFEST')
    additional=additional or {}
    if set(additional)&set(expected)or any(actual.get(p)!=h for p,h in additional.items()):
        raise ValueError('ADMINISTRATIVE_ARCHIVE_CHANGED_OR_OVERLAPS_S1')
    observed = {p: h for p, h in actual.items() if p != str(manifest_path)and p not in additional}
    if observed != expected:
        raise ValueError('S1_MANIFEST_CHANGED')


def inspect_boundary(root, contract_path, *, contract_override=None, additional=None,ledger_hash=None):
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
        contract = ex.validate_contract(contract_override if contract_override is not None else json.loads(contract_path.read_bytes()))
        state = Path(contract['state_path'])
        if state != out / 'state':
            raise ValueError('CANONICAL_STAGE2_STATE_REQUIRED')
        roots = [out, state, *[root / engine_state_dir(lin)
                              for lin in contract['lineages']],
                 ex.operational_scratch(contract)]
        before = ex.inventory(roots, include_cache=True)
        result['owned_manifest'] = before
        manifest_path = out / 'manifest-s1.json'
        verify_manifest(json.loads(manifest_path.read_bytes()), before, manifest_path,additional=additional)
        observed = json.loads((out / 'result-s1.json').read_bytes())
        if observed.get('status') != 'S1_OBSERVED':
            raise ValueError('S1_NOT_OBSERVED')
        if observed.get('subreaper', {}).get('status') != 'PASS':
            raise ValueError('S1_PROCESS_CONTAINMENT_UNPROVEN')
        aggregate = ex.StageBudget(out / 'budget', ledger_hash or contract['hash'], roots)
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
