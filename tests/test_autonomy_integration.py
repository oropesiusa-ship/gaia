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
    decisions=('rejected',);select_index=0;review_status='OK';promote=False;verification='PASS'
    def initialized(self):return False
    def initialize(self):return {'status':'UNIT_FIXTURE_NOT_REAL_CERTIFICATION'}
    def observe(self,full=False):return copy.deepcopy(OBSERVATION)
    def diagnose(self,ob,iteration):return diagnose(ob,diagnosis_id=f'd{iteration:06d}',improvement_objective=self.contract['objective'])
    def views_path(self):return self.local/'unit-views.json'
    def knowledge(self):
        views=json.loads(self.views_path().read_bytes())if self.views_path().exists()else[]
        return {'views':views,'context':None,'runs':[],'records':[]}
    def compare(self,target,candidates,hypothesis,previous,research):
        chosen=candidates[min(self.select_index,len(candidates)-1)]['plan_id']
        return {'schema':'gaia_experiment_review_v2','status':self.review_status,'authority':'NONE','selected_plan_id':chosen,
                'default_plan_id':candidates[0]['plan_id'],'method':'COGNITIVE_COMPARE_SINGLE_CITED_CANDIDATE','cited_candidates':[chosen],
                'previous':previous,'scope':'UNIT_BACKEND_FIXTURE'}
    def expected_id(self):return f"e{len(self.records())+1:05d}"
    def current_version(self):return 'v0000'
    def execute(self,m):
        n=len(self.records());decision=self.decisions[n%len(self.decisions)]
        after='v0001'if self.promote and decision=='accepted'else'v0000'
        return {'engine_result':decision,'before_version':'v0000','after_version':after,'evidence':{'id':f'e{n+1:05d}','decision':decision,
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
    def test_cognitive_selection_stays_within_previewed_candidates(self):
        class Second(FakeV2):select_index=1
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Second);self.go(loop)
        selections=[loop.store.get(e['state']['selection_ref'])for e in loop.store.events()if'selection_ref'in e['state']]
        candidates=[loop.store.get(e['state']['candidates_ref'])for e in loop.store.events()if'candidates_ref'in e['state']]
        self.assertTrue(all(s['selected_plan_id']in{c['plan']['plan_id']for x in candidates for c in x['candidates']}for s in selections))
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
        self.assertTrue(state['blocked']);self.assertEqual(state['block']['reason'],'UNLEARNED_EXECUTED_EXPERIMENT')
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
