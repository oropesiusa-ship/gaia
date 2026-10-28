"""Data-only research agenda contracts and the deliberately simple baseline selector."""
import hashlib
import json
import re

from .schema import safe_text
from .chat_quality import OBJECTIVE_TASKS
from ..provenance import canonical_json


SCHEMA='gaia_research_agenda_v1'
OBSERVATION_SCHEMA='gaia_benchmark_observation_v1'
MAX_MODEL_RUNS=12
MAX_DURATION_S=600
MAX_TOTAL_TOKENS=32768


def _source(value):
    if not isinstance(value,dict)or set(value)!={'id','sha256'}:raise ValueError('INVALID_RESEARCH_SOURCE')
    safe_text(value['id'],160)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',value['id'])or not re.fullmatch(r'[a-f0-9]{64}',value['sha256']):raise ValueError('INVALID_RESEARCH_SOURCE')
    return value


def _reference(source,pointer):return {'source':dict(source),'pointer':pointer}


class BenchmarkObservation:
    """Strict projection of scored failures; generated text is never reinterpreted."""
    @staticmethod
    def from_bytes(raw,source_id):
        if not isinstance(raw,bytes)or len(raw)>4*2**20:raise ValueError('BENCHMARK_INPUT_BOUND')
        try:document=json.loads(raw)
        except (ValueError,TypeError):raise ValueError('INVALID_BENCHMARK_JSON')from None
        return BenchmarkObservation.from_document(document,{'id':source_id,'sha256':hashlib.sha256(raw).hexdigest()})

    @staticmethod
    def from_document(document,source):
        _source(source)
        if not isinstance(document,dict)or document.get('schema')!='gaia_1_2_memory_quality_evidence_v1':raise ValueError('UNSUPPORTED_BENCHMARK_EVIDENCE')
        contracts={v['id']:v for v in OBJECTIVE_TASKS}
        memory_contracts={
            'within_conversation_recall':{'prompt':'¿Cuál es el código de sesión? Responde sólo con el código.','exact':'DELTA_314'},
            'fact_update':{'prompt':'¿Cuál es mi zona preferida vigente? Responde sólo con la zona.','exact':'SUR_20'},
            'cross_conversation_recall':{'prompt':'¿Cuál es la clave recuperable del proyecto ORION? Responde sólo con la clave.','exact':'NEBULA_77'}}
        all_contracts={**contracts,**memory_contracts};workload_ref={'id':'chat_quality.OBJECTIVE_TASKS','sha256':hashlib.sha256(
            canonical_json(all_contracts)).hexdigest()}
        issues={}
        refs=[]
        for section in ('baseline','memory'):
            rows=document.get(section,{}).get('rows')
            if not isinstance(rows,list):raise ValueError('INVALID_BENCHMARK_ROWS')
            for index,row in enumerate(rows):
                objective=row.get('objective')
                if objective is None:continue
                if not isinstance(objective,dict)or type(objective.get('pass'))is not bool:raise ValueError('INVALID_OBJECTIVE_RESULT')
                task_id=row.get('task');category=row.get('category')
                if not isinstance(task_id,str)or not isinstance(category,str):raise ValueError('INVALID_OBJECTIVE_IDENTITY')
                pointer=f'/{section}/rows/{index}/objective';reference=_reference(source,pointer);refs.append(reference)
                issue=issues.setdefault(task_id,{'task_id':task_id,'category':category,'failure_count':0,
                    'format_failure_count':0,'evidence_refs':[],'evidence_details':[]})
                if issue['category']!=category:raise ValueError('INCONSISTENT_OBJECTIVE_CATEGORY')
                failed=objective['pass']is False
                format_failed=objective.get('format_pass')is False
                if failed:issue['failure_count']+=1
                if format_failed:issue['format_failure_count']+=1
                if failed or format_failed:
                    issue['evidence_refs'].append(reference);contract=all_contracts.get(task_id,{})
                    expected=contract.get('expected',contract.get('exact'))
                    observed=row.get('text');safe_text(observed,2000)
                    issue['evidence_details'].append({'row_pointer':f'/{section}/rows/{index}','objective_pointer':pointer,
                        'prompt':contract.get('prompt'),'expected':expected,'observed':observed,'score_reason':objective.get('reason'),
                        'workload_ref':workload_ref})
        values=sorted((v for v in issues.values()if v['failure_count']or v['format_failure_count']),key=lambda v:v['task_id'])
        return {'schema':OBSERVATION_SCHEMA,'source':dict(source),'workload_ref':workload_ref,'issues':values,'valid_evidence_refs':refs,
                'interpretation':'OBJECTIVE_FIELDS_ONLY','authority':'NONE'}


def _priority(issue):return (-issue['failure_count'],-issue['format_failure_count'],issue['task_id'])


