"""v2 integrated closed loop; candidate execution, observation and LLM are unit fixtures only."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from gaia import genome as G,provenance
from gaia.autonomy.schema import campaign,validate_campaign,SUPPORTED_V2
from gaia.autonomy.store import CampaignStore
from gaia.autonomy.policy import identities,disk_used
from gaia.autonomy.controller import create_campaign,ClosedLoop
from gaia.autonomy.services import Services
from gaia.autonomy.lineage import LineageStore,create_lineage,engine_state_dir,LineageBusy,host_experiment_lock
from gaia.autonomy.materializer import materialize_v2,duplicate_v2,NotMaterializable,HP_OPS
from gaia.autonomy.hypothesis import assess
from gaia.autonomy import inference_surface as inference
from gaia.diagnosis.engine import diagnose
from gaia.prioritization.engine import prioritize
from gaia.experiment_strategy.engine import plan_experiments
from gaia.experiment_strategy.model import finish_plan
from gaia.experiment_strategy.schema import validate as validate_strategy

ROOT=Path(__file__).resolve().parents[1]
OBSERVATION=json.loads((ROOT/'docs/diagnosis_evidence/current-observation.json').read_bytes())
IMPROVE='IMPROVE_NUMPY_MLP_EXISTING_CRITERIA'


def resign(v):v=copy.deepcopy(v);v['hash']=provenance.digest({k:x for k,x in v.items()if k!='hash'});return v


class FakeV2(Services):
    """Real v2 coordination (lineage, records, strategy, materialization); fixtures replace measured side effects."""
    decisions=('rejected',);select_index=0;review_status='OK';promote=False;verification='PASS';reference_status='MEASURED';reference_cost=1.0
    def initialized(self):return False
    def initialize(self):return {'status':'UNIT_FIXTURE_NOT_REAL_CERTIFICATION'}
    def observe(self,full=False):return copy.deepcopy(OBSERVATION)
    def diagnose(self,ob,iteration):return diagnose(ob,diagnosis_id=f'd{iteration:06d}',improvement_objective=self.contract['objective'])
    def views_path(self):return self.local/'unit-views.json'
    def knowledge(self):
        views=json.loads(self.views_path().read_bytes())if self.views_path().exists()else[]
        return {'views':views,'context':None,'runs':[],'records':[]}
    def compare(self,target,candidates,hypothesis,previous,research):
        cited=candidates[min(self.select_index,len(candidates)-1)]['plan_id']
        return {'schema':'gaia_experiment_review_v3','status':self.review_status,'authority':'NONE','selected_plan_id':candidates[0]['plan_id'],
                'default_plan_id':candidates[0]['plan_id'],'method':'DETERMINISTIC_FIRST_ELIGIBLE_PLAN',
                'advisory':{'kind':'ADVISORY_COGNITIVE_REVIEW','cited_candidates':[cited],'influence_on_selection':'NONE'},
                'previous':previous,'scope':'UNIT_BACKEND_FIXTURE'}
    def champion_reference(self):return self.current_version(),self.reference_cost
    def remeasure(self,check_drift):
        before=(self.last_reference()or{}).get('cost_s');return self.current_version(),self.reference_cost,before,self.reference_status,None,len(self.records())
    def expected_id(self):return f"e{len(self.records())+1:05d}"
    def current_version(self):return 'v0000'
    def execute(self,m):
        n=len(self.records());decision=self.decisions[n%len(self.decisions)]
        after='v0001'if self.promote and decision=='accepted'else'v0000';reference=self.current_reference()
        return {'engine_result':decision,'before_version':'v0000','after_version':after,'reference_used':reference,'evidence':{'id':f'e{n+1:05d}','decision':decision,
            'candidate_genome_hash':m['genome_hash'],'search_cost_s':.01,'screen':{'status':'ok','cost_s':1.0},'overall_gates_passed':True}}
    def learn(self,e):
        outcome={'accepted':'ACCEPTED','rejected':'REJECTED','deferred':'INCONCLUSIVE'}[e['evidence']['decision']]
        views=self.knowledge()['views']+[{'item':{'learning_id':'k'+provenance.digest(e['evidence']['id'])[:24],'hash':provenance.digest(e['evidence']),
            'claim_type':'REJECTED_DIRECTION','claim':{'tested_configurations':[e['evidence']['candidate_genome_hash']],'negative_reuse_scope':'HISTORICAL_REJECTION_ONLY'}},
            'applicability_assessment':{'transferability':'EXACT_CONTEXT'},'effective_status':'ACTIVE'}]
        self.views_path().parent.mkdir(parents=True,exist_ok=True);self.views_path().write_text(json.dumps(views))
        return {'outcome':outcome,'source':{'unit':True},'scope':'SYNTHETIC_UNIT_COORDINATION_NOT_0_5_CERTIFICATION'}
    def verify(self,e,pre):return {'status':self.verification}
    def rollback(self,e,reason):return {'status':'COMPLETED'}
    def health_check(self):return {'status':'NOT_APPLICABLE','reason':'UNIT_FIXTURE'}
    def meta_tune(self):return {'adopted':False,'scope':'UNIT_FIXTURE'}


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        (self.root/'gaia').mkdir();(self.root/'gaia.py').write_text('# unit root\n');(self.root/'gaia/protected').mkdir();(self.root/'gaia/protected/evaluator.py').write_text('# protected unit fixture\n')
        self.state=self.root/'state'
    def lineage(self,objective=IMPROVE):return create_lineage(self.root,self.state,objective)
    def loop(self,lineage_id=None,mode='CONTROLLED_AUTONOMOUS',factory=FakeV2,objective=IMPROVE,**kwargs):
        c=create_campaign(self.root,self.state,campaign(objective,mode=mode,lineage_id=lineage_id,**kwargs))
        return ClosedLoop(self.root,self.state,c['campaign_id'],services_factory=factory)
    def go(self,loop):
        with patch('gaia.autonomy.controller.provenance.bwrap_capability',return_value={'verified':True}):return loop.run(authorized=True)
    def records(self,loop):return [loop.store.get(ev['state']['record_ref'])for i,ev in enumerate(loop.store.events())
        if'record_ref'in ev['state']and ev['state']['record_ref']not in[e['state'].get('record_ref')for e in loop.store.events()[:i]]]


class ContractTests(Fixture):
    def test_v1_default_is_unchanged(self):self.assertEqual(campaign()['schema'],'gaia_closed_loop_campaign_v1')
    def test_v2_objective_table_and_defaults(self):
        c=campaign(IMPROVE,'SHADOW',lineage_id='al'+'a'*24)
        self.assertEqual((c['maximum_iterations'],c['maximum_experiments'],c['maximum_wall_time'],c['maximum_compute_budget']),(5,5,3600,3600))
        self.assertEqual(set(c['allowed_experiment_classes']),set(SUPPORTED_V2))
    def test_inference_requires_lineage_and_no_network(self):
        with self.assertRaises(ValueError):campaign('IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA','SHADOW')
        with self.assertRaises(ValueError):campaign('IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA','SHADOW',lineage_id='al'+'a'*24,network=True,limits={'maximum_network_research':1})
    def test_v2_tampering_and_escalation_rejected(self):
        c=campaign(IMPROVE,'SHADOW',lineage_id='al'+'a'*24)
        for change in ({'allowed_components':['gpu']},{'surface':'local_inference'},{'maximum_wall_time':7200},{'stopping_conditions':[]},
                       {'promotion_policy':{**c['promotion_policy'],'allowed_classes':['CONTROL_EXPERIMENT']}},{'replication_cap':9}):
            with self.subTest(change=change),self.assertRaises(ValueError):validate_campaign(resign({**c,**change}))
    def test_unknown_objective_rejected(self):
        with self.assertRaises(ValueError):campaign('IMPROVE_EVERYTHING','SHADOW',lineage_id='al'+'a'*24)


class LineageTests(Fixture):
    def test_campaign_binds_to_lineage_engine_state(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id'])
        self.assertEqual(loop.configuration['engine_config']['workload']['state_dir'],engine_state_dir(lin['lineage_id']))
        self.assertEqual(loop.configuration['lineage']['hash'],lin['hash'])
    def test_source_change_requires_new_lineage(self):
        lin=self.lineage();(self.root/'gaia/protected/evaluator.py').write_text('# changed')
        with self.assertRaisesRegex(ValueError,'LINEAGE_SOURCE_CHANGED'):self.loop(lin['lineage_id'])
    def test_objective_must_match_lineage(self):
        lin=self.lineage()
        with self.assertRaises(ValueError):self.loop(lin['lineage_id'],objective='VERIFY_NUMPY_MLP_EXISTING_CRITERIA')
    def test_busy_lineage_blocks_without_touching_campaign(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);n=len(loop.store.events())
        with LineageStore(self.state,lin['lineage_id']).lock():r=self.go(loop)
        self.assertEqual(r['reason'],'LINEAGE_BUSY');self.assertEqual(len(loop.store.events()),n)
    def test_host_experiment_lock_is_exclusive(self):
        with host_experiment_lock(self.root),self.assertRaises(LineageBusy):
            with host_experiment_lock(self.root):pass
    def test_corrupted_lineage_journal_detected(self):
        lin=self.lineage();store=LineageStore(self.state,lin['lineage_id'])
        path=store.root/'events/000001.json';v=json.loads(path.read_bytes());v['payload']['lineage_hash']='0'*64;path.chmod(0o644);path.write_text(json.dumps(v))
        with self.assertRaises(ValueError):store.events()
    def test_status_is_a_pure_fold(self):
        lin=self.lineage();store=LineageStore(self.state,lin['lineage_id']);before=sorted(p.name for p in store.root.rglob('*'))
        store.state();self.assertEqual(before,sorted(p.name for p in store.root.rglob('*')))


class IntegratedLoopTests(Fixture):
    def test_campaign_runs_several_distinct_hyperparameter_experiments(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);r=self.go(loop)
        self.assertEqual(r['status'],'PASS');self.assertGreaterEqual(r['metrics']['experiments'],3)
        records=self.records(loop);hashes=[x['proposed_change']['candidate_hash']for x in records]
        self.assertEqual(len(hashes),len(set(hashes)));self.assertEqual(r['metrics']['distinct_candidates'],len(hashes))
        for x in records:
            self.assertTrue(all(str(c[0]).startswith('hp.')for c in x['proposed_change']['changes']))
            self.assertIn(x['result']['hypothesis_assessment'],('SUPPORTED','NOT_SUPPORTED','INCONCLUSIVE'))
            self.assertEqual(x['authority'],'DETERMINISTIC_ASSEMBLY_NOT_MODEL_TEXT')
        self.assertIn('EXPLORATION',r['metrics']['classes_exercised'])
        self.assertIn(r['stopping_reason'],('NO_PROGRESS','STOPPED_BUDGET'))
    def test_second_lineage_campaign_does_not_repeat_genomes(self):
        lin=self.lineage();first=self.loop(lin['lineage_id']);self.go(first)
        second=self.loop(lin['lineage_id']);r=self.go(second)
        a={x['proposed_change']['candidate_hash']for x in self.records(first)};b={x['proposed_change']['candidate_hash']for x in self.records(second)}
        self.assertTrue(b);self.assertFalse(a&b);self.assertEqual(r['metrics']['human_interventions_during_campaign'],0)
        state=LineageStore(self.state,lin['lineage_id']).state();self.assertEqual(state['experiments'],len(a)+len(b));self.assertEqual(state['open_campaigns'],[])
    def test_advisory_cognitive_review_never_changes_the_deterministic_plan(self):
        class Second(FakeV2):select_index=1
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Second);r=self.go(loop)
        events=loop.store.events();seen=set()
        for e in events:
            s=e['state']
            if 'selection_ref'in s and s['selection_ref']['id']not in seen:
                seen.add(s['selection_ref']['id']);selection=loop.store.get(s['selection_ref']);candidates=loop.store.get(s['candidates_ref'])['candidates']
                self.assertEqual(selection['method'],'DETERMINISTIC_FIRST_ELIGIBLE_PLAN');self.assertEqual(selection['selected_plan_id'],candidates[0]['plan']['plan_id'])
        self.assertTrue(seen);self.assertNotIn('cognitive_plan_selections',r['metrics'])
        self.assertEqual(r['metrics']['advisory_cognitive_reviews'],r['metrics']['deterministic_plan_selections'])
    def test_failed_review_cannot_authorize(self):
        class Bad(FakeV2):review_status='FAILED'
        lin=self.lineage();r=self.go(self.loop(lin['lineage_id'],factory=Bad));self.assertEqual(r['metrics']['experiments'],0)
    def test_dry_run_and_shadow_do_not_execute(self):
        lin=self.lineage()
        for mode in ('DRY_RUN','SHADOW'):
            r=self.go(self.loop(lin['lineage_id'],mode=mode));self.assertEqual(r['metrics']['experiments'],0);self.assertEqual(r['status'],'PASS')
    def test_research_without_authority_continues(self):
        lin=self.lineage()
        with patch('gaia.autonomy.controller.research.needed',return_value=True):loop=self.loop(lin['lineage_id']);r=self.go(loop)
        research=[loop.store.get(e['state']['research_ref'])for e in loop.store.events()if'research_ref'in e['state']]
        self.assertTrue(all(x['status']=='RESEARCH_NOT_AUTHORIZED'for x in research));self.assertGreater(r['metrics']['experiments'],0)
    def test_ambiguous_execution_blocks_lineage_until_explicit_review(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id'])
        for phase in ('OBSERVING','DIAGNOSING','PRIORITIZING','RETRIEVING','RESEARCHING','PLANNING','REVIEWING','AUTHORIZING','MATERIALIZING','EXPERIMENTING'):loop.store.event(phase)
        loop.store.event('EXPERIMENTING',{'execution_intent':True,'expected_experiment_id':'e00001'});loop.recover_execution=lambda _:None
        self.assertEqual(self.go(loop)['stopping_reason'],'NEEDS_RECOVERY')
        store=LineageStore(self.state,lin['lineage_id']);self.assertTrue(store.state()['blocked'])
        self.assertEqual(self.go(self.loop(lin['lineage_id']))['stopping_reason'],'LINEAGE_BLOCKED_NEEDS_RECOVERY')
        store.event('UNBLOCKED',{'reason':'unit review','authority':'EXPLICIT_OPERATOR_REVIEW'})
        self.assertGreater(self.go(self.loop(lin['lineage_id']))['metrics']['experiments'],0)
    def test_unlearned_executed_experiment_blocks_lineage(self):
        class Broken(FakeV2):
            def learn(self,e):raise ValueError('INVALID_LEARNING_SCOPE')
        lin=self.lineage();r=self.go(self.loop(lin['lineage_id'],factory=Broken))
        self.assertEqual(r['status'],'FAIL');state=LineageStore(self.state,lin['lineage_id']).state()
        self.assertTrue(state['blocked']);self.assertEqual(state['block']['reason'],'INTERRUPTED_IN_FLIGHT_EXPERIMENT');self.assertEqual(state['block']['phase'],'LEARNING')
    def test_patch_version_is_a_valid_learning_scope(self):
        from gaia.learning.schema import valid_context
        ctx={'environment_hash':'a'*64,'host_hash':'a'*64,'runtime_hash':'a'*64,'benchmark_hash':'a'*64,'source_hash':'a'*64,'workload':'numpy_mlp',
             'trainer_family':'numpy_mlp','quality_threshold':.6,'gaia_version':'gaia-v1.0.1','baseline_version':'v0000'}
        valid_context(ctx)
        with self.assertRaises(ValueError):valid_context({**ctx,'gaia_version':'gaia-v1'})
    def test_failed_follow_up_rolls_back_then_blocks_lineage(self):
        class Unhealthy(FakeV2):
            rolled=[]
            def health_check(self):return {'status':'FAIL','version':'v0001','rollback_to':'v0000'}
            def rollback(self,e,reason):Unhealthy.rolled.append(e['before_version']);return {'status':'COMPLETED'}
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Unhealthy);r=self.go(loop)
        self.assertEqual(r['stopping_reason'],'HEALTH_INVALID');self.assertEqual(Unhealthy.rolled,['v0000']);self.assertEqual(r['metrics']['rollback_count'],1)
        self.assertEqual(r['metrics']['experiments'],0);self.assertTrue(LineageStore(self.state,lin['lineage_id']).state()['blocked'])
    def future(self,seconds=10**4):
        now=time.time()+seconds
        return patch('gaia.autonomy.policy.time.time',return_value=now),patch('gaia.autonomy.controller.time.time',return_value=now)
    def test_budget_exhausted_on_resume_still_learns_the_committed_experiment(self):
        class Dies(FakeV2):
            def execute(self,m):Dies.committed=super().execute(m);raise SystemExit('process death after committed evidence')
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Dies)
        with self.assertRaises(SystemExit):self.go(loop)
        loop.recover_execution=lambda _:Dies.committed;a,b=self.future()
        with a,b:r=self.go(loop)
        self.assertEqual(r['stopping_reason'],'STOPPED_BUDGET');self.assertEqual(r['metrics']['experiments'],1);self.assertEqual(len(self.records(loop)),1)
        state=LineageStore(self.state,lin['lineage_id']).state();self.assertFalse(state['blocked']);self.assertEqual(state['experiments'],1)
    def test_deadline_during_learning_finishes_bookkeeping_under_grace(self):
        from gaia.autonomy.policy import BudgetExceeded
        clock=self.future()
        class Late(FakeV2):
            calls=0
            def learn(self,e):
                Late.calls+=1
                if Late.calls==1:
                    for c in clock:c.start()
                    raise BudgetExceeded('STOPPED_BUDGET')
                return super().learn(e)
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Late)
        try:r=self.go(loop)
        finally:
            for c in clock:c.stop()
        self.assertEqual(Late.calls,2);self.assertEqual(len(self.records(loop)),1);self.assertEqual(r['stopping_reason'],'STOPPED_BUDGET')
        self.assertFalse(LineageStore(self.state,lin['lineage_id']).state()['blocked'])
    def test_pause_in_flight_is_deferred_until_bookkeeping_completes(self):
        class Pausing(FakeV2):
            def learn(self,e):self.store.control('PAUSE');return super().learn(e)
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Pausing);r=self.go(loop)
        self.assertEqual(r['status'],'PAUSED');paused=loop.store.current()
        self.assertEqual(paused['resume_phase'],'REEVALUATING');self.assertEqual(len(self.records(loop)),1)
    def test_persisted_failed_health_check_is_acted_on_after_crash(self):
        class Bad(FakeV2):
            def health_check(self):return {'status':'FAIL','version':'v0001','rollback_to':None}
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Bad);original=loop.store.event
        def crash(phase,updates=None):
            value=original(phase,updates)
            if updates and updates.get('health_ref'):raise SystemExit('death after persisted health failure')
            return value
        with patch.object(loop.store,'event',side_effect=crash),self.assertRaises(SystemExit):self.go(loop)
        r=self.go(loop);self.assertEqual(r['stopping_reason'],'HEALTH_INVALID');self.assertEqual(r['metrics']['experiments'],0)
    def test_health_check_survives_crash_after_admission(self):
        class Crash(FakeV2):
            calls=0
            def health_check(self):
                Crash.calls+=1
                if Crash.calls==1:raise SystemExit('death before health check')
                return super().health_check()
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Crash)
        with self.assertRaises(SystemExit):self.go(loop)
        self.go(loop);events=LineageStore(self.state,lin['lineage_id']).events()
        self.assertEqual(Crash.calls,2);self.assertEqual(sum(e['kind']=='CAMPAIGN_ADMITTED'for e in events),1);self.assertEqual(sum(e['kind']=='HEALTH_CHECK'for e in events),1)
    def test_admission_is_idempotent_after_crash(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);original=loop.store.event
        def crash(phase,updates=None):
            if updates and updates.get('admitted'):raise SystemExit('death after lineage admission')
            return original(phase,updates)
        with patch.object(loop.store,'event',side_effect=crash),self.assertRaises(SystemExit):self.go(loop)
        self.go(loop);events=LineageStore(self.state,lin['lineage_id']).events()
        self.assertEqual(sum(e['kind']=='CAMPAIGN_ADMITTED'for e in events),1);self.assertEqual(sum(e['kind']=='CAMPAIGN_CLOSED'for e in events),1)
    def test_interrupted_meta_tune_is_recorded_and_not_replayed(self):
        class Tune(FakeV2):
            calls=0
            def meta_tune(self):
                Tune.calls+=1;raise SystemExit('death during strategy tuning')
        lin=self.lineage();self.go(self.loop(lin['lineage_id'],factory=Tune));loop=self.loop(lin['lineage_id'],factory=Tune)
        with self.assertRaises(SystemExit):self.go(loop)
        self.go(loop);events=LineageStore(self.state,lin['lineage_id']).events()
        self.assertEqual(Tune.calls,1);self.assertTrue(any(e['kind']=='META_TUNE'and e['payload'].get('interrupted')for e in events))
    def test_crash_inside_report_is_reconciled_on_rerun(self):
        class Recovery(FakeV2):pass
        lin=self.lineage();loop=self.loop(lin['lineage_id']);store=LineageStore(self.state,lin['lineage_id'])
        for phase in ('OBSERVING','DIAGNOSING','PRIORITIZING','RETRIEVING','RESEARCHING','PLANNING','REVIEWING','AUTHORIZING','MATERIALIZING','EXPERIMENTING'):loop.store.event(phase)
        loop.store.event('EXPERIMENTING',{'execution_intent':True,'expected_experiment_id':'e00001'});loop.recover_execution=lambda _:None
        original=LineageStore.event
        def crash(self_,kind,payload):
            if kind=='BLOCKED':raise SystemExit('death inside report')
            return original(self_,kind,payload)
        with patch.object(LineageStore,'event',crash),self.assertRaises(SystemExit):self.go(loop)
        self.assertFalse(store.state()['blocked']);self.assertEqual(self.go(loop)['stopping_reason'],'NEEDS_RECOVERY');self.assertTrue(store.state()['blocked'])
        self.assertEqual(sum(e['kind']=='BLOCKED'for e in store.events()),1)
    def test_unexpected_verification_error_rolls_back_promotion(self):
        class Promoted(FakeV2):
            decisions=('accepted',);promote=True
            def verify(self,e,pre):raise KeyError('unexpected')
        lin=self.lineage();r=self.go(self.loop(lin['lineage_id'],factory=Promoted,promotion=True))
        self.assertEqual(r['stopping_reason'],'POST_PROMOTION_REGRESSION_ROLLED_BACK');self.assertEqual(r['metrics']['rollback_count'],1)
    def test_mature_lineage_does_not_charge_new_campaign_before_admission(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id'],limits={'maximum_disk_budget':65536})
        (LineageStore(self.state,lin['lineage_id']).root/'history.bin').write_bytes(b'x'*10**6)
        self.assertLess(disk_used(loop.contract,{},self.state),65536);self.assertGreater(disk_used(loop.contract,{'admission_lineage_bytes':0},self.state),10**6)
    def test_accepted_exploration_is_not_promoted_directly(self):
        from types import SimpleNamespace
        lin=self.lineage();loop=self.loop(lin['lineage_id'],promotion=True);store=loop.store
        svc=Services(self.root,self.state,store,loop.contract,loop.configuration)
        for cls,expected in (('EXPLORATION',False),('CONTROL_EXPERIMENT',False)):
            m=store.put('MATERIALIZED',{'class':cls});a=store.put('AUTHORIZATION',{'status':'AUTHORIZED'})
            store.event('CREATED',{'started_at':time.time(),'materialized_ref':m,'authorization_ref':a})
            eng=SimpleNamespace(store=SimpleNamespace(dir=self.root/'native'))
            with self.subTest(cls=cls):self.assertIs(svc.promotion_allowed(eng,{'id':'e00001'},{'decision':'accepted','promotable':True,'evidence_hash':'a'*64}),expected)
        self.assertEqual(set(loop.contract['promotion_policy']['allowed_classes']),{'PARAMETER_LOCAL_SEARCH','REPLICATION','EXPLOITATION'})
    def test_linked_outcomes_reach_strategy(self):
        lin=self.lineage();self.go(self.loop(lin['lineage_id']));loop=self.loop(lin['lineage_id']);self.go(loop)
        strategy=next(loop.store.get(e['state']['strategy_ref'])for e in loop.store.events()if'strategy_ref'in e['state'])
        self.assertEqual(strategy['outcome_statistics']['mode'],'LINKED_EXECUTED_OUTCOMES');self.assertTrue(strategy['outcome_statistics']['outcomes'])
    def test_offline_v2_audit_reproduces_and_detects_tampering(self):
        from tools.audit_closed_loop import audit_data,get_artifacts,lineage_records_before
        lin=self.lineage();self.go(self.loop(lin['lineage_id']));loop=self.loop(lin['lineage_id']);self.go(loop)
        prior=lineage_records_before(self.state,loop.contract)
        args=(loop.contract,loop.configuration,loop.store.events(),get_artifacts(loop.store))
        def audit(events=None,artifacts=None,records=prior):
            with patch('tools.audit_closed_loop.validate_source',side_effect=lambda v:{'experiments':[{'outcome':'REJECTED'}]}):
                return audit_data(args[0],args[1],events or args[2],artifacts or args[3],check_source=False,lineage_records=records)
        self.assertEqual(audit()['status'],'PASS')
        events=copy.deepcopy(args[2]);events[1]['state']['experiments']=99
        with self.assertRaises(ValueError):audit(events=events)
        record_ids=[e['state']['record_ref']['id']for e in args[2]if'record_ref'in e['state']]
        artifacts=copy.deepcopy(args[3]);v=artifacts[record_ids[0]];v['payload']['next_step']='PROMOTE_NOW'
        v['id']='au'+provenance.digest({k:x for k,x in v.items()if k not in('id','hash')})[:24]
        with self.assertRaises(ValueError):audit(artifacts=artifacts)
        first=lineage_records_before(self.state,loop.contract)
        with self.assertRaises(ValueError):audit(records=first+[self.records(loop)[0]])
    def test_v2_without_lineage_keeps_campaign_scope(self):
        loop=self.loop(None);self.assertEqual(loop.configuration['engine_config']['workload']['state_dir'],'state_closed_loop_cpu_'+loop.contract['campaign_id'][2:])
        self.assertGreaterEqual(self.go(loop)['metrics']['experiments'],3)


class MaterializerV2Tests(Fixture):
    def setUp(self):
        super().setUp()
        self.contract=campaign(IMPROVE,'CONTROLLED_AUTONOMOUS',lineage_id='al'+'a'*24)
        d=diagnose(OBSERVATION,improvement_objective=IMPROVE);self.p=prioritize([d]);self.s=plan_experiments(self.p,diagnoses=[d])
        self.targets={t['target_id']:t for t in self.p['candidate_targets']}
    def plan(self,cls):return next(p for p in self.s['candidate_plans']if p['class']==cls)
    def target(self,plan):return self.targets[plan['target_ref']['target_id']]
    def m(self,plan,**kw):return materialize_v2(self.contract,self.target(plan),plan,None,G.new_genome(),[],iteration=1,preview=True,**kw)
    def test_exploration_changes_one_hyperparameter_deterministically(self):
        plan=self.plan('EXPLORATION');a=self.m(plan);b=self.m(plan)
        self.assertEqual(a['genome_hash'],b['genome_hash']);self.assertEqual(len(a['ops']),1);self.assertIn(a['ops'][0],HP_OPS)
        self.assertEqual(a['genome']['slots'],G.new_genome()['slots']);self.assertFalse(a['genome']['lits']or a['genome']['drops'])
    def test_novelty_excludes_seen_candidates(self):
        plan=self.plan('EXPLORATION');first=self.m(plan);second=self.m(plan,seen={first['candidate_hash']})
        self.assertNotEqual(first['candidate_hash'],second['candidate_hash'])
    def test_parallelism_is_not_materializable_on_hp_surface(self):
        plan=finish_plan({**self.plan('EXPLORATION'),'variables':['parallelism']})
        with self.assertRaises(NotMaterializable):self.m(plan)
    def test_replication_requires_qualified_reference(self):
        plan=finish_plan({**self.plan('EXPLORATION'),'class':'REPLICATION','candidate_variation':{**self.plan('EXPLORATION')['candidate_variation'],'kind':'REPEAT_REFERENCE_CONFIGURATION'}})
        with self.assertRaises(NotMaterializable):self.m(plan)
    def test_code_variation_and_unauthorized_execution_rejected(self):
        g=G.new_genome();g['lits']={'x':1.0};plan=self.plan('EXPLORATION')
        with self.assertRaises(ValueError):materialize_v2(self.contract,self.target(plan),plan,None,g,[],iteration=1,preview=True)
        with self.assertRaises(ValueError):materialize_v2(self.contract,self.target(plan),plan,None,G.new_genome(),[],iteration=1)
    def test_intentional_repeat_cap(self):
        m={**self.m(self.plan('EXPLORATION')),'intentional_repeat':True}
        self.assertIsNone(duplicate_v2(m,[],set(),{},2))
        self.assertEqual(duplicate_v2(m,[],set(),{m['candidate_hash']:2},2)['reason'],'INTENTIONAL_REPEAT_CAP_REACHED')
    def reference(self,hp,outcome='ACCEPTED',slots=None):
        from gaia.learning.ingestion import project_configuration
        g=G.new_genome(hp,slots);cfg={'hp':g['hp'],'slots':g['slots'],'genome_hash':provenance.digest(g),'code_variation_hash':project_configuration(g)['code_variation_hash']}
        record={'kind':'record','learning_id':'l'+provenance.digest(cfg)[:24],'hash':provenance.digest({'r':cfg}),
                'claim':{'outcome':outcome,'configuration':cfg,'configuration_hash':cfg['genome_hash']}}
        knowledge={'kind':'knowledge','learning_id':'k'+'1'*24,'hash':'k'*64,'claim':{'record_refs':[record['learning_id']]}}
        return g,record,knowledge
    def knowledge_plan(self,cls,g,knowledge,**extra):
        base=self.plan('EXPLORATION')
        return finish_plan({**base,'class':cls,'knowledge_refs':[{'learning_id':knowledge['learning_id'],'hash':knowledge['hash'],'claim_type':'OBSERVED_EFFECT',
            'effective_status':'ACTIVE','applicability':'EXACT_CONTEXT','stale':False}],
            'candidate_variation':{**base['candidate_variation'],'reference_configuration_hash':provenance.digest(g),**extra.pop('variation',{})},**extra})
    def mk(self,plan,records):return materialize_v2(self.contract,self.target(plan),plan,None,G.new_genome(),records,iteration=1,preview=True)
    def test_local_search_and_exploitation_vary_one_factor_of_the_accepted_reference(self):
        g,record,knowledge=self.reference({'hidden':32})
        for cls in ('PARAMETER_LOCAL_SEARCH','EXPLOITATION'):
            m=self.mk(self.knowledge_plan(cls,g,knowledge),[record,knowledge])
            diff=[d for d in G.diff(g,m['genome'])]
            with self.subTest(cls=cls):
                self.assertEqual(len(m['ops']),1);self.assertEqual(len(diff),1);self.assertEqual(m['reference']['learning_id'],record['learning_id'])
                self.assertEqual(m['method'],'EXISTING_HP_OPERATOR_FROM_QUALIFIED_REFERENCE')
    def test_replication_and_validation_repeat_the_reference_exactly(self):
        g,record,knowledge=self.reference({'hidden':32})
        for cls in ('REPLICATION','KNOWLEDGE_VALIDATION'):
            plan=self.knowledge_plan(cls,g,knowledge,variation={'kind':'REPEAT_REFERENCE_CONFIGURATION'})
            m=self.mk(plan,[record,knowledge])
            with self.subTest(cls=cls):self.assertEqual(m['genome'],g);self.assertTrue(m['intentional_repeat'])
    def test_rejected_reference_cannot_be_replicated_but_can_be_validated(self):
        g,record,knowledge=self.reference({'hidden':32},outcome='REJECTED')
        with self.assertRaises(NotMaterializable):self.mk(self.knowledge_plan('REPLICATION',g,knowledge,variation={'kind':'REPEAT_REFERENCE_CONFIGURATION'}),[record,knowledge])
        self.assertEqual(self.mk(self.knowledge_plan('KNOWLEDGE_VALIDATION',g,knowledge,variation={'kind':'REPEAT_REFERENCE_CONFIGURATION'}),[record,knowledge])['genome'],g)
    def test_factorial_design_walks_fixed_cells_then_completes(self):
        g,record,knowledge=self.reference({'lr':0.1})
        plan=self.knowledge_plan('DISCRIMINATION',g,knowledge,design='CONTROLLED_FACTORIAL',variables=['learning_rate','weight_decay'])
        seen=set();cells=[]
        for _ in range(4):
            m=materialize_v2(self.contract,self.target(plan),plan,None,G.new_genome(),[record,knowledge],iteration=1,preview=True,seen=seen)
            cells.append((m['genome']['hp']['lr'],m['genome']['hp']['wd']));seen.add(m['candidate_hash'])
        self.assertEqual(sorted(set(cells)),[(0.05,0.0),(0.05,0.0001),(0.2,0.0),(0.2,0.0001)])
        with self.assertRaises(NotMaterializable):materialize_v2(self.contract,self.target(plan),plan,None,G.new_genome(),[record,knowledge],iteration=1,preview=True,seen=seen)
    def test_reference_outside_hyperparameter_surface_rejected(self):
        g,record,knowledge=self.reference({},slots={'optimizer':'adam'})
        with self.assertRaises(NotMaterializable):self.mk(self.knowledge_plan('REPLICATION',g,knowledge,variation={'kind':'REPEAT_REFERENCE_CONFIGURATION'}),[record,knowledge])
    def test_unintended_repeat_of_evaluated_configuration_skipped(self):
        m=self.m(self.plan('EXPLORATION'))
        self.assertEqual(duplicate_v2(m,[],{m['candidate_hash']},{},2)['reason'],'CONFIGURATION_ALREADY_EVALUATED_IN_LINEAGE')


class StrategyAndHypothesisTests(Fixture):
    def test_default_v0_1_search_proposals_are_unchanged(self):
        # Digest produced by gaia/search.py at fe767aa (GAIA 1.0) for the same seeded history.
        import numpy as np
        from gaia import search
        rng=np.random.default_rng(0);h=search.History();h.add(G.new_genome(),1.0,'ok',None,[]);s=search.Strategy({},rng);out=[]
        for i in range(60):
            g,ops,ph,pc=s.propose(h);h.add(g,1.0-0.01*i if i%3 else None,'ok',pc,ops);out.append((G.genome_hash(g),ops))
        self.assertEqual(provenance.digest(out),'b4c9fcf65bb6bd513ed898989250b6a7f610188f3163cfad9a17ffa38bc75472')
    def test_restricted_search_never_leaves_hyperparameter_surface(self):
        import numpy as np
        from gaia import search
        from gaia.autonomy.materializer import hp_random_genome
        base=G.new_genome();rng=np.random.default_rng(1);h=search.History();h.add(base,1.0,'ok',None,[])
        s=search.Strategy({'p_global':.3},rng,op_names=HP_OPS,random_genome=hp_random_genome(base))
        for i in range(80):
            g,ops,ph,pc=s.propose(h);h.add(g,1.0,'ok',pc,ops)
            self.assertEqual(g['slots'],base['slots']);self.assertFalse(g['lits']or g['drops']);self.assertTrue(set(ops)<=set(HP_OPS)|{'random_global'})
    def test_linked_outcomes_are_bounded_reproducible_and_tamper_evident(self):
        d=diagnose(OBSERVATION,improvement_objective=IMPROVE);p=prioritize([d])
        outcomes=[{'experiment_id':'e00001','class':'CONTROL_EXPERIMENT','target_class':'TRAINER_OPTIMIZATION','outcome':'REJECTED','hypothesis_assessment':'SUPPORTED','cost_s':None}]
        s=plan_experiments(p,diagnoses=[d],outcomes=outcomes);control=next(x for x in s['candidate_plans']if x['class']=='CONTROL_EXPERIMENT')
        self.assertEqual(control['utility']['components']['linked_outcomes'],-2);self.assertTrue(s['outcome_statistics']['static_ranking'])
        bad=copy.deepcopy(s);bad['outcome_statistics']['by_class']={}
        with self.assertRaises(ValueError):validate_strategy(bad)
        self.assertNotIn('outcome_statistics',plan_experiments(p,diagnoses=[d]))
    def test_invalid_outcome_rejected(self):
        d=diagnose(OBSERVATION,improvement_objective=IMPROVE);p=prioritize([d])
        with self.assertRaises(ValueError):plan_experiments(p,diagnoses=[d],outcomes=[{'class':'X'}])
    def test_improvement_objective_is_not_a_detected_defect(self):
        d=diagnose(OBSERVATION,improvement_objective=IMPROVE);issue=[i for i in d['issues']if i['kind']=='WORKLOAD_OPTIMIZATION_OBJECTIVE']
        self.assertEqual(len(issue),1);self.assertEqual(issue[0]['details']['scope'],'REQUESTED_OPTIMIZATION_NOT_A_DETECTED_DEFECT')
        with self.assertRaises(ValueError):diagnose(OBSERVATION,improvement_objective='MAKE_IT_FASTER')
    def test_hypothesis_assessment_table(self):
        e={'evidence':{'decision':'rejected','id':'e1','screen':{'status':'ok'}}}
        control={'hypothesis_id':'h0001','expected_effect':'NO_EFFECT_VERSUS_IDENTICAL_BASELINE'}
        effect={'hypothesis_id':'h0001','expected_effect':'COST_TO_TARGET_DECREASES_QUALITY_PRESERVED'}
        self.assertEqual(assess(control,e,'REJECTED')['status'],'SUPPORTED');self.assertEqual(assess(control,e,'ACCEPTED')['note'],'CONTROL_ANOMALY_MEASUREMENT_SUSPECT')
        self.assertEqual(assess(effect,e,'REJECTED')['status'],'NOT_SUPPORTED');self.assertEqual(assess(effect,e,'INCONCLUSIVE')['status'],'INCONCLUSIVE')
    def test_v2_disk_budget_counts_campaign_plus_lineage_growth(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);c=loop.contract
        lineage_root=LineageStore(self.state,lin['lineage_id']).root;(lineage_root/'blob').write_bytes(b'x'*1000)
        used=disk_used(c,{'admission_lineage_bytes':0},self.state);grown=disk_used(c,{'admission_lineage_bytes':10**9},self.state)
        self.assertGreater(used,grown);self.assertGreaterEqual(used,1000)


PRIMARY={'backend':'VULKAN','context':1024,'gpu_layers':999,'kv':'f16','model_family':'smollm3','model_hash':'a'*64,'model_id':'unit','model_metadata':{'smollm3.block_count':36},
         'prefix_cache':False,'quantization':'Q4_K_M','runtime':'koboldcpp','runtime_hash':'b'*64,'runtime_install':'koboldcpp-unit','runtime_version':'1','stack_id':'stack-0','threads':8}


class ReferenceAndMatrixTests(Fixture):
    def references(self,lineage_id):return [e['payload']for e in LineageStore(self.state,lineage_id).events()if e['kind']=='REFERENCE_MEASURED']
    def test_admission_remeasures_reference_with_drift_guard_and_records_bind_it(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);r=self.go(loop)
        refs=self.references(lin['lineage_id']);self.assertEqual(refs[0]['reason'],'CAMPAIGN_ADMISSION')
        first=loop.store.get(refs[0]['measurement_ref']);self.assertTrue(first['drift_checked'])
        for x in self.records(loop):
            self.assertEqual(x['screen_reference']['version'],x['system_version']['version_before'])
            self.assertEqual(x['screen_reference']['measurement_ref'],refs[-1]['measurement_ref'])
        second=self.loop(lin['lineage_id']);self.go(second)
        self.assertEqual([x['reason']for x in self.references(lin['lineage_id'])],['CAMPAIGN_ADMISSION','CAMPAIGN_ADMISSION'])
        self.assertGreaterEqual(r['metrics']['reference_measurements'],1)
    def test_reference_drift_stops_before_any_experiment_and_requires_review(self):
        class Drift(FakeV2):reference_status='REFERENCE_DRIFT'
        lin=self.lineage();r=self.go(self.loop(lin['lineage_id'],factory=Drift))
        self.assertEqual(r['stopping_reason'],'REFERENCE_DRIFT');self.assertEqual(r['metrics']['experiments'],0)
        # As in v0.1 (NeedsHuman), a drifted reference clock is never silently accepted by the next campaign.
        self.assertEqual(LineageStore(self.state,lin['lineage_id']).state()['block']['reason'],'REFERENCE_DRIFT')
    def test_unreliable_reference_blocks_lineage(self):
        class Saturated(FakeV2):reference_status='BENCHMARK_SATURATED'
        lin=self.lineage();r=self.go(self.loop(lin['lineage_id'],factory=Saturated))
        self.assertEqual(r['stopping_reason'],'REFERENCE_UNRELIABLE');self.assertTrue(LineageStore(self.state,lin['lineage_id']).state()['blocked'])
    def test_reference_not_bound_to_champion_is_remeasured_before_screen(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);svc=loop.services
        loop.store.event('CREATED',{'started_at':time.time()})
        svc.measure_reference('CAMPAIGN_ADMISSION',True)
        self.assertFalse(svc.current_reference()['measured_now'])
        # A reverted version's cost (or another champion) left in the Engine state is never used for a screen.
        with patch.object(FakeV2,'champion_reference',return_value=('v0000',0.357)):
            bound=svc.current_reference()
        self.assertTrue(bound['measured_now']);self.assertEqual(bound['reason'],'REFERENCE_NOT_BOUND_TO_CURRENT_CHAMPION')
        with patch.object(FakeV2,'champion_reference',return_value=('v0001',1.0)):self.assertTrue(svc.current_reference()['measured_now'])
    def test_verification_rollback_remeasures_restored_champion_reference(self):
        class Promoted(FakeV2):decisions=('accepted',);promote=True;verification='FAIL'
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Promoted,promotion=True);r=self.go(loop)
        self.assertEqual(r['stopping_reason'],'POST_PROMOTION_REGRESSION_ROLLED_BACK')
        events=loop.store.events();rolled=next(i for i,e in enumerate(events)if e['state'].get('rollback_ref'))
        after=[loop.store.get(e['state']['reference_ref'])for e in events[rolled:]if e['state'].get('reference_ref')]
        self.assertEqual(after[-1]['reason'],'AFTER_ROLLBACK');self.assertEqual(after[-1]['version'],'v0000')
        self.assertEqual(self.references(lin['lineage_id'])[-1]['reason'],'AFTER_ROLLBACK')
    def test_health_check_rollback_remeasures_reference(self):
        class Unhealthy(FakeV2):
            def health_check(self):return {'status':'FAIL','version':'v0001','rollback_to':'v0000'}
        lin=self.lineage();r=self.go(self.loop(lin['lineage_id'],factory=Unhealthy))
        self.assertEqual(r['stopping_reason'],'HEALTH_INVALID');self.assertEqual(self.references(lin['lineage_id'])[-1]['reason'],'AFTER_ROLLBACK')
    def test_rollback_without_reference_remeasurement_fails_audit(self):
        from tools.audit_closed_loop import audit_references
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=type('P',(FakeV2,),{'decisions':('accepted',),'promote':True,'verification':'FAIL'}),promotion=True)
        self.go(loop);events=[e for e in loop.store.events()]
        get=lambda r,kind=None:loop.store.get(r)
        evaluations=[e['state']for e in events if e['state'].get('record_ref')][:1]
        audit_references(events,get,evaluations)
        cut=next(i for i,e in enumerate(events)if e['state'].get('reference_after_rollback'))
        stripped=copy.deepcopy(events)
        for e in stripped[cut-1:]:
            if e['state'].get('reference_ref')and loop.store.get(e['state']['reference_ref'])['reason']=='AFTER_ROLLBACK':e['state']['reference_ref']=events[cut-2]['state']['reference_ref']
        with self.assertRaisesRegex(ValueError,'ROLLBACK_WITHOUT_REFERENCE_REMEASUREMENT|EXPERIMENT_AFTER_ROLLBACK'):audit_references(stripped,get,evaluations)

    def test_restored_reference_is_measured_even_with_an_exhausted_campaign_budget(self):
        from types import SimpleNamespace
        from gaia.autonomy.services import BoundedEngine
        from gaia.autonomy.policy import BudgetExceeded
        lin=self.lineage();loop=self.loop(lin['lineage_id']);loop.store.event('CREATED',{'started_at':time.time()-10**5})
        eng=BoundedEngine.__new__(BoundedEngine);eng.lim={'max_experiment_seconds':60};eng.campaign_budget=(loop.contract,loop.store,self.state,self.root/'native')
        caps=[]
        with patch('gaia.engine.Engine.trial',side_effect=lambda src,seed,task,cap,**k:caps.append(cap)or{'reached':True}):
            with self.assertRaises(BudgetExceeded):eng.trial('src',1)
            eng.bookkeeping=True;eng.trial('src',1)
        self.assertEqual(caps,[min(60,loop.contract['maximum_trial_seconds'])])
        # Only the post-rollback measurement is bookkeeping; admission and guards stay on the campaign budget.
        seen=[];fake=SimpleNamespace(bookkeeping=False)
        def remeasure(self_,check_drift):seen.append(fake.bookkeeping);return 'v0000',1.0,None,'MEASURED',None,0
        with patch.object(FakeV2,'engine',return_value=fake),patch.object(FakeV2,'remeasure',remeasure):
            loop.services.measure_reference('AFTER_ROLLBACK',False);loop.services.measure_reference('CAMPAIGN_ADMISSION',True)
        self.assertEqual(seen,[True,False]);self.assertFalse(fake.bookkeeping)

    # ------------------------------------------------------------------ regression matrix policy
    def run_policy(self,attempts):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);svc=loop.services;calls=[]
        def run(kind,only=None):
            status,ids=attempts[len(calls)];calls.append((kind,only))
            return {'kind':kind,'status':status,'only':only,'failed_tests':[{'id':i,'rerun_id':i.split(' ')[0],'kind':'FAILURE','traceback_tail':'x'}for i in ids],
                    'reason':None if status=='PASS'else'FAILED_TESTS'if ids else'NO_TEST_REPORT'}
        loop.store.event('CREATED',{'started_at':time.time()})
        with patch.object(Services,'matrix_run',side_effect=run):m=svc.regression_matrix()
        self.policy_loop=loop
        return m,calls,[e['payload']for e in LineageStore(self.state,lin['lineage_id']).events()if e['kind']=='REGRESSION_SIGNAL']
    def test_matrix_pass_runs_once(self):
        m,calls,signals=self.run_policy([('PASS',[])])
        self.assertEqual((m['status'],[c[0]for c in calls],m['first_failure_signal'],signals),('PASS',['FULL'],None,[]))
    def test_matrix_repeated_failure_rolls_back_on_the_failed_ids(self):
        m,calls,signals=self.run_policy([('FAIL',['test_ledger.T.a','test_core.T.b']),('FAIL',['test_ledger.T.a'])])
        self.assertEqual(m['status'],'FAIL');self.assertEqual(calls,[('FULL',None),('FAILED_ONLY_RERUN',['test_ledger.T.a','test_core.T.b'])])
        self.assertEqual(m['rollback_trigger_test_ids'],['test_ledger.T.a']);self.assertFalse(m['first_failure_signal']['transient'])
        self.assertEqual(signals[0]['first_failed_test_ids'],['test_ledger.T.a','test_core.T.b'])
    def test_matrix_transient_failure_needs_a_second_full_pass_and_is_recorded(self):
        m,calls,signals=self.run_policy([('FAIL',['test_ledger.T.a']),('PASS',[]),('PASS',[])])
        self.assertEqual(m['status'],'PASS');self.assertEqual([c[0]for c in calls],['FULL','FAILED_ONLY_RERUN','FULL_CONFIRMATION'])
        self.assertEqual(m['first_failure_signal']['first_failed_test_ids'],['test_ledger.T.a']);self.assertTrue(m['first_failure_signal']['transient'])
        self.assertEqual(len(signals),1)
    def test_matrix_failure_in_confirmation_rolls_back(self):
        m,calls,_=self.run_policy([('FAIL',['test_ledger.T.a']),('PASS',[]),('FAIL',['test_gates.T.c'])])
        self.assertEqual((m['status'],m['rollback_trigger_test_ids'],len(calls)),('FAIL',['test_gates.T.c'],3))
    def test_matrix_failure_without_test_ids_rolls_back_without_retry(self):
        m,calls,_=self.run_policy([('FAIL',[])])
        self.assertEqual((m['status'],len(calls)),('FAIL',1))
    def test_audit_replays_matrix_policy(self):
        from tools.audit_closed_loop import matrix_policy
        for attempts in ([('PASS',[])],[('FAIL',['a.B.c']),('FAIL',['a.B.c'])],[('FAIL',['a.B.c']),('PASS',[]),('PASS',[])],[('FAIL',['a.B.c']),('PASS',[]),('FAIL',['d.E.f'])],[('FAIL',[])]):
            with self.subTest(attempts=attempts):
                m,_,_=self.run_policy(attempts);store=self.policy_loop.store
                matrix_policy(m,'PASS'if m['status']=='PASS'else'FAIL',lambda r,kind=None:store.get(r))
        m,_,_=self.run_policy([('FAIL',['a.B.c']),('PASS',[]),('PASS',[])])
        forged=copy.deepcopy(m);forged['attempts']=forged['attempts'][:1];forged['attempts'][0]['status']='PASS'
        with self.assertRaises(ValueError):matrix_policy(forged,'PASS')
        hidden=copy.deepcopy(m);hidden['first_failure_signal']=None
        with self.assertRaises(ValueError):matrix_policy(hidden,'PASS')
    def test_regression_module_reports_failing_test_ids(self):
        from gaia.autonomy import regression
        with tempfile.TemporaryDirectory()as d:
            (Path(d)/'unit_matrix_probe.py').write_text('import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):pass\n    def test_bad(self):self.assertEqual(1,2)\n')
            report=Path(d)/'report.json'
            with patch('sys.path',[d]+__import__('sys').path),patch('sys.stdout'),patch('sys.stderr'):
                code=regression.main(['--only','unit_matrix_probe.T.test_ok','unit_matrix_probe.T.test_bad','--report',str(report)])
            value=json.loads(report.read_text())
        self.assertEqual(code,1);self.assertEqual([f['id']for f in value['failed']],['unit_matrix_probe.T.test_bad'])
        self.assertEqual((value['tests'],value['failures'],value['scope']),(2,1,'ONLY_GIVEN_TEST_IDS'));self.assertIn('AssertionError',value['failed'][0]['traceback'])
    def test_real_matrix_process_runs_only_given_ids_and_projects_private_paths(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);svc=Services(ROOT,self.state,loop.store,loop.contract,loop.configuration)
        run=svc.matrix_run('FAILED_ONLY_RERUN',['test_autonomy_integration.ContractTests.test_v1_default_is_unchanged'])
        self.assertEqual((run['status'],run['summary']['tests'],run['failed_tests']),('PASS',1,[]))
        # A real failing test in a clean process: IDs and tracebacks kept, the private root path replaced.
        with tempfile.TemporaryDirectory()as d:
            probe=Path(d);(probe/'gaia').symlink_to(ROOT/'gaia',target_is_directory=True)
            (probe/'unit_matrix_failure.py').write_text('import unittest\nclass T(unittest.TestCase):\n    def test_bad(self):\n        for v in (1,2):\n            with self.subTest(v=v):self.assertEqual(v,1)\n')
            svc.root=probe;failed=svc.matrix_run('FAILED_ONLY_RERUN',['unit_matrix_failure.T.test_bad'])
        self.assertEqual(failed['status'],'FAIL');self.assertEqual(failed['failed_tests'][0]['rerun_id'],'unit_matrix_failure.T.test_bad')
        self.assertIn('(v=2)',failed['failed_tests'][0]['id']);self.assertIn('<root>',failed['failed_tests'][0]['traceback_tail'])
        self.assertNotIn(d,json.dumps(failed))
    def test_resumed_verification_continues_the_same_matrix_sequence(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);svc=loop.services;loop.store.event('CREATED',{'started_at':time.time()});calls=[]
        script=[('FAIL',['a.B.c']),('PASS',[]),'CRASH',('PASS',[])]
        def run(kind,only=None):
            step=script[len(calls)];calls.append(kind)
            if step=='CRASH':raise SystemExit('death during the confirmation matrix')
            status,ids=step
            return {'kind':kind,'status':status,'only':only,'failed_tests':[{'id':i,'rerun_id':i,'kind':'FAILURE','traceback_tail':'x'}for i in ids],'reason':None if status=='PASS'else'FAILED_TESTS'}
        with patch.object(Services,'matrix_run',side_effect=run):
            with self.assertRaises(SystemExit):svc.regression_matrix()
            m=svc.regression_matrix()
        self.assertEqual(calls,['FULL','FAILED_ONLY_RERUN','FULL_CONFIRMATION','FULL_CONFIRMATION'])
        self.assertEqual(m['status'],'PASS');self.assertEqual(m['interrupted_attempts_rerun'],['FULL_CONFIRMATION'])
        self.assertEqual(m['first_failure_signal']['first_failed_test_ids'],['a.B.c'])
        self.assertEqual(sum(e['kind']=='REGRESSION_SIGNAL'for e in LineageStore(self.state,lin['lineage_id']).events()),1)
        from tools.audit_closed_loop import matrix_runs_accounted,matrix_policy
        events=loop.store.events();matrix_runs_accounted(events,m);matrix_policy(m,'PASS',lambda r,kind=None:loop.store.get(r))
        hidden=copy.deepcopy(m);hidden['interrupted_attempts_rerun']=[]
        with self.assertRaisesRegex(ValueError,'NOT_ACCOUNTED'):matrix_runs_accounted(events,hidden)
        first=next(i for i,e in enumerate(events)if e['state'].get('regression_first_failure'))
        rerun=next(i for i,e in enumerate(events)if(e['state'].get('matrix_progress')or{}).get('intent')=='FAILED_ONLY_RERUN')
        self.assertLess(first,rerun)
    def test_v1_campaign_keeps_the_single_matrix_run(self):
        c=create_campaign(self.root,self.state,campaign());svc=Services(self.root,self.state,CampaignStore(self.state,c['campaign_id']),c,CampaignStore(self.state,c['campaign_id']).read('configuration'))
        with patch.object(Services,'regression_matrix_v1',return_value={'status':'FAIL'})as v1,patch.object(Services,'matrix_run')as v2:
            self.assertEqual(svc.regression_matrix(),{'status':'FAIL'})
        v1.assert_called_once();v2.assert_not_called()
    def test_stale_reference_after_rollback_is_never_used_end_to_end(self):
        class Champion(FakeV2):
            version='v0000';costs={'v0000':0.86,'v0001':0.357};decisions=('accepted',);promote=True;verification='FAIL'
            def current_version(self):return Champion.version
            def champion_reference(self):return Champion.version,Champion.engine_ref
            def remeasure(self,check_drift):
                before=Champion.engine_ref;Champion.engine_ref=Champion.costs[Champion.version]
                return Champion.version,Champion.engine_ref,before,'MEASURED',None,len(self.records())
            def execute(self,m):
                value=super().execute(m)
                if value['after_version']=='v0001':Champion.version='v0001';Champion.engine_ref=0.357  # the Engine refreshes on promotion
                return {**value,'before_version':value['reference_used']['version']}
            def rollback(self,e,reason):Champion.version='v0000';return {'status':'COMPLETED','resulting_current':'v0000'}  # Engine ref left stale
        Champion.engine_ref=None
        lin=self.lineage();r=self.go(self.loop(lin['lineage_id'],factory=Champion,promotion=True))
        self.assertEqual(r['stopping_reason'],'POST_PROMOTION_REGRESSION_ROLLED_BACK')
        last=self.references(lin['lineage_id'])[-1];self.assertEqual((last['reason'],last['version'],last['cost_s']),('AFTER_ROLLBACK','v0000',0.86))
        Champion.decisions=('rejected',);Champion.engine_ref=0.357  # even if the Engine state were stale again
        loop=self.loop(lin['lineage_id'],factory=Champion);self.go(loop)
        for x in self.records(loop):self.assertEqual((x['screen_reference']['version'],x['screen_reference']['cost_s']),('v0000',0.86))


class InferenceSurfaceTests(Fixture):
    def setUp(self):
        super().setUp()
        self.contract=campaign('IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA','CONTROLLED_AUTONOMOUS',lineage_id='al'+'b'*24)
        d=diagnose(OBSERVATION,improvement_objective='IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA');self.p=prioritize([d]);self.s=plan_experiments(self.p,diagnoses=[d])
        self.targets={t['target_id']:t for t in self.p['candidate_targets']}
    def plan(self,cls):return next(p for p in self.s['candidate_plans']if p['class']==cls and p['target_ref']['target_class']=='INFERENCE_CONFIGURATION')
    def m(self,plan,**kw):return inference.materialize(self.contract,self.targets[plan['target_ref']['target_id']],plan,None,PRIMARY,{'threads':8,'max_context':4096},['CPU','VULKAN'],iteration=1,preview=True,**kw)
    def test_exploration_changes_one_knob_with_fixed_runtime_and_model(self):
        m=self.m(self.plan('EXPLORATION'));self.assertEqual(len(m['changes']),1);self.assertIn(m['changes'][0][0],inference.KNOBS)
        for key in ('runtime','runtime_hash','model_hash','model_family','quantization'):self.assertEqual(m['stack'][key],PRIMARY[key])
        self.assertNotEqual(m['candidate_hash'],PRIMARY['stack_id']);self.assertFalse(m['model_or_weight_change'])
    def test_control_benchmarks_current_primary(self):
        m=self.m(self.plan('CONTROL_EXPERIMENT'));self.assertEqual(m['stack'],PRIMARY);self.assertEqual(m['changes'],[])
    def test_parallelism_maps_to_threads(self):
        plan=finish_plan({**self.plan('EXPLORATION'),'class':'DISCRIMINATION','mode':'VERIFY','variables':['parallelism']})
        self.assertEqual(self.m(plan)['changes'][0][0],'threads')
    def test_seen_stacks_are_not_repeated(self):
        plan=self.plan('EXPLORATION');first=self.m(plan);second=self.m(plan,seen={first['candidate_hash']})
        self.assertNotEqual(first['candidate_hash'],second['candidate_hash'])
    def test_grid_stays_within_qualified_host_budget(self):
        limits={'threads':6,'max_context':1024};values=inference.grid(PRIMARY,limits,['VULKAN'])
        self.assertTrue(all(1<=t<=6 for t in values['threads']));self.assertTrue(all(256<=c<=1024 for c in values['context']))
        self.assertEqual(values['backend'],['VULKAN']);self.assertTrue(set(values['kv'])<={'f16','q8_0'})
        plan=self.plan('EXPLORATION')
        for i in range(1,30):
            m=inference.materialize(self.contract,self.targets[plan['target_ref']['target_id']],plan,None,PRIMARY,limits,['VULKAN'],iteration=i,preview=True)
            self.assertLessEqual(m['stack']['threads'],6);self.assertLessEqual(m['stack']['context'],1024);self.assertNotEqual(m['stack']['backend'],'CPU')
        with self.assertRaises(inference.NotMaterializable):
            inference.materialize(self.contract,self.targets[self.plan('CONTROL_EXPERIMENT')['target_ref']['target_id']],self.plan('CONTROL_EXPERIMENT'),None,PRIMARY,limits,['VULKAN'],iteration=1,preview=True)
    def test_cpu_backend_disables_offload(self):
        self.assertEqual(inference.candidate(PRIMARY,'backend','CPU')['gpu_layers'],0)
    def test_decision_guards_precede_latency(self):
        base={'quality':.9,'structured_output':1.,'reliability':1.,'tool_intent_accuracy':1.,'latency_stability':'STABLE','quality_task_mean_latency_s':1.}
        self.assertEqual(inference.decide(base,{**base,'quality_task_mean_latency_s':.8})[0],'accepted')
        self.assertEqual(inference.decide(base,{**base,'quality':.5,'quality_task_mean_latency_s':.5})[0],'rejected')
        self.assertEqual(inference.decide(base,{**base,'quality_task_mean_latency_s':.98})[0],'rejected')
        self.assertEqual(inference.decide(base,{**base,'latency_stability':'NOISY','quality_task_mean_latency_s':.5})[0],'deferred')
        self.assertEqual(inference.decide({**base,'latency_stability':'NOISY'},base)[0],'deferred')
        self.assertEqual(inference.decide(base,None)[0],'rejected')

    def test_inference_loop_runs_distinct_stack_experiments(self):
        class FakeInference(FakeV2):
            def diagnose(self,ob,iteration):return diagnose(ob,diagnosis_id=f'd{iteration:06d}',improvement_objective=self.contract['objective'])
            def materialize(self,target,plan,authorization,knowledge,iteration,preview=False,history=None):
                return inference.materialize(self.contract,target,plan,authorization,PRIMARY,{'threads':8,'max_context':4096},['CPU','VULKAN'],
                                             iteration=iteration,seen=self.seen(),preview=preview)
            def seen(self):return {r['proposed_change']['candidate_hash']for r in self.records()}
            def execute(self,m):
                n=len(self.records())
                dims={'quality':.9,'structured_output':1.,'reliability':1.,'tool_intent_accuracy':1.,'latency_stability':'STABLE','quality_task_mean_latency_s':1.}
                decision,reason=inference.decide(dims,{**dims,'quality_task_mean_latency_s':1.0})
                return {'engine_result':decision,'before_version':'li0','after_version':'li0','evidence':{'id':f'i{n+1:05d}','decision':decision,'reason':reason,
                    'candidate_hash':m['candidate_hash'],'control_dimensions':dims,'candidate_dimensions':dims,'search_cost_s':.01}}
            def learn(self,e):return {'outcome':{'accepted':'ACCEPTED','rejected':'REJECTED','deferred':'INCONCLUSIVE'}[e['evidence']['decision']]}
        objective='IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA';lin=self.lineage(objective)
        loop=self.loop(lin['lineage_id'],factory=FakeInference,objective=objective);r=self.go(loop)
        records=self.records(loop);self.assertGreaterEqual(len(records),3)
        hashes=[x['proposed_change']['candidate_hash']for x in records];self.assertEqual(len(hashes),len(set(hashes)))
        self.assertTrue(all(x['reversal']=='PREVIOUS_SELECTION_POINTER'for x in records))
        self.assertEqual(r['claim'],'BOUNDED_CLOSED_LOOP_LOCAL_INFERENCE_CONFIGURATION_NOT_MODEL_IMPROVEMENT')

    def promotion_fixture(self,candidate_latency=.5,allowed=True,crash_on_pointer=False):
        from gaia.local_intelligence.schema import artifact
        from gaia.local_intelligence.store import IntelligenceStore
        state=self.root/'li';store=IntelligenceStore(state);lineage_root=self.root/'lineage'
        primary=dict(PRIMARY);selection=store.put(artifact('SELECTION',{'primary':{'stack':primary},'coverage':None,'host_ref':{'id':'li'+'0'*24,'hash':'0'*64}}))
        m=self.m(self.plan('EXPLORATION'))
        base={'quality':.9,'structured_output':1.,'reliability':1.,'tool_intent_accuracy':1.,'latency_stability':'STABLE','quality_task_mean_latency_s':1.}
        def run_stack(stack,state,limits,screen=False):
            payload={'stack':stack,'status':'SCREEN_PASSED'if screen else'QUALIFIED','backend_verification':{'verified':True},'benchmark_hash':'b'*64}
            return artifact('SMOKE'if screen else'BENCHMARK',payload)
        def dims(value):return {**base,'quality_task_mean_latency_s':candidate_latency}if value['payload']['stack']['stack_id']==m['candidate_hash']else dict(base)
        def select(results,profile,coverage):
            best=min(results,key=lambda r:dims(r)['quality_task_mean_latency_s'])
            return artifact('SELECTION',{'primary':{'stack':best['payload']['stack']},'coverage':coverage,'host_ref':selection['payload']['host_ref']})
        original=store.set_pointer
        def pointer(*a,**k):
            if crash_on_pointer:raise SystemExit('simulated process death before pointer commit')
            return original(*a,**k)
        patches=[patch('gaia.local_intelligence.campaign.run_stack',side_effect=run_stack),patch('gaia.local_intelligence.selection.dimensions',side_effect=dims),
                 patch('gaia.local_intelligence.selection.select',side_effect=select),patch('gaia.autonomy.inference_surface.store',return_value=store)]
        for x in patches:x.start();self.addCleanup(x.stop)
        store.set_pointer=pointer
        run=lambda:inference.execute(state,lineage_root,m,selection,{'payload':{}},{},'i00001',lambda e:allowed)
        return store,selection,m,run,lineage_root,state
    def test_inference_promotion_moves_pointer_and_rollback_restores(self):
        store,selection,m,run,lineage_root,state=self.promotion_fixture()
        evaluation=run();self.assertEqual(evaluation['evidence']['decision'],'accepted');self.assertNotEqual(evaluation['after_version'],selection['id'])
        self.assertEqual(store.read('current','SELECTION')['payload']['primary']['stack']['stack_id'],m['candidate_hash'])
        self.assertEqual(inference.recover(state,lineage_root,'i00001',selection['id'])['after_version'],evaluation['after_version'])
        inference.rollback(state,selection['id'],'unit regression');self.assertEqual(store.read('current','SELECTION')['id'],selection['id'])
    def test_inference_policy_denial_keeps_pointer(self):
        store,selection,m,run,_,_=self.promotion_fixture(allowed=False)
        evaluation=run();self.assertEqual(evaluation['evidence']['decision'],'accepted');self.assertEqual(evaluation['after_version'],selection['id']);self.assertIsNone(store.pointer())
    def test_inference_rejection_never_promotes(self):
        store,selection,m,run,_,_=self.promotion_fixture(candidate_latency=1.0)
        self.assertEqual(run()['evidence']['decision'],'rejected');self.assertIsNone(store.pointer())
    def test_crash_before_pointer_commit_recovers_without_promotion_or_rerun(self):
        store,selection,m,run,lineage_root,state=self.promotion_fixture(crash_on_pointer=True)
        with self.assertRaises(SystemExit):run()
        recovered=inference.recover(state,lineage_root,'i00001',selection['id'])
        self.assertEqual(recovered['engine_result'],'RECOVERED_COMMITTED_EVIDENCE');self.assertEqual(recovered['after_version'],selection['id'])
        self.assertIsNone(inference.recover(state,lineage_root,'i00002',selection['id']))

    def test_inference_recovery_never_claims_another_lineages_promotion(self):
        store,selection,m,run,lineage_root,state=self.promotion_fixture()
        evaluation=run();self.assertNotEqual(evaluation['after_version'],selection['id'])
        other=inference.recover(state,lineage_root,'i00001',selection['id'],'al'+'9'*24,m['candidate_hash'])
        self.assertEqual(other['after_version'],selection['id'])
        with self.assertRaises(ValueError):inference.recover(state,lineage_root,'i00001',selection['id'],None,'stack-other')

    def test_selection_pointer_is_transactional_and_reversible(self):
        from gaia.local_intelligence.schema import artifact
        from gaia.local_intelligence.store import IntelligenceStore
        store=IntelligenceStore(self.root/'li');a=store.put(artifact('SELECTION',{'n':1}));time.sleep(.002);b=store.put(artifact('SELECTION',{'n':2}))
        self.assertEqual(store.read('latest','SELECTION')['id'],b['id'])
        store.set_pointer(a,reason='CLOSED_LOOP_ROLLBACK',receipt={'unit':True});self.assertEqual(store.read('latest','SELECTION')['id'],a['id'])
        store.set_pointer(b,reason='CLOSED_LOOP_PROMOTION',receipt={'experiment_id':'i00001'});self.assertEqual(store.read('current','SELECTION')['id'],b['id'])
        self.assertEqual(len(store.pointer_entries()),2)
        path=sorted((store.directory/'selection-pointer').glob('*.json'))[0];v=json.loads(path.read_bytes());v['reason']='X';path.chmod(0o644);path.write_text(json.dumps(v))
        with self.assertRaises(ValueError):store.read('current','SELECTION')


if __name__=='__main__':unittest.main()
