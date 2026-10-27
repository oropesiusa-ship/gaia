"""FD accounting contracts and isolated kernel tests, not Stage 2 campaigns."""
import copy
import json
import os
import subprocess
import sys
import unittest
from tools.stage2_fds import SCHEMA, LINK, fd_count
from tools.stage2_executor import ROOT


class FDAccountingTests(unittest.TestCase):
    def fixture(self):
        proof = {'fd': 10, 'pid': 1001, 'start_time': 100, 'identity': [5, 123],
                 'kernel_pid': 1001, 'link': LINK, 'cloexec': True}
        metrics = {'pid': 50, 'start_time': 10, 'fds': 12,
            'fd_accounting': {'schema': SCHEMA, 'owner_pid': 50, 'owner_start_time': 10,
                'active_epoch': True, 'raw_fds': 12, 'pidfds': [proof], 'unaccounted_fds': 11}}
        capture = {'kind': 'CHILD_CAPTURED', 'role': 'OWNED_CHILD', 'pid': 1001, 'starttime': 100,
                   'pidfd': 10, 'pidfd_identity': [5, 123], 'custodian_pid': 50,
                   'custodian_starttime': 10, 'clock': {'boot_id': 'fixture', 'monotonic': 1}}
        return metrics, [capture], {'boot_id': 'fixture', 'monotonic': 2}

    def test_raw_count_is_preserved_and_only_exact_capture_is_subtracted(self):
        metrics, captures, clock = self.fixture()
        self.assertEqual(fd_count(metrics, captures=captures, clock=clock), 11)
        self.assertEqual(metrics['fds'], 12)
        metrics['fd_accounting']['pidfds'][0]['kernel_pid'] = -1
        self.assertEqual(fd_count(metrics, captures=captures, clock=clock), 11)

    def test_missing_mismatched_or_future_capture_is_not_credit(self):
        metrics, captures, clock = self.fixture()
        for evidence in (None, [], [{**captures[0], 'pid': 1002}],
                         [{**captures[0], 'custodian_pid': 51}],
                         [{**captures[0], 'pidfd_identity': [5, 999]}],
                         [{**captures[0], 'clock': {'boot_id': 'fixture', 'monotonic': 3}}]):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                fd_count(metrics, captures=evidence, clock=clock)

    def test_ordinary_foreign_duplicate_and_inheritable_fds_are_rejected(self):
        original, captures, clock = self.fixture()
        for key, value in (('link', '/dev/null'), ('kernel_pid', 2000), ('cloexec', False)):
            metrics = copy.deepcopy(original)
            metrics['fd_accounting']['pidfds'][0][key] = value
            with self.assertRaises(ValueError):
                fd_count(metrics, captures=captures, clock=clock)
        metrics = copy.deepcopy(original)
        metrics['fd_accounting']['pidfds'] *= 2
        metrics['fd_accounting']['unaccounted_fds'] = 10
        with self.assertRaises(ValueError):
            fd_count(metrics, captures=captures, clock=clock)

    def test_idle_must_have_zero_custody_descriptors_and_closed_epoch(self):
        metrics, captures, clock = self.fixture()
        with self.assertRaises(ValueError):
            fd_count(metrics, captures=captures, clock=clock, idle=True)
        metrics['fd_accounting'].update(pidfds=[], unaccounted_fds=12, active_epoch=False)
        self.assertEqual(fd_count(metrics, idle=True), 12)

    def test_historical_raw_evidence_is_not_reinterpreted(self):
        self.assertEqual(fd_count({'fds': 20}), 20)
        with self.assertRaises(ValueError):
            fd_count({'fds': 20}, required=True)

    def test_arithmetic_and_owner_tampering_are_rejected(self):
        original, captures, clock = self.fixture()
        for key, value in (('raw_fds', 99), ('unaccounted_fds', 0),
                           ('unaccounted_fds', True), ('owner_pid', 51), ('owner_start_time', 11)):
            metrics = copy.deepcopy(original)
            metrics['fd_accounting'][key] = value
            with self.assertRaises(ValueError):
                fd_count(metrics, captures=captures, clock=clock)

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'pidfd_open'), 'Linux pidfds required')
    def test_real_pidfds_and_unknown_leak_are_distinguished_and_drained(self):
        script = '''import contextlib,json,os,subprocess,sys
from tools.stage2_children import ChildBoundary
from tools.stage2_runtime import process_metrics
from tools.stage2_fds import with_owned_pidfds,fd_count
from gaia.autonomy.clock import stamp
events=[]
child="import subprocess,sys; children=[subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']) for _ in range(7)]; print('READY',flush=True); [p.wait() for p in children]"
with ChildBoundary(lambda event:events.append({'clock':stamp(),**event})) as owner:
    owner.begin()
    proc=subprocess.Popen([sys.executable,'-B','-c',child],stdout=subprocess.PIPE,text=True,start_new_session=True)
    assert proc.stdout.readline().strip()=='READY'
    proc.stdout.close()
    baseline=len(os.listdir('/proc/self/fd'))
    owner.attach(proc)
    active=with_owned_pidfds(process_metrics(os.getpid()),owner)
    assert len(active['fd_accounting']['pidfds'])==8
    assert active['fds']>baseline+5
    assert fd_count(active,captures=events,clock=stamp())==baseline
    with contextlib.ExitStack() as stack:
        for _ in range(6):stack.enter_context(open(os.devnull,'rb'))
        leaking=with_owned_pidfds(process_metrics(os.getpid()),owner)
        assert fd_count(leaking,captures=events,clock=stamp())>baseline+5
        pid=next(iter(owner.fds)); original=owner.fds[pid]
        try:
            owner.fds[pid]=stack.enter_context(open(os.devnull,'rb')).fileno()
            try:with_owned_pidfds(process_metrics(os.getpid()),owner)
            except RuntimeError:pass
            else:raise AssertionError('ordinary FD was credited as custody')
        finally:owner.fds[pid]=original
    owner.drain()
    clean=with_owned_pidfds(process_metrics(os.getpid()),owner)
    assert fd_count(clean,captures=events,clock=stamp(),idle=True)==baseline
    assert owner.kernel_empty()
print(json.dumps({'raw_active':active['fds'],'unaccounted':active['fd_accounting']['unaccounted_fds'],
                  'raw_after_cleanup':clean['fds'],'baseline':baseline,'restored':not owner.enabled}))
'''
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value['restored'])
        self.assertEqual(value['raw_after_cleanup'], value['baseline'])

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'pidfd_open'), 'Linux pidfds required')
    def test_real_supervisor_guard_accepts_custody_but_rejects_unknown_growth(self):
        script = '''import contextlib,json,os,subprocess,sys
sys.path.insert(0,'tests')
from unittest.mock import patch
from test_stage2_runtime import Stage2RuntimeTests
from tools import stage2_runtime as rt,stage2_executor as ex
from tools.stage2_children import ChildBoundary
from tools.stage2_fds import fd_count
from gaia.autonomy.clock import stamp
fixture=Stage2RuntimeTests('test_charge_is_conservative_and_rejects_nan')
fixture.setUp()
events=[]
try:
    s,b,lin,now=fixture.setup_supervisor()
    s.stage_contract={'boot_id':ex.boot_id(),'commit':'unit','preregistration_sha256':ex.sha(ex.PREREG),
        'plan':{**ex.scratch_plan(fixture.root),'administrative_hashes':{p:ex.sha(ex.ROOT/p)for p in ex.ADMIN_FILES}}}
    child="import subprocess,sys; children=[subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']) for _ in range(7)]; print('READY',flush=True); [p.wait() for p in children]"
    with ChildBoundary(lambda event:events.append({'clock':stamp(),**event})) as owner:
        s.boundary=owner
        owner.begin()
        proc=subprocess.Popen([sys.executable,'-B','-c',child],stdout=subprocess.PIPE,text=True,start_new_session=True)
        assert proc.stdout.readline().strip()=='READY'
        proc.stdout.close();owner.attach(proc)
        s.child=proc;s.child_started=now[0]
        with patch.object(ex,'git',return_value='unit'),patch.object(ex,'changes',return_value=[]),\\
             patch.object(rt,'memory',return_value={'available_bytes':10**10,'below_reserve':False}),\\
             patch.object(rt,'filesystem',return_value={'free_bytes':10**11,'below_reserve':False}),\\
             patch.object(rt,'processes',return_value={}):
            s.guard();s.sample('REVIEWING')
            with contextlib.ExitStack() as stack:
                for _ in range(6):stack.enter_context(open(os.devnull,'rb'))
                try:s.guard()
                except RuntimeError as exc:assert str(exc)=='SUPERVISOR_FD_BAND',str(exc)
                else:raise AssertionError('unknown FD growth was not blocked')
            owner.drain();s.child=None
            s.guard();s.sample('POST_CLEANUP')
        rows=[row for row in s.telemetry.samples() if row['kind']=='STAGE2_METRICS']
        assert rows[0]['supervisor']['fds']>s.baseline['fds']+5
        for row in rows:
            count=fd_count(row['supervisor'],captures=events,clock=row['clock'],idle=row['phase']=='POST_CLEANUP')
            assert count<=s.baseline['fds']+5
        assert owner.kernel_empty()
    print(json.dumps({'raw_active':rows[0]['supervisor']['fds'],
                      'raw_clean':rows[-1]['supervisor']['fds'],'baseline':s.baseline['fds'],
                      'untracked_leak_blocked':True,'restored':not owner.enabled}))
finally:fixture.doCleanups()
'''
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['untracked_leak_blocked'])