def _hypothesis(issue,rank):
    refs=[dict(v)for v in issue['evidence_refs']]
    problem=(f"{issue['task_id']} failed {issue['failure_count']} objective runs and "
             f"{issue['format_failure_count']} strict-format checks.")
    return {'id':f'h{rank}','problem':problem,'evidence_refs':refs,
        'causal_hypothesis':'The model may not reliably preserve the task constraint through generation; this is unverified and is not a finding.',
        'proposed_change':'Compare the frozen task unchanged against one pre-registered instruction-adapter variant; do not change scoring or expected output.',
        'prediction':'The variant increases exact objective passes without reducing any currently passing frozen task.',
        'success_metric':{'name':'exact_objective_passes','criterion':'variant_passes >= control_passes + 1 and regressions == 0','evaluator':'FROZEN_EXISTING'},
        'budget':{'max_model_runs':4,'max_duration_s':180,'max_total_tokens':8192},
        'authority_required':'LOCAL_COMPUTE','uncertainties':['Only two observations per configuration are available.','The evidence does not isolate a causal mechanism.'],
        'stop_conditions':['Stop if the frozen evaluator or task changes.','Stop on any regression in a currently passing task.','Stop when the budget is exhausted.']}


def deterministic_agenda(observed):
    if not isinstance(observed,dict)or observed.get('schema')!=OBSERVATION_SCHEMA:raise ValueError('INVALID_BENCHMARK_OBSERVATION')
    ordered=sorted(observed['issues'],key=_priority)
    agenda=[{'rank':n,'task_id':v['task_id'],'category':v['category'],'failure_count':v['failure_count'],
             'format_failure_count':v['format_failure_count'],'evidence_refs':[dict(r)for r in v['evidence_refs']]}
            for n,v in enumerate(ordered,1)]
    if not agenda:
        value={'schema':SCHEMA,'selector':'DETERMINISTIC_BASELINE_V1','authority':'NONE','proposal_authority':'NONE',
            'decision':'STOP','reason':'INSUFFICIENT_FAILURE_EVIDENCE','agenda':[],'hypotheses':[],'critique':[],
            'experiment':None,'source':dict(observed['source'])}
    else:
        hypotheses=[_hypothesis(v,n)for n,v in enumerate(ordered,1)]
        selected=hypotheses[0]
        value={'schema':SCHEMA,'selector':'DETERMINISTIC_BASELINE_V1','authority':'NONE','proposal_authority':'NONE',
            'decision':'CONTINUE','reason':'OBJECTIVE_FAILURES_OBSERVED','agenda':agenda,'hypotheses':hypotheses,
            'critique':[{'hypothesis_id':selected['id'],'verdict':'UNVERIFIED','contradictions':[],
                'risks':['Prompt sensitivity may not generalize.','A small sample can produce a false improvement.'],
                'insufficient_evidence':['No causal ablation has been run.']}],
            'experiment':{'id':'exp1','hypothesis_id':selected['id'],'protocol':['Run the frozen workload once as control.','Run the same frozen workload with the pre-registered adapter variant.','Score both with the unchanged objective evaluator.','Report every pass, failure, latency and token count.'],
                'success_metric':dict(selected['success_metric']),'budget':dict(selected['budget']),'authority_required':'LOCAL_COMPUTE',
                'execute':False,'network_requests':0,'source_changes':0,'evaluator_changes':0,'promotion_allowed':False},
            'source':dict(observed['source'])}
    return validate_research_artifact(value,observed=observed)


