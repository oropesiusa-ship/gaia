"""Synthetic telemetry audits only; no campaign or resource measurements."""
import copy
import unittest
from test_autonomy_integration import Fixture
from gaia.autonomy.clock import stamp
from gaia.autonomy.freeze import freeze
from gaia.autonomy.session import SessionStore, session_contract
from gaia.autonomy.store import durable
from gaia.autonomy.telemetry import Telemetry
from tools.stage2_executor import LIMITS
from tools.stage2_fds import SCHEMA, LINK
from tools.audit_endurance_session import audit_session


class FDAuditorTests(Fixture):
    def audit(self, *, leak=0, tamper=False, drop_metadata=False, legacy=False):
        lineage = self.lineage()['lineage_id']
        contract = session_contract([lineage], stage='stage2', limits=LIMITS,
                                    frozen=freeze(self.root, self.state, [lineage]))
        store = SessionStore(self.state, contract['session_id'])
        store.create(contract, self.root)
        clock = stamp()
        def metrics(raw, proofs, active):
            value = {'pid': 42, 'start_time': 10, 'fds': raw, 'rss_bytes': 100, 'pss_bytes': 50}
            if not legacy:
                value['fd_accounting'] = {'schema': SCHEMA, 'owner_pid': 42, 'owner_start_time': 10,
                    'active_epoch': active, 'raw_fds': raw, 'pidfds': proofs,
                    'unaccounted_fds': raw - len(proofs)}
            return value
        baseline = metrics(6, [], False)
        durable(store.root / 'evidence/baseline.json', {'supervisor': baseline, 'vram': {'gpus': []}})
        proofs = [{'fd': 100+i, 'pid': 500+i, 'start_time': 200+i,
                   'identity': [5, 1000+i], 'kernel_pid': 500+i, 'link': LINK, 'cloexec': True}
                  for i in range(8)]
        captures = [{'kind': 'CHILD_CAPTURED', 'role': 'OWNED_CHILD', 'pid': row['pid'],
            'starttime': row['start_time'], 'pidfd': row['fd'], 'pidfd_identity': row['identity'],
            'custodian_pid': 42, 'custodian_starttime': 10, 'clock': clock} for row in proofs]
        durable(store.root / 'evidence/pidfd-captures.json', captures)
        active = metrics(14+leak, copy.deepcopy(proofs), True)
        if tamper:
            active['fd_accounting']['pidfds'][0]['identity'] = [5, 99999]
        telemetry = Telemetry(store.root / 'telemetry')
        for index, (phase, value) in enumerate((('SCHEDULED_IDLE', baseline), ('REVIEWING', active))):
            measured_clock = {**clock, 'monotonic': clock['monotonic'] + (index+1)*.001}
            process = {'kind': 'PROCESS', 'clock': measured_clock, 'supervisor_pid': 42,
                'supervisor_start_time': 10, 'supervisor_fds': value['fds'], 'supervisor_rss_bytes': 100}
            if not legacy and not drop_metadata:
                process['supervisor_fd_accounting'] = value['fd_accounting']
            telemetry.append(process)
            telemetry.append({'kind': 'STAGE2_METRICS', 'clock': measured_clock, 'phase': phase,
                              'supervisor': value, 'stage_storage_bytes': 0, 'stage_budget': {}})
        store.event('STOPPED', {'reason': 'SYNTHETIC_TEST'})
        return audit_session(self.root, self.state, store.identifier, stage='stage2')

    def test_eight_verified_pidfds_do_not_create_a_false_leak(self):
        result = self.audit()
        self.assertFalse(any('FD_' in reason for reason in result['failures']), result)
        self.assertEqual(result['bands']['supervisor_fds']['max'], 6)
        # Other missing real campaign/window evidence still fails, as it must.
        self.assertEqual(result['status'], 'FAIL')

    def test_six_unknown_descriptors_still_fail_both_bands(self):
        result = self.audit(leak=6)
        self.assertIn('SUPERVISOR_FD_BAND', result['failures'])
        self.assertIn('STAGE2_IDLE_FD_BAND', result['failures'])

    def test_capture_tampering_and_dropped_metadata_fail(self):
        for options in ({'tamper': True}, {'drop_metadata': True}):
            with self.subTest(options=options):
                result = self.audit(**options)
                self.assertTrue(any(reason.startswith('FD_ACCOUNTING_INVALID:') for reason in result['failures']))

    def test_old_raw_evidence_keeps_its_original_fd_failure(self):
        result = self.audit(legacy=True)
        self.assertIn('SUPERVISOR_FD_BAND', result['failures'])
        self.assertIn('STAGE2_IDLE_FD_BAND', result['failures'])
