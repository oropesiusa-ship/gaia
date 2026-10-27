"""Read-only evidence gates for the master-plan orchestration.

The master plan is the governing work order. Historical drills are evidence,
not a ban on the newly requested work. Tests, endurance PASS, or a missing
promotion can never satisfy the real post-promotion recovery gate.
"""
import json
from pathlib import Path

from tools import stage2_executor as ex
from gaia.autonomy.policy import identities


FILES = (*ex.ADMIN_FILES, 'tools/stage2_boundary.py', 'tools/stage2_learning.py',
         'tools/stage2_terminal.py', 'tools/stage2_session2.py',
         'tools/stage2_orchestrator.py', 'tools/stage2_protocol.py', 'tools/stage2_observer.py',
         'tools/stage2_audit.py')


def tool_hashes(root):
    return {path: ex.sha(Path(root) / path) for path in FILES}


def verify_tools(root, expected):
    if set(expected) != set(FILES) or tool_hashes(root) != expected:
        raise ValueError('ORCHESTRATION_TOOL_HASH_CHANGED')


def recovery_claim_gate(seal, result, fault, current_identity):
    """Validate claims before the independent native/state audit.

    This pure check is necessary, never sufficient: verify_recovery also replays
    the actual journals and validates the restored native ledger/reference.
    """
    failures = []
    if seal.get('status') != 'PASS' or seal.get('outcome') != 'PASS':
        failures.append('REAL_RECOVERY_NOT_PASS')
    if seal.get('identity') != current_identity:
        failures.append('RECOVERY_SOURCE_IDENTITY_CHANGED')
    if result.get('status') != 'PASS' or result.get('outcome') != 'PASS':
        failures.append('REAL_RECOVERY_RESULT_NOT_PASS')
    if not fault.get('injection', {}).get('injected'):
        failures.append('REAL_FAULT_NOT_OBSERVED')
    if result.get('survivors'):
        failures.append('RECOVERY_PROCESS_SURVIVORS')
    if not result.get('native_ledger', {}).get('ok'):
        failures.append('RECOVERY_NATIVE_LEDGER_UNVERIFIED')
    if not result.get('rollback_count'):
        failures.append('REAL_ROLLBACK_NOT_OBSERVED')
    reference = result.get('reference') or {}
    if reference.get('reason') != 'AFTER_ROLLBACK' or reference.get('status') != 'MEASURED':
        failures.append('RESTORED_REFERENCE_NOT_REMEASURED')
    return failures


def master_recovery_claim_gate(seal, result, fault, current_identity):
    """Keep the legacy rollback claim separate from master-plan phase 5.

    Phase 5 requires real recovery to a valid version, not an unnecessary
    rollback of a promotion whose resumed verification passes. The old drill's
    stricter rollback result is retained verbatim; no legacy gate is changed.
    A resume claim still needs independent journals, gates, ledger and replay
    below, and can never be inferred from this claim-only function.
    """
    if result.get('outcome') != 'NOT_EXERCISED_ROLLBACK':
        return 'ROLLBACK_RESTORE', recovery_claim_gate(seal, result, fault, current_identity)
    failures = []
    if seal.get('outcome') != 'NOT_EXERCISED_ROLLBACK' or seal.get('status') != 'FAIL':
        failures.append('LEGACY_ROLLBACK_CLAIM_INCONSISTENT')
    if result.get('status') != 'FAIL' or result.get('rollback_count') != 0:
        failures.append('LEGACY_ROLLBACK_RESULT_INCONSISTENT')
    if seal.get('identity') != current_identity:
        failures.append('RECOVERY_SOURCE_IDENTITY_CHANGED')
    if not fault.get('injection', {}).get('injected'):
        failures.append('REAL_FAULT_NOT_OBSERVED')
    if result.get('survivors') or result.get('lineage_blocked') is not False:
        failures.append('UNSAFE_RECOVERY_STATE')
    if not result.get('native_ledger', {}).get('ok'):
        failures.append('RECOVERY_NATIVE_LEDGER_UNVERIFIED')
    reference = result.get('reference') or {}
    if (reference.get('reason') != 'POST_PROMOTION' or reference.get('status') != 'MEASURED'
            or reference.get('version') != result.get('native_version')):
        failures.append('PROMOTED_REFERENCE_UNVERIFIED')
    return 'RESUME_VERIFICATION', failures


