"""1.1 §1/§2: supervised sessions with real child process groups that drive campaign journals; budgets are aggregate."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from gaia.autonomy import session as session_module
from gaia.autonomy.session import SessionStore,session_contract,validate_session
from gaia.autonomy.supervisor import Supervisor,status,alive
from gaia.autonomy.freeze import freeze,changes
from gaia.autonomy.store import CampaignStore
from gaia.autonomy.lineage import LineageStore
from test_autonomy_integration import Fixture,ROOT

CHILD='''
import os,sys,time,subprocess
sys.path.insert(0,{root!r})
from gaia.autonomy.store import CampaignStore
state,cid,behaviour,marker=sys.argv[1:5]
if behaviour=='noop':sys.exit(0)  # like a controller refused by a lock: clean exit, no journal progress
s=CampaignStore(state,cid)
if s.inspect()['state']['phase']=='CREATED':s.event('OBSERVING')
if behaviour=='hang_once'and not os.path.exists(marker):
    open(marker,'w').write('hung')
    subprocess.Popen([sys.executable,'-c','import time;time.sleep(600)'],start_new_session=True)  # a descendant in another session
    time.sleep(600)
if behaviour=='hang':time.sleep(600)
if behaviour=='slow_ok':time.sleep(1.5)
if behaviour=='crash':sys.exit(3)
if behaviour=='reconcile':
    s.event('STOPPED',{{'reason':'NEEDS_RECOVERY','report_ref':s.put('REPORT',{{'status':'FAIL','metrics':{{'total_wall_time':1.0}}}})}});sys.exit(0)
if behaviour=='pause':
    s.control('PAUSE');s.event('PAUSED',{{'resume_phase':'OBSERVING'}});sys.exit(0)
if behaviour=='orphan_exit':
    open(marker,'w').write(str(subprocess.Popen([sys.executable,'-c','import time;time.sleep(600)']).pid))  # same process group
reason='NEEDS_RECOVERY'if behaviour=='needs_recovery'else'NO_PROGRESS'
s.event('STOPPED',{{'reason':reason,'report_ref':s.put('REPORT',{{'status':'PASS','metrics':{{'total_wall_time':12.5,'research_calls':0,'experiments':1}}}})}})
'''


class SessionFixture(Fixture):
    def setUp(self):
        super().setUp()
        fast={**session_module.LIMITS,'hang_timeout_s':(1,6*3600),'heartbeat_s':(0,600),'minimum_campaign_s':(1,3600)}
        p=patch.dict(session_module.LIMITS,fast);p.start();self.addCleanup(p.stop)
        self.script=self.root/'child.py';self.script.write_text(CHILD.format(root=str(ROOT)));self.launched=[];self.behaviour='ok'
    def make(self,lineages=None,**limits):
        lineages=lineages or[self.lineage()['lineage_id']]
        base={'hang_timeout_s':2,'heartbeat_s':0,'minimum_campaign_s':60,'maximum_campaigns':2,'relaunches_per_campaign':1}
        c=session_contract(lineages,stage='unit',limits={**base,**limits},frozen=freeze(self.root,self.state,lineages))
        SessionStore(self.state,c['session_id']).create(c,self.root);return c
    def supervisor(self,c,behaviour=None):
        def launch(cid):
            b=behaviour(cid,len(self.launched))if callable(behaviour)else(behaviour or self.behaviour)
            self.launched.append((cid,b))
            return subprocess.Popen([sys.executable,str(self.script),str(self.state),cid,b,str(self.root/('marker-'+cid))],start_new_session=True,
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        sup=Supervisor(self.root,self.state,c['session_id'],launch=launch,sleep=lambda s:time.sleep(min(s,.1)or .05))
        return sup
    def events(self,c):return [(e['kind'],e['payload'])for e in SessionStore(self.state,c['session_id']).events()]


class SupervisorTests(SessionFixture):

    def test_campaigns_run_sequentially_under_aggregate_budgets(self):
        c=self.make();result=self.supervisor(c).run()
        self.assertEqual(result['reason'],'SESSION_CAMPAIGN_BUDGET');view=SessionStore(self.state,c['session_id']).state_view()
        self.assertEqual(len(view['finished']),2);self.assertEqual(view['compute_s'],25.0)
        self.assertTrue(all(f['recovery']=='TERMINAL_OK'for f in view['finished']))
        started=[p for k,p in self.events(c)if k=='CAMPAIGN_STARTED']
        self.assertTrue(all(p['campaign_seconds']<=3600 for p in started))
        for p in started:
            contract=CampaignStore(self.state,p['campaign_id']).read('contract');self.assertEqual(contract['maximum_wall_time'],p['campaign_seconds'])
    def test_new_campaign_ids_never_reset_the_session_budget(self):
        c=self.make(maximum_compute_s=70,maximum_campaigns=10);result=self.supervisor(c).run()
        # 12.5 s charged per campaign: the second cannot start with less than the minimum campaign time left.
        self.assertEqual(result['reason'],'SESSION_COMPUTE_BUDGET');self.assertEqual(len(SessionStore(self.state,c['session_id']).state_view()['campaigns']),1)
    def test_hang_preserves_evidence_stops_only_its_processes_and_relaunches(self):
        c=self.make(maximum_campaigns=1)
        bystander=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True);self.addCleanup(bystander.kill)
        result=self.supervisor(c,'hang_once').run()
        kinds=[k for k,_ in self.events(c)];self.assertIn('HANG_DETECTED',kinds);self.assertIn('CAMPAIGN_RELAUNCHED',kinds)
        hang=next(p for k,p in self.events(c)if k=='HANG_DETECTED')
        evidence=json.loads((SessionStore(self.state,c['session_id']).root/'evidence'/hang['evidence']).read_text())
        self.assertGreaterEqual(len(evidence['processes']),2);self.assertEqual(evidence['inspection']['recovery'],'RECOVERABLE')
        time.sleep(.5)
        for row in evidence['processes']:self.assertFalse(alive(row['pid']),row)
        self.assertEqual(result['reason'],'SESSION_CAMPAIGN_BUDGET')
        view=SessionStore(self.state,c['session_id']).state_view();self.assertEqual((view['restarts'],view['finished'][0]['recovery']),(1,'TERMINAL_OK'))
        self.assertIsNone(bystander.poll())  # a process outside the campaign's tree is never targeted
    def test_relaunch_budget_then_lineage_skipped(self):
        c=self.make();result=self.supervisor(c,'crash').run()
        self.assertEqual(result['reason'],'NO_ELIGIBLE_LINEAGE');view=SessionStore(self.state,c['session_id']).state_view()
        self.assertEqual(view['finished'][0]['recovery'],'RECOVERABLE');self.assertEqual(len(self.launched),2)
        self.assertEqual(list(view['skipped'].values()),['CAMPAIGN_RECOVERABLE'])
    def test_campaign_needing_recovery_skips_its_lineage_and_others_continue(self):
        a=self.lineage()['lineage_id'];b=self.lineage()['lineage_id'];c=self.make([a,b],maximum_campaigns=3)
        result=self.supervisor(c,lambda cid,n:'needs_recovery'if n==0 else'ok').run()
        view=SessionStore(self.state,c['session_id']).state_view()
        self.assertEqual(view['skipped'],{a:'CAMPAIGN_NEEDS_RECOVERY'});self.assertEqual([f['lineage_id']for f in view['finished']],[a,b,b])
        self.assertEqual(result['reason'],'SESSION_CAMPAIGN_BUDGET')
    def test_operator_stop_and_storage_ceiling(self):
        c=self.make();(SessionStore(self.state,c['session_id']).root/'control.json').write_text('{"request":"STOP"}')
        self.assertEqual(self.supervisor(c).run()['reason'],'OPERATOR_STOP');self.assertEqual(self.launched,[])
        d=self.make(maximum_storage_bytes=4096,maximum_campaigns=10);self.launched=[]
        self.assertEqual(self.supervisor(d).run()['reason'],'STORAGE_GATE_95');self.assertEqual(len(self.launched),1)
        gates=[p['gate']for k,p in self.events(d)if k=='STORAGE_GATE'];self.assertEqual(gates[-1],95);self.assertEqual(gates,sorted(gates))
    def test_restarted_supervisor_adopts_its_running_child(self):
        c=self.make(maximum_campaigns=1);store=SessionStore(self.state,c['session_id']);sup=self.supervisor(c)
        cid=sup.create(c['lineages'][0],600);store.event('CAMPAIGN_STARTED',{'campaign_id':cid,'lineage_id':c['lineages'][0],'campaign_seconds':600})
        orphan=subprocess.Popen([sys.executable,str(self.script),str(self.state),cid,'slow_ok',str(self.root/'m'),'autonomy-run'],
                                start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        sup.heartbeat(campaign_id=cid,child_pid=orphan.pid)
        result=sup.run();orphan.wait(5)
        self.assertEqual(SessionStore(self.state,c['session_id']).state_view()['finished'][0]['recovery'],'TERMINAL_OK')
        self.assertNotIn('HANG_DETECTED',[k for k,_ in self.events(c)])
        self.assertEqual(self.launched,[]);self.assertEqual(result['reason'],'SESSION_CAMPAIGN_BUDGET')
    def test_status_is_pure_and_reports_heartbeat(self):
        c=self.make(maximum_campaigns=1);self.supervisor(c).run();root=SessionStore(self.state,c['session_id']).root
        before={str(p):p.read_bytes()for p in root.rglob('*')if p.is_file()};value=status(self.state,c['session_id'])
        self.assertEqual({str(p):p.read_bytes()for p in root.rglob('*')if p.is_file()},before)
        self.assertEqual(value['inspection'],'READ_ONLY_NO_LOCK_NO_REPAIR');self.assertIsNotNone(value['heartbeat_age_s'])
    def test_contract_rejects_escalation(self):
        lin=[self.lineage()['lineage_id']];frozen=freeze(self.root,self.state,lin)
        with self.assertRaises(ValueError):session_contract(lin,stage='unit',limits={'maximum_research':1},frozen=frozen)
        with self.assertRaises(ValueError):session_contract(lin,stage='unit')
        c=session_contract(lin,stage='unit',frozen=frozen);c={**c,'limits':{**c['limits'],'maximum_campaigns':10**4}}
        with self.assertRaises(ValueError):validate_session(c)
        forged=session_contract(lin,stage='unit',frozen=frozen);forged={**forged,'freeze':{**forged['freeze'],'acceptance':{}}}
        with self.assertRaises(ValueError):validate_session(forged)

    def test_protocol_change_stops_the_session_before_the_next_campaign(self):
        c=self.make(maximum_campaigns=3)
        def behaviour(cid,n):
            if n==0:(self.root/'gaia/protected/evaluator.py').write_text('# changed during the session\n')
            return 'ok'
        result=self.supervisor(c,behaviour).run()
        self.assertEqual(result['reason'],'PROTOCOL_CHANGED');self.assertIn('PROTECTED_HASH_CHANGED',result['changes'])
        self.assertEqual(len(self.launched),1)
    def test_freeze_records_the_protocol_and_detects_changes(self):
        lin=[self.lineage()['lineage_id']];frozen=freeze(self.root,self.state,lin)
        self.assertEqual(set(frozen),{'commit','source_identity_hash','protected_hash','engine_config_hash','acceptance','lineages','selections','hash'})
        self.assertEqual(changes(self.root,self.state,frozen),[])
        (self.root/'state_local_intelligence').mkdir();self.assertEqual(changes(self.root,self.state,frozen),['SELECTION_CHANGED_OUTSIDE_SESSION'])
        (self.root/'gaia/new_module.py').write_text('x=1\n')
        with self.assertRaisesRegex(ValueError,'LINEAGE_SOURCE_DIFFERS'):freeze(self.root,self.state,lin)


class ReviewFindingTests(SessionFixture):
    def test_operator_pause_is_not_relaunched_and_keeps_the_lineage(self):
        c=self.make();result=self.supervisor(c,'pause').run();view=SessionStore(self.state,c['session_id']).state_view()
        self.assertEqual(result['reason'],'CAMPAIGN_PAUSED_BY_OPERATOR');self.assertEqual((len(self.launched),view['restarts'],view['skipped']),(1,0,{}))
    def test_lock_held_outside_the_session_is_waited_for_not_relaunched(self):
        c=self.make()
        with LineageStore(self.state,c['lineages'][0]).lock():result=self.supervisor(c).run()
        view=SessionStore(self.state,c['session_id']).state_view()
        self.assertEqual(result['reason'],'LOCK_BUSY_OUTSIDE_SESSION');self.assertEqual((self.launched,view['restarts'],view['skipped']),([],0,{}))
    def test_clean_runs_without_progress_are_never_relaunches(self):
        c=self.make();result=self.supervisor(c,'noop').run();view=SessionStore(self.state,c['session_id']).state_view()
        self.assertEqual(result['reason'],'LOCK_BUSY_OUTSIDE_SESSION');self.assertEqual((view['restarts'],view['skipped']),(0,{}))
        self.assertGreater(len(self.launched),1)
    def test_a_session_stop_during_a_pause_keeps_the_stop_reason(self):
        c=self.make();root=SessionStore(self.state,c['session_id']).root
        def behaviour(cid,n):(root/'control.json').write_text('{"request":"STOP"}');return 'pause'
        result=self.supervisor(c,behaviour).run();self.assertEqual(result['reason'],'OPERATOR_STOP')
    def test_ambiguous_non_terminal_campaign_gets_one_reconciliation_run(self):
        c=self.make(maximum_campaigns=1)
        def behaviour(cid,n):
            if n==0:
                s=CampaignStore(self.state,cid);s.event('OBSERVING',{'initialization_intent':True});return 'crash'
            return 'reconcile'
        result=self.supervisor(c,behaviour).run();kinds=[k for k,_ in self.events(c)]
        self.assertIn('CAMPAIGN_RECONCILE',kinds);self.assertEqual(len(self.launched),2)
        self.assertEqual(SessionStore(self.state,c['session_id']).state_view()['restarts'],0)
    def test_compute_is_charged_even_without_a_report(self):
        c=self.make(maximum_campaigns=1);self.supervisor(c,'crash').run();f=SessionStore(self.state,c['session_id']).state_view()['finished'][0]
        self.assertIsNone(f['campaign_wall_s']);self.assertGreater(f['wall_s'],0);self.assertEqual(f['wall_s'],f['supervised_s'])
        self.assertGreater(SessionStore(self.state,c['session_id']).state_view()['compute_s'],0)
    def test_restarted_supervisor_inspects_before_relaunching(self):
        c=self.make(maximum_campaigns=1);store=SessionStore(self.state,c['session_id']);sup=self.supervisor(c)
        cid=sup.create(c['lineages'][0],600);store.event('CAMPAIGN_STARTED',{'campaign_id':cid,'lineage_id':c['lineages'][0],'campaign_seconds':600})
        campaign=CampaignStore(self.state,cid);campaign.event('OBSERVING');campaign.event('STOPPED',{'reason':'NEEDS_RECOVERY'})
        sup.run();self.assertEqual(self.launched,[]);self.assertEqual(store.state_view()['finished'][0]['recovery'],'NEEDS_RECOVERY')
        d=self.make(maximum_campaigns=1);other=SessionStore(self.state,d['session_id']);sup=self.supervisor(d);self.launched=[]
        cid=sup.create(d['lineages'][0],600);other.event('SUPERVISOR_STARTED',{'pid':1})  # the previous supervisor
        other.event('CAMPAIGN_STARTED',{'campaign_id':cid,'lineage_id':d['lineages'][0],'campaign_seconds':600})
        sup.run();self.assertEqual(len(self.launched),1)
        from gaia.autonomy.session import restarts_used
        view=other.state_view();self.assertEqual((view['restarts'],restarts_used(view)),(0,1))  # counted once, by the supervisor restart
        self.assertEqual([p['reason']for k,p in self.events(d)if k=='CAMPAIGN_RELAUNCHED'],['SUPERVISOR_RESTART'])
    def test_processes_outliving_the_controller_are_stopped(self):
        c=self.make(maximum_campaigns=1);self.supervisor(c,'orphan_exit').run()
        cid=next(p['campaign_id']for k,p in self.events(c)if k=='CAMPAIGN_STARTED')
        orphan=int((self.root/('marker-'+cid)).read_text());time.sleep(.3)
        self.assertFalse(alive(orphan));self.assertTrue(any(p['orphans_stopped']for k,p in self.events(c)if k=='CHILD_EXITED'))
    def test_pid_reuse_and_zombies_are_not_alive(self):
        from gaia.autonomy.supervisor import proc_info
        me=proc_info(os.getpid());self.assertTrue(alive(os.getpid(),me[7]));self.assertFalse(alive(os.getpid(),me[7]+1))
        z=subprocess.Popen([sys.executable,'-c','pass']);time.sleep(.5);self.assertFalse(alive(z.pid));z.wait()
    def test_supervisor_restarts_count_against_the_restart_budget(self):
        c=self.make(maximum_restarts=0,maximum_campaigns=5);store=SessionStore(self.state,c['session_id'])
        store.event('SUPERVISOR_STARTED',{'pid':1})
        self.assertEqual(self.supervisor(c).run()['reason'],'SESSION_RESTART_BUDGET')
    def test_pointer_moves_owned_by_the_session(self):
        from gaia.autonomy.freeze import pointer_moves_owned
        a,b,x={'id':'lia','hash':'1'},{'id':'lib','hash':'2'},{'id':'lix','hash':'3'};mine=['al'+'1'*24]
        promo=lambda sel,lin:{'reason':'CLOSED_LOOP_PROMOTION','selection_ref':sel,'receipt':{'lineage_id':lin}}
        back=lambda sel:{'reason':'CLOSED_LOOP_ROLLBACK','selection_ref':sel,'receipt':{}}
        self.assertTrue(pointer_moves_owned([promo(b,mine[0]),back(a)],a,mine))
        self.assertFalse(pointer_moves_owned([back(x)],a,mine));self.assertFalse(pointer_moves_owned([promo(b,'al'+'9'*24)],a,mine))
        self.assertFalse(pointer_moves_owned([{'reason':'MANUAL','selection_ref':b,'receipt':{}}],a,mine))
    def test_partial_telemetry_line_does_not_break_status(self):
        from gaia.autonomy.telemetry import Telemetry
        t=Telemetry(self.root/'tele');t.append({'kind':'PROCESS','i':1})
        with t.files()[-1].open('a')as f:f.write('{"kind": "PROC')
        self.assertEqual([r['i']for r in t.samples()],[1])


class TelemetryTests(SessionFixture):
    def test_samples_and_storage_owners_are_recorded(self):
        from gaia.autonomy.telemetry import Telemetry
        c=self.make(maximum_campaigns=1);self.supervisor(c,'slow_ok').run()
        rows=Telemetry(SessionStore(self.state,c['session_id']).root/'telemetry').samples()
        self.assertTrue(any(r['kind']=='PROCESS'and r['child_rss_bytes']>0 for r in rows))
        storage=[r for r in rows if r['kind']=='STORAGE'];self.assertTrue(storage)
        self.assertEqual(set(storage[-1]['owners']),{'campaigns','session','evidence','telemetry','logs','shared_state','learning','cognition',
                                                     'observations','inference_scratch','engine'})
        self.assertGreater(storage[-1]['owners']['campaigns'],0)
    def test_telemetry_is_bounded_by_rotation(self):
        from gaia.autonomy import telemetry
        with patch.object(telemetry,'TELEMETRY_FILE_BYTES',200),patch.object(telemetry,'TELEMETRY_FILES',3):
            t=telemetry.Telemetry(self.root/'tele')
            for i in range(50):t.append({'kind':'PROCESS','i':i})
            self.assertEqual(len(t.files()),3);self.assertLessEqual(sum(f.stat().st_size for f in t.files()),3*200+200)
            self.assertEqual(t.samples()[-1]['i'],49)
    def test_filesystem_reserve_stops_before_launching(self):
        c=self.make()
        with patch('gaia.autonomy.supervisor.filesystem',return_value={'total_bytes':1,'free_bytes':0,'reserve_bytes':1,'below_reserve':True}):
            self.assertEqual(self.supervisor(c).run()['reason'],'FILESYSTEM_RESERVE')
        self.assertEqual(self.launched,[])
    def test_stage_budgets_reach_every_campaign_contract(self):
        c=self.make(maximum_campaigns=1,campaign_wall_s=900,campaign_iterations=3,campaign_experiments=1,campaign_disk_bytes=512*2**20)
        self.supervisor(c).run();cid=next(p['campaign_id']for k,p in self.events(c)if k=='CAMPAIGN_STARTED')
        contract=CampaignStore(self.state,cid).read('contract')
        self.assertEqual((contract['maximum_wall_time'],contract['maximum_compute_budget'],contract['maximum_iterations'],contract['maximum_experiments'],
                          contract['maximum_disk_budget'],contract['maximum_network_research'],contract['promotion_policy']['enabled']),(900,900,3,1,512*2**20,0,False))
    def test_host_memory_reserve_stops_before_launching(self):
        c=self.make()
        with patch('gaia.autonomy.supervisor.memory',return_value={'available_bytes':1,'total_bytes':2,'reserve_bytes':2,'below_reserve':True}):
            self.assertEqual(self.supervisor(c).run()['reason'],'HOST_MEMORY_RESERVE')
        self.assertEqual(self.launched,[])
    def test_host_memory_reserve_during_a_campaign_stops_it_at_a_safe_boundary(self):
        c=self.make();calls=[0]
        def mem():
            calls[0]+=1;low=calls[0]>2
            return {'available_bytes':1 if low else 10**12,'total_bytes':10**12,'reserve_bytes':2,'below_reserve':low}
        with patch('gaia.autonomy.supervisor.memory',side_effect=mem):result=self.supervisor(c,'slow_ok').run()
        self.assertEqual(result['reason'],'HOST_MEMORY_RESERVE');self.assertIn('RESOURCE_RESERVE',[k for k,_ in self.events(c)])
        self.assertEqual(len(self.launched),1)
    def test_vram_and_host_memory_are_sampled(self):
        from gaia.autonomy.telemetry import Telemetry
        c=self.make(maximum_campaigns=1);self.supervisor(c,'slow_ok').run()
        rows=Telemetry(SessionStore(self.state,c['session_id']).root/'telemetry').samples()
        self.assertTrue(any(r['kind']=='VRAM'and r['source']in('NVIDIA_SMI','UNAVAILABLE')for r in rows))
        self.assertTrue(all('host_memory'in r and'supervisor_fds'in r for r in rows if r['kind']=='PROCESS'))
    def test_campaign_logs_are_bounded(self):
        from gaia.autonomy.telemetry import bound_log
        path=self.root/'big.log';path.write_bytes(b'x'*5000)
        self.assertTrue(bound_log(path,1000));self.assertLess(path.stat().st_size,1100);self.assertFalse(bound_log(path,2000))


if __name__=='__main__':unittest.main()
