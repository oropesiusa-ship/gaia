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
         'tools/stage2_orchestrator.py', 'tools/stage2_protocol.py')


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


def verify_recovery(root, state, evidence):
    """Independent read-only audit of a real drill; never runs another drill."""
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
        result['failures'] = recovery_claim_gate(seal, native_result, fault, identities(root))
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
        if verdict != 'PASS' or not ledger['ok']:
            raise ValueError('INDEPENDENT_RECOVERY_AUDIT_FAILED')
        evaluation = campaign.get(current['evaluation_ref'])
        restored = native.current_version()
        if (reference['version'] != restored or restored != evaluation['before_version']
                or restored != native_result['native_version']):
            raise ValueError('RESTORED_VERSION_REFERENCE_MISMATCH')
        proof = json.loads((session.root / 'verification-kill-intent.json').read_bytes())
        if proof != fault['injection']['proof'] or proof['campaign_id'] != cid:
            raise ValueError('REAL_FAULT_PROOF_MISMATCH')
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
