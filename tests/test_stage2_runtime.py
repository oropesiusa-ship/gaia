"""Disposable administrative fixtures only; never launch a measured Stage 2 session."""
import json
import unittest
from unittest.mock import patch,Mock

from test_autonomy_integration import Fixture,FakeV2
from gaia.autonomy.controller import ClosedLoop
from tools import stage2_executor as ex,stage2_runtime as rt
from gaia.autonomy.freeze import freeze
from gaia.autonomy.session import SessionStore,session_contract
from gaia.autonomy.supervisor import Supervisor


class Stage2RuntimeTests(Fixture):
    def setup_supervisor(self):
        lin=self.lineage()['lineage_id'];frozen=freeze(self.root,self.state,[lin])
        c=session_contract([lin],stage='unit',limits=ex.LIMITS,frozen=frozen)
        store=SessionStore(self.state,c['session_id']);store.create(c,self.root)
        b=ex.StageBudget(self.root/'evidence'/'budget','fixture',[self.root/'evidence',self.state])
        now=[store.state_view()['started_clock']['monotonic']]
        def sleep(seconds):now[0]+=seconds
        with patch.object(rt,'vram',return_value={'source':'UNIT','gpus':[]}):
            s=rt.FirstSessionSupervisor(self.root,self.state,c['session_id'],{},b,sleep=sleep,now=lambda:now[0])
        return s,b,lin,now

    def test_explicit_authorization_precedes_import_or_io(self):
        with patch('tools.stage2_runtime.run_first')as run:
            with self.assertRaisesRegex(ValueError,'AUTHORIZATION'):
                ex.run_first_session(self.root,self.root/'missing-contract')
        run.assert_not_called()

    def test_imported_runtime_refuses_in_process_launch(self):
        with self.assertRaisesRegex(RuntimeError,'DEDICATED_RUNTIME_CLI_REQUIRED'):
            rt.run_first(self.root,self.root/'missing-contract')

    def test_charge_is_conservative_and_rejects_nan(self):
        self.assertEqual(rt.charge_wall(8,10),10)
        self.assertEqual(rt.charge_wall(10,8),10)
        self.assertEqual(rt.charge_wall(None,10),10)
        for value in (-1,float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):rt.charge_wall(value,1)

    def test_reservation_is_durable_before_campaign_creation(self):
        s,b,lin,_=self.setup_supervisor();cid='ac'+'1'*24
        with b.exclusive():
            b.start_session(s.session.identifier)
            def create(*args):
                self.assertEqual(b.view()['reserved_compute_s'],1800)
                self.assertEqual(args[-1],1740)
                return cid
            with patch.object(s,'guard'),patch.object(Supervisor,'create_campaign',side_effect=create):
                self.assertEqual(s.create_campaign(lin,1800),cid)
            self.assertEqual(b.view()['bindings'],{'S1-C1':cid})

    def test_failed_creation_does_not_refund_or_allow_retry(self):
        s,b,lin,_=self.setup_supervisor()
        with b.exclusive():
            b.start_session(s.session.identifier)
            with patch.object(s,'guard'),patch.object(Supervisor,'create_campaign',side_effect=RuntimeError('unit failure')):
                with self.assertRaisesRegex(RuntimeError,'unit failure'):s.create_campaign(lin,1800)
                with self.assertRaisesRegex(ValueError,'ROLE_ORDER'):s.create_campaign(lin,1800)
            self.assertEqual(b.view()['reserved_compute_s'],1800)

    def test_storage_headroom_blocks_before_reservation(self):
        s,b,lin,_=self.setup_supervisor()
        with b.exclusive():
            b.start_session(s.session.identifier)
            with patch.object(s,'guard'),patch.object(b,'storage',return_value=4*2**30-rt.HEADROOM-1):
                with self.assertRaisesRegex(RuntimeError,'STORAGE_ADMISSION'):s.create_campaign(lin,1800)
            self.assertEqual(b.view()['reservations'],{})

    def test_two_full_hour_slots_are_observed_without_real_waiting(self):
        s,b,_,now=self.setup_supervisor();start=now[0]
        with patch.object(s,'guard'),patch.object(s,'heartbeat'),patch.object(s,'storage_check'),patch.object(rt,'vram',return_value={'gpus':[]}):
            # Simulate an early terminal campaign; the slot's idle tail is still observed.
            now[0]+=50;s.observe_until(start+3600)
            self.assertEqual(now[0],start+3600)
            now[0]+=50;s.observe_until(start+7200)
        self.assertEqual(now[0]-start,7200)
        rows=s.telemetry.samples()
        self.assertGreater(len([r for r in rows if r['kind']=='IDLE']),700)
        self.assertTrue(all(r['kind']in ('IDLE','VRAM')for r in rows))

    def test_finish_charges_max_and_observes_next_slot(self):
        s,b,lin,_=self.setup_supervisor();loop=self.loop(lin);self.go(loop)
        cid=loop.contract['campaign_id'];state=loop.store.inspect()['state']
        report=loop.store.get(state['report_ref']);reported=report['metrics']['total_wall_time']
        with b.exclusive():
            b.start_session(s.session.identifier);b.reserve(s.session.identifier,'S1-C1');b.bind('S1-C1',cid)
            s.roles[cid]='S1-C1'
            s.session.event('CAMPAIGN_STARTED',{'campaign_id':cid,'lineage_id':lin,'campaign_seconds':1740})
            with patch.object(s,'sample'),patch.object(s,'observe_until')as observe:
                s.finish(cid,lin,{'recovery':'TERMINAL_OK','reason':'UNIT'},'DONE',reported+1)
            self.assertEqual(s.session.state_view()['compute_s'],reported+1)
            self.assertEqual(b.view()['charges']['S1-C1'],reported+1)
            self.assertEqual(observe.call_args.args[0],s.session.state_view()['started_clock']['monotonic']+3600)
            s.stop('UNIT')
            with patch('audit_closed_loop.audit_campaign',return_value={'status':'PASS'}):
                result=ex.reconcile(s.session,[self.state],root=self.root)
            self.assertNotIn('COMPUTE_REPORT_MISMATCH:'+cid,result.get('failures',[]))

    def test_ledger_overrun_is_recorded_and_never_refunded(self):
        s,b,_,_=self.setup_supervisor();cid='ac'+'1'*24
        with b.exclusive():
            b.start_session(s.session.identifier);b.reserve(s.session.identifier,'S1-C1');b.bind('S1-C1',cid)
            b.finish('S1-C1',cid,1801)
            self.assertTrue(b.view()['overrun']);self.assertEqual(b.view()['reserved_compute_s'],1800)
        reopened=ex.StageBudget(b.path,'fixture',b.owned_paths)
        self.assertEqual(reopened.view()['actual_compute_s'],1801)

    def test_stage2_auditor_allows_v2_five_iterations_and_checks_conservative_wall(self):
        lin=self.lineage()['lineage_id'];loop=self.loop(lin,limits={'maximum_iterations':5,'maximum_experiments':3,
            'maximum_wall_time':1740,'maximum_compute_budget':1740,'maximum_disk_budget':512*2**20})
        self.go(loop);cid=loop.contract['campaign_id'];state=loop.store.inspect()['state']
        reported=loop.store.get(state['report_ref'])['metrics']['total_wall_time'];supervised=reported+1
        for charged,expect_mismatch in ((supervised,False),(reported,True)):
            with self.subTest(charged=charged):
                c=session_contract([lin],stage='unit',limits=ex.LIMITS,frozen=freeze(self.root,self.state,[lin]))
                store=SessionStore(self.state,c['session_id']);store.create(c,self.root)
                store.event('CAMPAIGN_STARTED',{'campaign_id':cid,'lineage_id':lin,'campaign_seconds':1740})
                store.event('CAMPAIGN_FINISHED',{'campaign_id':cid,'wall_s':charged,'supervised_s':supervised})
                store.event('STOPPED',{'reason':'UNIT'})
                with patch('tools.audit_endurance_session.audit_closed_loop.audit_campaign',return_value={'status':'PASS'}):
                    audit=rt.audit_session(self.root,self.state,store.identifier,stage='stage2')
                self.assertFalse(any('LOOSER_THAN_1_0' in f for f in audit['failures']),audit)
                self.assertEqual('CAMPAIGN_CHARGE_MISMATCH:'+cid in audit['failures'],expect_mismatch)

    def test_live_guard_rechecks_freeze_boot_and_campaign_deadline(self):
        s,b,_,now=self.setup_supervisor()
        s.stage_contract={'boot_id':ex.boot_id(),'commit':'unit','preregistration_sha256':ex.sha(ex.PREREG),
            'plan':{**ex.scratch_plan(self.root),'administrative_hashes':{p:ex.sha(ex.ROOT/p)for p in ex.ADMIN_FILES}}}
        with patch.object(ex,'git',return_value='unit'),patch.object(ex,'changes',return_value=[]),\
             patch.object(rt,'memory',return_value={'available_bytes':10**10,'below_reserve':False}),\
             patch.object(rt,'filesystem',return_value={'free_bytes':10**11,'below_reserve':False}):
            s.guard()
            with patch.object(ex,'boot_id',return_value='another-boot'):
                with self.assertRaisesRegex(RuntimeError,'BOOT_ID'):s.guard()
            with patch.object(ex,'changes',return_value=['PROTECTED_HASH_CHANGED']):
                with self.assertRaisesRegex(RuntimeError,'PROTOCOL_CHANGED'):s.guard()
            with patch.object(rt,'processes',return_value={987654:(1,987654,987654,0,3,'runtime_worker','S',1)}):
                with self.assertRaisesRegex(RuntimeError,'EXTERNAL_BACKEND_BUSY'):s.guard()
            s.child=Mock();s.child.poll.return_value=None;s.child_started=now[0]-1770
            with self.assertRaisesRegex(RuntimeError,'SUPERVISION_DEADLINE'):s.guard()
            scratch=rt.Path(s.stage_contract['plan']['scratch_root'])
            scratch.rename(scratch.with_name('original-root'));scratch.mkdir()
            with self.assertRaisesRegex(ValueError,'SCRATCH_ROOT_REPLACED'):s.guard()

    def test_supervisor_loop_admits_only_two_sequential_unit_campaigns(self):
        s,b,lin,now=self.setup_supervisor();start=now[0];admitted=[]
        def unit_supervise(cid,lineage_id):
            admitted.append(now[0])
            self.assertEqual(lineage_id,lin)
            loop=ClosedLoop(self.root,self.state,cid,services_factory=FakeV2);self.go(loop)
            return rt.inspect_campaign(self.state,cid),'DONE',1
        host={'available_bytes':10**10,'below_reserve':False}
        disk={'free_bytes':10**11,'below_reserve':False}
        with b.exclusive():
            b.start_session(s.session.identifier)
            with patch.object(s,'guard'),patch.object(s,'sample'),patch.object(s,'supervise',side_effect=unit_supervise),\
                 patch('gaia.autonomy.supervisor.memory',return_value=host),\
                 patch.object(rt,'filesystem',return_value=disk),patch.object(rt,'vram',return_value={'gpus':[]}):
                result=s.run()
            self.assertEqual(result['reason'],'SESSION_CAMPAIGN_BUDGET')
            self.assertEqual(admitted,[start,start+3600])
            self.assertEqual(now[0],start+7200)
            self.assertEqual(len(s.session.state_view()['finished']),2)
            self.assertEqual(b.view()['reserved_compute_s'],3600)
            self.assertEqual(len(b.view()['charges']),2)
            self.assertEqual(rt.audit_aggregate(s.session,b)['status'],'PASS')


if __name__=='__main__':unittest.main()
