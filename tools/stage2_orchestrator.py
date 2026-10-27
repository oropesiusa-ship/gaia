"""Stage 2 cross-session orchestration, separate from the frozen S1 executor.

Preparation, S1, boundary and S2 are separate CLI operations. The boundary is
read-only for S1 state, exercises terminal reopening under syscall tracing,
then archives NEW boundary evidence. Every real session requires explicit
authorization and independently audited recovery. S2_OBSERVED is not Stage 2
PASS: drift, catalogue decisions and lock-holder coverage are separate gates.

Boundary contract:
  input: unchanged, audited S1_OBSERVED with exactly two completed reservations;
  output: archived reconciliation and terminal-noop/process traces;
  rejection: missing/partial/modified evidence, changed budgets, any replay
             action/write/child or lost process containment;
  interruption: preserve evidence, prohibit automatic retry or state repair;
  idempotence: read-only checks repeat; an archived attempt is never overwritten.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import signal

from tools import stage2_executor as ex
from tools.stage2_boundary import inspect_boundary
from tools.stage2_children import ChildBoundary
from tools.stage2_terminal import traced_terminal_noop
from gaia.autonomy.clock import stamp
from gaia.autonomy.lineage import engine_state_dir
from gaia.autonomy.store import durable
from gaia.atomic_publish import fsync_directory
from tools.stage2_protocol import tool_hashes, verify_tools, verify_recovery


def prepare(root, out):
    """Fresh S1 contract plus binding of ALL added orchestration tools; no run."""
    contract = ex.prepare(root, out)
    value = {'schema': 'gaia_master_stage2_orchestration_v1',
             'base_contract_hash': contract['hash'], 'files': tool_hashes(root),
             'master_plan_sha256': ex.sha(Path(root) / 'docs' /
                 'GAIA — Plan Maestro de Estabilización y Cierre de la Versión 1.1'),
             'real_recovery_required': True, 'execution_prohibited': True}
    value['hash'] = ex.digest(value)
    durable(Path(out) / 'orchestration.json', value, True)
    return {'status': 'PREPARED_ONLY', 'execution_prohibited': True,
            'contract_hash': contract['hash'], 'orchestration_hash': value['hash']}


def binding(root, contract_path):
    contract_path = ex.safe_out(root, Path(contract_path)).resolve()
    contract = ex.validate_contract(json.loads(contract_path.read_bytes()))
    value = json.loads((contract_path.parent / 'orchestration.json').read_bytes())
    if (value.get('schema') != 'gaia_master_stage2_orchestration_v1'
            or value.get('hash') != ex.digest({k: v for k, v in value.items() if k != 'hash'})
            or value.get('base_contract_hash') != contract['hash']
            or value.get('real_recovery_required') is not True
            or value.get('execution_prohibited') is not True):
        raise ValueError('INVALID_MASTER_ORCHESTRATION_BINDING')
    verify_tools(root, value['files'])
    plan = Path(root) / 'docs' / 'GAIA — Plan Maestro de Estabilización y Cierre de la Versión 1.1'
    if ex.sha(plan) != value['master_plan_sha256']:
        raise ValueError('MASTER_PLAN_CHANGED')
    return contract, value


def run_first(root, contract_path, recovery_state, recovery_evidence, *, authorize=False):
    if not authorize:
        raise ValueError('EXPLICIT_STAGE2_S1_AUTHORIZATION_REQUIRED')
    binding(root, contract_path)
    recovery = verify_recovery(root, recovery_state, recovery_evidence)
    if recovery['status'] != 'PASS':
        return {'status': 'BLOCKED_PREEXECUTION', 'recovery': recovery,
                'sessions_started': 0, 'campaigns_started': 0}
    result = ex.run_first_session(root, contract_path, authorize=True)
    binding(root, contract_path)
    return result


def verified_boundary(root, contract_path, contract, roots):
    """Verify archived proof AND unchanged owned state before any S2 write."""
    from tools.stage2_terminal import process_trace
    out = Path(contract_path).resolve().parent
    archive = out / 'boundary'
    manifest_path = archive / 'manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    actual = ex.inventory([archive], include_cache=True)
    if {p: h for p, h in actual.items() if p != str(manifest_path)} != manifest:
        raise ValueError('BOUNDARY_ARCHIVE_CHANGED')
    proof = json.loads((archive / 'result.json').read_bytes())
    if (proof.get('status') != 'PASS' or proof.get('contract_hash') != contract['hash']
            or proof.get('containment') != 'PASS' or not proof.get('budget_unchanged')
            or len(proof.get('terminal_replays', [])) != 2):
        raise ValueError('BOUNDARY_NOT_PROVEN')
    children = [json.loads(line) for line in (archive / 'children.jsonl').read_text().splitlines()]
    drained = [row for row in children if row.get('kind') == 'CLEANUP_DRAINED']
    if (not children or children[-1].get('kind') != 'SUBREAPER_RESTORED'
            or children[-1].get('verified') is not True or len(drained) != 2
            or any(row.get('kernel_echild') is not True for row in drained)):
        raise ValueError('BOUNDARY_PROCESS_CONTAINMENT_UNPROVEN')
    for role, replay in zip(('S1-C1', 'S1-C2'), proof['terminal_replays']):
        trace_path = archive / f'{role}.strace'
        if (replay.get('status') != 'PASS' or replay.get('child_creation_claim') != 'PASS'
                or ex.sha(trace_path) != replay.get('trace_sha256')
                or process_trace(trace_path.read_text())['status'] != 'PASS'):
            raise ValueError('BOUNDARY_TERMINAL_REPLAY_UNPROVEN')
    baseline = proof['inspection']['owned_manifest']
    observed = ex.inventory(roots, include_cache=True)
    observed = {p: h for p, h in observed.items()
                if not Path(p).is_relative_to(archive)}
    if observed != baseline:
        raise ValueError('STATE_CHANGED_AFTER_BOUNDARY')
    return proof


def run_second(root, contract_path, recovery_state, recovery_evidence, *, authorize=False):
    """One dedicated, explicitly authorized S2; no repair or automatic retry."""
    if not authorize:
        raise ValueError('EXPLICIT_STAGE2_S2_AUTHORIZATION_REQUIRED')
    if __name__ != '__main__':
        raise RuntimeError('DEDICATED_ORCHESTRATOR_CLI_REQUIRED')
    from tools.stage2_boundary import boundary_admission
    from tools.stage2_session2 import SecondSessionSupervisor, audit_second_aggregate
    from tools.stage2_terminal import traced_terminal_noop
    from tools.audit_endurance_session import audit_session
    from tools.stage1_coverage import window_coverage
    from gaia.autonomy.lineage import create_lineage
    from gaia.autonomy.freeze import freeze
    from gaia.autonomy.session import SessionStore, session_contract
    root, contract_path = Path(root).resolve(), Path(contract_path).resolve()
    contract, protocol = binding(root, contract_path)
    recovery = verify_recovery(root, recovery_state, recovery_evidence)
    if recovery['status'] != 'PASS':
        return {'status': 'BLOCKED_PREEXECUTION', 'recovery': recovery,
                'sessions_started': 0, 'campaigns_started': 0}
    out, state = contract_path.parent, Path(contract['state_path'])
    if (out / 'session2-start.json').exists():
        raise ValueError('S2_ALREADY_STARTED_OR_AMBIGUOUS_NO_AUTOMATIC_RETRY')
    roots = [out, state, *[root / engine_state_dir(lin) for lin in contract['lineages']],
             ex.operational_scratch(contract)]
    if not (out / 'budget/.lock').is_file():
        raise ValueError('MISSING_S1_BUDGET_LOCK')
    aggregate = ex.StageBudget(out / 'budget', contract['hash'], roots)
    with aggregate.exclusive():
        proof = verified_boundary(root, contract_path, contract, roots)
        admission = boundary_admission(contract, root, state)
        if admission['status'] != 'PASS':
            return {'status': 'BLOCKED_PREEXECUTION', 'admission': admission,
                    'sessions_started': 0, 'campaigns_started': 0}
        # Mark intent before the first state change. A crash leaves an explicit
        # ambiguous attempt; restarting never silently creates a new lineage.
        durable(out / 'session2-start.json', {'clock': stamp(),
                'contract_hash': contract['hash'], 'orchestration_hash': protocol['hash'],
                'boundary_manifest_sha256': ex.sha(out / 'boundary/manifest.json')}, True)
        numpy = contract['lineages'][0]
        inference = create_lineage(root, state, 'IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA')
        inference_native = root / engine_state_dir(inference['lineage_id'])
        if inference_native.exists():
            raise ValueError('EXISTING_INFERENCE_ENGINE_NAMESPACE')
        roots.append(inference_native)
        aggregate.owned_paths.append(inference_native)
        aggregate.check_paths()
        ids = [inference['lineage_id'], numpy]
        frozen = freeze(root, state, ids)
        session = session_contract(ids, stage='stage2', limits=ex.LIMITS, frozen=frozen)
        sid = session['session_id']
        aggregate.start_session(sid)
        store = SessionStore(state, sid)
        store.create(session, root)
        first = SessionStore(state, proof['inspection']['session_id'])
        temporary = Path(tempfile.mkdtemp(prefix='gaia-stage2-session2-', dir='/tmp/opencode'))
        # Trace output is outside the read-only replay scope, but never outside
        # the aggregate storage budget. Keep it after archival as evidence.
        aggregate.owned_paths.append(temporary)
        aggregate.check_paths()
        result = {'status': 'FAIL', 'session_id': sid, 'terminal_replays': [],
                  'temporary_evidence': str(temporary), 'final_stage2_status': 'NOT_EXERCISED',
                  'final_pass_blockers': ['FULL_DRIFT_ATTRIBUTION_NOT_EXERCISED',
                      'CATALOGUE_REFERENCE_DECISION_COVERAGE_NOT_PROVEN',
                      'LOCK_HOLDER_ATTRIBUTION_NOT_EXERCISED']}

        def record(event):
            with (temporary / 'children.jsonl').open('a') as stream:
                stream.write(json.dumps({'clock': stamp(), **event}, sort_keys=True) + '\n')
                stream.flush()
                os.fsync(stream.fileno())

        with ChildBoundary(record) as owner:
            supervisor = SecondSessionSupervisor(root, state, sid, contract, aggregate,
                original_numpy=numpy, orchestration_hashes=protocol['files'], boundary=owner)
            try:
                supervisor.run()
                checks = {'session': audit_session(root, state, sid, stage='stage2'),
                          'reconciliation': ex.reconcile(store, roots, root=root),
                          'aggregate': audit_second_aggregate(store, aggregate, first),
                          'coverage': window_coverage(store)}
                result['checks'] = checks
                for cid in store.state_view()['campaigns']:
                    row = traced_terminal_noop(state, cid, roots, temporary / f'{cid}.strace',
                                               root=root, boundary=owner)
                    result['terminal_replays'].append(row)
                    if row['status'] != 'PASS':
                        break
                if (all(check['status'] == 'PASS' for check in checks.values())
                        and len(result['terminal_replays']) == 2
                        and all(row['status'] == 'PASS' for row in result['terminal_replays'])):
                    result['status'] = 'S2_OBSERVED'
            except BaseException as exc:
                result['error'] = f'{type(exc).__name__}: {exc}'
                if not store.state_view()['stopped']:
                    supervisor.stop('STAGE2_SAFETY_STOP', error=result['error'])
        result['aggregate'] = aggregate.view()
        durable(out / 'result-s2.json', result, True)
        required = sum(p.stat().st_size for p in temporary.rglob('*') if p.is_file())
        if aggregate.storage() + required + 4096 >= 4 * 2**30:
            raise RuntimeError('S2_ARCHIVAL_STORAGE_BUDGET; retained at ' + str(temporary))
        shutil.copytree(temporary, out / 'session2-process-evidence')
        durable(out / 'manifest-s2.json', ex.inventory(roots, include_cache=True), True)
        return result


def boundary(root, contract_path):
    """Dedicated CLI operation; a diagnostic failure never admits a session."""
    if __name__ != '__main__':
        raise RuntimeError('DEDICATED_ORCHESTRATOR_CLI_REQUIRED')
    root = Path(root).resolve()
    contract_path = ex.safe_out(root, Path(contract_path)).resolve()
    out = contract_path.parent
    destination = out / 'boundary'
    if destination.exists():
        raise FileExistsError('BOUNDARY_ALREADY_ATTEMPTED_NO_AUTOMATIC_RETRY')
    # Do not create a budget/lock while inspecting partial or missing S1 state.
    if not (out / 'budget/.lock').is_file():
        raise ValueError('MISSING_S1_BUDGET_LOCK')
    contract = ex.validate_contract(json.loads(contract_path.read_bytes()))
    state = Path(contract['state_path'])
    roots = [out, state, *[root / engine_state_dir(lin) for lin in contract['lineages']],
             ex.operational_scratch(contract)]
    aggregate = ex.StageBudget(out / 'budget', contract['hash'], roots)
    temporary_root = Path('/tmp/opencode')
    if not temporary_root.is_dir():
        raise ValueError('APPROVED_TEMPORARY_DIRECTORY_UNAVAILABLE')
    # Never delete a failed diagnostic's traces: the directory is archived below,
    # or retained at its original path if archival is itself interrupted.
    work = Path(tempfile.mkdtemp(prefix='gaia-stage2-boundary-', dir=temporary_root))
    result = {'status': 'BLOCKED_PREEXECUTION', 'execution_prohibited': True,
              'clock': stamp(), 'contract_hash': contract['hash'],
              'temporary_evidence': str(work), 'terminal_replays': []}
    with aggregate.exclusive():
        snapshot = aggregate.view()
        result['inspection'] = inspect_boundary(root, contract_path)
        if result['inspection']['status'] == 'PASS':
            def record(event):
                with (work / 'children.jsonl').open('a') as stream:
                    stream.write(json.dumps({'clock': stamp(), **event}, sort_keys=True) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
            try:
                with ChildBoundary(record) as owner:
                    for role in ('S1-C1', 'S1-C2'):
                        cid = snapshot['bindings'][role]
                        row = traced_terminal_noop(state, cid, roots, work / f'{role}.strace',
                                                   root=root, boundary=owner)
                        result['terminal_replays'].append(row)
                        if row['status'] != 'PASS':
                            break
                if owner.record_error:
                    raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:' + owner.record_error)
                result['containment'] = 'PASS'
                if (len(result['terminal_replays']) == 2
                        and all(row['status'] == 'PASS' for row in result['terminal_replays'])
                        and aggregate.view() == snapshot):
                    result['status'] = 'PASS'
            except (OSError, ValueError, RuntimeError) as exc:
                result['error'] = str(exc)
        result['budget_unchanged'] = aggregate.view() == snapshot
        if not result['budget_unchanged']:
            result['status'] = 'BLOCKED_PREEXECUTION'
        durable(work / 'result.json', result, True)
        required = sum(p.stat().st_size for p in work.rglob('*') if p.is_file())
        if aggregate.storage() + required + 4096 >= 4 * 2**30:
            raise RuntimeError('BOUNDARY_ARCHIVAL_STORAGE_BUDGET; retained at ' + str(work))
        # Preserve originals and refuse overwrite. S1 manifest remains unchanged;
        # this explicit NEW evidence directory is written only after inspection.
        shutil.copytree(work, destination)
        for source in work.rglob('*'):
            if source.is_file():
                target = destination / source.relative_to(work)
                if ex.sha(source) != ex.sha(target):
                    raise RuntimeError('BOUNDARY_ARCHIVE_HASH_MISMATCH')
                with target.open('rb') as stream:
                    os.fsync(stream.fileno())
                target.chmod(0o444)
        durable(destination / 'manifest.json', ex.inventory([destination], include_cache=True), True)
        fsync_directory(destination)
        fsync_directory(out)
    result['evidence_path'] = str(destination)
    return result


def dispatch():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare')
    prep.add_argument('--out', required=True)
    inspect = commands.add_parser('inspect-boundary')
    inspect.add_argument('--contract', required=True)
    first = commands.add_parser('run-first-session')
    first.add_argument('--contract', required=True)
    first.add_argument('--recovery-state', required=True)
    first.add_argument('--recovery-evidence', required=True)
    first.add_argument('--authorize-stage2-s1', action='store_true')
    second = commands.add_parser('run-second-session')
    second.add_argument('--contract', required=True)
    second.add_argument('--recovery-state', required=True)
    second.add_argument('--recovery-evidence', required=True)
    second.add_argument('--authorize-stage2-s2', action='store_true')
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(ex.ROOT, args.out)
    elif args.command == 'run-first-session':
        result = run_first(ex.ROOT, args.contract, args.recovery_state,
                           args.recovery_evidence, authorize=args.authorize_stage2_s1)
    elif args.command == 'run-second-session':
        result = run_second(ex.ROOT, args.contract, args.recovery_state,
                            args.recovery_evidence, authorize=args.authorize_stage2_s2)
    else:
        result = boundary(ex.ROOT, args.contract)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] in ('PASS', 'PREPARED_ONLY', 'S1_OBSERVED', 'S2_OBSERVED') else 2


def main():
    def stop(signum, frame):
        raise KeyboardInterrupt(f'STAGE2_ORCHESTRATOR_SIGNAL_{signum}')
    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        return dispatch()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
