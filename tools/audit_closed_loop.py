#!/usr/bin/env python3
"""Offline closed-loop audit. Never runs an experiment, model, network fetch or promotion."""
import argparse
import ast
import hashlib
import json
from pathlib import Path,PurePosixPath
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gaia.autonomy.schema import validate_campaign,validate_artifact,ref
from gaia.autonomy.store import CampaignStore,NEXT,TERMINAL
from gaia.autonomy.policy import authorize,identities
from gaia.autonomy.materializer import ExperimentMaterializer,rejected_duplicate
from gaia.autonomy.research import needed
from gaia.diagnosis.schema import validate as valid_diagnosis
from gaia.prioritization.schema import validate as valid_priority
from gaia.experiment_strategy.schema import validate as valid_strategy
from gaia.experiment_strategy.engine import plan_experiments
from gaia.learning.schema import validate_source
from gaia.learning.engine import learn
from gaia.learning.contradictions import with_history
from gaia.observation.schema import validate as valid_observation
from gaia import genome as G,stats
from gaia.protected.sandbox import rlimit_policy,environment as sandbox_environment
from gaia.provenance import canonical_json,digest


def source_policy():
    files={}
    for path in sorted((ROOT/'gaia/autonomy').glob('*.py')):
        raw=path.read_bytes();files[path.relative_to(ROOT).as_posix()]=hashlib.sha256(raw).hexdigest()
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node,ast.Call):
                name=node.func.attr if isinstance(node.func,ast.Attribute)else node.func.id if isinstance(node.func,ast.Name)else''
                if name in ('eval','exec','system','popen','install_runtime','download'):raise ValueError('UNRESTRICTED_AUTONOMY_AUTHORITY')
                if name in ('run_trial','Popen'):raise ValueError('DUPLICATED_WORKER_OR_EVALUATOR')
                if any(k.arg=='shell'and isinstance(k.value,ast.Constant)and k.value.value for k in node.keywords):raise ValueError('SHELL_EXECUTION_DENIED')
    return {'status':'PASS','files':files,'hash':digest(files),'execution_entry':'EXISTING_ENGINE_EXPERIMENT_ONLY','scope':'STATIC_BOUNDARY_REVIEW_NOT_FORMAL_PROGRAM_PROOF'}


def get_artifacts(store):
    values={}
    for path in sorted((store.root/'artifacts').glob('au*.json')):
        if path.is_symlink():raise ValueError('AUDIT_SYMLINK')
        v=validate_artifact(json.loads(path.read_bytes()))
        if path.stem!=v['id']:raise ValueError('AUDIT_ARTIFACT_ID')
        values[v['id']]=v
    return values