def resume_sequence_gate(events, campaign_id, fault_clock):
    """One killed controller, a normal VERIFYING relaunch, then a clean exit."""
    relevant = [e for e in events if e['kind'] in ('CHILD_EXITED', 'CAMPAIGN_RELAUNCHED')
                and e['payload'].get('campaign_id') == campaign_id]
    if len(relevant) != 3:
        raise ValueError('REAL_RECOVERY_SEQUENCE_NOT_PROVEN')
    killed, resumed, completed = relevant
    if (killed['kind'] != 'CHILD_EXITED' or killed['payload'].get('returncode') != -9
            or resumed['kind'] != 'CAMPAIGN_RELAUNCHED'
            or resumed['payload'].get('reason') != 'RESUMES_AT_VERIFYING'
            or completed['kind'] != 'CHILD_EXITED' or completed['payload'].get('returncode') != 0
            or any(e['payload'].get('survivors') or e['payload'].get('orphans_stopped') for e in relevant)):
        raise ValueError('REAL_RECOVERY_SEQUENCE_NOT_PROVEN')
    clocks = [fault_clock, *[e['clock'] for e in relevant]]
    if (len({clock['boot_id'] for clock in clocks}) != 1
            or any(b['monotonic'] < a['monotonic'] for a, b in zip(clocks, clocks[1:]))):
        raise ValueError('REAL_RECOVERY_CLOCK_SEQUENCE_INVALID')
    return completed['clock']['monotonic'] - fault_clock['monotonic']


