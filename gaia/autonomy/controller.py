"""Explicit closed-loop state machine; every side effect follows a durable intent."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import time
from .. import config,genome as G,provenance,engine as cpu_engine
from .schema import campaign,validate_campaign
from .store import CampaignStore,durable,TERMINAL
from .policy import identities,budget_check,BudgetExceeded,authorize,disk_bytes
from .materializer import ExperimentMaterializer,rejected_duplicate,duplicate_v2,NotMaterializable
from .inference_surface import NotMaterializable as InferenceNotMaterializable
from .services import Services
from . import research
from .deadline import wall_deadline
from .clock import elapsed as campaign_elapsed,stamp,interval
from .hypothesis import carried,assess
from .records import assemble
from .lineage import LineageStore,LineageBusy,engine_state_dir,host_experiment_lock

MAX_CANDIDATES=4
BLOCKING=('NEEDS_RECOVERY','RECOVERY_COORDINATION_FAILED','ROLLBACK_FAILED','HEALTH_INVALID','REFERENCE_UNRELIABLE','REFERENCE_DRIFT')
# Phases between an executed side effect and its learning/verification; a stop there leaves the lineage inconsistent.
IN_FLIGHT=('EXPERIMENTING','EVALUATING','LEARNING','PROMOTING','VERIFYING','ROLLING_BACK')
BOOKKEEPING_GRACE_S=600


def effective_phase(state):
    """A paused campaign is still in the phase it will resume."""
    return state.get('resume_phase')if state['phase']=='PAUSED'else state['phase']


def create_campaign(root,state,contract,*,intelligence_state='state_local_intelligence'):
    validate_campaign(contract);root=Path(root);lineage=None
    if contract.get('schema')=='gaia_closed_loop_campaign_v2'and contract['lineage_id']:
        lineage=LineageStore(state,contract['lineage_id']).read()
        if lineage['objective']!=contract['objective']:raise ValueError('LINEAGE_OBJECTIVE_MISMATCH')
        if identities(root)['hash']!=lineage['source_identity_hash']:raise ValueError('LINEAGE_SOURCE_CHANGED_NEW_LINEAGE_REQUIRED')
        intelligence_state=lineage['intelligence_state']
    if Path(intelligence_state).is_absolute()or len(Path(intelligence_state).parts)!=1:raise ValueError('LOCAL_INTELLIGENCE_STATE_REQUIRED')
    cfg=copy.deepcopy(config.load(root))
    cfg['workload']['state_dir']=engine_state_dir(lineage['lineage_id'])if lineage else'state_closed_loop_cpu_'+contract['campaign_id'][2:]
    cfg['limits']['max_experiments']=min(cfg['limits']['max_experiments'],contract['maximum_experiments'])
    cfg['limits']['max_total_minutes']=min(cfg['limits']['max_total_minutes'],contract['maximum_wall_time']/60)
    cfg['limits']['max_experiment_seconds']=min(cfg['limits']['max_experiment_seconds'],contract['maximum_trial_seconds'])
    cfg['limits']['max_disk_mb']=min(cfg['limits']['max_disk_mb'],contract['maximum_disk_budget']/2**20)
    configured={'schema':'gaia_closed_loop_configuration_v1','engine_config':cfg,'engine_config_hash':provenance.digest(cfg),
        'source_identity':identities(root),'intelligence_state':intelligence_state,'initial_authorizations':1}
    if lineage:configured={**configured,'schema':'gaia_closed_loop_configuration_v2','lineage':{'id':lineage['lineage_id'],'hash':lineage['hash']}}
    store=CampaignStore(state,contract['campaign_id']);store.create(contract,configured);return contract


class ClosedLoop:
    def __init__(self,root,state,identifier,*,services_factory=Services):
        self.root=Path(root);self.state=Path(state);self.store=CampaignStore(state,identifier)
        self.contract=validate_campaign(self.store.read('contract'));self.configuration=self.store.read('configuration')
        if provenance.digest(self.configuration['engine_config'])!=self.configuration['engine_config_hash']:raise ValueError('CONFIGURATION_TAMPERED')
        self.v2=self.contract['schema']=='gaia_closed_loop_campaign_v2'
        self.lineage=LineageStore(state,self.contract['lineage_id'])if self.v2 and self.contract['lineage_id']else None
        expected=engine_state_dir(self.contract['lineage_id'])if self.lineage else'state_closed_loop_cpu_'+identifier[2:]
        if self.configuration['engine_config']['workload']['state_dir']!=expected:raise ValueError('ENGINE_STATE_SCOPE_ESCAPE')
        if self.lineage and self.configuration.get('lineage')!={'id':self.lineage.identifier,'hash':self.lineage.read()['hash']}:raise ValueError('LINEAGE_BINDING_MISMATCH')
        self.services=services_factory(root,state,self.store,self.contract,self.configuration);self.grace=False

    def check(self,recovering=False):
        if identities(self.root)!=self.configuration['source_identity']:raise ValueError('PROTECTED_OR_SOURCE_CHANGED')
        current=self.store.current();engine_path=self.root/self.configuration['engine_config']['workload']['state_dir']
        try:budget_check(self.contract,current,self.state,engine_path)
        except BudgetExceeded:
            # Finishing committed work never starts a new experiment: recovery, learning, verification-or-rollback only.
            tolerated=('EVALUATING','LEARNING','ROLLING_BACK')+(('PROMOTING','VERIFYING')if self.v2 else())
            phase=effective_phase(current)if self.v2 else current['phase']
            if phase in tolerated or(self.v2 and recovering and phase=='EXPERIMENTING'and current.get('execution_intent')):
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
            'total_wall_time':campaign_elapsed(current),
            'experiment_cost_s':sum(self.store.get(ev['state']['evaluation_ref'])['evidence']['search_cost_s']for i,ev in enumerate(events)if'evaluation_ref'in ev['state']and ev['state']['evaluation_ref']not in[e['state'].get('evaluation_ref')for e in events[:i]]),
            'information_producing_experiments':len(completed),'rollback_count':current.get('rollback_count',0),
            'initial_human_authorizations':1,'human_interventions_during_campaign':len(list((self.store.root/'controls').glob('*.json')))}
        if self.v2:metrics.update(self.v2_metrics(events,reason))
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
        if self.v2:
            result={**result,'schema':'gaia_closed_loop_report_v2','lineage_id':self.contract['lineage_id'],'surface':self.contract['surface'],
                'objective':self.contract['objective'],
                'claim':'BOUNDED_CLOSED_LOOP_LOCAL_INFERENCE_CONFIGURATION_NOT_MODEL_IMPROVEMENT'if self.contract['surface']=='local_inference'else'BOUNDED_CLOSED_LOOP_NUMPY_MLP_NOT_GENERAL_AUTONOMY'}
        r=self.store.put('REPORT',result);self.store.event(phase,{'report_ref':r,'reason':reason})
        self.close_lineage()
        return result

    def close_lineage(self):
        """Idempotent lineage bookkeeping from the committed terminal campaign state (safe to repeat after a crash)."""
        if not self.lineage:return
        events=self.store.events();final=events[-1]['state']
        if final['phase']not in TERMINAL:return
        prior=events[-2]['state']if len(events)>1 else final
        journal=self.lineage.events();mine=[e for e in journal if e['payload'].get('campaign_id')==self.contract['campaign_id']]
        reason=final['reason'];experiments=len({json.dumps(e['state']['learning_ref'],sort_keys=True)for e in events if'learning_ref'in e['state']})
        # CLOSED pairs only with an admission; blocking reasons always block.
        if any(e['kind']=='CAMPAIGN_ADMITTED'for e in mine)and not any(e['kind']=='CAMPAIGN_CLOSED'for e in mine):
            self.lineage.event('CAMPAIGN_CLOSED',{'campaign_id':self.contract['campaign_id'],'report_hash':final['report_ref']['hash'],'reason':reason,
                'phase':final['phase'],'experiments':experiments,'version':final.get('after_version')or final.get('before_version')})
        # A stop between an executed side effect and its learning/verification leaves the shared lineage inconsistent.
        interrupted=effective_phase(prior)in IN_FLIGHT and reason not in ('POST_PROMOTION_REGRESSION_ROLLED_BACK',)
        if(reason in BLOCKING or interrupted)and not any(e['kind']=='BLOCKED'for e in mine):
            self.lineage.event('BLOCKED',{'campaign_id':self.contract['campaign_id'],
                'reason':reason if reason in BLOCKING else'INTERRUPTED_IN_FLIGHT_EXPERIMENT','phase':effective_phase(prior),'resolution':'EXPLICIT_HUMAN_REVIEW_REQUIRED'})

    def v2_metrics(self,events,reason=None):
        def unique(key):
            seen=[]
            for ev in events:
                if key in ev['state']and ev['state'][key]not in seen:seen.append(ev['state'][key])
            return [self.store.get(r)for r in seen]
        records=unique('record_ref');assessments=unique('assessment_ref');selections=unique('selection_ref');skips=unique('candidates_ref')
        return {'time':self.time_breakdown(events,unique('review_ref')),'progress':self.progress(records,assessments,unique('strategy_ref'),skips,events,reason),'distinct_candidates':len({r['proposed_change']['candidate_hash']for r in records}),
            'distinct_experiment_contexts':len({(r['proposed_change']['class'],r['proposed_change']['candidate_hash'],r['reference_state']['version'])for r in records}),
            'classes_exercised':sorted({r['proposed_change']['class']for r in records}),
            'hypothesis_assessments':{k:[a['status']for a in assessments].count(k)for k in ('SUPPORTED','NOT_SUPPORTED','INCONCLUSIVE')},
            'experiment_records':len(records),'plans_skipped':sum(len(c['skipped'])for c in skips),
            'plans_skipped_as_duplicates':sum(1 for c in skips for x in c['skipped']if x.get('learning_reuse')),
            'deterministic_plan_selections':sum(1 for s in selections if s['method']=='DETERMINISTIC_FIRST_ELIGIBLE_PLAN'),
            'advisory_cognitive_reviews':len(selections),
            'advisory_reviews_citing_selected_plan':sum(1 for s in selections if s['selected_plan_id']in s.get('advisory_cited_candidates',[])),
            'reference_measurements':len(unique('reference_ref')),
            'regression_matrix_runs':sum(len(v['regression_matrix']['attempts'])for v in unique('verification_ref')if isinstance(v.get('regression_matrix'),dict)and'attempts'in v['regression_matrix']),
            'regression_first_failures':sum(1 for v in unique('verification_ref')if(v.get('regression_matrix')or{}).get('first_failure_signal')),
            'regression_transient_signals':sum(1 for v in unique('verification_ref')if((v.get('regression_matrix')or{}).get('first_failure_signal')or{}).get('transient')),
            'meta_tunes':len(unique('meta_tune_ref')),
            'learned_ranking_changed_top_plan':sum(1 for x in unique('strategy_ref')if x.get('outcome_statistics')and x['ranking'][:1]!=x['outcome_statistics']['static_ranking'][:1]),
            'strategies_with_linked_outcomes':sum(1 for x in unique('strategy_ref')if x.get('outcome_statistics',{}).get('outcomes'))}

    INTENTIONAL_REPEATS=('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT','REPLICATION','KNOWLEDGE_VALIDATION')

    def progress(self,records,assessments,strategies,skips,events,reason):
        """§8: progress counters from committed records; an experiment is informative only if its hypothesis was decided."""
        c=self.contract;final=events[-1]['state'];outcomes=[r['result']['classification']for r in records]
        streak=longest=0
        for o in outcomes:
            streak=0 if o=='ACCEPTED'else streak+1;longest=max(longest,streak)
        mine={r['record_hash']for r in records};seen=set();redundant=0
        for r in self.services.records():
            h=r['proposed_change']['candidate_hash']
            if r['record_hash']in mine and h in seen and r['proposed_change']['class']not in self.INTENTIONAL_REPEATS:redundant+=1
            seen.add(h)
        targets=[r['problem']['target_class']for r in records]
        tail=outcomes[-c['no_progress_limit']:]
        expected={'NO_PROGRESS':len(outcomes)>=c['no_progress_limit']and'ACCEPTED'not in tail,
            'REPEATED_INCONCLUSIVE':outcomes[-2:]==['INCONCLUSIVE','INCONCLUSIVE'],
            'STOPPED_BUDGET':final.get('iteration',0)>=c['maximum_iterations']or final.get('experiments',0)>=c['maximum_experiments']
                or bool(final.get('budget_exhausted'))or campaign_elapsed(final)>=min(c['maximum_wall_time'],c['maximum_compute_budget'])}
        return {'experiments':len(records),'informative_experiments':sum(a['status']in ('SUPPORTED','NOT_SUPPORTED')for a in assessments),
            'inconclusive_experiments':sum(a['status']=='INCONCLUSIVE'for a in assessments),
            'longest_streak_without_acceptance':longest,'current_streak_without_acceptance':streak,
            'repeated_target_iterations':sum(1 for a,b in zip(targets,targets[1:])if a==b),
            'redundant_experiments':redundant,
            'decisions_changed_by_learned_ranking':sum(1 for x in strategies if x.get('outcome_statistics')and x['ranking'][:1]!=x['outcome_statistics']['static_ranking'][:1]),
            'plans_skipped_by_learning':sum(1 for k in skips for x in k['skipped']if x.get('learning_reuse')),
            'stopping_reason':reason,'stopping_condition_met':expected.get(reason),
            'scope':'STOPPING_CONDITION_REPLAYED_FOR_NO_PROGRESS_REPEATED_INCONCLUSIVE_AND_BUDGET_OTHERS_NOT_EVALUATED'}

    def time_breakdown(self,events,reviews):
        """§3: wall, active, idle, model, tool, experiment, verification and CPU seconds from the stamped journal."""
        final=events[-1]['state'];active=paused=gaps=0.;discontinuities=0;cpu=0.;boots=[]
        for a,b in zip(events,events[1:]):
            ca,cb=a.get('clock'),b.get('clock')
            if not(ca and cb):continue
            dt,jump=interval(ca,cb)
            if jump:discontinuities+=1;continue
            if b['state'].get('controller_runs',0)!=a['state'].get('controller_runs',0):gaps+=dt;continue
            if a['state']['phase']=='PAUSED':paused+=dt;continue
            active+=dt;cpu+=max(0.,cb['cpu_s']-ca['cpu_s'])
        for e in events:
            boot=(e.get('clock')or{}).get('boot_id')
            if boot and(not boots or boots[-1]!=boot):boots.append(boot)
        performance=[(r.get('cognitive_result')or{}).get('payload',{}).get('performance')or{}for r in reviews]
        wall=campaign_elapsed(final)
        return {'wall_s':wall,'active_s':active,'idle_s':max(0.,wall-active),'paused_s':paused,'between_runs_s':gaps,
            'model_s':sum(p.get('model_time_s',0)for p in performance),'tool_s':sum(p.get('tool_overhead_s',0)for p in performance),
            'experiment_s':final.get('experiment_s',0.),'verification_s':final.get('verification_s',0.),'cpu_s':cpu,
            'controller_runs':final.get('controller_runs',0),'boots':len(boots),'clock_discontinuities':discontinuities,
            'scope':'MONOTONIC_WITHIN_BOOT_WALL_ACROSS_REBOOT_CPU_OF_CONTROLLER_AND_FINISHED_CHILDREN_DURING_ACTIVE_STEPS'}

    def run(self,*,authorized=False):
        if not authorized:raise ValueError('EXPLICIT_CAMPAIGN_AUTHORIZATION_REQUIRED')
        # Read without repair: the derived cursor is only rewritten under the campaign lock.
        current=self.store.inspect()['state']
        if current['phase']in TERMINAL:
            if self.lineage:
                try:
                    with self.lineage.lock():self.close_lineage()
                except LineageBusy:pass
            return self.store.get(current['report_ref'])
        try:
            with ExitStack()as stack:
                # One campaign per lineage and one measured experiment surface per host at a time.
                if self.lineage:stack.enter_context(self.lineage.lock())
                if self.v2 and self.contract['mode']=='CONTROLLED_AUTONOMOUS':stack.enter_context(host_experiment_lock(self.root))
                return self._run_deadline()
        except LineageBusy as exc:return {'status':'BLOCKED','reason':str(exc),'campaign_id':self.contract['campaign_id']}

    def _run_deadline(self,grace=False):
        current=self.store.current()
        remaining=min(self.contract['maximum_wall_time'],self.contract['maximum_compute_budget'])-campaign_elapsed(current)
        in_flight=self.v2 and(effective_phase(current)in IN_FLIGHT or current.get('execution_intent'))
        if grace or(in_flight and remaining<=0):remaining=BOOKKEEPING_GRACE_S;grace=True
        self.grace=grace
        try:
            with wall_deadline(remaining):return self._run_locked()
        except BudgetExceeded:
            # A deadline inside committed work gets one bounded grace to learn, verify or roll back; never a new experiment.
            if self.v2 and not grace and self.store.current()['phase']in IN_FLIGHT and self.store.current()['phase']not in TERMINAL:return self._run_deadline(grace=True)
            with self.store.lock():
                if self.store.current()['phase']in TERMINAL:self.close_lineage();return self.store.get(self.store.current()['report_ref'])
                return self.report('STOPPED','STOPPED_BUDGET')

    def _run_locked(self):
        with self.store.lock():
            cur=self.store.current()
            if cur['phase']in TERMINAL:return self.store.get(cur['report_ref'])
            if self.lineage and self.lineage.state()['blocked']:return self.report('STOPPED','LINEAGE_BLOCKED_NEEDS_RECOVERY')
            try:self.check(recovering=True)
            except BudgetExceeded:return self.report('STOPPED','STOPPED_BUDGET')
            except ValueError:return self.report('FAILED','PROTECTED_OR_SOURCE_CHANGED')
            if self.v2:
                # Every controller start is counted and stamped: restarts and gaps between runs are measured, never active time.
                self.store.event(cur['phase'],{'controller_runs':cur.get('controller_runs',0)+1,'run_clock':stamp()})
            if cur['phase']=='PAUSED':
                if self.store.read('control')['request']!='RUN':return {'status':'PAUSED'}
                self.store.event(cur['resume_phase'],{'resumed':True})
            # A durable execution intent without a receipt is never blindly repeated.
            cur=self.store.current()
            if cur.get('research_intent')or cur.get('rollback_intent')or cur.get('initialization_intent'):return self.report('STOPPED','NEEDS_RECOVERY')
            if cur.get('meta_tune_intent'):
                # Strategy tuning only appends paired comparisons; an interrupted round is recorded once, never replayed.
                done=[e for e in(self.lineage.events()if self.lineage else[])if e['kind']=='META_TUNE'and e['payload']['campaign_id']==self.contract['campaign_id']
                      and e['payload'].get('intent_sequence')==cur['meta_tune_intent']]
                ref=self.store.put('META_TUNE',{'status':'COMPLETED_BEFORE_CRASH'if done else'INTERRUPTED_NOT_REPLAYED','adopted':done[0]['payload']['adopted']if done else None})
                if self.lineage and not done:self.lineage.event('META_TUNE',{'campaign_id':self.contract['campaign_id'],'adopted':None,'interrupted':True,
                    'tune_hash':ref['hash'],'intent_sequence':cur['meta_tune_intent']})
                self.store.event(cur['phase'],{'meta_tune_intent':False,'meta_tune_ref':ref})
            if cur['phase']=='EXPERIMENTING'and cur.get('execution_intent'):
                try:recovered=self.recover_execution(cur)
                except (OSError,ValueError,RuntimeError):return self.report('STOPPED','NEEDS_RECOVERY')
                if recovered is None:return self.report('STOPPED','NEEDS_RECOVERY')
                self.store.event('EVALUATING',{'evaluation_ref':self.store.put('EVALUATION',recovered)})
            try:
                return self._drive()
            except BudgetExceeded:
                # A deadline inside committed work is finished under the bounded bookkeeping grace instead.
                if self.v2 and self.store.current()['phase']in IN_FLIGHT and not self.grace:raise
                return self.report('STOPPED','STOPPED_BUDGET')
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
            # v2 honours STOP/PAUSE once committed work is learned and verified, never between a side effect and its bookkeeping.
            deferred=self.v2 and phase in IN_FLIGHT
            if control=='STOP'and not deferred:return self.report('STOPPED','OPERATOR_STOP')
            if control=='PAUSE'and not deferred:self.store.event('PAUSED',{'resume_phase':phase});return {'status':'PAUSED'}
            outcome=self.step(phase,cur)
            if outcome is not None:return outcome

    def step(self,phase,s):
        c=self.contract;svc=self.services;put=self.store.put;get=self.store.get;event=self.store.event
        if phase=='CREATED':
            started=stamp()
            event(phase,{'started_at':s.get('started_at')or started['wall'],**({}if s.get('started_at')else{'started_clock':started}),
                         'initialization_intent':False,'initialization_done':False})
            if self.lineage and not s.get('admitted'):
                # Idempotent admission: a crash after the lineage event reuses it instead of admitting twice.
                prior=[e for e in self.lineage.events()if e['kind']=='CAMPAIGN_ADMITTED'and e['payload']['campaign_id']==c['campaign_id']]
                if prior:admission=prior[0]['payload']['admission_lineage_bytes']
                else:
                    admission=disk_bytes(self.lineage.root)+disk_bytes(self.root/self.configuration['engine_config']['workload']['state_dir'])
                    self.lineage.event('CAMPAIGN_ADMITTED',{'campaign_id':c['campaign_id'],'admission_lineage_bytes':admission,'mode':c['mode']})
                event(phase,{'admitted':True,'admission_lineage_bytes':admission});s=self.store.current()
            if self.lineage and c['mode']=='CONTROLLED_AUTONOMOUS':
                if s.get('health_ref'):health=get(s['health_ref'])
                else:
                    health=svc.health_check()
                    if not any(e['kind']=='HEALTH_CHECK'and e['payload']['campaign_id']==c['campaign_id']for e in self.lineage.events()):
                        self.lineage.event('HEALTH_CHECK',{'campaign_id':c['campaign_id'],'status':health['status'],'version':health.get('version')})
                    event(phase,{'health_ref':put('LINEAGE_HEALTH_CHECK',health)});s=self.store.current()
                if health['status']=='FAIL':
                    # Follow-up failure of a promoted version: restore the known-good predecessor, then require review.
                    if health.get('rollback_to')and not s.get('rollback_ref'):
                        event(phase,{'rollback_intent':True})
                        result=svc.rollback({'before_version':health['rollback_to']},'Lineage follow-up health check failed')
                        if result['status']not in ('ROLLED_BACK','COMMITTED','SUCCESS','COMPLETED'):return self.report('FAILED','ROLLBACK_FAILED')
                        event(phase,{'rollback_ref':put('ROLLBACK',result),'rollback_count':s.get('rollback_count',0)+1,'rollback_intent':False})
                    if self.store.current().get('rollback_ref')and not self.store.current().get('reference_after_rollback'):
                        if self.reference_after_rollback()!='MEASURED':return self.report('STOPPED','REFERENCE_UNRELIABLE')
                    return self.report('STOPPED','HEALTH_INVALID')
            event('OBSERVING',{'iteration':1})
        elif phase=='OBSERVING':
            ob=svc.observe(full=s['iteration']==1)if self.v2 else svc.observe()
            event('DIAGNOSING',{'observation_ref':put('OBSERVATION',ob)})
        elif phase=='DIAGNOSING':event('PRIORITIZING',{'diagnosis_ref':put('DIAGNOSIS',svc.diagnose(get(s['observation_ref']),s['iteration']))})
        elif phase=='PRIORITIZING':
            priority=svc.prioritize(get(s['diagnosis_ref']),s['iteration'])
            if not priority['ordering']:return self.report('STOPPED','NO_SIGNIFICANT_TARGET')
            event('RETRIEVING',{'priority_ref':put('PRIORITY',priority)})
        elif phase=='RETRIEVING':event('RESEARCHING',{'knowledge_ref':put('KNOWLEDGE_QUERY',svc.knowledge())})
        elif phase=='RESEARCHING':
            if research.needed(get(s['diagnosis_ref'])):
                remaining=c['maximum_network_research']-s.get('network_requests',0)
                if not c['network_authorized']or remaining<1 or not c['research_urls']:
                    if not self.v2:return self.report('STOPPED','NEEDS_HUMAN_AUTHORIZATION')
                    # Optional external evidence is recorded as unavailable; it never halts local experimentation.
                    asked=research.question(get(s['diagnosis_ref']))
                    event('PLANNING',{'research_ref':put('RESEARCH',{'status':'RESEARCH_NOT_AUTHORIZED','question':asked['question'],'topics':asked['topics'],
                        'reason':'NETWORK_RESEARCH_NOT_AUTHORIZED_BY_CONTRACT','instruction_authority':'NONE'})})
                    return None
                event(phase,{'network_requests':s.get('network_requests',0)+remaining,'research_intent':True})
                r=research.investigate(c,svc.local,remaining,get(s['diagnosis_ref']))if self.v2 else research.investigate(c,svc.local,remaining)
                event('PLANNING',{'research_ref':put('RESEARCH',r),'research_calls':s.get('research_calls',0)+1,'research_intent':False})
            else:event('PLANNING',{'research_ref':put('RESEARCH',{'status':'RESEARCH_NOT_NEEDED','reason':'LOCAL_CONTROLLED_VERIFICATION_REQUIRED_NOT_WEB_ADVICE','instruction_authority':'NONE'})})
        elif phase=='PLANNING':
            priority=get(s['priority_ref']);knowledge=get(s['knowledge_ref']);strategy=svc.strategy(priority,knowledge,get(s['diagnosis_ref']),s['iteration'])
            plans={p['plan_id']:p for p in strategy['candidate_plans']};targets={t['target_id']:t for t in priority['candidate_targets']}
            eligible=[plans[pid]for pid in strategy['ranking']if plans[pid]['class']in c['allowed_experiment_classes']and not plans[pid]['blocked_by']and targets[plans[pid]['target_ref']['target_id']]['component_id']in c['allowed_components']and targets[plans[pid]['target_ref']['target_id']]['target_class']in c['allowed_target_classes']]
            if not eligible:return self.report('STOPPED','NO_AUTHORIZED_EXPERIMENT')
            if not self.v2:
                chosen=eligible[0]
                event('REVIEWING',{'strategy_ref':put('STRATEGY',strategy),'plan_ref':put('SELECTED_PLAN',chosen),'target_ref':put('SELECTED_TARGET',targets[chosen['target_ref']['target_id']])})
                return None
            return self.plan_v2(s,strategy,eligible,targets,knowledge)
        elif phase=='REVIEWING':
            if not self.v2:
                event('AUTHORIZING',{'review_ref':put('COGNITIVE_REVIEW',svc.review(get(s['target_ref']),get(s['plan_ref']),s['strategy_ref']))})
                return None
            candidates=get(s['candidates_ref'])['candidates'];records=svc.records()
            previous={'class':records[-1]['proposed_change']['class'],'classification':records[-1]['result']['classification'],
                'hypothesis_assessment':records[-1]['result']['hypothesis_assessment'],'decision_reason':records[-1]['decision_reason'],
                'change':json.dumps(records[-1]['proposed_change']['changes'])[:200]}if records else None
            summary=[{'plan_id':x['plan']['plan_id'],'class':x['plan']['class'],'mode':x['plan']['mode'],'expected_effect':x['hypothesis']['expected_effect'],
                'novelty':x['plan']['novelty'],'information_value':x['plan']['estimates']['information_value'],'improvement_potential':x['plan']['estimates']['improvement_potential'],
                'cost':x['plan']['estimates']['cost'],'risk':x['plan']['estimates']['risk'],'change':json.dumps(x['changes'])[:200]}for x in candidates]
            review=svc.compare(get(s['target_ref']),summary,candidates[0]['hypothesis'],previous,get(s['research_ref']))
            chosen=next(x for x in candidates if x['plan']['plan_id']==review['selected_plan_id'])
            event('AUTHORIZING',{'review_ref':put('COGNITIVE_REVIEW',review),'plan_ref':put('SELECTED_PLAN',chosen['plan']),'target_ref':put('SELECTED_TARGET',chosen['target']),
                'hypothesis_ref':put('HYPOTHESIS',chosen['hypothesis']),'preview_hash':chosen['preview_hash'],
                'selection_ref':put('PLAN_SELECTION',{'method':review['method'],'selected_plan_id':review['selected_plan_id'],'default_plan_id':review['default_plan_id'],
                    'advisory_cited_candidates':review['advisory']['cited_candidates'],'authority':'DETERMINISTIC_RANKING_ADVISORY_REVIEW_HAS_NO_INFLUENCE'})})
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
            if self.v2 and c['mode']=='CONTROLLED_AUTONOMOUS'and c['surface']=='numpy_mlp'and not self.store.current().get('admission_reference'):
                # Every admitted campaign re-measures the champion reference under the v0.1 drift guard before any screen.
                measured=svc.measure_reference('CAMPAIGN_ADMISSION',True)
                event(phase,{'admission_reference':measured['status']})
                if measured['status']=='REFERENCE_DRIFT':return self.report('STOPPED','REFERENCE_DRIFT')
                if measured['status']!='MEASURED':return self.report('STOPPED','REFERENCE_UNRELIABLE')
                self.check()
            if self.v2:return self.materialize_v2(s)
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
        elif phase=='EXPERIMENTING':
            started=stamp();evaluation=svc.execute(get(s['materialized_ref']))
            timing={'experiment_s':s.get('experiment_s',0)+interval(started,stamp())[0]}if self.v2 else{}
            event('EVALUATING',{'evaluation_ref':put('EVALUATION',evaluation),'execution_intent':False,**timing})
        elif phase=='EVALUATING':
            evaluation=get(s['evaluation_ref']);decision=evaluation['evidence']['decision']
            if decision not in ('accepted','rejected','deferred','pareto_alternative'):return self.report('FAILED','INVALID_EVALUATION')
            classification={'accepted':'ACCEPTED','rejected':'REJECTED','deferred':'INCONCLUSIVE','pareto_alternative':'INCONCLUSIVE'}[decision]
            updates={'classification':classification}
            if self.v2:updates['assessment_ref']=put('HYPOTHESIS_ASSESSMENT',assess(get(s['hypothesis_ref']),evaluation,classification))
            event('LEARNING',updates)
        elif phase=='LEARNING':
            learned=svc.learn(get(s['evaluation_ref']));evaluation=get(s['evaluation_ref'])
            outcome={'strategy_class':get(s['plan_ref'])['class'],'mode':get(s['plan_ref'])['mode'],'information_gained':'LOCAL_PROTECTED_EVALUATION',
                'outcome':learned['outcome'],'improvement_found':learned['outcome']=='ACCEPTED','cost_s':evaluation['evidence']['search_cost_s'],'strategy_ref':s['strategy_ref']}
            updates={}
            if self.v2:
                assessment=get(s['assessment_ref'])
                outcome={**outcome,'linked':{'plan_id':get(s['plan_ref'])['plan_id'],'experiment_id':evaluation['evidence'].get('id'),
                    'hypothesis_assessment':assessment['status']},'information_gained':assessment['note']}
                record=assemble(c,self.configuration,s['iteration'],get(s['target_ref']),get(s['plan_ref']),get(s['hypothesis_ref']),get(s['materialized_ref']),
                    evaluation,s['classification'],assessment,learned,get(s['selection_ref']))
                svc.save_record(record);updates['record_ref']=put('EXPERIMENT_RECORD',record)
            link=put('STRATEGY_OUTCOME',outcome)
            promoted=evaluation['before_version']!=evaluation['after_version']
            event('PROMOTING'if promoted else'REEVALUATING',{'learning_ref':put('LEARNING',learned),'strategy_outcome_ref':link,**updates,
                **({'after_version':evaluation['after_version']}if self.v2 else{})})
        elif phase=='PROMOTING':event('VERIFYING',{'promotions':s.get('promotions',0)+1})
        elif phase=='VERIFYING':
            started=stamp()
            try:
                if s.get('recovered_publication_health_failure'):checked={'status':'FAIL','reason':'RECOVERED_POST_PUBLICATION_HEALTH_FAILURE'}
                elif self.v2 and s.get('budget_exhausted'):checked={'status':'FAIL','reason':'VERIFICATION_BUDGET_EXHAUSTED','requires_existing_rollback':True,
                                                                    'regression_matrix_partial':svc.matrix_progress()}
                else:checked=svc.verify(get(s['evaluation_ref']),get(s['observation_ref']))
            except (OSError,ValueError,RuntimeError,cpu_engine.NeedsHuman,TimeoutError)as exc:
                checked={'status':'FAIL','reason':type(exc).__name__,'requires_existing_rollback':True}
                # v2 keeps every matrix attempt already committed (failing tests, first-failure signal) in the verification record.
                if self.v2:checked['regression_matrix_partial']=svc.matrix_progress()
            except Exception as exc:
                # v2: any unexpected verification error after a committed promotion uses the existing rollback.
                if not self.v2:raise
                checked={'status':'FAIL','reason':type(exc).__name__,'requires_existing_rollback':True,'regression_matrix_partial':svc.matrix_progress()}
            r=put('POST_PROMOTION_VERIFICATION',checked)
            timing={'verification_s':s.get('verification_s',0)+interval(started,stamp())[0]}if self.v2 else{}
            event('REEVALUATING'if checked['status']=='PASS'else'ROLLING_BACK',{'verification_ref':r,**timing})
        elif phase=='ROLLING_BACK'and not self.v2:
            if s.get('rollback_intent'):return self.report('STOPPED','NEEDS_RECOVERY')
            event(phase,{'rollback_intent':True});result=svc.rollback(get(s['evaluation_ref']),'Closed-loop post-promotion verification failed')
            if result['status']not in ('ROLLED_BACK','COMMITTED','SUCCESS','COMPLETED'):return self.report('FAILED','ROLLBACK_FAILED')
            event('REEVALUATING',{'rollback_ref':put('ROLLBACK',result),'rollback_count':s.get('rollback_count',0)+1,'rollback_intent':False})
        elif phase=='ROLLING_BACK':
            if s.get('rollback_for')!=s['evaluation_ref']['id']:
                if s.get('rollback_intent'):return self.report('STOPPED','NEEDS_RECOVERY')
                event(phase,{'rollback_intent':True});result=svc.rollback(get(s['evaluation_ref']),'Closed-loop post-promotion verification failed')
                if result['status']not in ('ROLLED_BACK','COMMITTED','SUCCESS','COMPLETED'):return self.report('FAILED','ROLLBACK_FAILED')
                event(phase,{'rollback_ref':put('ROLLBACK',result),'rollback_count':s.get('rollback_count',0)+1,'rollback_intent':False,
                             'rollback_for':s['evaluation_ref']['id']})
            # The restored champion's reference is measured before anything else is screened or learned against it.
            if self.reference_after_rollback()!='MEASURED':return self.report('STOPPED','REFERENCE_UNRELIABLE')
            event('REEVALUATING',{})
        elif phase=='REEVALUATING':
            post=svc.observe();d=svc.diagnose(post,s['iteration']+1);p=svc.prioritize(d,s['iteration']+1)
            coverage=getattr(svc,'coverage',[])
            event(phase,{'reevaluation_ref':put('REEVALUATION',{'observation':post,'diagnosis':d,'priority':p,'knowledge_coverage':coverage}),
                         **({'coverage_ref':put('LEARNING_REUSE',{'items':coverage,'reason':'VERIFICATION_GAP_REEVALUATED_FROM_REAL_LEARNING'})}if coverage else{})})
            if self.v2:self.maintain_lineage(self.store.current())
            if s.get('rollback_count',0):return self.report('STOPPED','POST_PROMOTION_REGRESSION_ROLLED_BACK')
            if s['iteration']>=c['maximum_iterations']or s['experiments']>=c['maximum_experiments']:return self.report('STOPPED','STOPPED_BUDGET')
            histories=[self.store.get(ev['state']['learning_ref'])['outcome']for i,ev in enumerate(self.store.events())if'learning_ref'in ev['state']and ev['state']['learning_ref']not in[e['state'].get('learning_ref')for e in self.store.events()[:i]]]
            if len(histories)>=2 and histories[-2:]==['INCONCLUSIVE','INCONCLUSIVE']:return self.report('STOPPED','REPEATED_INCONCLUSIVE')
            if self.v2 and len(histories)>=c['no_progress_limit']and'ACCEPTED'not in histories[-c['no_progress_limit']:]:return self.report('STOPPED','NO_PROGRESS')
            event('OBSERVING',{'iteration':s['iteration']+1,'execution_intent':False,**({'budget_exhausted':False}if self.v2 else{})})
        else:raise ValueError('UNHANDLED_CAMPAIGN_STATE')

    def plan_v2(self,s,strategy,eligible,targets,knowledge):
        """Pure previews of each eligible plan; duplicates and non-materializable plans fall through, recorded."""
        svc=self.services;put=self.store.put;c=self.contract
        seen=svc.seen();repeats=svc.repeats();controls=svc.controls_done();diagnosis=self.store.get(s['diagnosis_ref']);candidates=[];skipped=[];reuse=[]
        initialized=svc.initialized()
        for plan in eligible:
            if len(candidates)>=MAX_CANDIDATES:break
            target=targets[plan['target_ref']['target_id']]
            try:m=svc.materialize(target,plan,None,knowledge,s['iteration'],preview=True,history=initialized)
            except (NotMaterializable,InferenceNotMaterializable)as exc:skipped.append({'plan_id':plan['plan_id'],'class':plan['class'],'reason':exc.reason});continue
            duplicate=duplicate_v2(m,knowledge['views'],seen,repeats,c['replication_cap'],controls)
            if duplicate:
                skipped.append({'plan_id':plan['plan_id'],'class':plan['class'],'reason':duplicate['reason'],'learning_reuse':duplicate});reuse.append(duplicate);continue
            candidates.append({'plan':plan,'target':target,'preview_hash':m['genome_hash'],'candidate_hash':m['candidate_hash'],'changes':m['changes'],
                               'hypothesis':carried(diagnosis,target,plan)})
        record=put('ELIGIBLE_CANDIDATES',{'candidates':candidates,'skipped':skipped,'engine_initialized_at_planning':initialized,
            'scope':'PURE_PREVIEWS_SAME_SEED_AS_EXECUTION'})
        updates={'strategy_ref':put('STRATEGY',strategy),'candidates_ref':record,'planning_engine_initialized':initialized,
                 **({'duplicate_ref':put('LEARNING_REUSE',{'items':reuse,'reason':'DUPLICATES_SKIPPED_TO_NEXT_RANKED_PLAN'})}if reuse else{})}
        if not candidates:
            self.store.event('PLANNING',updates)
            novelty=skipped and all(x['reason']in ('NO_NOVEL_CANDIDATE','FACTORIAL_DESIGN_COMPLETE')for x in skipped if not x.get('learning_reuse'))and any(not x.get('learning_reuse')for x in skipped)
            return self.report('STOPPED','NO_NOVEL_CANDIDATE'if novelty else'NO_AUTHORIZED_NON_DUPLICATE_EXPERIMENT')
        first=candidates[0]
        self.store.event('REVIEWING',{**updates,'plan_ref':put('SELECTED_PLAN',first['plan']),'target_ref':put('SELECTED_TARGET',first['target']),
            'hypothesis_ref':put('HYPOTHESIS',first['hypothesis'])})

    def materialize_v2(self,s):
        svc=self.services;put=self.store.put;get=self.store.get;c=self.contract
        # Materialize under exactly the inputs the preview used (engine history only if it existed at planning).
        m=svc.materialize(get(s['target_ref']),get(s['plan_ref']),get(s['authorization_ref']),get(s['knowledge_ref']),s['iteration'],
                          history=s.get('planning_engine_initialized',False))
        if m['genome_hash']!=s['preview_hash']:return self.report('FAILED','MATERIALIZATION_NONDETERMINISTIC')
        if c['mode']!='CONTROLLED_AUTONOMOUS':
            self.store.event('MATERIALIZING',{'materialized_ref':put('MATERIALIZED',m)})
            return self.report('COMPLETED',c['mode']+'_COMPLETE_NO_EXPERIMENT_EXECUTED')
        if s['experiments']>=c['maximum_experiments']:raise BudgetExceeded('STOPPED_BUDGET')
        if c['surface']=='numpy_mlp':
            # Bind the screen reference to the current champion before the execution intent exists.
            try:svc.current_reference()
            except cpu_engine.NeedsHuman:return self.report('STOPPED','REFERENCE_UNRELIABLE')
        self.store.event('EXPERIMENTING',{'materialized_ref':put('MATERIALIZED',m),'execution_intent':True,'experiments':s['experiments']+1,
            'expected_experiment_id':svc.expected_id(),'before_version':svc.current_version()})

    def reference_after_rollback(self):
        """Mandatory re-measurement of the restored champion's reference (numpy); inference re-benchmarks its control per experiment."""
        if self.contract['surface']!='numpy_mlp':
            self.store.event(self.store.current()['phase'],{'reference_after_rollback':'NOT_APPLICABLE_CONTROL_REMEASURED_PER_EXPERIMENT'})
            return 'MEASURED'
        measured=self.services.measure_reference('AFTER_ROLLBACK',False)
        self.store.event(self.store.current()['phase'],{'reference_after_rollback':measured['status']})
        return measured['status']

    def maintain_lineage(self,s):
        """Level D maintenance: v0.1 paired strategy tuning on the contracted surface, when budget allows."""
        if not(self.lineage and self.contract['surface']=='numpy_mlp'and self.contract['mode']=='CONTROLLED_AUTONOMOUS'):return
        state=self.lineage.state()
        if state['experiments']-state['experiments_at_last_tune']<5 or self.services.remaining(s)<900:return
        sequence=len(self.store.events())+1
        self.store.event('REEVALUATING',{'meta_tune_intent':sequence})
        tuned=self.services.meta_tune()
        ref=self.store.put('META_TUNE',tuned)
        self.lineage.event('META_TUNE',{'campaign_id':self.contract['campaign_id'],'adopted':tuned['adopted'],'tune_hash':ref['hash'],'intent_sequence':sequence})
        self.store.event('REEVALUATING',{'meta_tune_intent':False,'meta_tune_ref':ref})

    def recover_execution(self,current):
        if self.v2 and self.contract['surface']=='local_inference':return self.services.recover_inference(current)
        eng=self.services.engine()
        if not(eng.store.dir/'benchmark.json').exists():return None
        eng._load();recovery=eng.store.recover_publications(eng)
        if recovery['status']!='READY':return None
        rows=[r for r in eng.store.records()if r['type']=='end'and r['id']==current['expected_experiment_id']]
        if len(rows)!=1:return None
        m=self.store.get(current['materialized_ref'])
        if rows[0]['candidate_genome_hash']!=m['genome_hash']:raise ValueError('RECOVERY_EXPERIMENT_IDENTITY_MISMATCH')
        evidence=json.loads((eng.store.dir/rows[0]['evidence_path']).read_bytes())
        value={'engine_result':'RECOVERED_COMMITTED_EVIDENCE','evidence':evidence,'before_version':current['before_version'],'after_version':eng.store.current_version()}
        if self.v2:
            # The reference was bound to the champion before the execution intent; the experiment may since have refreshed it.
            last=self.services.last_reference()or{}
            value['reference_used']={'version':last.get('version'),'cost_s':last.get('cost_s'),'reason':last.get('reason'),
                'measurement_ref':last.get('measurement_ref'),'measured_now':False}
        return value