def audit_data(contract,configuration,events,artifacts,*,core=None,check_source=True,allow_privacy_projections=False,lineage_records=None,intelligence=None):
    validate_campaign(contract)
    if contract['schema']=='gaia_closed_loop_campaign_v2':
        return audit_data_v2(contract,configuration,events,artifacts,core=core,check_source=check_source,lineage_records=lineage_records or[],intelligence=intelligence)
    if configuration['engine_config_hash']!=digest(configuration['engine_config']):raise ValueError('CONFIGURATION_HASH')
    if configuration['engine_config']['workload']['state_dir']!='state_closed_loop_cpu_'+contract['campaign_id'][2:]:raise ValueError('ENGINE_STATE_ESCAPE')
    if check_source and identities(ROOT)!=configuration['source_identity']:raise ValueError('SOURCE_OR_PROTECTED_IDENTITY_CHANGED')
    if not events or events[0]['state']['phase']!='CREATED':raise ValueError('JOURNAL_INITIAL_STATE')
    projected=set()
    def get(r,kind=None):
        v=artifacts[r['id']]
        if v.get('schema')=='gaia_closed_loop_privacy_projection_v1':
            if not allow_privacy_projections or v['original_ref']!=r or v['original_kind']!='EVALUATION'or kind not in (None,'EVALUATION'):raise ValueError('UNAUTHORIZED_PRIVACY_PROJECTION')
            if v['projection_hash']!=digest({k:x for k,x in v.items()if k!='projection_hash'}):raise ValueError('PRIVACY_PROJECTION_HASH')
            projected.add(r['id']);return v['payload']
        validate_artifact(v)
        if ref(v)!=r or kind and v['kind']!=kind:raise ValueError('CROSS_ARTIFACT_REFERENCE_MISMATCH')
        return v['payload']
    def references(node):
        if isinstance(node,dict):
            if set(node)=={'id','hash'}and isinstance(node['id'],str)and node['id'].startswith('au'):get(node)
            for v in node.values():references(v)
        elif isinstance(node,list):
            for v in node:references(v)
    previous=None;prior_phase=None;prior_state={};prior_time=0;seen_refs={};unique={}
    for i,event in enumerate(events,1):
        if event['sequence']!=i or event['previous_hash']!=previous or event['hash']!=digest({k:v for k,v in event.items()if k!='hash'}):raise ValueError('JOURNAL_HASH')
        if event['timestamp']<prior_time:raise ValueError('JOURNAL_TIME_REGRESSION')
        s=event['state'];phase=s['phase'];resumed=prior_phase=='PAUSED'and phase==prior_state.get('resume_phase')
        if prior_phase in TERMINAL or(prior_phase and phase!=prior_phase and not resumed and phase not in NEXT.get(prior_phase,set())and phase not in TERMINAL|{'PAUSED'}):raise ValueError('INVALID_JOURNAL_TRANSITION')
        for field,maximum in [('iteration','maximum_iterations'),('experiments','maximum_experiments'),('network_requests','maximum_network_research')]:
            if s.get(field,0)>contract[maximum]:raise ValueError('CAMPAIGN_BUDGET_ESCALATION')
            if s.get(field,0)<prior_state.get(field,0):raise ValueError('CAMPAIGN_COUNTER_RESET')
        if prior_state.get('started_at')is not None and s['started_at']!=prior_state['started_at']:raise ValueError('WALL_CLOCK_RESET')
        references(s)
        for key,r in s.items():
            if key.endswith('_ref')and isinstance(r,dict):unique.setdefault(key,{})[r['id']]=r
        if phase=='EXPERIMENTING'and prior_phase!='EXPERIMENTING':
            decision=get(s['authorization_ref'],'AUTHORIZATION')
            if decision['status']!='AUTHORIZED'or not s['execution_intent']or contract['mode']!='CONTROLLED_AUTONOMOUS':raise ValueError('EXPERIMENT_WITHOUT_AUTHORITY')
        if s.get('authorization_ref')and s['authorization_ref']['id']not in seen_refs:
            decision=get(s['authorization_ref']);plan=get(s['plan_ref']);target=get(s['target_ref']);review=get(s['review_ref'])
            replay=authorize(contract,target,plan,review,remaining=True,integrity=True,sandbox=True)
            if replay!=decision:raise ValueError('AUTHORIZATION_DOES_NOT_REPRODUCE')
            seen_refs[decision['plan_id']]=True;seen_refs[s['authorization_ref']['id']]=True
        previous=event['hash'];prior_phase=phase;prior_state=s;prior_time=event['timestamp']
    final=events[-1]['state'];report=get(final['report_ref'],'REPORT')
    if final['phase']not in TERMINAL or report['trace_hash']!=events[-1]['previous_hash']or report['campaign_id']!=contract['campaign_id']or report['contract_hash']!=contract['hash']:raise ValueError('REPORT_TRACE_BINDING')
    if report['permission_expansions']!=0:raise ValueError('AUTHORITY_EXPANSION')
    for r in unique.get('observation_ref',{}).values():valid_observation(get(r))
    for r in unique.get('diagnosis_ref',{}).values():valid_diagnosis(get(r))
    for r in unique.get('priority_ref',{}).values():valid_priority(get(r))
    for r in unique.get('strategy_ref',{}).values():valid_strategy(get(r))
    checked_strategies=set();checked_research=set();checked_materializations=set()
    for event in events:
        s=event['state']
        if s.get('strategy_ref')and s['strategy_ref']['id']not in checked_strategies:
            checked_strategies.add(s['strategy_ref']['id'])
            saved=get(s['strategy_ref']);knowledge=get(s['knowledge_ref'])
            replay=plan_experiments(get(s['priority_ref']),knowledge['runs'],diagnoses=[get(s['diagnosis_ref'])],strategy_id=saved['strategy_id'])
            if {k:v for k,v in saved.items()if k not in ('timestamp','cost','output_hash')}!={k:v for k,v in replay.items()if k not in ('timestamp','cost','output_hash')}:raise ValueError('STRATEGY_DOES_NOT_REPRODUCE')
        if s.get('research_ref')and s['research_ref']['id']not in checked_research:
            checked_research.add(s['research_ref']['id'])
            r=get(s['research_ref'])
            if r['status']=='RESEARCH_NOT_NEEDED'and needed(get(s['diagnosis_ref'])):raise ValueError('RESEARCH_JUSTIFICATION_MISMATCH')
            if r.get('instruction_authority')!='NONE':raise ValueError('RESEARCH_AUTHORITY_ESCALATION')
        if s.get('materialized_ref')and s['materialized_ref']['id']not in checked_materializations:
            checked_materializations.add(s['materialized_ref']['id'])
            m=get(s['materialized_ref']);genome=m['genome']
            if m['arbitrary_code_generated']or m['surface']!='numpy_mlp_genome_hyperparameters'or genome['lits']or genome['drops']:raise ValueError('MATERIALIZED_CODE_ESCAPE')
            if digest(genome)!=m['genome_hash']or hashlib.sha256(G.render(genome).encode()).hexdigest()!=m['trainer_hash']:raise ValueError('CANDIDATE_IDENTITY')
            base=G.new_genome()
            if core:
                base=next((d for name,d in core.items()if name.startswith('stable/')and name.endswith('/genome.json')and digest(d)==m['baseline_hash']),None)
                if base is None:raise ValueError('MATERIALIZER_BASELINE_MISSING')
            replay=ExperimentMaterializer().materialize(contract,get(s['target_ref']),get(s['plan_ref']),get(s['authorization_ref']),base,get(s['knowledge_ref'])['records'],iteration=s['iteration'])
            if replay!=m:raise ValueError('MATERIALIZATION_DOES_NOT_REPRODUCE')
        if s.get('duplicate_ref'):
            if rejected_duplicate(get(s['materialized_ref']),get(s['knowledge_ref'])['views'])!=get(s['duplicate_ref']):raise ValueError('LEARNING_REUSE_DOES_NOT_REPRODUCE')
    evaluation_refs=list(unique.get('evaluation_ref',{}).values());evaluations=[get(r)for r in evaluation_refs]
    for er,evaluation in zip(evaluation_refs,evaluations):
        e=evaluation['evidence']
        masked=er['id']in projected
        if not masked and e['evidence_hash']!=digest({k:v for k,v in e.items()if k!='evidence_hash'}):raise ValueError('EVALUATION_HASH')
        sandboxes=[t['result'].get('sandbox_evidence',{})for t in e['trial_metrics']]
        if not sandboxes or(not masked and digest(sandboxes)!=e['sandbox_evidence_hash']):raise ValueError('SANDBOX_EVIDENCE_HASH')
        if masked:
            projection=artifacts[er['id']]
            if projection['original_evidence_hash']!=e['evidence_hash']or len(projection['original_sandbox_hashes'])!=len(sandboxes):raise ValueError('ORIGINAL_NATIVE_HASH_COMMITMENT')
            if any(s.get('backend')!='bwrap'or s.get('worker_sha256')!=configuration['source_identity']['files']['gaia/protected/worker.py']for s in sandboxes):raise ValueError('PROJECTED_SANDBOX_WORKER_IDENTITY')
        if any(not b.get('validated')or not b.get('checks')or not all(b['checks'].values())for b in sandboxes):raise ValueError('UNVERIFIED_SANDBOX_EXECUTION')
        expected_limits=rlimit_policy(configuration['engine_config']['limits']);expected_environment=sandbox_environment(configuration['engine_config']['limits']['worker_threads'])
        for trial,b in zip(e['trial_metrics'],sandboxes):
            if b['active_limits']!=expected_limits or b['handshake']['limits']!=expected_limits or b['handshake']['environment']!=expected_environment:raise ValueError('CANDIDATE_RESOURCE_OR_ENVIRONMENT_ESCALATION')
            if b['candidate_sha256']!=trial['trainer_hash']or b['worker_sha256']!=configuration['source_identity']['files']['gaia/protected/worker.py']:raise ValueError('WORKER_OR_CANDIDATE_IDENTITY')
        if not e['overall_gates_passed']:raise ValueError('FAILED_PROTECTED_GATES')
        if e['decision']=='accepted'and not e['promotable']:raise ValueError('UNPROMOTABLE_ACCEPTANCE')
        if e.get('confirm'):
            n=e['confirm']['n'];trials=[t['result']for t in e['trial_metrics']][1:];champ=[];cand=[]
            if len(trials)!=2*n:raise ValueError('PAIRED_TRIAL_COUNT')
            for i in range(n):
                first=configuration['engine_config']['acceptance']['confirm_seeds'];parity=i%2 if i<first else(i-first+1)%2
                a,b=trials[2*i:2*i+2];champ.append(b if parity else a);cand.append(a if parity else b)
            decision=stats.decide(champ,cand,configuration['engine_config']['acceptance'])
            if any(e['confirm'].get(k)!=v for k,v in decision.items())or decision['decision']!=e['decision']:raise ValueError('PROTECTED_ACCEPTANCE_DOES_NOT_REPRODUCE')
        elif e['decision']!='rejected':raise ValueError('ACCEPTANCE_WITHOUT_CONFIRMATION')
        if evaluation['before_version']!=evaluation['after_version']:
            approvals=[get(r)for r in unique.get('promotion_decision_ref',{}).values()]
            if not any(a['allowed']and a['experiment_id']==e['id']for a in approvals):raise ValueError('PROMOTION_WITHOUT_CAMPAIGN_POLICY')
    learning=[get(r)for r in unique.get('learning_ref',{}).values()];previous_knowledge={};sources={}
    for item in learning:
        source=validate_source(item['source']);sources[source['source_hash']]=source;run=item['batch']['run']
        reproduced=with_history(learn([sources[h]for h in run['source_hashes']],{'learning':run['settings']}),previous_knowledge.values())
        if {k:v for k,v in run.items()if k not in ('run_hash','cost')}!={k:v for k,v in reproduced.items()if k not in ('run_hash','cost')}:raise ValueError('LEARNING_DOES_NOT_REPRODUCE')
        previous_knowledge.update({k['learning_id']:k for k in run['knowledge']})
    if len(learning)!=len(evaluations):raise ValueError('FINALIZED_EXPERIMENT_WITHOUT_LEARNING')
    for r in unique.get('pre_promotion_learning_ref',{}).values():
        preview=get(r,'PRE_PUBLICATION_LEARNING');source=validate_source(preview['source']);run=preview['run'];replay=learn([source])
        if preview['operational_knowledge_adopted']is not False or {k:v for k,v in run.items()if k not in ('run_hash','cost')}!={k:v for k,v in replay.items()if k not in ('run_hash','cost')}:raise ValueError('PRE_PUBLICATION_LEARNING_INVALID')
    if report['metrics']['experiments']!=len(evaluations):raise ValueError('EXPERIMENT_ACCOUNTING')
    if contract['mode']!='CONTROLLED_AUTONOMOUS'and evaluations:raise ValueError('SIMULATION_EXECUTED_CANDIDATE')
    if report['status']=='PASS'and contract['mode']=='CONTROLLED_AUTONOMOUS':
        required=('OBSERVING','DIAGNOSING','PRIORITIZING','RETRIEVING','RESEARCHING','PLANNING','REVIEWING','AUTHORIZING','MATERIALIZING','EXPERIMENTING','EVALUATING','LEARNING','REEVALUATING')
        if not evaluations or not unique.get('reevaluation_ref')or any(phase not in[e['state']['phase']for e in events]for phase in required):raise ValueError('PARTIAL_LOOP_CANNOT_BE_CERTIFIED')
    if core:
        baseline=core['stable/v0000/manifest.json']
        if baseline['manifest_hash']!=digest({k:v for k,v in baseline.items()if k!='manifest_hash'}):raise ValueError('BASELINE_MANIFEST_HASH')
        if baseline['source']['protected_hash']!=configuration['source_identity']['protected_hash']:raise ValueError('PROTECTED_BASELINE_IDENTITY')
        if baseline['effective_config']['acceptance']!=configuration['engine_config']['acceptance']:raise ValueError('ACCEPTANCE_THRESHOLDS_CHANGED')
        for evaluation in evaluations:
            e=evaluation['evidence'];gate=core[e['gate_report_path']]
            if gate['gate_report_hash']!=digest({k:v for k,v in gate.items()if k!='gate_report_hash'})or gate['overall']!='PASS'or not all(g['ok']for g in gate['gates'].values()):raise ValueError('G0_G5_NOT_VERIFIED')
            if core[e['evidence_path']]!=e:raise ValueError('ENGINE_EVIDENCE_MISMATCH')
            if not e.get('confirm')and e['screen']['status']=='ok'and e['screen']['reached']:
                reference=gate['gates']['G2_reliability']['details']['median_s'];threshold=reference*(1-configuration['engine_config']['acceptance']['min_gain']/2)
                if e['screen']['cost_s']<threshold-.0002:raise ValueError('SCREEN_REJECTION_DOES_NOT_REPRODUCE')
            em=core[f"experiments/{e['id']}/manifest.json"]
            if em['manifest_hash']!=e['experiment_manifest_hash']or em['candidate_genome_hash']!=e['candidate_genome_hash']:raise ValueError('EXPERIMENT_MANIFEST_BINDING')
    return {'status':'PASS','campaign_id':contract['campaign_id'],'mode':contract['mode'],'report_status':report['status'],'events':len(events),
        'experiments':len(evaluations),'learning_batches':len(learning),'metrics':report['metrics'],'levels':report['levels'],
        'protected_hash':configuration['source_identity']['protected_hash'],'claim':report['claim'],
        'privacy_projected_evaluations':len(projected),'audit_scope':'PROJECTED_NATIVE_METADATA_WITH_ORIGINAL_LOCAL_AUDIT_COMMITMENTS'if projected else'ORIGINAL_LOCAL_ARTIFACTS'}


