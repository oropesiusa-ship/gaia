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
from gaia.autonomy.store import CampaignStore
from test_autonomy_integration import Fixture,ROOT

CHILD='''
import os,sys,time,subprocess
sys.path.insert(0,{root!r})
from gaia.autonomy.store import CampaignStore
state,cid,behaviour,marker=sys.argv[1:5]
s=CampaignStore(state,cid)
if s.inspect()['state']['phase']=='CREATED':s.event('OBSERVING')
if behaviour=='hang_once'and not os.path.exists(marker):
    open(marker,'w').write('hung')
    subprocess.Popen([sys.executable,'-c','import time;time.sleep(600)'],start_new_session=True)  # a descendant in another session
    time.sleep(600)
if behaviour=='hang':time.sleep(600)
if behaviour=='slow_ok':time.sleep(1.5)
if behaviour=='crash':sys.exit(3)
reason='NEEDS_RECOVERY'if behaviour=='needs_recovery'else'NO_PROGRESS'
s.event('STOPPED',{{'reason':reason,'report_ref':s.put('REPORT',{{'status':'PASS','metrics':{{'total_wall_time':12.5,'research_calls':0,'experiments':1}}}})}})
'''


class SupervisorTests(Fixture):
    def setUp(self):
        super().setUp()
        fast={**session_module.LIMITS,'hang_timeout_s':(1,6*3600),'heartbeat_s':(0,600),'minimum_campaign_s':(1,3600)}
        p=patch.dict(session_module.LIMITS,fast);p.start();self.addCleanup(p.stop)
        self.script=self.root/'child.py';self.script.write_text(CHILD.format(root=str(ROOT)));self.launched=[];self.behaviour='ok'
    def make(self,lineages=None,**limits):
        lineages=lineages or[self.lineage()['lineage_id']]
        base={'hang_timeout_s':2,'heartbeat_s':0,'minimum_campaign_s':60,'maximum_campaigns':2,'relaunches_per_campaign':1}
        c=session_contract(lineages,stage='unit',limits={**base,**limits});SessionStore(self.state,c['session_id']).create(c,self.root);return c
    def supervisor(self,c,behaviour=None):
        def launch(cid):
            b=behaviour(cid,len(self.launched))if callable(behaviour)else(behaviour or self.behaviour)
            self.launched.append((cid,b))
            return subprocess.Popen([sys.executable,str(self.script),str(self.state),cid,b,str(self.root/('marker-'+cid))],start_new_session=True,
                                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        sup=Supervisor(self.root,self.state,c['session_id'],launch=launch,sleep=lambda s:time.sleep(min(s,.1)or .05))
        return sup
    def events(self,c):return [(e['kind'],e['payload'])for e in SessionStore(self.state,c['session_id']).events()]

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
        self.assertEqual(self.supervisor(d).run()['reason'],'SESSION_STORAGE_BUDGET');self.assertEqual(len(self.launched),1)
    def test_restarted_supervisor_adopts_its_running_child(self):
        c=self.make(maximum_campaigns=1);store=SessionStore(self.state,c['session_id']);sup=self.supervisor(c)
        cid=sup.create(c['lineages'][0],600);store.event('CAMPAIGN_STARTED',{'campaign_id':cid,'lineage_id':c['lineages'][0],'campaign_seconds':600})
        orphan=subprocess.Popen([sys.executable,str(self.script),str(self.state),cid,'slow_ok',str(self.root/'m'),'autonomy-run'],
                                start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        sup.heartbeat(campaign_id=cid,child_pid=orphan.pid)
        result=sup.run();orphan.wait(5)
        self.assertEqual(SessionStore(self.state,c['session_id']).state_view()['finished'][0]['recovery'],'TERMINAL_OK')
        self.assertEqual(self.launched,[]);self.assertEqual(result['reason'],'SESSION_CAMPAIGN_BUDGET')
    def test_status_is_pure_and_reports_heartbeat(self):
        c=self.make(maximum_campaigns=1);self.supervisor(c).run();root=SessionStore(self.state,c['session_id']).root
        before={str(p):p.read_bytes()for p in root.rglob('*')if p.is_file()};value=status(self.state,c['session_id'])
        self.assertEqual({str(p):p.read_bytes()for p in root.rglob('*')if p.is_file()},before)
        self.assertEqual(value['inspection'],'READ_ONLY_NO_LOCK_NO_REPAIR');self.assertIsNotNone(value['heartbeat_age_s'])
    def test_contract_rejects_escalation(self):
        with self.assertRaises(ValueError):session_contract([self.lineage()['lineage_id']],stage='unit',limits={'maximum_research':1})
        c=session_contract([self.lineage()['lineage_id']],stage='unit');c={**c,'limits':{**c['limits'],'maximum_campaigns':10**4}}
        with self.assertRaises(ValueError):validate_session(c)


if __name__=='__main__':unittest.main()