def verify_recovery(root, state, evidence):
    """Independent master-plan phase 5 audit; legacy rollback result is retained."""
    root, state, evidence = Path(root).resolve(), Path(state).absolute(), Path(evidence).absolute()
    result = {'status': 'BLOCKED_PREEXECUTION', 'failures': [], 'execution_prohibited': True}
    before = None
    scope = [state, evidence]
    try:
        if (state.parent != root or not state.name.startswith('state_endurance_stage1_recovery_')
                or state.is_symlink() or not state.is_dir()):
            raise ValueError('EXISTING_DISPOSABLE_RECOVERY_STATE_REQUIRED')
        before = ex.inventory(scope, include_cache=True)
        seal = json.loads((evidence / '07-seal.json').read_bytes())
        native_result = json.loads((evidence / '05-recovery_result.json').read_bytes())
        fault = json.loads((evidence / '03-planned_fault.json').read_bytes())
        mode, result['failures'] = master_recovery_claim_gate(seal, native_result, fault, identities(root))
        result.update(recovery_mode=mode, legacy_outcome=native_result.get('outcome'),
                      rollback_claim='PASS' if mode == 'ROLLBACK_RESTORE' else 'NOT_EXERCISED')
        if result['failures']:
            return result
        from gaia.autonomy.session import SessionStore
        from gaia.autonomy.lineage import LineageStore, engine_state_dir
        from gaia.autonomy.store import CampaignStore
        from gaia.store import Store
        from gaia.ledger import verify_ledger
        from tools.audit_endurance_session import audit_session
        from tools.stage0_preflight import no_duplicate_execution
        from tools.stage1_recovery_drill import recovery_outcome
        session = SessionStore(state, seal['session_id'])
        view = session.state_view()
        if not view['stopped'] or view['running'] or len(view['campaigns']) != 1:
            raise ValueError('RECOVERY_SESSION_NOT_CLEANLY_TERMINAL')
        cid = view['campaigns'][0]
        campaign = CampaignStore(state, cid)
        configuration = campaign.read('contract')
        lineage_id = configuration['lineage_id']
        native_path = root / engine_state_dir(lineage_id)
        if not native_path.is_dir() or str(native_path) != native_result['native_state']:
            raise ValueError('RECOVERY_NATIVE_STATE_MISMATCH')
        # Include native state in the read-only snapshot before opening Store;
        # the existence check prevents its constructor from creating a directory.
        scope.append(native_path)
        before.update(ex.inventory([native_path], include_cache=True))
        native = Store(root, engine_state_dir(lineage_id))
        ledger = verify_ledger(native)
        lineage = LineageStore(state, lineage_id).state()
        current = campaign.inspect()['state']
        audit = audit_session(root, state, session.identifier)
        duplicates = no_duplicate_execution(state, cid)
        reference = lineage.get('reference')
        verdict = recovery_outcome(True, audit, duplicates, lineage, current, reference)
        if (audit['status'] != 'PASS' or not duplicates['unique']
                or duplicates['intents_reserved'] != duplicates['evaluations']
                or lineage['blocked'] or not ledger['ok']
                or (mode == 'ROLLBACK_RESTORE' and verdict != 'PASS')):
            raise ValueError('INDEPENDENT_RECOVERY_AUDIT_FAILED')
        evaluation = campaign.get(current['evaluation_ref'])
        restored = native.current_version()
        expected_version = evaluation['before_version' if mode == 'ROLLBACK_RESTORE' else 'after_version']
        if (reference['version'] != restored or restored != expected_version
                or restored != native_result['native_version']):
            raise ValueError('RESTORED_VERSION_REFERENCE_MISMATCH')
        proof = json.loads((session.root / 'verification-kill-intent.json').read_bytes())
        if proof != fault['injection']['proof'] or proof['campaign_id'] != cid:
            raise ValueError('REAL_FAULT_PROOF_MISMATCH')
        if mode == 'RESUME_VERIFICATION':
            elapsed = resume_sequence_gate(session.events(), cid, proof['clock'])
            verification = campaign.get(current['verification_ref'])
            if (evaluation['before_version'] == evaluation['after_version']
                    or verification.get('status') != 'PASS' or not verification.get('ledger_ok')
                    or not verification.get('persisted_improvement')
                    or verification.get('gates', {}).get('status') != 'READY_FOR_CAMPAIGN'
                    or verification.get('regression_matrix', {}).get('status') != 'PASS'
                    or 'FULL' not in verification['regression_matrix'].get('interrupted_attempts_rerun', [])):
                raise ValueError('RESUMED_POST_PROMOTION_VERIFICATION_NOT_PASS')
            measured = [e for e in LineageStore(state, lineage_id).events()
                        if e['kind'] == 'REFERENCE_MEASURED'
                        and e['payload'].get('measurement_ref') == reference['measurement_ref']]
            if (len(measured) != 1 or measured[0]['clock']['boot_id'] != proof['clock']['boot_id']
                    or measured[0]['clock']['monotonic'] <= proof['clock']['monotonic']):
                raise ValueError('REFERENCE_NOT_REMEASURED_AFTER_REAL_RESTART')
            if any(current.get(k) for k in ('execution_intent', 'initialization_intent',
                                           'research_intent', 'rollback_intent')):
                raise ValueError('UNRECONCILED_RECOVERY_INTENT')
            if not (native.stable / evaluation['before_version'] / 'manifest.json').is_file():
                raise ValueError('RECOVERABLE_PREDECESSOR_MISSING')
            replay = ex.terminal_noop(state, cid, scope, root=root)
            if replay['status'] != 'PASS':
                raise ValueError('RECOVERED_TERMINAL_REPLAY_FAILED')
            result.update(recovery_time_s=elapsed, terminal_replay=replay,
                          preserved_predecessor=evaluation['before_version'])
        result.update(status='PASS', session_id=session.identifier, campaign_id=cid,
                      lineage_id=lineage_id, restored_version=restored,
                      evidence_manifest=before, audit=audit['status'])
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        result['failures'].append(str(exc))
    finally:
        if before is not None:
            try:
                if ex.inventory(scope, include_cache=True) != before:
                    result['failures'].append('RECOVERY_INSPECTION_WROTE_OR_STATE_CHANGED')
            except (OSError, ValueError) as exc:
                result['failures'].append(str(exc))
        if result['failures']:
            result['status'] = 'BLOCKED_PREEXECUTION'
    return result
