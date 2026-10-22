"""Adapters to 0.1–0.9. No second evaluator, planner or learning engine."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time
from .. import config,genome as G,engine,provenance,manifest
from ..observation.collector import collect
from ..observation.store import ObservationStore
from ..diagnosis.engine import diagnose
from ..prioritization.engine import prioritize
from ..learning.store import LearningStore
from ..learning.query import query
from ..learning.ingestion import curate_archive
from ..experiment_strategy.engine import plan_experiments
from ..cognition.orchestrator import CognitiveOrchestrator
from ..cognition.store import CognitiveStore
from ..cognition.schema import task as cognitive_task
from ..cognition.evidence import import_evidence
from .schema import artifact
from .store import durable
from .policy import budget_check,BudgetExceeded,disk_bytes,disk_used


class BoundedEngine(engine.Engine):
    """Only restrict existing trial caps; all execution still goes through Engine/evaluator."""
    def trial(self,src,seed,task='main',cap=None,**kwargs):
        if hasattr(self,'campaign_budget'):
            contract,store,state,engine_path=self.campaign_budget
            current=store.current();budget_check(contract,current,state,engine_path)
            remaining=min(contract['maximum_wall_time'],contract['maximum_compute_budget'])-(time.time()-current['started_at'])
            cap=min(cap or self.lim['max_experiment_seconds'],contract['maximum_trial_seconds'],remaining)
            if cap<=0:raise BudgetExceeded('STOPPED_BUDGET')
            if store.read('control')['request']!='RUN':raise InterruptedError('OPERATOR_CONTROL_AT_TRIAL_BOUNDARY')
        return super().trial(src,seed,task,cap,**kwargs)


class Services:
    def __init__(self,root,state,store,contract,configuration):
        self.root=Path(root);self.state=Path(state);self.store=store;self.contract=contract;self.configuration=configuration
        self.v2=contract.get('schema')=='gaia_closed_loop_campaign_v2';self.lineage=None
        if self.v2 and contract['lineage_id']:
            from .lineage import LineageStore
            self.lineage=LineageStore(state,contract['lineage_id'])
        # A lineage shares learning, observation baseline, strategy outcomes and cognition across its campaigns.
        self.local=self.lineage.subsystems if self.lineage else self.store.root/'subsystems';self.eng=None
        self.gaia_version='gaia-v1.0.1'if self.v2 else'gaia-v1.0'
        self.surface=contract.get('surface','numpy_mlp')

    def engine(self):
        if self.eng is None:
            self.eng=BoundedEngine(self.root,copy.deepcopy(self.configuration['engine_config']),log=lambda *_:None,promotion_authorizer=self.promotion_allowed)
            self.eng.campaign_budget=(self.contract,self.store,self.state,self.eng.store.dir)
        return self.eng

    def remaining(self,current=None):
        current=current or self.store.current()
        return min(self.contract['maximum_wall_time'],self.contract['maximum_compute_budget'])-(time.time()-current['started_at'])

    def promotion_allowed(self,eng,record,out):
        current=self.store.current();m=self.store.get(current['materialized_ref']);a=self.store.get(current['authorization_ref'])
        from .policy import identities
        try:budget_check(self.contract,current,self.state,eng.store.dir);budget_ok=True
        except BudgetExceeded:budget_ok=False
        if identities(self.root)!=self.configuration['source_identity']:raise ValueError('PROTECTED_OR_SOURCE_CHANGED')
        remaining=self.remaining(current)
        p=self.contract['promotion_policy'];allowed=budget_ok and p['enabled']and m['class']in p['allowed_classes']and out['decision']=='accepted'and out['promotable']and a['status']=='AUTHORIZED'and remaining>=1600
        if allowed:
            # The legacy Engine couples acceptance/publication in one call.
            # Perform and durably retain 0.5 interpretation before granting its
            # publication callback. Canonical LearningStore ingestion follows
            # afterward, when publication metadata can no longer change.
            from ..learning.engine import learn
            source=curate_archive(eng.store.dir,archive_aggregate=hashlib.sha256(eng.store.ledger.read_bytes()).hexdigest(),
                gaia_version=self.gaia_version,experiment_ids=[record['id']])
            interpreted=learn([source])
            if not interpreted['records']or any(r['claim']['outcome']!='ACCEPTED'for r in interpreted['records']):allowed=False
            self.store.event(current['phase'],{'pre_promotion_learning_ref':self.store.put('PRE_PUBLICATION_LEARNING',
                {'source':source,'run':interpreted,'operational_knowledge_adopted':False,
                 'scope':'DURABLE_0_5_INTERPRETATION_BEFORE_PUBLICATION_NOT_FINAL_PUBLICATION_METADATA'})})
        self.store.event(current['phase'],{'promotion_decision_ref':self.store.put('PROMOTION_AUTHORIZATION',{'allowed':bool(allowed),
            'experiment_id':record['id'],'evaluation_hash':out['evidence_hash'],'campaign_hash':self.contract['hash'],'class':m['class'],
            'verification_reserve_required_s':1600,'remaining_budget_s':remaining,
            'reason':'EXISTING_PUBLICATION_GATES_STILL_REQUIRED'if allowed else'CAMPAIGN_POLICY_OR_VERIFICATION_RESERVE_DENIES_PROMOTION'})})
        return bool(allowed)

    def initialize(self):
        if self.surface=='local_inference':
            from . import inference_surface as inference
            selection,profile,limits=inference.current(self.intelligence_state())
            return {'current_version':selection['id'],'selection_hash':selection['hash'],'host_profile_hash':profile['hash'],'limits':limits}
        eng=self.engine()
        if not(eng.store.dir/'benchmark.json').exists():eng.init(initialize_mvp=True)
        eng._load()
        return {'current_version':eng.store.current_version(),'baseline_manifest_hash':eng.store.load_state()['baseline_manifest_hash'],
            'benchmark_hash':manifest.file_hash(eng.store.dir/'benchmark.json'),'source_snapshot':eng.store.load_state()['source_snapshot']}

    def initialized(self):
        if self.surface=='local_inference':return True
        return (self.engine().store.dir/'benchmark.json').exists()

    def intelligence_state(self):return self.root/self.configuration['intelligence_state']

    # ------------------------------------------------------------------ observation and diagnosis
    def observe(self,full=False):
        # Full observations measure the protected numpy workload; they anchor the lineage baseline.
        quick=not(self.v2 and full and self.surface=='numpy_mlp')
        return ObservationStore(self.local).save(collect(self.root,self.local,self.configuration['engine_config'],quick=quick))

    def baseline_observation(self,current):
        if not self.v2:return None
        store=ObservationStore(self.local);pointer=self.lineage.state()['baseline']if self.lineage else self.store.current().get('observation_baseline')
        if pointer is None:
            if current['sections']['context']['mode']!='full':return None
            reference={'observation_id':current['observation_id'],'observation_hash':current['observation_hash']}
            if self.lineage:self.lineage.event('BASELINE_OBSERVATION',{**reference,'campaign_id':self.contract['campaign_id'],'reason':'FIRST_FULL_OBSERVATION'})
            return None
        if pointer['observation_id']==current['observation_id']:return None
        value=store.read(pointer['observation_id'])
        if value['observation_hash']!=pointer['observation_hash']:raise ValueError('Observation baseline hash mismatch')
        return value

    def renew_baseline(self,observation,reason):
        if self.lineage and observation['sections']['context']['mode']=='full':
            self.lineage.event('BASELINE_OBSERVATION',{'observation_id':observation['observation_id'],'observation_hash':observation['observation_hash'],
                'campaign_id':self.contract['campaign_id'],'reason':reason})

    def diagnose(self,ob,iteration):
        self.coverage=[]
        if not self.v2 or self.contract['objective']=='VERIFY_NUMPY_MLP_EXISTING_CRITERIA':
            ctx=self.experimental_context();learning=LearningStore(self.local)
            if ctx and learning.batches():
                for view in query(learning,workload='numpy_mlp',context=ctx,include_stale=True):
                    k=view['item']
                    if view['applicability_assessment']['transferability']=='EXACT_CONTEXT'and view['effective_status']not in ('CONTRADICTED','SUPERSEDED')and any(e['confirmation']and e['confirmation']['pairs']>=3 for e in k['supporting_evidence']):
                        self.coverage.append({'learning_id':k['learning_id'],'hash':k['hash'],'reason':'EXISTING_PAIRED_VERIFICATION_SATISFIES_REQUESTED_EVIDENCE_GAP_NOT_AN_IMPROVEMENT_CLAIM'})
            if not self.v2:return diagnose(ob,diagnosis_id=f'd{iteration:06d}',verification_objective=None if self.coverage else self.contract['objective'])
        baseline=self.baseline_observation(ob)
        objective=self.contract['objective']
        return diagnose(ob,baseline,self.configuration['engine_config'],diagnosis_id=f'd{iteration:06d}',
            verification_objective=objective if objective.startswith('VERIFY')and not self.coverage else None,
            improvement_objective=objective if objective.startswith('IMPROVE')else None)

    def prioritize(self,d,iteration):
        if not self.v2:return prioritize([d],prioritization_id=f'p{iteration:06d}')
        return prioritize([d],self.configuration['engine_config'],prioritization_id=f'p{iteration:06d}')

    # ------------------------------------------------------------------ knowledge and strategy
    def experimental_context(self):
        if self.surface=='local_inference':return None
        eng=self.engine()
        if not(eng.store.dir/'benchmark.json').exists():return None
        baseline=json.loads((eng.store.stable/'v0000/manifest.json').read_bytes());bench=json.loads((eng.store.dir/'benchmark.json').read_bytes())
        return {**{k:baseline[k]for k in ('environment_hash','host_hash','runtime_hash','source_hash')},
            'benchmark_hash':manifest.file_hash(eng.store.dir/'benchmark.json'),'workload':'numpy_mlp','trainer_family':'numpy_mlp',
            'quality_threshold':bench['calibrated']['main']['target'],'gaia_version':self.gaia_version,'baseline_version':eng.store.current_version()}

    def knowledge(self):
        if self.surface=='local_inference':
            return {'views':[],'context':None,'runs':[],'records':[],'scope':'0_5_LEARNING_SCHEMA_IS_NUMPY_SPECIFIC_INFERENCE_USES_LINEAGE_RECORDS'}
        s=LearningStore(self.local);ctx=self.experimental_context()
        views=query(s,workload='numpy_mlp',context=ctx,include_stale=True)if s.batches()else[]
        return {'views':views,'context':ctx,'runs':[b['run']for b in s.batches()],
            'records':s.items('records')+s.items('knowledge'),'scope':'EXPERIMENT_MANIFEST_CONTEXT_NOT_OBSERVATION_ENVIRONMENT_IDENTITY'}

    def strategy(self,priority,knowledge,diagnosis,iteration):
        # Do not falsely equate observation and execution-manifest environment hashes.
        # 0.6 unbound knowledge is not exploitable; exact-context duplicate policy
        # is separately checked against the real experiment manifest below.
        if not self.v2:return plan_experiments(priority,knowledge['runs'],diagnoses=[diagnosis],strategy_id=f's{iteration:06d}')
        ctx=knowledge['context']
        return plan_experiments(priority,knowledge['runs'],context=ctx,context_scope='EXECUTION_MANIFEST'if ctx else'OBSERVATION_ENVIRONMENT',
            diagnoses=[diagnosis],strategy_id=f's{iteration:06d}',outcomes=self.strategy_outcomes())

    # ------------------------------------------------------------------ lineage records
    def records(self):
        if self.lineage:
            result=[]
            for ev in self.lineage.events():
                if ev['kind']=='EXPERIMENT_RECORDED':
                    path=self.lineage.root/'records'/(ev['payload']['record_ref']['hash']+'.json')
                    value=json.loads(path.read_bytes())
                    if provenance.digest({k:v for k,v in value.items()if k!='record_hash'})!=value['record_hash']:raise ValueError('EXPERIMENT_RECORD_CORRUPTED')
                    result.append(value)
            return result
        return [self.store.get(ev['state']['record_ref'])for i,ev in enumerate(self.store.events())if'record_ref'in ev['state']
                and ev['state']['record_ref']not in[e['state'].get('record_ref')for e in self.store.events()[:i]]]

    def save_record(self,record):
        if self.lineage:
            durable(self.lineage.root/'records'/(record['record_hash']+'.json'),record,True)
            # Re-entering LEARNING after a crash must not index the same record twice.
            if any(ev['kind']=='EXPERIMENT_RECORDED'and ev['payload']['record_ref']['hash']==record['record_hash']for ev in self.lineage.events()):return
            self.lineage.event('EXPERIMENT_RECORDED',{'record_ref':{'experiment_id':record['experiment_id'],'hash':record['record_hash']},
                'campaign_id':self.contract['campaign_id'],'class':record['proposed_change']['class'],'candidate_hash':record['proposed_change']['candidate_hash'],
                'classification':record['result']['classification']})

    def strategy_outcomes(self):
        """Executed plans linked to their outcome, hypothesis assessment and cost (0.6 LINKED input)."""
        return [{'experiment_id':r['experiment_id'],'class':r['proposed_change']['class'],'target_class':r['problem']['target_class'],
                 'outcome':r['result']['classification'],'hypothesis_assessment':r['result']['hypothesis_assessment'],
                 'cost_s':r['primary_metrics'].get('cost_s')} for r in self.records()]

    def seen(self):
        values={r['proposed_change']['candidate_hash']for r in self.records()}
        if self.surface=='numpy_mlp'and self.initialized():
            eng=self.engine();eng._load();values|=set(eng.hist.seen)
        return values

    def controls_done(self):
        return {r['reference_state']['baseline_hash']for r in self.records()if r['proposed_change']['class']in ('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT')}

    def repeats(self):
        counts={}
        for r in self.records():counts[r['proposed_change']['candidate_hash']]=counts.get(r['proposed_change']['candidate_hash'],0)+1
        return counts

    # ------------------------------------------------------------------ materialization
    def materialize(self,target,plan,authorization,knowledge,iteration,preview=False,history=None):
        from .materializer import materialize_v2
        if self.surface=='local_inference':
            from . import inference_surface as inference
            selection,profile,limits=inference.current(self.intelligence_state())
            primary=selection['payload']['primary']['stack']
            return inference.materialize(self.contract,target,plan,authorization,primary,limits,inference.qualified_backends(self.intelligence_state(),primary),
                iteration=iteration,seen=self.seen(),preview=preview)
        if self.contract['mode']=='CONTROLLED_AUTONOMOUS'and(self.initialized()if history is None else history):
            eng=self.engine();eng._load();base=eng.store.load_version()[0];hist=eng.hist;strategy=eng.state['strategy']
        else:base,hist,strategy=G.new_genome(),None,None
        return materialize_v2(self.contract,target,plan,authorization,base,knowledge['records'],iteration=iteration,
            seen=self.seen(),hist=hist,strategy=strategy,preview=preview)

    # ------------------------------------------------------------------ cognition
    def backend_factory(self):
        def factory():
            from ..local_intelligence.primary import PrimaryLocalIntelligenceBackend
            engine_path=self.root/self.configuration['engine_config']['workload']['state_dir']
            current=self.store.current()
            remaining=self.contract['maximum_disk_budget']-(disk_used(self.contract,current,self.state,engine_path)if self.v2 else disk_bytes(self.state)+disk_bytes(engine_path))
            if remaining<=0:raise BudgetExceeded('STOPPED_BUDGET')
            backend=PrimaryLocalIntelligenceBackend(self.intelligence_state(),'current'if self.v2 else'latest')
            # 0.8's worker supervises /work + private /tmp at one quarter of this
            # budget. Restrict it to remaining campaign bytes, never enlarge it.
            backend.adapter.budget['disk_budget_bytes']=min(backend.adapter.budget['disk_budget_bytes'],remaining*4)
            return backend
        return factory

    def review(self,target,plan,strategy_ref):
        packet=artifact('EXPERIMENT_REVIEW_INPUT',{'target':target['target_class'],'experiment_class':plan['class'],'mode':plan['mode'],
            'expected_information':plan['discriminates'],'risks':plan['estimates']['risk'],'missing_evidence':['CAUSALITY_NOT_ESTABLISHED'],
            'strategy_ref':strategy_ref,'plan_hash':plan['plan_hash']})
        store=CognitiveStore(self.local);reference=import_evidence(store,packet,'selected bounded experimental plan evidence risk uncertainty')
        task=cognitive_task('Review the selected experiment class, mode and risk from the evidence. This is not execution authority.','ANALYZE',[reference])
        task['evidence_requirements']['required_fields']=['payload.experiment_class','payload.mode','payload.risks']
        task.pop('task_id');task.pop('hash');task['task_id']='ct'+provenance.digest(task)[:24];task['hash']=provenance.digest(task)
        run=CognitiveOrchestrator(self.local,backend_factory=self.backend_factory()).run(task)
        result=run['result']['payload']
        return {'schema':'gaia_experiment_review_v1','target':target['target_id'],'evidence_summary':result['claims'],
            'why_this_plan':plan['rationale'],'expected_information':plan['discriminates'],'known_risks':plan['estimates'],
            'missing_evidence':result['uncertainty']['missing_evidence'],'uncertainty':result['uncertainty'],
            'status':result['status'],'authority':'NONE','cognitive_result':run['result'],'cognitive_trace':run['trace'],'input':packet}

    def compare(self,target,candidates,hypothesis,previous,research):
        """One bounded cognitive call: compare eligible plans, review risk and explain the previous outcome.

        The model can only cite facts; a choice is the single candidate plan_id it cites. Authority stays NONE."""
        current=self.store.current()
        budget_check(self.contract,current,self.state,self.root/self.configuration['engine_config']['workload']['state_dir'])
        packet=artifact('PLAN_COMPARISON_INPUT',{'target':target['target_class'],'candidates':candidates,'previous_outcome':previous,
            'missing_evidence':hypothesis['missing_evidence']if hypothesis else[],'risks':sorted({c['risk']for c in candidates}),
            'research_status':(research or{}).get('status')})
        store=CognitiveStore(self.local);reference=import_evidence(store,packet,'candidate experiment plans comparison previous outcome risk')
        task=cognitive_task('Compare the candidate experiment plans using the evidence. Cite the plan_id fact of the single most informative next plan, '
                            'its risk and any previous outcome facts. This is not execution authority.','COMPARE',[reference])
        task['evidence_requirements']['required_fields']=['payload.candidates']
        task.pop('task_id');task.pop('hash');task['task_id']='ct'+provenance.digest(task)[:24];task['hash']=provenance.digest(task)
        run=CognitiveOrchestrator(self.local,backend_factory=self.backend_factory()).run(task)
        result=run['result']['payload']
        if result['status']=='FAILED':
            # A budget exhausted inside cognition is a budget stop, not a cognitive rejection.
            budget_check(self.contract,self.store.current(),self.state,self.root/self.configuration['engine_config']['workload']['state_dir'])
        ids={c['plan_id']for c in candidates}
        cited=sorted({c['claim']['value']for c in result['claims']if re.fullmatch(r'payload\.candidates\.\d+\.plan_id',c['claim']['field'])and c['claim']['value']in ids})
        default=candidates[0]['plan_id']
        selected,method=(cited[0],'COGNITIVE_COMPARE_SINGLE_CITED_CANDIDATE')if len(cited)==1 else(default,'DETERMINISTIC_FIRST_RANKED_'+('NO_CITED_CANDIDATE'if not cited else'MULTIPLE_CITED_CANDIDATES'))
        analysis=[c for c in result['claims']if c['claim']['field'].startswith('payload.previous_outcome')]
        return {'schema':'gaia_experiment_review_v2','target':target['target_id'],'evidence_summary':result['claims'],
            'selected_plan_id':selected,'default_plan_id':default,'method':method,'cited_candidates':cited,
            'failure_analysis':{'facts':analysis,'authority':'NONE','scope':'CITED_PREVIOUS_OUTCOME_FACTS_NOT_CAUSAL_EXPLANATION'}if previous else None,
            'missing_evidence':result['uncertainty']['missing_evidence'],'uncertainty':result['uncertainty'],
            'status':result['status'],'authority':'NONE','cognitive_result':run['result'],'cognitive_trace':run['trace'],'input':packet}

    # ------------------------------------------------------------------ execution
    def expected_id(self):
        if self.surface=='local_inference':
            from .inference_surface import experiments_dir
            return f"i{len(list(experiments_dir(self.lineage.root).glob('i*.json')))+1:05d}"
        return f"e{self.engine().store.load_state()['n_experiments']+1:05d}"

    def current_version(self):
        if self.surface=='local_inference':
            from . import inference_surface as inference
            return inference.current(self.intelligence_state())[0]['id']
        return self.engine().store.current_version()

    def execute(self,m):
        if self.surface=='local_inference':
            from . import inference_surface as inference
            selection,profile,limits=inference.current(self.intelligence_state())
            current=self.store.current();identifier=current['expected_experiment_id']
            def allowed(evidence):
                p=self.contract['promotion_policy'];a=self.store.get(current['authorization_ref'])
                try:budget_check(self.contract,self.store.current(),self.state);ok=True
                except BudgetExceeded:ok=False
                decision=ok and p['enabled']and m['class']in p['allowed_classes']and a['status']=='AUTHORIZED'and self.remaining()>=1200
                self.store.event(self.store.current()['phase'],{'promotion_decision_ref':self.store.put('PROMOTION_AUTHORIZATION',{'allowed':bool(decision),
                    'experiment_id':identifier,'class':m['class'],'verification_reserve_required_s':1200,'remaining_budget_s':self.remaining(),
                    'reason':'TRANSACTIONAL_SELECTION_POINTER_AFTER_EXISTING_0_8_GUARDS'if decision else'CAMPAIGN_POLICY_OR_VERIFICATION_RESERVE_DENIES_PROMOTION'})})
                return bool(decision)
            return inference.execute(self.intelligence_state(),self.lineage.root,m,selection,profile,limits,identifier,allowed,self.lineage.identifier)
        eng=self.engine();eng._load()
        parent=eng.store.load_version()[0];before=eng.store.current_version()
        # The champion's measured reference cost lets v0.1 operator statistics learn real rewards.
        parent_cost=(eng.state.get('ref')or{}).get('cost')if self.v2 else None
        result=eng.experiment(proposal=(m['genome'],m['ops'],G.genome_hash(parent),parent_cost))
        records=[r for r in eng.store.records()if r['type']=='end'];out=records[-1]
        out=json.loads((eng.store.dir/out['evidence_path']).read_bytes())
        return {'engine_result':result,'evidence':out,'before_version':before,'after_version':eng.store.current_version()}

    def recover_inference(self,current):
        from . import inference_surface as inference
        return inference.recover(self.intelligence_state(),self.lineage.root,current['expected_experiment_id'],current['before_version'],
                                 self.lineage.identifier,self.store.get(current['materialized_ref'])['candidate_hash'])

    def learn(self,evaluation):
        if self.surface=='local_inference':
            outcome={'accepted':'ACCEPTED','rejected':'REJECTED','deferred':'INCONCLUSIVE'}[evaluation['evidence']['decision']]
            return {'outcome':outcome,'scope':'LINEAGE_INFERENCE_EXPERIMENT_RECORDS_NOT_0_5_NUMPY_SCHEMA','evidence_id':evaluation['evidence']['id']}
        eng=self.engine();eid=evaluation['evidence']['id']
        sha=hashlib.sha256(eng.store.ledger.read_bytes()).hexdigest()
        source=curate_archive(eng.store.dir,archive_aggregate=sha,gaia_version=self.gaia_version,experiment_ids=[eid])
        batch=LearningStore(self.local).ingest([source])
        return {'source':source,'batch':batch,'outcome':source['experiments'][0]['outcome']}

    def verify(self,evaluation,pre):
        if self.surface=='local_inference':
            from . import inference_surface as inference
            checked=inference.verify(self.root,self.intelligence_state(),self.local)
            matrix=self.regression_matrix()
            return {**checked,'status':'PASS'if checked['status']=='PASS'and matrix['status']=='PASS'else'FAIL','regression_matrix':matrix}
        from .. import readiness,ledger
        from ..observation.compare import compare
        eng=self.engine();eng._load();ob=self.observe(full=True);checks=readiness.run_gates(eng)
        current=eng.store.current_version();loaded_g,src=eng.store.load_version()
        ref=eng.refresh_ref(src,check_drift=False)
        old=evaluation['evidence'].get('confirm')or{};costs=[c for c in old.get('champ_costs',[])if isinstance(c,(int,float))]
        import statistics
        improvement=bool(costs)and ref<statistics.median(costs)*(1-eng.acc['min_gain'])
        matrix=self.regression_matrix()
        status='PASS'if checks['status']=='READY_FOR_CAMPAIGN'and improvement and matrix['status']=='PASS'else'FAIL'
        if self.v2 and status=='PASS':self.renew_baseline(ob,'VERIFIED_PROMOTION')
        return {'status':status,
            'post_observation':ob,'comparison':compare(pre,ob),'gates':checks,'persisted_improvement':improvement,'current_version':current,
            'ledger_ok':ledger.verify_ledger(eng.store)['ok'],'regression_matrix':matrix}

    def regression_matrix(self):
        # Fixed test IDs only, executed in a separate local controller process.
        import subprocess,sys
        modules=['critical_v0_1','relevant_0_2_to_1_0']
        result=subprocess.run([sys.executable,'-B','-W','error::ResourceWarning','-m','gaia.autonomy.regression'],
            cwd=self.root,capture_output=True,text=True,timeout=900,
            env={**os.environ,'PYTHONPATH':str(self.root),'PYTHONDONTWRITEBYTECODE':'1'})
        return {'status':'PASS'if result.returncode==0 else'FAIL','modules':modules,'returncode':result.returncode,
                'stdout_sha256':hashlib.sha256(result.stdout.encode()).hexdigest(),'stderr_sha256':hashlib.sha256(result.stderr.encode()).hexdigest()}

    def rollback(self,evaluation,reason):
        if self.surface=='local_inference':
            from . import inference_surface as inference
            return inference.rollback(self.intelligence_state(),evaluation['before_version'],reason)
        return self.engine().rollback(evaluation['before_version'],reason)

    # ------------------------------------------------------------------ lineage maintenance (Level D, follow-up)
    def meta_tune(self):
        """Existing v0.1 paired strategy adoption, restricted to the contracted hyperparameter surface."""
        from .. import meta
        from .materializer import HP_OPS,hp_random_genome
        eng=self.engine();eng._load();champion=eng.store.load_version()[0]
        before=dict(eng.state['strategy'])
        summary=meta.tune(eng,rounds=1,seeds=[100,101,102,103],budget=8,surface=(HP_OPS,hp_random_genome(champion)))
        eng._load()
        return {'before':before,'after':dict(eng.state['strategy']),'adopted':eng.state['strategy']!=before,'summary':summary,
                'surface_operators':HP_OPS,'scope':'V0_1_PAIRED_LANDSCAPE_COMPARISON_HP_SURFACE_ONLY'}

    def health_check(self):
        """Follow-up of a previously promoted lineage version before admitting more experiments."""
        if self.surface=='local_inference':
            from . import inference_surface as inference
            selection=inference.current(self.intelligence_state())[0]
            try:
                from ..local_intelligence.controller import selected_backend
                selected_backend(self.intelligence_state(),'current');return {'status':'PASS','version':selection['id'],'checks':'0_8_SELECTION_GUARDS'}
            except ValueError as exc:
                previous=[e['receipt']['previous_selection']['id']for e in inference.store(self.intelligence_state()).pointer_entries()
                          if e['reason']=='CLOSED_LOOP_PROMOTION'and e['selection_ref']['id']==selection['id']]
                return {'status':'FAIL','version':selection['id'],'reason':str(exc)[:100],'rollback_to':previous[-1]if previous else None}
        from .. import readiness
        eng=self.engine()
        if not(eng.store.dir/'benchmark.json').exists():return {'status':'NOT_APPLICABLE','reason':'LINEAGE_ENGINE_NOT_INITIALIZED'}
        eng._load();version=eng.store.current_version()
        if version=='v0000':return {'status':'NOT_APPLICABLE','reason':'NO_PROMOTED_VERSION_TO_FOLLOW_UP','version':version}
        checks=readiness.run_gates(eng)
        # The known-good predecessor is the version the lineage promoted from.
        previous=[r['system_version']['version_before']for r in self.records()if r['system_version']['version_after']==version and r['system_version']['version_before']!=version]
        return {'status':'PASS'if checks['status']=='READY_FOR_CAMPAIGN'else'FAIL','version':version,'gates':checks,'rollback_to':previous[-1]if previous else None}