V2_SKIP_REASONS={'NO_NOVEL_CANDIDATE','NOT_MATERIALIZABLE_ON_SURFACE','QUALIFIED_REFERENCE_CONFIGURATION_MISSING','REFERENCE_REQUIRES_UNSUPPORTED_CODE_VARIATION',
    'REFERENCE_OUTSIDE_HYPERPARAMETER_SURFACE','FACTORIAL_DESIGN_COMPLETE','EXACT_REJECTED_CONFIGURATION_AVOIDED','BUDGETED_REPEAT_DEFERRED_USING_EXISTING_LEARNING',
    'CONFIGURATION_ALREADY_EVALUATED_IN_LINEAGE','INTENTIONAL_REPEAT_CAP_REACHED','CONTROL_ALREADY_EXECUTED_FOR_CURRENT_CHAMPION'}
V2_METHODS={'IDENTICAL_CURRENT_BASELINE','EXISTING_HP_OPERATOR_FROM_CURRENT_CHAMPION','FIXED_FACTORIAL_CELL_FROM_REFERENCE','EXACT_LEARNING_REFERENCE_REPEAT',
    'EXISTING_HP_OPERATOR_FROM_QUALIFIED_REFERENCE','IDENTICAL_CURRENT_PRIMARY_STACK','ONE_FACTOR_QUALIFIED_STACK_VARIATION'}


