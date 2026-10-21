"""Explicit closed-loop state machine; every side effect follows a durable intent."""
import copy
import json
from pathlib import Path
import time
from .. import config,genome as G,provenance,engine as cpu_engine
from .schema import campaign,validate_campaign
from .store import CampaignStore,durable,TERMINAL
from .policy import identities,budget_check,BudgetExceeded,authorize
from .materializer import ExperimentMaterializer,rejected_duplicate
from .services import Services
from . import research
from .deadline import wall_deadline


def create_campaign(root,state,contract,*,intelligence_state='state_local_intelligence'):
    validate_campaign(contract);root=Path(root)
    if Path(intelligence_state).is_absolute()or len(Path(intelligence_state).parts)!=1:raise ValueError('LOCAL_INTELLIGENCE_STATE_REQUIRED')
    cfg=copy.deepcopy(config.load(root));cfg['workload']['state_dir']='state_closed_loop_cpu_'+contract['campaign_id'][2:]
    cfg['limits']['max_experiments']=min(cfg['limits']['max_experiments'],contract['maximum_experiments'])
    cfg['limits']['max_total_minutes']=min(cfg['limits']['max_total_minutes'],contract['maximum_wall_time']/60)
    cfg['limits']['max_experiment_seconds']=min(cfg['limits']['max_experiment_seconds'],contract['maximum_trial_seconds'])
    cfg['limits']['max_disk_mb']=min(cfg['limits']['max_disk_mb'],contract['maximum_disk_budget']/2**20)
    configured={'schema':'gaia_closed_loop_configuration_v1','engine_config':cfg,'engine_config_hash':provenance.digest(cfg),
        'source_identity':identities(root),'intelligence_state':intelligence_state,'initial_authorizations':1}
    store=CampaignStore(state,contract['campaign_id']);store.create(contract,configured);return contract


