"""Fail-closed qualification for resuming the interrupted Stage 2 C3.

This module does not execute a campaign.  It creates and validates the sealed
prospective contract needed by a dedicated recovery runner.  The existing C3
reservation and campaign are reused; no session, campaign or compute authority
is added and the historical result remains immutable.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import MethodType

from gaia.autonomy.inspection import inspect_campaign
from gaia.autonomy.session import SessionStore
from gaia.autonomy.supervisor import Supervisor
from gaia.autonomy.store import durable
from tools import stage2_executor as ex


SCHEMA = 'gaia_stage2_c3_recovery_v1'


def _sealed(value):
    if (not isinstance(value, dict)
            or value.get('hash') != ex.digest({k: v for k, v in value.items() if k != 'hash'})):
        raise ValueError('C3_RECOVERY_CONTRACT_HASH_MISMATCH')
    return value


def qualify(root, out, amendment):
    """Return the exact recoverable prefix or fail before writing anything."""
    root, out = Path(root).resolve(), Path(out).resolve()
    result_path = out / 'result-s2.json'
    start_path = out / 'session2-start.json'
    manifest_path = out / 'manifest-s2.json'
    if not all(p.is_file() and not p.is_symlink() for p in (result_path, start_path, manifest_path)):
        raise ValueError('C3_RECOVERY_EVIDENCE_MISSING')
    result = json.loads(result_path.read_bytes())
    start = json.loads(start_path.read_bytes())
    amendment = Path(amendment).resolve()
    if (result.get('status') != 'INCONCLUSIVE_ENVIRONMENT'
            or result.get('final_stage2_status') != 'INCONCLUSIVE_ENVIRONMENT'
            or result.get('error') != 'RuntimeError: EXTERNAL_BACKEND_BUSY'
            or result.get('terminal_replays') != []):
        raise ValueError('C3_RECOVERY_PREDECESSOR_NOT_QUALIFIED')
    if (result.get('administrative_amendment', {}).get('path') != str(amendment)
            or result['administrative_amendment'].get('sha256') != ex.sha(amendment)
            or start.get('administrative_amendment_sha256') != ex.sha(amendment)):
        raise ValueError('C3_RECOVERY_AMENDMENT_MISMATCH')
    effective = json.loads(amendment.read_bytes())['contract']
    state = Path(effective['state_path'])
    store = SessionStore(state, result['session_id'])
    view = store.state_view()
    if (view['campaigns'] != [view['running']] or view['finished'] or view['recoveries'] not in (0, 1)
            or view.get('stopped', {}).get('reason') != 'STAGE2_SAFETY_STOP'):
        raise ValueError('C3_RECOVERY_SESSION_PREFIX_INVALID')
    cid = view['running']
    campaign = inspect_campaign(state, cid)
    if (campaign['recovery'] != 'RECOVERABLE' or not campaign['resumable']
            or campaign['lineage_id'] != store.read()['lineages'][0]):
        raise ValueError('C3_CAMPAIGN_NOT_UNAMBIGUOUSLY_RECOVERABLE')
    if view['recoveries'] == 1:
        relaunches = [e for e in store.events() if e['kind'] == 'CAMPAIGN_RELAUNCHED']
        if (len(relaunches) != 1 or relaunches[0]['payload'].get('campaign_id') != cid
                or relaunches[0]['payload'].get('reason') != 'EXPLICIT_C3_PREFIX_RECOVERY'):
            raise ValueError('C3_RECOVERY_ATTEMPT_PREFIX_INVALID')
    aggregate = ex.StageBudget(out / 'budget', start['ledger_contract_hash'], [out])
    budget = aggregate.view()
    if (budget['sessions'][-1:] != [store.identifier]
            or budget['bindings'].get('S2-C3') != cid
            or 'S2-C3' in budget['charges']
            or 'S2-C4' in budget['reservations']
            or budget['reservations'].get('S2-C3', {}).get('seconds') != 1800):
        raise ValueError('C3_RECOVERY_BUDGET_PREFIX_INVALID')
    events = aggregate.events()
    if not events:
        raise ValueError('C3_RECOVERY_BUDGET_PREFIX_MISSING')
    return {'session_id': store.identifier, 'campaign_id': cid,
            'lineage_id': campaign['lineage_id'], 'campaign': campaign,
            'budget_prefix': {'events': len(events), 'tip': events[-1]['hash'], 'view': budget},
            'session_prefix': {'events': len(store.events()), 'tip': store.events()[-1]['hash'], 'view': view},
            'evidence': {str(p): ex.sha(p) for p in (result_path, start_path, manifest_path, amendment)},
            'ledger_contract_hash': start['ledger_contract_hash']}


def create(root, out, amendment, destination, *, authorize=False):
    if not authorize:
        raise ValueError('EXPLICIT_C3_RECOVERY_CONTRACT_AUTHORIZATION_REQUIRED')
    root, out, destination = Path(root).resolve(), Path(out).resolve(), Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(out):
        raise ValueError('NEW_EXTERNAL_C3_RECOVERY_DIRECTORY_REQUIRED')
    prefix = qualify(root, out, amendment)
    value = {'schema': SCHEMA, 'source_out': str(out), 'amendment': str(Path(amendment).resolve()),
             'commit': ex.safe_git(root, 'rev-parse', 'HEAD'), **prefix,
             'authority': {'new_sessions': 0, 'new_campaigns': 0, 'new_reservations': 0,
                           'resume_existing_campaign_only': True, 'promotion': False},
             'execution_prohibited': True}
    value['hash'] = ex.digest(value)
    destination.mkdir(parents=True)
    durable(destination / 'contract.json', value, True)
    return value


def validate(root, path):
    root, path = Path(root).resolve(), Path(path).resolve()
    value = _sealed(json.loads(path.read_bytes()))
    if value.get('schema') != SCHEMA or value.get('execution_prohibited') is not True:
        raise ValueError('INVALID_C3_RECOVERY_CONTRACT')
    if value['commit'] != ex.safe_git(root, 'rev-parse', 'HEAD'):
        raise ValueError('C3_RECOVERY_COMMIT_CHANGED')
    current = qualify(root, value['source_out'], value['amendment'])
    for key in ('session_id', 'campaign_id', 'lineage_id', 'budget_prefix', 'session_prefix',
                'evidence', 'ledger_contract_hash'):
        if value[key] != current[key]:
            raise ValueError('C3_RECOVERY_PREFIX_CHANGED:' + key)
    return value


def _supervisor(root, stage_contract, store, aggregate, boundary, evidence):
    """Construct the existing S2 supervisor without overwriting its old baseline."""
    from tools.stage2_session2 import SecondSessionSupervisor, session2_lineages
    from tools.stage2_runtime import EvidenceTelemetry
    from tools.stage2_fds import with_owned_pidfds
    from tools.stage2_runtime import process_metrics

    sup = SecondSessionSupervisor.__new__(SecondSessionSupervisor)
    Supervisor.__init__(sup, root, store.state, store.identifier)
    sup.lineage_contracts = session2_lineages(store.state, sup.contract['lineages'],
                                              sup.contract['lineages'][1])
    sup.original_numpy = sup.contract['lineages'][1]
    from tools.stage2_protocol import tool_hashes
    sup.orchestration_hashes = tool_hashes(root)
    sup.catalogue_before = {}
    sup.attribution_sampled = None
    sup.stage_contract = stage_contract
    sup.aggregate = aggregate
    sup.now = time.monotonic
    sup.boundary = boundary
    sup.telemetry = EvidenceTelemetry(evidence / 'telemetry', fd_provider=sup.fd_metrics)
    sup.child = None; sup.child_started = None; sup.owned = {}; sup.last_extra = None
    # Account only descriptors held by this new custody epoch.
    sup.baseline = with_owned_pidfds(process_metrics(os.getpid()), boundary)
    sup.last_fd_snapshot = sup.baseline
    sup.benchmark = None
    sup.environment_evidence = []
    sup.roles = {}

    def recovery_launch(this, campaign_id):
        """Launch with recovery-scoped receipts; never overwrite original C3 evidence."""
        this.guard()
        if this.boundary is None:
            raise RuntimeError('DEDICATED_SUBREAPER_REQUIRED')
        this.boundary.begin()
        scratch = ex.operational_scratch(this.stage_contract)
        binding = this.stage_contract['plan']['scratch_identity']
        logs = evidence / 'logs'; logs.mkdir(exist_ok=True)
        with (logs / f'{campaign_id}.out').open('ab') as out, \
                (logs / f'{campaign_id}.err').open('ab') as err:
            proc = subprocess.Popen([sys.executable, '-B', '-m', 'tools.stage2_campaign', 'autonomy-run',
                '--session', this.session.identifier, '--campaign', campaign_id, '--state-dir', str(this.state),
                '--scratch-root', str(scratch), '--scratch-device', str(binding['device']),
                '--scratch-inode', str(binding['inode']), '--journal',
                str(this.session.root / 'evidence/scratch-lifecycle.jsonl')], cwd=this.root,
                stdout=out, stderr=err, stdin=subprocess.DEVNULL, start_new_session=True,
                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        this.child = proc; this.child_started = this.now(); this.boundary.attach(proc)
        from gaia.autonomy.supervisor import proc_info
        info = proc_info(proc.pid)
        if info is None and proc.poll() is None:
            proc.kill(); proc.wait(); raise RuntimeError('CHILD_IDENTITY_UNAVAILABLE')
        if info:
            this.owned[proc.pid] = {'pid': proc.pid, 'starttime': info[7]}
        durable(evidence / f'{campaign_id}-launch.json', {'pid': proc.pid,
                'starttime': info[7] if info else None, 'campaign_id': campaign_id}, True)
        return proc

    sup.launch_run = MethodType(recovery_launch, sup)
    return sup


def execute(root, contract_path, *, authorize=False):
    """Resume only the sealed C3 campaign; C4 remains a separate operation."""
    if not authorize:
        raise ValueError('EXPLICIT_C3_RECOVERY_EXECUTION_AUTHORIZATION_REQUIRED')
    root, contract_path = Path(root).resolve(), Path(contract_path).resolve()
    contract = validate(root, contract_path)
    out = Path(contract['source_out'])
    amendment = json.loads(Path(contract['amendment']).read_bytes())
    stage_contract = dict(amendment['contract'])
    stage_contract['commit'] = contract['commit']
    stage_contract['hash'] = ex.digest({k: v for k, v in stage_contract.items() if k != 'hash'})
    state = Path(stage_contract['state_path'])
    store = SessionStore(state, contract['session_id'])
    from gaia.autonomy.lineage import engine_state_dir
    roots = [out, state, *[root / engine_state_dir(lin) for lin in stage_contract['lineages']],
             ex.operational_scratch(stage_contract)]
    aggregate = ex.StageBudget(out / 'budget', contract['ledger_contract_hash'], roots)
    evidence = contract_path.parent
    if (evidence / 'execution-intent.json').exists():
        raise ValueError('C3_RECOVERY_ALREADY_ATTEMPTED')
    with aggregate.exclusive():
        validate(root, contract_path)
        durable(evidence / 'execution-intent.json', {'contract_hash': contract['hash'],
                'budget_prefix': contract['budget_prefix'], 'session_prefix': contract['session_prefix']}, True)
        temporary = Path(tempfile.mkdtemp(prefix='gaia-stage2-c3-recovery-', dir='/tmp/opencode'))
        aggregate.owned_paths.extend([evidence, temporary])
        aggregate.check_paths()
        def record(event):
            with (temporary / 'children.jsonl').open('a') as stream:
                stream.write(json.dumps(event, sort_keys=True) + '\n'); stream.flush(); os.fsync(stream.fileno())
        from tools.stage2_children import ChildBoundary
        result = {'status': 'FAIL', 'contract_hash': contract['hash'],
                  'campaign_id': contract['campaign_id'], 'new_campaigns': 0,
                  'new_reservations': 0, 'budget_prefix_preserved': True}
        try:
            with ChildBoundary(record) as boundary:
                sup = _supervisor(root, stage_contract, store, aggregate, boundary, evidence)
                cid = contract['campaign_id']; sup.roles[cid] = 'S2-C3'
                before = store.root / 'evidence/S2-C3-catalogue-before.json'
                sup.catalogue_before[cid] = json.loads(before.read_bytes())
                # The old attempt spent real wall time before its guard stopped it.
                started = next(e['clock'] for e in store.events()
                               if e['kind'] == 'CAMPAIGN_STARTED' and e['payload']['campaign_id'] == cid)
                interrupted = json.loads((store.root / f'evidence/{cid}-interrupted.json').read_bytes())['clock']
                if started['boot_id'] != interrupted['boot_id']:
                    raise ValueError('C3_PRIOR_WALL_BOOT_DISCONTINUITY')
                prior_wall = max(0., interrupted['monotonic'] - started['monotonic'])
                if store.state_view()['recoveries'] == 0:
                    store.event('CAMPAIGN_RELAUNCHED', {'campaign_id': cid,
                        'lineage_id': contract['lineage_id'], 'relaunch': 1,
                        'reason': 'EXPLICIT_C3_PREFIX_RECOVERY', 'contract_hash': contract['hash']})
                info, outcome, supervised = sup.supervise(cid, contract['lineage_id'])
                sup.finish(cid, contract['lineage_id'], info, outcome, prior_wall + supervised)
                result.update(status='C3_RECOVERED', prior_wall_s=prior_wall,
                              resumed_wall_s=supervised, aggregate=aggregate.view(),
                              campaign=info, session=store.state_view())
        except BaseException as exc:
            result['error'] = f'{type(exc).__name__}: {exc}'
        durable(evidence / 'result.json', result, True)
        shutil.copytree(temporary, evidence / 'process-evidence')
        durable(evidence / 'manifest.json', ex.inventory([evidence], include_cache=True), True)
        return result