def audit_data_v2(contract,configuration,events,artifacts,*,core=None,check_source=True,lineage_records=(),intelligence=None):
    """v2: structural replay of the integrated loop; weight-based operator choice is checked by surface and novelty, not re-sampled."""
    from gaia.autonomy.lineage import engine_state_dir
    from gaia.autonomy.hypothesis import assess
    from gaia.autonomy.records import assemble
    from gaia.autonomy.schema import supported
    if configuration['engine_config_hash']!=digest(configuration['engine_config']):raise ValueError('CONFIGURATION_HASH')
    expected=engine_state_dir(contract['lineage_id'])if contract['lineage_id']else'state_closed_loop_cpu_'+contract['campaign_id'][2:]
    if configuration['engine_config']['workload']['state_dir']!=expected:raise ValueError('ENGINE_STATE_ESCAPE')
    if check_source and identities(ROOT)!=configuration['source_identity']:raise ValueError('SOURCE_OR_PROTECTED_IDENTITY_CHANGED')
    if not events or events[0]['state']['phase']!='CREATED':raise ValueError('JOURNAL_INITIAL_STATE')
    def get(r,kind=None):
        v=validate_artifact(artifacts[r['id']])
        if ref(v)!=r or kind and v['kind']!=kind:raise ValueError('CROSS_ARTIFACT_REFERENCE_MISMATCH')
        return v['payload']
    previous=None;prior_phase=None;prior_state={};prior_time=0;unique={}
    for i,event in enumerate(events,1):
        if event['sequence']!=i or event['previous_hash']!=previous or event['hash']!=digest({k:v for k,v in event.items()if k!='hash'}):raise ValueError('JOURNAL_HASH')
        if event['timestamp']<prior_time:raise ValueError('JOURNAL_TIME_REGRESSION')
        s=event['state'];phase=s['phase'];resumed=prior_phase=='PAUSED'and phase==prior_state.get('resume_phase')
        if prior_phase in TERMINAL or(prior_phase and phase!=prior_phase and not resumed and phase not in NEXT.get(prior_phase,set())and phase not in TERMINAL|{'PAUSED'}):raise ValueError('INVALID_JOURNAL_TRANSITION')
        for field,maximum in [('iteration','maximum_iterations'),('experiments','maximum_experiments'),('network_requests','maximum_network_research')]:
            if s.get(field,0)>contract[maximum]:raise ValueError('CAMPAIGN_BUDGET_ESCALATION')
            if s.get(field,0)<prior_state.get(field,0):raise ValueError('CAMPAIGN_COUNTER_RESET')
        if prior_state.get('started_at')is not None and s['started_at']!=prior_state['started_at']:raise ValueError('WALL_CLOCK_RESET')
        for key,r in s.items():
            if key.endswith('_ref')and isinstance(r,dict):get(r);unique.setdefault(key,{})[r['id']]=r
        if phase=='EXPERIMENTING'and prior_phase!='EXPERIMENTING':
            decision=get(s['authorization_ref'],'AUTHORIZATION')
            if decision['status']!='AUTHORIZED'or not s['execution_intent']or contract['mode']!='CONTROLLED_AUTONOMOUS':raise ValueError('EXPERIMENT_WITHOUT_AUTHORITY')
            m=get(s['materialized_ref'],'MATERIALIZED')
            if m['genome_hash']!=s['preview_hash']:raise ValueError('PREVIEW_MATERIALIZATION_MISMATCH')
        previous=event['hash'];prior_phase=phase;prior_state=s;prior_time=event['timestamp']
    final=events[-1]['state'];report=get(final['report_ref'],'REPORT')
    if final['phase']not in TERMINAL or report['trace_hash']!=events[-1]['previous_hash']or report['campaign_id']!=contract['campaign_id']or report['contract_hash']!=contract['hash']:raise ValueError('REPORT_TRACE_BINDING')
    if report['permission_expansions']!=0:raise ValueError('AUTHORITY_EXPANSION')
    for r in unique.get('observation_ref',{}).values():valid_observation(get(r))
    for r in unique.get('diagnosis_ref',{}).values():valid_diagnosis(get(r))
    for r in unique.get('priority_ref',{}).values():valid_priority(get(r))
    prior_ids={rec['experiment_id']for rec in lineage_records}
    for r in unique.get('strategy_ref',{}).values():
        strategy=valid_strategy(get(r))
        linked=strategy.get('outcome_statistics')
        if linked and any(o['experiment_id']not in prior_ids|{x['experiment_id']for x in [get(q)for q in unique.get('record_ref',{}).values()]}for o in linked['outcomes']):
            raise ValueError('LINKED_OUTCOME_WITHOUT_EXPERIMENT_RECORD')
    for r in unique.get('candidates_ref',{}).values():
        c=get(r,'ELIGIBLE_CANDIDATES')
        if len(c['candidates'])>4 or any(x['reason']not in V2_SKIP_REASONS for x in c['skipped']):raise ValueError('UNKNOWN_PLAN_SKIP_REASON')
        for x in c['candidates']:
            if x['plan']['class']not in supported(contract)or x['plan']['blocked_by']:raise ValueError('INELIGIBLE_CANDIDATE_PREVIEWED')
    for r in unique.get('authorization_ref',{}).values():
        events_with=[e['state']for e in events if e['state'].get('authorization_ref')==r]
        s=events_with[0];replay=authorize(contract,get(s['target_ref']),get(s['plan_ref']),get(s['review_ref']),remaining=True,integrity=True,sandbox=True)
        if replay!=get(r):raise ValueError('AUTHORIZATION_DOES_NOT_REPRODUCE')
        selection=get(s['selection_ref'],'PLAN_SELECTION');candidates=get(s['candidates_ref'],'ELIGIBLE_CANDIDATES')['candidates']
        if selection['selected_plan_id']not in{x['plan']['plan_id']for x in candidates}or selection['selected_plan_id']!=get(s['plan_ref'])['plan_id']:raise ValueError('SELECTION_OUTSIDE_PREVIEWED_CANDIDATES')
    seen=set(rec['proposed_change']['candidate_hash']for rec in lineage_records);surface=contract['surface']
    for r in unique.get('materialized_ref',{}).values():
        m=get(r,'MATERIALIZED')
        if m['arbitrary_code_generated']or m['method']not in V2_METHODS:raise ValueError('MATERIALIZED_CODE_ESCAPE')
        if surface=='numpy_mlp':
            g=m['genome']
            if m['surface']!='numpy_mlp_genome_hyperparameters'or g['lits']or g['drops']or any(not str(c[0]).startswith('hp.')for c in m['changes']):raise ValueError('MATERIALIZED_SURFACE_ESCAPE')
            if digest(g)!=m['genome_hash']or hashlib.sha256(G.render(g).encode()).hexdigest()!=m['trainer_hash']or G.genome_hash(g)!=m['candidate_hash']:raise ValueError('CANDIDATE_IDENTITY')
            if len(m['ops'])>1 and m['method']!='FIXED_FACTORIAL_CELL_FROM_REFERENCE':raise ValueError('MULTI_FACTOR_ESCAPE')
        else:
            if m['surface']!='local_inference_stack_configuration'or m['model_or_weight_change']or len(m['changes'])>1 or digest(m['stack'])!=m['genome_hash']:raise ValueError('INFERENCE_SURFACE_ESCAPE')
    evaluations=[]
    for s in [e['state']for e in events]:
        if s.get('record_ref')and s['record_ref']in[x for x in unique.get('record_ref',{}).values()]and s['record_ref']['id']not in[x['record_ref']['id']for x in evaluations]:
            evaluations.append(s)
    for s in evaluations:
        record=get(s['record_ref'],'EXPERIMENT_RECORD');m=get(s['materialized_ref']);evaluation=get(s['evaluation_ref'])
        candidate=m['candidate_hash']
        if candidate in seen and not m['intentional_repeat']and m['class']not in ('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT'):raise ValueError('UNINTENDED_REPEATED_EXPERIMENT')
        seen.add(candidate)
        replay=assess(get(s['hypothesis_ref']),evaluation,s['classification'])
        if replay!=get(s['assessment_ref']):raise ValueError('HYPOTHESIS_ASSESSMENT_DOES_NOT_REPRODUCE')
        rebuilt=assemble(contract,configuration,s['iteration'],get(s['target_ref']),get(s['plan_ref']),get(s['hypothesis_ref']),m,evaluation,s['classification'],replay,
                         get(s['learning_ref']),get(s['selection_ref']))
        if rebuilt!=record:raise ValueError('EXPERIMENT_RECORD_DOES_NOT_REPRODUCE')
        e=evaluation['evidence']
        if surface=='numpy_mlp':
            if e['candidate_genome_hash']!=m['genome_hash']:raise ValueError('EXECUTED_CANDIDATE_IDENTITY')
            if not e['overall_gates_passed']:raise ValueError('FAILED_PROTECTED_GATES')
            if e.get('confirm'):
                n=e['confirm']['n'];trials=[t['result']for t in e['trial_metrics']][1:];champ=[];cand=[]
                if len(trials)!=2*n:raise ValueError('PAIRED_TRIAL_COUNT')
                for i in range(n):
                    first=configuration['engine_config']['acceptance']['confirm_seeds'];parity=i%2 if i<first else(i-first+1)%2
                    a,b=trials[2*i:2*i+2];champ.append(b if parity else a);cand.append(a if parity else b)
                decision=stats.decide(champ,cand,configuration['engine_config']['acceptance'])
                if decision['decision']!=e['decision']:raise ValueError('PROTECTED_ACCEPTANCE_DOES_NOT_REPRODUCE')
            elif e['decision']!='rejected':raise ValueError('ACCEPTANCE_WITHOUT_CONFIRMATION')
            learned=get(s['learning_ref']);source=validate_source(learned['source'])
            if source['experiments'][0]['outcome']!=learned['outcome']:raise ValueError('LEARNING_OUTCOME_MISMATCH')
        else:
            from gaia.autonomy.inference_surface import decide
            from gaia.local_intelligence.selection import dimensions
            if intelligence is None:raise ValueError('INFERENCE_EVIDENCE_STORE_REQUIRED')
            control=intelligence.read(e['control_ref']['id'],'BENCHMARK')
            cand=intelligence.read(e['candidate_ref']['id'],'BENCHMARK')if e['candidate_ref']else None
            def dims(b):return dimensions(b)if b and b['payload']['status']=='QUALIFIED'and b['payload']['backend_verification']['verified']else None
            if {'id':control['id'],'hash':control['hash']}!=e['control_ref']or dims(control)!=e['control_dimensions']or dims(cand)!=e['candidate_dimensions']:raise ValueError('INFERENCE_BENCHMARK_BINDING')
            if cand and cand['payload']['stack']['stack_id']!=candidate:raise ValueError('INFERENCE_CANDIDATE_IDENTITY')
            if decide(e['control_dimensions'],e['candidate_dimensions'])!=(e['decision'],e['reason']):raise ValueError('INFERENCE_DECISION_DOES_NOT_REPRODUCE')
        if evaluation['before_version']!=evaluation['after_version']:
            approvals=[get(r)for r in unique.get('promotion_decision_ref',{}).values()]
            if not any(a['allowed']and a['experiment_id']==e['id']and a['class']in contract['promotion_policy']['allowed_classes']for a in approvals):raise ValueError('PROMOTION_WITHOUT_CAMPAIGN_POLICY')
    if report['metrics']['experiments']!=len(unique.get('learning_ref',{}))or len(evaluations)!=len(unique.get('learning_ref',{})):raise ValueError('EXPERIMENT_ACCOUNTING')
    if contract['mode']!='CONTROLLED_AUTONOMOUS'and evaluations:raise ValueError('SIMULATION_EXECUTED_CANDIDATE')
    if report['status']=='PASS'and contract['mode']=='CONTROLLED_AUTONOMOUS':
        required=('OBSERVING','DIAGNOSING','PRIORITIZING','RETRIEVING','RESEARCHING','PLANNING','REVIEWING','AUTHORIZING','MATERIALIZING','EXPERIMENTING','EVALUATING','LEARNING','REEVALUATING')
        if not evaluations or any(phase not in[e['state']['phase']for e in events]for phase in required):raise ValueError('PARTIAL_LOOP_CANNOT_BE_CERTIFIED')
    return {'status':'PASS','campaign_id':contract['campaign_id'],'lineage_id':contract['lineage_id'],'surface':surface,'mode':contract['mode'],'report_status':report['status'],
        'events':len(events),'experiments':len(evaluations),'distinct_candidates':len({get(s['materialized_ref'])['candidate_hash']for s in evaluations}),
        'metrics':report['metrics'],'levels':report['levels'],'protected_hash':configuration['source_identity']['protected_hash'],'claim':report['claim'],
        'audit_scope':'V2_STRUCTURAL_REPLAY_SURFACE_NOVELTY_RECORDS_ASSESSMENTS_PROTECTED_DECISIONS_NOT_OPERATOR_WEIGHT_RESAMPLING'}