class ClosedLoop:
    def __init__(self,root,state,identifier,*,services_factory=Services):
        self.root=Path(root);self.state=Path(state);self.store=CampaignStore(state,identifier)
        self.contract=validate_campaign(self.store.read('contract'));self.configuration=self.store.read('configuration')
        if provenance.digest(self.configuration['engine_config'])!=self.configuration['engine_config_hash']:raise ValueError('CONFIGURATION_TAMPERED')
        if self.configuration['engine_config']['workload']['state_dir']!='state_closed_loop_cpu_'+identifier[2:]:raise ValueError('ENGINE_STATE_SCOPE_ESCAPE')
        self.services=services_factory(root,state,self.store,self.contract,self.configuration)

    def check(self):
        if identities(self.root)!=self.configuration['source_identity']:raise ValueError('PROTECTED_OR_SOURCE_CHANGED')
        current=self.store.current();engine_path=self.root/self.configuration['engine_config']['workload']['state_dir']
        try:budget_check(self.contract,current,self.state,engine_path)
        except BudgetExceeded:
            if current['phase']in ('EVALUATING','LEARNING','ROLLING_BACK'):
                if not current.get('budget_exhausted'):self.store.event(current['phase'],{'budget_exhausted':True})
            else:raise

    def report(self,phase,reason):
        current=self.store.current();events=self.store.events();completed=[];avoided=[];reviews=[];coverage=[];research_calls=0
        for ev in events:
            s=ev['state']
            for key,target in [('learning_ref',completed),('duplicate_ref',avoided),('review_ref',reviews)]:
                if key in s and s[key]not in target:target.append(s[key])
            if s.get('coverage_ref')and s['coverage_ref']not in coverage:coverage.append(s['coverage_ref'])
        outcomes=[self.store.get(r)['outcome']for r in completed]
        metrics={'iterations':current.get('iteration',0),'experiments':len(completed),'experiment_intents_reserved':current.get('experiments',0),'accepted':outcomes.count('ACCEPTED'),
            'rejected':outcomes.count('REJECTED'),'inconclusive':outcomes.count('INCONCLUSIVE'),'research_calls':current.get('research_calls',0),
            'network_requests':current.get('network_requests',0),'duplicate_experiments_avoided':len(avoided),'learning_reused':len(avoided)+len(coverage),
            'total_wall_time':time.time()-(current.get('started_at')or time.time()),
            'experiment_cost_s':sum(self.store.get(ev['state']['evaluation_ref'])['evidence']['search_cost_s']for i,ev in enumerate(events)if'evaluation_ref'in ev['state']and ev['state']['evaluation_ref']not in[e['state'].get('evaluation_ref')for e in events[:i]]),
            'information_producing_experiments':len(completed),'rollback_count':current.get('rollback_count',0),
            'initial_human_authorizations':1,'human_interventions_during_campaign':len(list((self.store.root/'controls').glob('*.json')))}
        controlled=self.contract['mode']=='CONTROLLED_AUTONOMOUS'
        passed=phase!='FAILED'and(bool(completed)if controlled else phase=='COMPLETED'and bool(current.get('materialized_ref')))
        levels={'PIPELINE_CLOSED_LOOP':'PASS'if passed else'FAIL','AUTONOMOUS_EXECUTION':'PASS'if completed else'NOT_EXERCISED',
            'AUTONOMOUS_LEARNING':'PASS'if completed else'NOT_EXERCISED','AUTONOMOUS_PROMOTION':'PASS'if current.get('promotions',0)else'NOT_EXERCISED',
            'AUTONOMOUS_ROLLBACK':'PASS'if current.get('rollback_count',0)else'NOT_EXERCISED'}
        result={'schema':'gaia_closed_loop_report_v1','campaign_id':self.contract['campaign_id'],'contract_hash':self.contract['hash'],
            'status':'PASS'if passed else'FAIL','stopping_reason':reason,'mode':self.contract['mode'],'metrics':metrics,'levels':levels,
            'trace_hash':events[-1]['hash'],'learning_refs':completed,'learning_reuse_refs':avoided,'knowledge_coverage_refs':coverage,'cognitive_review_refs':reviews,
            'claim':'BOUNDED_CLOSED_LOOP_NUMPY_MLP_NOT_GENERAL_AUTONOMY','permission_expansions':0,
            'source_identity':self.configuration['source_identity'],'rollback_historical_reference':'GAIA v0.1 certified rollback; no destructive regression injected'}
        r=self.store.put('REPORT',result);self.store.event(phase,{'report_ref':r,'reason':reason});return result

    def run(self,*,authorized=False):
        if not authorized:raise ValueError('EXPLICIT_CAMPAIGN_AUTHORIZATION_REQUIRED')
        current=self.store.current()
        if current['phase']in TERMINAL:return self.store.get(current['report_ref'])
        remaining=min(self.contract['maximum_wall_time'],self.contract['maximum_compute_budget'])-(time.time()-current['started_at']if current.get('started_at')is not None else 0)
        try:
            with wall_deadline(remaining):return self._run_locked()
        except BudgetExceeded:
            with self.store.lock():
                if self.store.current()['phase']in TERMINAL:return self.store.get(self.store.current()['report_ref'])
                return self.report('STOPPED','STOPPED_BUDGET')

    def _run_locked(self):
        with self.store.lock():
            cur=self.store.current()
            if cur['phase']in TERMINAL:return self.store.get(cur['report_ref'])
            try:self.check()
            except BudgetExceeded:return self.report('STOPPED','STOPPED_BUDGET')
            except ValueError:return self.report('FAILED','PROTECTED_OR_SOURCE_CHANGED')
            if cur['phase']=='PAUSED':
                if self.store.read('control')['request']!='RUN':return {'status':'PAUSED'}
                self.store.event(cur['resume_phase'],{'resumed':True})
            # A durable execution intent without a receipt is never blindly repeated.
            cur=self.store.current()
            if cur.get('research_intent')or cur.get('rollback_intent')or cur.get('initialization_intent'):return self.report('STOPPED','NEEDS_RECOVERY')
            if cur['phase']=='EXPERIMENTING'and cur.get('execution_intent'):
                try:recovered=self.recover_execution(cur)
                except (OSError,ValueError,RuntimeError):return self.report('STOPPED','NEEDS_RECOVERY')
                if recovered is None:return self.report('STOPPED','NEEDS_RECOVERY')
                self.store.event('EVALUATING',{'evaluation_ref':self.store.put('EVALUATION',recovered)})
            try:
                return self._drive()
            except BudgetExceeded:return self.report('STOPPED','STOPPED_BUDGET')
            except (OSError,ValueError,RuntimeError,KeyError,TypeError,InterruptedError,cpu_engine.NeedsHuman)as exc:
                if identities(self.root)!=self.configuration['source_identity']:return self.report('FAILED','PROTECTED_OR_SOURCE_CHANGED')
                try:budget_check(self.contract,self.store.current(),self.state,self.root/self.configuration['engine_config']['workload']['state_dir'])
                except BudgetExceeded:return self.report('STOPPED','STOPPED_BUDGET')
                current=self.store.current()
                if current['phase']=='EXPERIMENTING':
                    try:recovered=self.recover_execution(current)
                    except (OSError,ValueError,RuntimeError,KeyError):recovered=None
                    if recovered is not None:
                        changed=recovered['before_version']!=recovered['after_version']
                        self.store.event('EVALUATING',{'evaluation_ref':self.store.put('EVALUATION',recovered),'execution_intent':False,
                            'recovered_execution_failure_ref':self.store.put('RECOVERY',{'exception_type':type(exc).__name__,'message_hash':provenance.digest(str(exc)),
                                'original_publication_recovery_used':True,'experiment_reexecuted':False}),
                            'recovered_publication_health_failure':changed})
                        try:return self._drive()
                        except (OSError,ValueError,RuntimeError,KeyError,TypeError,cpu_engine.NeedsHuman):return self.report('FAILED','RECOVERY_COORDINATION_FAILED')
                reason=str(exc)if isinstance(exc,ValueError)and str(exc).isupper()and len(str(exc))<100 else type(exc).__name__
                return self.report('FAILED',reason)

    def _drive(self):
        while True:
            self.check();cur=self.store.current();phase=cur['phase'];control=self.store.read('control')['request']
            if control=='STOP':return self.report('STOPPED','OPERATOR_STOP')
            if control=='PAUSE':self.store.event('PAUSED',{'resume_phase':phase});return {'status':'PAUSED'}
            outcome=self.step(phase,cur)
            if outcome is not None:return outcome

    def step(self,phase,s):
        c=self.contract;svc=self.services;put=self.store.put;get=self.store.get;event=self.store.event
        if phase=='CREATED':
            event(phase,{'started_at':s.get('started_at')or time.time(),'initialization_intent':False,'initialization_done':False})
            event('OBSERVING',{'iteration':1})
        elif phase=='OBSERVING':event('DIAGNOSING',{'observation_ref':put('OBSERVATION',svc.observe())})
        elif phase=='DIAGNOSING':event('PRIORITIZING',{'diagnosis_ref':put('DIAGNOSIS',svc.diagnose(get(s['observation_ref']),s['iteration']))})
        elif phase=='PRIORITIZING':
            priority=svc.prioritize(get(s['diagnosis_ref']),s['iteration'])
            if not priority['ordering']:return self.report('STOPPED','NO_SIGNIFICANT_TARGET')
            event('RETRIEVING',{'priority_ref':put('PRIORITY',priority)})
        elif phase=='RETRIEVING':event('RESEARCHING',{'knowledge_ref':put('KNOWLEDGE_QUERY',svc.knowledge())})
        elif phase=='RESEARCHING':
            if research.needed(get(s['diagnosis_ref'])):
                remaining=c['maximum_network_research']-s.get('network_requests',0)
                if not c['network_authorized']or remaining<1 or not c['research_urls']:return self.report('STOPPED','NEEDS_HUMAN_AUTHORIZATION')
                event(phase,{'network_requests':s.get('network_requests',0)+remaining,'research_intent':True})
                r=research.investigate(c,svc.local,remaining)
                event('PLANNING',{'research_ref':put('RESEARCH',r),'research_calls':s.get('research_calls',0)+1,'research_intent':False})
            else:event('PLANNING',{'research_ref':put('RESEARCH',{'status':'RESEARCH_NOT_NEEDED','reason':'LOCAL_CONTROLLED_VERIFICATION_REQUIRED_NOT_WEB_ADVICE','instruction_authority':'NONE'})})
        elif phase=='PLANNING':
            priority=get(s['priority_ref']);knowledge=get(s['knowledge_ref']);strategy=svc.strategy(priority,knowledge,get(s['diagnosis_ref']),s['iteration'])
            plans={p['plan_id']:p for p in strategy['candidate_plans']};targets={t['target_id']:t for t in priority['candidate_targets']}
            chosen=next((plans[pid]for pid in strategy['ranking']if plans[pid]['class']in c['allowed_experiment_classes']and not plans[pid]['blocked_by']and targets[plans[pid]['target_ref']['target_id']]['component_id']in c['allowed_components']and targets[plans[pid]['target_ref']['target_id']]['target_class']in c['allowed_target_classes']),None)
            if chosen is None:return self.report('STOPPED','NO_AUTHORIZED_EXPERIMENT')
            event('REVIEWING',{'strategy_ref':put('STRATEGY',strategy),'plan_ref':put('SELECTED_PLAN',chosen),'target_ref':put('SELECTED_TARGET',targets[chosen['target_ref']['target_id']])})
        elif phase=='REVIEWING':event('AUTHORIZING',{'review_ref':put('COGNITIVE_REVIEW',svc.review(get(s['target_ref']),get(s['plan_ref']),s['strategy_ref']))})
        elif phase=='AUTHORIZING':
            review=get(s['review_ref']);decision=authorize(c,get(s['target_ref']),get(s['plan_ref']),review,
                remaining=s['experiments']<c['maximum_experiments'],integrity=identities(self.root)==self.configuration['source_identity'],sandbox=provenance.bwrap_capability()['verified'])
            r=put('AUTHORIZATION',decision)
            if decision['status']!='AUTHORIZED':return self.report('STOPPED',decision['status'])
            event('MATERIALIZING',{'authorization_ref':r})
        elif phase=='MATERIALIZING':
            if c['mode']=='CONTROLLED_AUTONOMOUS'and not s.get('initialization_done'):
                if s.get('initialization_intent'):return self.report('STOPPED','NEEDS_RECOVERY')
                event(phase,{'initialization_intent':True})
                initial=svc.initialize()
                event(phase,{'initialization_ref':put('INITIALIZATION',initial),'initialization_intent':False,'initialization_done':True})
                self.check()
            base=svc.engine().store.load_version()[0]if c['mode']=='CONTROLLED_AUTONOMOUS'else G.new_genome()
            m=ExperimentMaterializer().materialize(c,get(s['target_ref']),get(s['plan_ref']),get(s['authorization_ref']),base,get(s['knowledge_ref'])['records'],iteration=s['iteration'])
            duplicate=rejected_duplicate(m,get(s['knowledge_ref'])['views'])
            if duplicate:
                event(phase,{'duplicate_ref':put('LEARNING_REUSE',duplicate),'materialized_ref':put('MATERIALIZED',m)})
                return self.report('STOPPED','NO_AUTHORIZED_NON_DUPLICATE_EXPERIMENT')
            if c['mode']!='CONTROLLED_AUTONOMOUS':
                event(phase,{'materialized_ref':put('MATERIALIZED',m)})
                return self.report('COMPLETED',c['mode']+'_COMPLETE_NO_EXPERIMENT_EXECUTED')
            if s['experiments']>=c['maximum_experiments']:raise BudgetExceeded('STOPPED_BUDGET')
            event('EXPERIMENTING',{'materialized_ref':put('MATERIALIZED',m),'execution_intent':True,'experiments':s['experiments']+1,
                'expected_experiment_id':f"e{svc.engine().store.load_state()['n_experiments']+1:05d}",'before_version':svc.engine().store.current_version()})
        elif phase=='EXPERIMENTING':event('EVALUATING',{'evaluation_ref':put('EVALUATION',svc.execute(get(s['materialized_ref']))),'execution_intent':False})
        elif phase=='EVALUATING':
            evaluation=get(s['evaluation_ref']);decision=evaluation['evidence']['decision']
            if decision not in ('accepted','rejected','deferred','pareto_alternative'):return self.report('FAILED','INVALID_EVALUATION')
            event('LEARNING',{'classification':{'accepted':'ACCEPTED','rejected':'REJECTED','deferred':'INCONCLUSIVE','pareto_alternative':'INCONCLUSIVE'}[decision]})
        elif phase=='LEARNING':
            learned=svc.learn(get(s['evaluation_ref']));evaluation=get(s['evaluation_ref'])
            link=put('STRATEGY_OUTCOME',{'strategy_class':get(s['plan_ref'])['class'],'mode':get(s['plan_ref'])['mode'],'information_gained':'LOCAL_PROTECTED_EVALUATION',
                'outcome':learned['outcome'],'improvement_found':learned['outcome']=='ACCEPTED','cost_s':evaluation['evidence']['search_cost_s'],'strategy_ref':s['strategy_ref']})
            promoted=evaluation['before_version']!=evaluation['after_version']
            event('PROMOTING'if promoted else'REEVALUATING',{'learning_ref':put('LEARNING',learned),'strategy_outcome_ref':link})
        elif phase=='PROMOTING':event('VERIFYING',{'promotions':s.get('promotions',0)+1})
        elif phase=='VERIFYING':
            try:checked={'status':'FAIL','reason':'RECOVERED_POST_PUBLICATION_HEALTH_FAILURE'}if s.get('recovered_publication_health_failure')else svc.verify(get(s['evaluation_ref']),get(s['observation_ref']))
            except (OSError,ValueError,RuntimeError,cpu_engine.NeedsHuman,TimeoutError)as exc:checked={'status':'FAIL','reason':type(exc).__name__,'requires_existing_rollback':True}
            r=put('POST_PROMOTION_VERIFICATION',checked)
            event('REEVALUATING'if checked['status']=='PASS'else'ROLLING_BACK',{'verification_ref':r})
        elif phase=='ROLLING_BACK':
            if s.get('rollback_intent'):return self.report('STOPPED','NEEDS_RECOVERY')
            event(phase,{'rollback_intent':True});result=svc.rollback(get(s['evaluation_ref']),'Closed-loop post-promotion verification failed')
            if result['status']not in ('ROLLED_BACK','COMMITTED','SUCCESS','COMPLETED'):return self.report('FAILED','ROLLBACK_FAILED')
            event('REEVALUATING',{'rollback_ref':put('ROLLBACK',result),'rollback_count':s.get('rollback_count',0)+1,'rollback_intent':False})
        elif phase=='REEVALUATING':
            post=svc.observe();d=svc.diagnose(post,s['iteration']+1);p=svc.prioritize(d,s['iteration']+1)
            coverage=getattr(svc,'coverage',[])
            event(phase,{'reevaluation_ref':put('REEVALUATION',{'observation':post,'diagnosis':d,'priority':p,'knowledge_coverage':coverage}),
                         **({'coverage_ref':put('LEARNING_REUSE',{'items':coverage,'reason':'VERIFICATION_GAP_REEVALUATED_FROM_REAL_LEARNING'})}if coverage else{})})
            if s.get('rollback_count',0):return self.report('STOPPED','POST_PROMOTION_REGRESSION_ROLLED_BACK')
            if s['iteration']>=c['maximum_iterations']or s['experiments']>=c['maximum_experiments']:return self.report('STOPPED','STOPPED_BUDGET')
            histories=[self.store.get(ev['state']['learning_ref'])['outcome']for i,ev in enumerate(self.store.events())if'learning_ref'in ev['state']and ev['state']['learning_ref']not in[e['state'].get('learning_ref')for e in self.store.events()[:i]]]
            if len(histories)>=2 and histories[-2:]==['INCONCLUSIVE','INCONCLUSIVE']:return self.report('STOPPED','REPEATED_INCONCLUSIVE')
            event('OBSERVING',{'iteration':s['iteration']+1,'execution_intent':False})
        else:raise ValueError('UNHANDLED_CAMPAIGN_STATE')

    def recover_execution(self,current):
        eng=self.services.engine()
        if not(eng.store.dir/'benchmark.json').exists():return None
        eng._load();recovery=eng.store.recover_publications(eng)
        if recovery['status']!='READY':return None
        rows=[r for r in eng.store.records()if r['type']=='end'and r['id']==current['expected_experiment_id']]
        if len(rows)!=1:return None
        m=self.store.get(current['materialized_ref'])
        if rows[0]['candidate_genome_hash']!=m['genome_hash']:raise ValueError('RECOVERY_EXPERIMENT_IDENTITY_MISMATCH')
        evidence=json.loads((eng.store.dir/rows[0]['evidence_path']).read_bytes())
        return {'engine_result':'RECOVERED_COMMITTED_EVIDENCE','evidence':evidence,'before_version':current['before_version'],'after_version':eng.store.current_version()}