def validate_research_artifact(value,observed=None):
    keys={'schema','selector','authority','proposal_authority','decision','reason','agenda','hypotheses','critique','experiment','source'}
    if not isinstance(value,dict)or set(value)!=keys or value['schema']!=SCHEMA or value['selector']!='DETERMINISTIC_BASELINE_V1':raise ValueError('INVALID_RESEARCH_ARTIFACT')
    _source(value['source'])
    if value['authority']!='NONE'or value['proposal_authority']!='NONE':raise ValueError('RESEARCH_AUTHORITY_ESCALATION')
    if value['decision']not in ('STOP','CONTINUE')or not isinstance(value['agenda'],list)or not isinstance(value['hypotheses'],list)or not isinstance(value['critique'],list):raise ValueError('INVALID_RESEARCH_DECISION')
    valid_refs=None
    if observed is not None:
        if observed.get('source')!=value['source']:raise ValueError('RESEARCH_SOURCE_MISMATCH')
        valid_refs={(r['pointer'],r['source']['sha256'])for r in observed['valid_evidence_refs']}
    for hypothesis in value['hypotheses']:
        required={'id','problem','evidence_refs','causal_hypothesis','proposed_change','prediction','success_metric','budget','authority_required','uncertainties','stop_conditions'}
        if not isinstance(hypothesis,dict)or set(hypothesis)!=required:raise ValueError('INVALID_RESEARCH_HYPOTHESIS')
        for field in ('problem','causal_hypothesis','proposed_change','prediction'):safe_text(hypothesis[field],1000)
        if hypothesis['authority_required']!='LOCAL_COMPUTE'or not hypothesis['evidence_refs']:raise ValueError('INVALID_RESEARCH_AUTHORITY')
        metric=hypothesis['success_metric']
        if not isinstance(metric,dict)or set(metric)!={'name','criterion','evaluator'}or metric['evaluator']!='FROZEN_EXISTING':raise ValueError('INVALID_RESEARCH_METRIC')
        for field in ('uncertainties','stop_conditions'):
            if not isinstance(hypothesis[field],list)or not hypothesis[field]or len(hypothesis[field])>8:raise ValueError('INVALID_RESEARCH_HYPOTHESIS')
            for text in hypothesis[field]:safe_text(text,500)
        budget=hypothesis['budget']
        if set(budget)!={'max_model_runs','max_duration_s','max_total_tokens'}or any(type(v)is not int for v in budget.values())or not(1<=budget['max_model_runs']<=MAX_MODEL_RUNS and 1<=budget['max_duration_s']<=MAX_DURATION_S and 1<=budget['max_total_tokens']<=MAX_TOTAL_TOKENS):raise ValueError('RESEARCH_BUDGET_EXCEEDED')
        for reference in hypothesis['evidence_refs']:
            _source(reference.get('source'))
            if reference['source']!=value['source']or not isinstance(reference.get('pointer'),str)or not re.fullmatch(r'/(baseline|memory)/rows/[0-9]+/objective',reference['pointer'])or valid_refs is not None and (reference['pointer'],reference['source']['sha256'])not in valid_refs:raise ValueError('INVALID_RESEARCH_REFERENCE')
    for rank,item in enumerate(value['agenda'],1):
        if not isinstance(item,dict)or set(item)!={'rank','task_id','category','failure_count','format_failure_count','evidence_refs'}or item['rank']!=rank:raise ValueError('INVALID_RESEARCH_AGENDA')
        if type(item['failure_count'])is not int or type(item['format_failure_count'])is not int or min(item['failure_count'],item['format_failure_count'])<0:raise ValueError('INVALID_RESEARCH_AGENDA')
        for reference in item['evidence_refs']:
            if reference['source']!=value['source']or not re.fullmatch(r'/(baseline|memory)/rows/[0-9]+/objective',reference.get('pointer',''))or valid_refs is not None and (reference['pointer'],reference['source']['sha256'])not in valid_refs:raise ValueError('INVALID_RESEARCH_REFERENCE')
    hypothesis_ids={v['id']for v in value['hypotheses']}
    if len(hypothesis_ids)!=len(value['hypotheses']):raise ValueError('DUPLICATE_RESEARCH_HYPOTHESIS')
    for critique in value['critique']:
        if not isinstance(critique,dict)or set(critique)!={'hypothesis_id','verdict','contradictions','risks','insufficient_evidence'}or critique['hypothesis_id']not in hypothesis_ids or critique['verdict']!='UNVERIFIED':raise ValueError('INVALID_RESEARCH_CRITIQUE')
        for field in ('contradictions','risks','insufficient_evidence'):
            if not isinstance(critique[field],list)or len(critique[field])>8:raise ValueError('INVALID_RESEARCH_CRITIQUE')
            for text in critique[field]:safe_text(text,500)
    experiment=value['experiment']
    if value['decision']=='STOP':
        if value['hypotheses']or value['agenda']or experiment is not None or value['reason']!='INSUFFICIENT_FAILURE_EVIDENCE':raise ValueError('INVALID_RESEARCH_STOP')
    else:
        if not value['hypotheses']or not value['agenda']or not isinstance(experiment,dict):raise ValueError('INVALID_RESEARCH_CONTINUE')
        if set(experiment)!={'id','hypothesis_id','protocol','success_metric','budget','authority_required','execute','network_requests','source_changes','evaluator_changes','promotion_allowed'}or experiment['hypothesis_id']!=value['hypotheses'][0]['id']:raise ValueError('INVALID_RESEARCH_EXPERIMENT')
        if not isinstance(experiment['protocol'],list)or not 1<=len(experiment['protocol'])<=12:raise ValueError('INVALID_RESEARCH_EXPERIMENT')
        for step in experiment['protocol']:safe_text(step,500)
        if experiment.get('execute')is not False or experiment.get('network_requests')!=0 or experiment.get('source_changes')!=0 or experiment.get('evaluator_changes')!=0 or experiment.get('promotion_allowed')is not False:raise ValueError('EXECUTABLE_RESEARCH_PROPOSAL')
        if experiment.get('authority_required')!='LOCAL_COMPUTE'or experiment.get('budget')!=value['hypotheses'][0]['budget']:raise ValueError('INVALID_EXPERIMENT_BOUNDARY')
    return value