def core_documents(directory):
    root=Path(directory);result={}
    for pattern in ('benchmark.json','state.json','stable/*/*.json','experiments/*/*.json','campaigns/*/*.json'):
        for path in root.glob(pattern):
            if path.is_symlink():raise ValueError('CORE_EVIDENCE_SYMLINK')
            result[path.relative_to(root).as_posix()]=json.loads(path.read_bytes())
    return result


def lineage_records_before(state,contract):
    """Records the lineage held before this campaign was admitted (prior novelty set)."""
    from gaia.autonomy.lineage import LineageStore
    if not contract.get('lineage_id'):return []
    lineage=LineageStore(state,contract['lineage_id']);result=[]
    for ev in lineage.events():
        if ev['kind']=='CAMPAIGN_ADMITTED'and ev['payload']['campaign_id']==contract['campaign_id']:break
        if ev['kind']=='EXPERIMENT_RECORDED':
            value=json.loads((lineage.root/'records'/(ev['payload']['record_ref']['hash']+'.json')).read_bytes())
            if digest({k:v for k,v in value.items()if k!='record_hash'})!=value['record_hash']:raise ValueError('LINEAGE_RECORD_CORRUPTED')
            result.append(value)
    return result


def audit_campaign(root,state,identifier):
    store=CampaignStore(state,identifier);configuration=store.read('configuration');contract=store.read('contract')
    path=Path(root)/configuration['engine_config']['workload']['state_dir'];core=core_documents(path)if(path/'benchmark.json').exists()else None
    intelligence=None
    if contract.get('surface')=='local_inference':
        from gaia.local_intelligence.store import IntelligenceStore
        intelligence=IntelligenceStore(Path(root)/configuration['intelligence_state'])
    result=audit_data(contract,configuration,store.events(),get_artifacts(store),core=core,lineage_records=lineage_records_before(state,contract),intelligence=intelligence)
    from gaia.cognition.store import CognitiveStore
    from tools.audit_cognition import audit_trace
    from gaia.autonomy.lineage import LineageStore
    cognition=CognitiveStore(LineageStore(state,contract['lineage_id']).subsystems if contract.get('lineage_id')else store.root/'subsystems');cognitive=[]
    for r in result_review_refs(store.events()):
        review=store.get(r);trace=review['cognitive_trace']
        cognitive.append(audit_trace(cognition,trace))
        if review['cognitive_result']['payload']['authority']!='NONE':raise ValueError('COGNITIVE_AUTHORITY_ESCALATION')
    result['cognitive_trace_audits']=cognitive
    if core:
        from gaia.store import Store
        from gaia.ledger import verify_ledger
        ledger=verify_ledger(Store(root,configuration['engine_config']['workload']['state_dir']))
        if not ledger['ok']:raise ValueError('CPU_LEDGER_INVALID')
        result['cpu_ledger_valid']=True
    return result


