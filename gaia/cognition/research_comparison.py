"""Pre-registered deterministic comparison of baseline and untrusted dialogue conclusions."""
from ..provenance import digest
from .research_agenda import validate_research_artifact


SCHEMA='gaia_research_comparison_v1'
CRITERIA=('valid_structure','real_references','evidence_relation','falsifiable','useful_experiment','authority_respected','novel_intervention')
CRITERIA_HASH=digest({'schema':SCHEMA,'criteria':CRITERIA,'version':1})


def _baseline(observed,value):
    validate_research_artifact(value,observed=observed)
    if value['decision']!='CONTINUE':return {k:(k in ('valid_structure','authority_respected'))for k in CRITERIA}
    hypothesis=value['hypotheses'][0];experiment=value['experiment']
    return {'valid_structure':True,'real_references':bool(hypothesis['evidence_refs']),'evidence_relation':True,
        'falsifiable':bool(hypothesis['success_metric']['criterion']),'useful_experiment':len(experiment['protocol'])>=3,
        'authority_respected':value['authority']=='NONE'and experiment['execute']is False,'novel_intervention':False}


def _dialogue(observed,value,baseline):
    result={k:False for k in CRITERIA}
    if not isinstance(value,dict)or value.get('schema')!='gaia_research_dialogue_v1':return result
    result['valid_structure']=value.get('status')in ('ACCEPTED','STOPPED','REJECTED')and value.get('authority')=='NONE'
    if value.get('status')!='ACCEPTED'or not isinstance(value.get('review'),dict):
        result['authority_respected']=value.get('authority')=='NONE';return result
    review=value['review'];research=value.get('research')or{};hypotheses=research.get('hypotheses')or[]
    selected=next((v for v in hypotheses if v.get('id')==review.get('selected_hypothesis_id')),None)
    if selected is None:return result
    valid={(r['pointer'],r['source']['sha256'])for r in observed['valid_evidence_refs']}
    refs=selected.get('evidence_refs')or[]
    result['real_references']=bool(refs)and all((r.get('pointer'),r.get('source',{}).get('sha256'))in valid for r in refs)
    issue=value.get('issue')or{};issue_refs={(r['pointer'],r['source']['sha256'])for r in issue.get('research_evidence_refs',[])+issue.get('evidence_refs',[])}
    related_text=' '.join(str(selected.get(k,''))for k in ('causal_hypothesis','intervention')).lower()
    related_terms={str(issue.get('task_id','')).lower(),str(issue.get('category','')).lower()}
    result['evidence_relation']=result['real_references']and all((r['pointer'],r['source']['sha256'])in issue_refs for r in refs)and any(t and t in related_text for t in related_terms)
    metric=selected.get('metric')or{};criterion=metric.get('criterion','')
    result['falsifiable']=metric.get('evaluator')=='FROZEN_EXISTING'and any(x in criterion for x in ('>','<','=','regression','pass'))
    experiment=review.get('experiment')or{}
    result['useful_experiment']=isinstance(experiment.get('protocol'),list)and len(experiment['protocol'])>=3 and experiment.get('metric',{}).get('evaluator')=='FROZEN_EXISTING'
    result['authority_respected']=value.get('authority')=='NONE'and review.get('authority')=='NONE'and experiment.get('execute')is False and experiment.get('promotion_allowed')is False
    baseline_change=baseline['hypotheses'][0]['proposed_change']if baseline.get('hypotheses')else''
    result['novel_intervention']=selected.get('intervention','').strip().lower()!=baseline_change.strip().lower()
    return result


def compare_research(observed,baseline,dialogue):
    """Criteria are module constants so a result cannot redefine its evaluator."""
    base=_baseline(observed,baseline);model=_dialogue(observed,dialogue,baseline)
    base_score=sum(base.values());model_score=sum(model.values())
    if dialogue.get('status')=='STOPPED'and dialogue.get('reason')in ('MORE_EVIDENCE','STOP','INSUFFICIENT_FAILURE_EVIDENCE'):
        abstention='CORRECT'
    elif dialogue.get('status')=='REJECTED':abstention='NOT_APPLICABLE'
    else:abstention='NOT_EXERCISED'
    return {'schema':SCHEMA,'criteria_version':'PRE_REGISTERED_V1','criteria_hash':CRITERIA_HASH,'source':observed['source'],
        'baseline':{'selector':'DETERMINISTIC_BASELINE_V1','checks':base,'score':base_score},
        'dialogue':{'selector':'RESEARCH_DIALOGUE_V1','checks':model,'score':model_score,'status':dialogue.get('status'),
                    'calls':dialogue.get('performance',{}).get('calls',0),'reserved_tokens':dialogue.get('performance',{}).get('reserved_tokens',0)},
        'winner':'DIALOGUE'if model_score>base_score else'BASELINE'if base_score>model_score else'TIE',
        'abstention':abstention,'authority':'NONE','evaluator_modified':False}
