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
  c={'schema':'gaia_stage2_contract_v2','stage':'stage2','status':'READY_TO_EXECUTE','state_path':str(self.state.resolve()),'commit':'c','identity':{'hash':'i'},'freeze':self.f,'limits':stage2.LIMITS,'lineages':[self.lin],'preregistration_sha256':'p','baseline':{},'plan':{},'executor_sha256':'e','runtime':{},'boot_id':'b','resources':{},'inventory':{},'campaigns_authorized':0,'sessions_started':0,'execution_prohibited':True,'clock':{}}
  c['plan']=stage2.scratch_plan(self.state.parent)
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
  report=loop.store.get(loop.store.inspect()['state']['report_ref'])
  value=stage2.terminal_noop(self.state,cid,[self.state],root=self.root,replay=lambda _:report)
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
  r={'pid':p.pid,'start_time':proc_info(p.pid)[7],'process_group':p.pid,'owner_verified':True}
  refused=stage2.cleanup_pids([r]);self.assertEqual(refused['status'],'FAIL');self.assertIsNone(p.poll())
  v=stage2.cleanup_pids([r],launched={p.pid:p});p.wait(5);self.assertEqual(v['status'],'PASS')

 def test_old_contract_and_used_lineage_are_rejected(self):
   c=self.ready();c['schema']='gaia_stage2_contract_v1'
   with self.assertRaisesRegex(ValueError,'INVALID_STAGE2_CONTRACT'):stage2.validate_contract(c)
   stage2.fresh_lineage(self.root,self.state,[self.lin])
   self.loop(self.lin)
   with self.assertRaisesRegex(ValueError,'FRESH_STAGE2_STATE'):stage2.fresh_lineage(self.root,self.state,[self.lin])

 def test_terminal_replay_detects_writes_and_wrong_report(self):
   loop=self.loop(self.lin);self.go(loop);cid=loop.contract['campaign_id']
   def write(_):
    (self.state/'unexpected').write_text('bad');return {}
   result=stage2.terminal_noop(self.state,cid,[self.state],root=self.root,replay=write)
   self.assertEqual(result['status'],'FAIL');self.assertTrue(result['writes'])

 def test_terminal_fixture_through_real_cli(self):
   loop=self.loop(self.lin);self.go(loop);cid=loop.contract['campaign_id']
   result=stage2.terminal_noop(self.state,cid,[self.state],root=stage2.ROOT)
   self.assertEqual(result['status'],'PASS',result)
   self.assertEqual(result['execution_path'],'REAL_CLI')

 def test_terminal_replay_does_not_ignore_bytecode_writes(self):
   loop=self.loop(self.lin);self.go(loop);cid=loop.contract['campaign_id']
   report=loop.store.get(loop.store.inspect()['state']['report_ref'])
   def write(_):
    cache=self.state/'__pycache__';cache.mkdir();(cache/'extra.pyc').write_bytes(b'new');return report
   result=stage2.terminal_noop(self.state,cid,[self.state],root=self.root,replay=write)
   self.assertEqual(result['status'],'FAIL');self.assertTrue(result['writes'])

 def test_nonterminal_guard_never_calls_replay(self):
   cid=self.loop(self.lin).contract['campaign_id']
   with patch('tools.stage2_executor.subprocess.run')as run:
    result=stage2.terminal_noop(self.state,cid,[self.state],root=self.root)
   self.assertEqual(result['reason'],'NONTERMINAL_REOPEN_REFUSED');run.assert_not_called()

 def test_stage_reservations_survive_new_supervisor(self):
   path=self.root/'evidence'/'budget';owners=[self.root/'evidence',self.state]
   b=stage2.StageBudget(path,'contract',owners)
   with b.exclusive():
    b.start_session('session-one');b.reserve('session-one','S1-C1');b.reserve('session-one','S1-C2')
    for role,cid in (('S1-C1','ac'+'1'*24),('S1-C2','ac'+'2'*24)):
     b.bind(role,cid);b.finish(role,cid,100)
    with self.assertRaisesRegex(ValueError,'ROLE_ORDER'):b.reserve('session-one','S1-C3')
   reopened=stage2.StageBudget(path,'contract',owners)
   with reopened.exclusive():
    self.assertEqual(reopened.view()['reserved_compute_s'],3600)
    reopened.start_session('session-two');reopened.reserve('session-two','S2-C3');reopened.reserve('session-two','S2-C4')
    self.assertEqual(reopened.view()['remaining_compute_s'],0)
    with self.assertRaisesRegex(ValueError,'SESSION_BUDGET'):reopened.start_session('third')
   with self.assertRaisesRegex(ValueError,'CORRUPT'):stage2.StageBudget(path,'different',owners).view()

 def test_stage_storage_is_absolute_and_counts_overlap_once(self):
   path=self.root/'evidence'/'budget';b=stage2.StageBudget(path,'c',[self.root,self.state])
   with b.exclusive():
    initial=b.storage();(self.state/'extra').write_bytes(b'x'*100)
    self.assertEqual(b.storage()-initial,100)
    with patch.object(b,'storage',return_value=4*2**30):
     with self.assertRaisesRegex(ValueError,'STORAGE_BUDGET'):b.start_session('one')
   self.assertEqual(b.events(),[])

 def test_stage_ledger_requires_lock_and_rejects_tamper(self):
   b=stage2.StageBudget(self.root/'evidence'/'budget','c',[self.root/'evidence'])
   with self.assertRaisesRegex(ValueError,'LOCK_REQUIRED'):b.start_session('one')
   with b.exclusive():b.start_session('one')
   (b.path/'000001.json').chmod(0o600);(b.path/'000001.json').write_text('{}')
   with self.assertRaisesRegex(ValueError,'CORRUPT'):b.view()

 def test_stage_symlinked_ownership_root_is_rejected(self):
   target=self.root/'target';target.mkdir();link=self.root/'link';link.symlink_to(target,target_is_directory=True)
   with self.assertRaisesRegex(ValueError,'SYMLINK'):stage2.StageBudget(target/'budget','c',[link])
 def test_reconciliation_rejects_nonterminal_session_without_writing(self):
  c=session_contract([self.lin],stage='unit',frozen=self.f);s=SessionStore(self.state,c['session_id']);s.create(c,self.root);before=stage2.inventory([s.root]);v=stage2.reconcile(s,[s.root]);self.assertEqual(v['status'],'FAIL');self.assertIn('SESSION_NOT_TERMINAL',v['failures']);self.assertEqual(before,stage2.inventory([s.root]))
 def test_classifications(self):
  self.assertEqual(stage2.classify(freeze_ok=False),'BLOCKED_PREEXECUTION');self.assertEqual(stage2.classify(environment_ok=False),'INCONCLUSIVE_ENVIRONMENT');self.assertEqual(stage2.classify(integrity_ok=False),'FAIL');self.assertEqual(stage2.classify(executed=False),'NOT_EXERCISED')

 def test_preflight_pass_requires_all_current_conditions(self):
   c=self.ready();c['runtime']={'python':sys.version,'executable':sys.executable}
   c['plan'].update(administrative_hashes={p:'e'for p in stage2.ADMIN_FILES})
   c['hash']=stage2.digest({k:v for k,v in c.items()if k!='hash'})
   with patch.object(stage2,'frozen',return_value=self.f),patch.object(stage2,'git',return_value='c'),\
        patch.object(stage2,'identities',return_value={'hash':'i'}),patch.object(stage2,'changes',return_value=[]),\
        patch.object(stage2,'sha',side_effect=lambda p:'p'if p==stage2.PREREG else'e'),\
        patch.object(stage2,'boot_id',return_value='b'),patch.object(stage2,'inventory',return_value={}),\
        patch.object(stage2,'qualify_backend'),patch.object(stage2,'safe_git',return_value=''),\
        patch.object(stage2,'memory',return_value={'available_bytes':10**10,'below_reserve':False}),\
        patch.object(stage2,'filesystem',return_value={'free_bytes':10**11,'below_reserve':False}):
    self.assertEqual(stage2.admission(c,self.root,self.state)['status'],'PASS')
    historical=self.root/next(iter(self.f['selections']))/'work'
    historical.mkdir(parents=True,exist_ok=True);(historical/'inference-retained-fixture').mkdir()
    self.assertEqual(stage2.admission(c,self.root,self.state)['status'],'PASS')
    scratch=Path(c['plan']['scratch_root']);(scratch/'inference-retained-fixture').mkdir()
    blocked=stage2.admission(c,self.root,self.state)
    self.assertEqual(blocked['status'],'BLOCKED_PREEXECUTION')
    self.assertIn('OPERATIONAL_BACKEND_SCRATCH_BUSY',blocked['reasons'])
    with patch.object(stage2,'qualify_backend',side_effect=ValueError('artifact changed')):
     self.assertIn('BACKEND_QUALIFICATION_FAILED',stage2.admission(c,self.root,self.state)['reasons'])

 def test_missing_selected_backend_cannot_qualify(self):
   with self.assertRaisesRegex(ValueError,'BACKEND_REQUIRED'):stage2.qualify_backend(self.root,{'selections':{}})

 def test_contract_binds_only_canonical_isolated_scratch(self):
   c=self.ready()
   self.assertEqual(stage2.validate_contract(c)['plan']['scratch_root'],str(self.state.parent/'backend-work'))
   for change in ({'scratch_root':str(self.root/'state_local_intelligence'/'work')},
                  {'scratch_scope':'ADOPT_INHERITED_WORK'}, {'scratch_identity':{'device':True,'inode':1}},
                  {'scratch_root':str(self.state.parent/'other-attempt'/'backend-work')}):
    altered=copy.deepcopy(c);altered['plan'].update(change)
    altered['hash']=stage2.digest({k:v for k,v in altered.items()if k!='hash'})
    with self.assertRaisesRegex(ValueError,'SCRATCH_PLAN'):stage2.validate_contract(altered)

 def test_operational_root_replacement_missing_symlink_and_nonempty_block(self):
   c=self.ready();scratch=Path(c['plan']['scratch_root'])
   stage2.operational_scratch(c,empty=True)
   scratch.rename(scratch.with_name('original-root'))
   with self.assertRaisesRegex(ValueError,'ROOT_INVALID'):stage2.operational_scratch(c,empty=True)
   scratch.mkdir()
   with self.assertRaisesRegex(ValueError,'ROOT_REPLACED'):stage2.operational_scratch(c,empty=True)
   scratch.rmdir()  # Disposable empty fixture only.
   scratch.symlink_to(scratch.with_name('original-root'),target_is_directory=True)
   with self.assertRaisesRegex(ValueError,'SYMLINK'):stage2.operational_scratch(c,empty=True)

 def test_prepare_uses_fresh_attempt_and_never_inspects_historical_work(self):
   historical=self.root/'state_local_intelligence'/'work';historical.mkdir(parents=True)
   (historical/'inference-inherited').mkdir();(historical/'inference-inherited'/'data').write_bytes(b'preserve')
   before=stage2.inventory([historical],include_cache=True)
   out=self.root/'.gaia'/'stage2'/'disposable-preparation'
   def fixture_contract(root,path,lineages,state):
    plan=stage2.scratch_plan(path.parent)
    stage2.operational_scratch({'plan':plan},empty=True)
    self.assertEqual(stage2.inventory([historical],include_cache=True),before)
    return {'plan':plan}
   with patch.object(stage2,'safe_git',return_value=''),patch.object(stage2,'contract',side_effect=fixture_contract):
    result=stage2.prepare(self.root,out)
   self.assertEqual(result['plan']['scratch_root'],str(out/'backend-work'))
   self.assertEqual(list((out/'backend-work').iterdir()),[])
   with self.assertRaises(FileExistsError):stage2.prepare(self.root,out)

if __name__=='__main__':unittest.main()
