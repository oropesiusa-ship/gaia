"""Administrative Stage 2 executor tests; no Stage 2 session is started."""
import copy,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from tools import stage2_executor as stage2
from gaia.autonomy.session import SessionStore,session_contract
from gaia.autonomy.freeze import freeze
from gaia.autonomy.store import CampaignStore
from test_autonomy_integration import Fixture

class Stage2ExecutorTests(Fixture):
 def setUp(self):
  super().setUp();self.lin=self.lineage()['lineage_id'];self.f=freeze(self.root,self.state,[self.lin])
 def ready(self):
  # Contract validator is separately tested; this is a fully hashed preflight fixture.
  c={'schema':'gaia_stage2_contract_v1','stage':'stage2','status':'READY_TO_EXECUTE','commit':'c','identity':{'hash':'i'},'freeze':self.f,'limits':stage2.LIMITS,'lineages':[self.lin],'preregistration_sha256':'p','baseline':{},'plan':{},'executor_sha256':'e','runtime':{},'boot_id':'b','resources':{},'inventory':{},'campaigns_authorized':0,'sessions_started':0,'execution_prohibited':True,'clock':{}}
  c['hash']=stage2.digest(c);return c
 def test_any_frozen_hash_change_blocks_admission(self):
  c=self.ready();changed=copy.deepcopy(self.f);changed['protected_hash']='different'
  with patch.object(stage2,'frozen',return_value=changed),patch.object(stage2,'git',return_value='c'),patch.object(stage2,'identities',return_value={'hash':'i'}),patch.object(stage2,'changes',return_value=[]),patch.object(stage2,'sha',side_effect=lambda x:'p'if str(x).endswith('.md')else'e'),patch.object(stage2,'boot_id',return_value='b'),patch.object(stage2,'memory',return_value={'below_reserve':False}),patch.object(stage2,'filesystem',return_value={'below_reserve':False}):
   self.assertEqual(stage2.admission(c,self.root,self.state)['status'],'BLOCKED_PREEXECUTION')
 def test_tampered_contract_fails_closed(self):
  c=self.ready();c['limits']=dict(c['limits'],maximum_compute_s=1)
  with self.assertRaisesRegex(ValueError,'HASH'):stage2.admission(c,self.root,self.state)
 def test_read_only_inspection_does_not_write(self):
  p=self.state/'owned';p.mkdir(parents=True);(p/'record').write_text('fixed')
  self.assertEqual(stage2.read_only_inspection([p])['status'],'PASS');self.assertEqual((p/'record').read_text(),'fixed')
 def test_terminal_noop_real_terminal_and_nonterminal_refusal(self):
  loop=self.loop(self.lin);self.go(loop);cid=loop.contract['campaign_id']
  value=stage2.terminal_noop(self.state,cid,[self.state])
  self.assertEqual((value['status'],value['result'],value['writes']),('PASS','TERMINAL_NOOP',False))
  other=self.loop(self.lin).contract['campaign_id'];before=stage2.inventory([self.state])
  refused=stage2.terminal_noop(self.state,other,[self.state])
  self.assertEqual(refused['reason'],'NONTERMINAL_REOPEN_REFUSED');self.assertEqual(before,stage2.inventory([self.state]))
 def test_aggregate_budget_preserved(self):
  c=session_contract([self.lin],stage='unit',limits={'maximum_campaigns':2,'maximum_compute_s':100,'maximum_wall_s':1000,'minimum_campaign_s':60},frozen=self.f);s=SessionStore(self.state,c['session_id']);s.create(c,self.root)
  s.event('CAMPAIGN_STARTED',{'campaign_id':'ac'+'1'*24,'lineage_id':self.lin,'campaign_seconds':60});s.event('CAMPAIGN_FINISHED',{'wall_s':50,'research_calls':0})
  v=stage2.aggregate_preserved(s,self.root);self.assertEqual(v['compute_s'],50);self.assertIn('SESSION_COMPUTE_BUDGET',v['reasons'])
 def test_learning_exact_and_incompatible(self):
  b={k:'x'for k in ('source_identity_hash','environment_hash','surface','objective','reference_version','reference_baseline_hash')};r={'binding':b}
  self.assertEqual(stage2.learning(r,b)['applicability']['status'],'EXACT');self.assertEqual(stage2.learning(r,{**b,'surface':'local'})['applicability']['status'],'INCOMPATIBLE')
 def test_reserves_and_backend_protocol_drift_block(self):
  c=self.ready()
  with patch.object(stage2,'frozen',return_value=self.f),patch.object(stage2,'git',return_value='c'),patch.object(stage2,'identities',return_value={'hash':'i'}),patch.object(stage2,'changes',return_value=['SELECTION_CHANGED_OUTSIDE_SESSION']),patch.object(stage2,'sha',side_effect=lambda x:'p'if str(x).endswith('.md')else'e'),patch.object(stage2,'boot_id',return_value='b'),patch.object(stage2,'memory',return_value={'below_reserve':True}),patch.object(stage2,'filesystem',return_value={'below_reserve':True}):
   self.assertEqual(stage2.admission(c,self.root,self.state)['status'],'BLOCKED_PREEXECUTION')
 def test_cleanup_requires_owned_group(self):
  p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True);self.addCleanup(lambda:p.poll()is None and p.kill());time.sleep(.05)
  from gaia.autonomy.supervisor import proc_info
  r={'pid':p.pid,'start_time':proc_info(p.pid)[7],'process_group':p.pid,'owner_verified':True};v=stage2.cleanup_pids([r]);p.wait(5);self.assertEqual(v['status'],'PASS')
 def test_reconciliation_rejects_nonterminal_session_without_writing(self):
  c=session_contract([self.lin],stage='unit',frozen=self.f);s=SessionStore(self.state,c['session_id']);s.create(c,self.root);before=stage2.inventory([s.root]);v=stage2.reconcile(s,[s.root]);self.assertEqual(v['status'],'FAIL');self.assertIn('SESSION_NOT_TERMINAL',v['failures']);self.assertEqual(before,stage2.inventory([s.root]))
 def test_classifications(self):
  self.assertEqual(stage2.classify(freeze_ok=False),'BLOCKED_PREEXECUTION');self.assertEqual(stage2.classify(environment_ok=False),'INCONCLUSIVE_ENVIRONMENT');self.assertEqual(stage2.classify(integrity_ok=False),'FAIL');self.assertEqual(stage2.classify(executed=False),'NOT_EXERCISED')

if __name__=='__main__':unittest.main()