def result_review_refs(events):
    return list({s['state']['review_ref']['id']:s['state']['review_ref']for s in events if'review_ref'in s['state']}.values())


def audit_bundle(directory):
    root=Path(directory);manifest=json.loads((root/'manifest.json').read_bytes());documents={};total=0
    if manifest['schema']!='gaia_closed_loop_bundle_v1'or manifest['hash']!=digest({k:v for k,v in manifest.items()if k!='hash'}):raise ValueError('BUNDLE_MANIFEST_HASH')
    for name,sha in manifest['files'].items():
        path=root/name;relative=PurePosixPath(name)
        if relative.is_absolute()or'..'in relative.parts or path.is_symlink()or not path.resolve().is_relative_to(root.resolve()):raise ValueError('BUNDLE_PATH_ESCAPE')
        total+=path.stat().st_size
        if total>64*2**20:raise ValueError('BUNDLE_SIZE_LIMIT')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('BUNDLE_FILE_HASH')
        documents[name]=json.loads(raw)
    results=[]
    for item in manifest['campaigns']:
        p=documents[item['path']];artifacts={(v['original_ref']['id']if v.get('schema')=='gaia_closed_loop_privacy_projection_v1'else v['id']):v for v in p['artifacts']}
        receipt=p['original_local_audit']
        if receipt['status']!='PASS'or receipt['campaign_id']!=p['contract']['campaign_id']or receipt['privacy_projected_evaluations']!=0:raise ValueError('ORIGINAL_LOCAL_AUDIT_REQUIRED')
        checked=audit_data(p['contract'],p['configuration'],p['events'],artifacts,core=p['core'],allow_privacy_projections=True)
        from tools.audit_cognition import audit_trace
        from gaia.cognition.schema import validate as valid_cognition
        cognitive_records={v['id']:valid_cognition(v)for v in p['cognition_records']}
        class CognitiveBundle:
            def get(self,identifier,kind):
                v=cognitive_records.get(identifier)
                if v is None or v['kind']!=kind:raise FileNotFoundError('MISSING_COGNITIVE_BUNDLE_RECORD')
                return v
        cognitive=[]
        for review_ref in result_review_refs(p['events']):
            review=artifacts[review_ref['id']]['payload']
            if review['cognitive_result']!=cognitive_records[review['cognitive_result']['id']]or review['cognitive_trace']!=cognitive_records[review['cognitive_trace']['id']]:raise ValueError('COGNITIVE_BUNDLE_BINDING')
            cognitive.append(audit_trace(CognitiveBundle(),review['cognitive_trace']))
        checked['cognitive_trace_audits']=cognitive;results.append(checked)
    if {r['mode']for r in results}!={'DRY_RUN','SHADOW','CONTROLLED_AUTONOMOUS'}or any(r['report_status']!='PASS'for r in results):raise ValueError('CERTIFICATION_MODES_NOT_PASSED')
    return {'status':'PASS','campaigns':results,'files':len(documents),'bytes':total}


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--bundle',type=Path);g.add_argument('--state-dir',type=Path)
    p.add_argument('--campaign');p.add_argument('--output',type=Path);a=p.parse_args()
    try:
        result={'schema':'gaia_closed_loop_audit_v1','status':'PASS','source_policy':source_policy(),
            'evidence':audit_bundle(a.bundle)if a.bundle else audit_campaign(ROOT,a.state_dir,a.campaign)}
        result['hash']=digest(result)
        if a.output:
            with a.output.open('xb')as f:f.write(canonical_json(result))
        print(json.dumps(result,indent=2));return 0
    except (OSError,ValueError,KeyError,TypeError,AttributeError):print('Closed-loop audit: FAIL');return 2


if __name__=='__main__':raise SystemExit(main())
