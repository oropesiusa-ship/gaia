"""Adapters to 0.1–0.9. No second evaluator, planner or learning engine."""
import copy
import hashlib
import json
import os
from pathlib import Path
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
from .policy import budget_check,BudgetExceeded,disk_bytes


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
        self.local=self.store.root/'subsystems';self.eng=None

    def engine(self):
        if self.eng is None:
            self.eng=BoundedEngine(self.root,copy.deepcopy(self.configuration['engine_config']),log=lambda *_:None,promotion_authorizer=self.promotion_allowed)
            self.eng.campaign_budget=(self.contract,self.store,self.state,self.eng.store.dir)
        return self.eng

    def promotion_allowed(self,eng,record,out):
        current=self.store.current();m=self.store.get(current['materialized_ref']);a=self.store.get(current['authorization_ref'])
        from .policy import identities
        try:budget_check(self.contract,current,self.state,eng.store.dir);budget_ok=True
        except BudgetExceeded:budget_ok=False
        if identities(self.root)!=self.configuration['source_identity']:raise ValueError('PROTECTED_OR_SOURCE_CHANGED')
        remaining=min(self.contract['maximum_wall_time'],self.contract['maximum_compute_budget'])-(time.time()-current['started_at'])
        p=self.contract['promotion_policy'];allowed=budget_ok and p['enabled']and m['class']in p['allowed_classes']and out['decision']=='accepted'and out['promotable']and a['status']=='AUTHORIZED'and remaining>=1600
        if allowed:
            # The legacy Engine couples acceptance/publication in one call.
            # Perform and durably retain 0.5 interpretation before granting its
            # publication callback. Canonical LearningStore ingestion follows
            # afterward, when publication metadata can no longer change.
            from ..learning.engine import learn
            source=curate_archive(eng.store.dir,archive_aggregate=hashlib.sha256(eng.store.ledger.read_bytes()).hexdigest(),
                gaia_version='gaia-v1.0',experiment_ids=[record['id']])
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
        eng=self.engine()
        if not(eng.store.dir/'benchmark.json').exists():eng.init(initialize_mvp=True)
        eng._load()
        return {'current_version':eng.store.current_version(),'baseline_manifest_hash':eng.store.load_state()['baseline_manifest_hash'],
            'benchmark_hash':manifest.file_hash(eng.store.dir/'benchmark.json'),'source_snapshot':eng.store.load_state()['source_snapshot']}

    def observe(self):return ObservationStore(self.local).save(collect(self.root,self.local,self.configuration['engine_config'],quick=True))
    def diagnose(self,ob,iteration):
        self.coverage=[];ctx=self.experimental_context();learning=LearningStore(self.local)
        if ctx and learning.batches():
            for view in query(learning,workload='numpy_mlp',context=ctx,include_stale=True):
                k=view['item']
                if view['applicability_assessment']['transferability']=='EXACT_CONTEXT'and view['effective_status']not in ('CONTRADICTED','SUPERSEDED')and any(e['confirmation']and e['confirmation']['pairs']>=3 for e in k['supporting_evidence']):
                    self.coverage.append({'learning_id':k['learning_id'],'hash':k['hash'],'reason':'EXISTING_PAIRED_VERIFICATION_SATISFIES_REQUESTED_EVIDENCE_GAP_NOT_AN_IMPROVEMENT_CLAIM'})
        return diagnose(ob,diagnosis_id=f'd{iteration:06d}',verification_objective=None if self.coverage else self.contract['objective'])
    def prioritize(self,d,iteration):return prioritize([d],prioritization_id=f'p{iteration:06d}')

    def experimental_context(self):
        eng=self.engine()
        if not(eng.store.dir/'benchmark.json').exists():return None
        baseline=json.loads((eng.store.stable/'v0000/manifest.json').read_bytes());bench=json.loads((eng.store.dir/'benchmark.json').read_bytes())
        return {**{k:baseline[k]for k in ('environment_hash','host_hash','runtime_hash','source_hash')},
            'benchmark_hash':manifest.file_hash(eng.store.dir/'benchmark.json'),'workload':'numpy_mlp','trainer_family':'numpy_mlp',
            'quality_threshold':bench['calibrated']['main']['target'],'gaia_version':'gaia-v1.0','baseline_version':eng.store.current_version()}

    def knowledge(self):
        s=LearningStore(self.local);ctx=self.experimental_context()
        views=query(s,workload='numpy_mlp',context=ctx,include_stale=True)if s.batches()else[]
        return {'views':views,'context':ctx,'runs':[b['run']for b in s.batches()],
            'records':s.items('records')+s.items('knowledge'),'scope':'EXPERIMENT_MANIFEST_CONTEXT_NOT_OBSERVATION_ENVIRONMENT_IDENTITY'}

    def strategy(self,priority,knowledge,diagnosis,iteration):
        # Do not falsely equate observation and execution-manifest environment hashes.
        # 0.6 unbound knowledge is not exploitable; exact-context duplicate policy
        # is separately checked against the real experiment manifest below.
        return plan_experiments(priority,knowledge['runs'],diagnoses=[diagnosis],strategy_id=f's{iteration:06d}')

    def review(self,target,plan,strategy_ref):
        packet=artifact('EXPERIMENT_REVIEW_INPUT',{'target':target['target_class'],'experiment_class':plan['class'],'mode':plan['mode'],
            'expected_information':plan['discriminates'],'risks':plan['estimates']['risk'],'missing_evidence':['CAUSALITY_NOT_ESTABLISHED'],
            'strategy_ref':strategy_ref,'plan_hash':plan['plan_hash']})
        store=CognitiveStore(self.local);reference=import_evidence(store,packet,'selected bounded experimental plan evidence risk uncertainty')
        task=cognitive_task('Review the selected experiment class, mode and risk from the evidence. This is not execution authority.','ANALYZE',[reference])
        task['evidence_requirements']['required_fields']=['payload.experiment_class','payload.mode','payload.risks']
        task.pop('task_id');task.pop('hash');task['task_id']='ct'+provenance.digest(task)[:24];task['hash']=provenance.digest(task)
        def backend_factory():
            from ..local_intelligence.primary import PrimaryLocalIntelligenceBackend
            engine_path=self.root/self.configuration['engine_config']['workload']['state_dir']
            remaining=self.contract['maximum_disk_budget']-disk_bytes(self.state)-disk_bytes(engine_path)
            if remaining<=0:raise BudgetExceeded('STOPPED_BUDGET')
            backend=PrimaryLocalIntelligenceBackend(self.root/self.configuration['intelligence_state'])
            # 0.8's worker supervises /work + private /tmp at one quarter of this
            # budget. Restrict it to remaining campaign bytes, never enlarge it.
            backend.adapter.budget['disk_budget_bytes']=min(backend.adapter.budget['disk_budget_bytes'],remaining*4)
            return backend
        run=CognitiveOrchestrator(self.local,backend_factory=backend_factory).run(task)
        result=run['result']['payload']
        return {'schema':'gaia_experiment_review_v1','target':target['target_id'],'evidence_summary':result['claims'],
            'why_this_plan':plan['rationale'],'expected_information':plan['discriminates'],'known_risks':plan['estimates'],
            'missing_evidence':result['uncertainty']['missing_evidence'],'uncertainty':result['uncertainty'],
            'status':result['status'],'authority':'NONE','cognitive_result':run['result'],'cognitive_trace':run['trace'],'input':packet}

    def execute(self,m):
        eng=self.engine();eng._load()
        parent=eng.store.load_version()[0];before=eng.store.current_version()
        result=eng.experiment(proposal=(m['genome'],m['ops'],G.genome_hash(parent),None))
        records=[r for r in eng.store.records()if r['type']=='end'];out=records[-1]
        out=json.loads((eng.store.dir/out['evidence_path']).read_bytes())
        return {'engine_result':result,'evidence':out,'before_version':before,'after_version':eng.store.current_version()}

    def learn(self,evaluation):
        eng=self.engine();eid=evaluation['evidence']['id']
        sha=hashlib.sha256(eng.store.ledger.read_bytes()).hexdigest()
        source=curate_archive(eng.store.dir,archive_aggregate=sha,gaia_version='gaia-v1.0',experiment_ids=[eid])
        batch=LearningStore(self.local).ingest([source])
        return {'source':source,'batch':batch,'outcome':source['experiments'][0]['outcome']}

    def verify(self,evaluation,pre):
        from .. import readiness,ledger
        from ..observation.compare import compare
        eng=self.engine();eng._load();ob=self.observe();checks=readiness.run_gates(eng)
        current=eng.store.current_version();loaded_g,src=eng.store.load_version()
        ref=eng.refresh_ref(src,check_drift=False)
        old=evaluation['evidence'].get('confirm')or{};costs=[c for c in old.get('champ_costs',[])if isinstance(c,(int,float))]
        import statistics
        improvement=bool(costs)and ref<statistics.median(costs)*(1-eng.acc['min_gain'])
        matrix=self.regression_matrix()
        return {'status':'PASS'if checks['status']=='READY_FOR_CAMPAIGN'and improvement and matrix['status']=='PASS'else'FAIL',
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

    def rollback(self,evaluation,reason):return self.engine().rollback(evaluation['before_version'],reason)
