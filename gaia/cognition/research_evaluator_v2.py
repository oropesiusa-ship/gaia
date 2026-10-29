"""Pre-registered structural and causal evaluator; V1 remains unchanged."""
from ..provenance import digest


SCHEMA='gaia_research_evaluator_v2'
CRITERIA=('valid_structure','real_references','structural_task_binding','causal_consistency','falsifiable','useful_experiment','authority_respected','novel_intervention')
CRITERIA_HASH=digest({'schema':SCHEMA,'criteria':CRITERIA,'version':2})
CAUSAL_RULES={
    'LANGUAGE_OR_OPERATOR_REPRESENTATION_SUPPORTED':('operator','symbolic','language','multiplication','times',' por ','representation'),
    'SPANISH_INSTRUCTION_AND_CASING_INTERACTION_SUPPORTED':('spanish','instruction','literal','case','casing','translation','translate','json'),
}
REQUIRED={'schema','task_id','cause','intervention','evidence_refs','prediction','metric','experiment','authority'}


def _ref_key(value):return value.get('pointer'),value.get('source',{}).get('sha256')


def evaluate_candidate(issue,candidate,baseline):
    checks={key:False for key in CRITERIA}
    if not isinstance(candidate,dict):return _result(checks)
    checks['valid_structure']=(set(candidate)==REQUIRED and candidate.get('schema')=='gaia_research_candidate_v2'
        and all(isinstance(candidate.get(key),str)and candidate[key].strip() for key in ('task_id','cause','intervention','prediction')))
    valid={_ref_key(ref)for ref in issue.get('evidence_refs',[])+issue.get('research_evidence_refs',[])}
    refs=candidate.get('evidence_refs')
    checks['real_references']=isinstance(refs,list)and bool(refs)and all(_ref_key(ref)in valid for ref in refs)
    checks['structural_task_binding']=candidate.get('task_id')==issue.get('task_id')
    diagnosis=(issue.get('diagnostic_details')or{}).get('diagnosis');terms=CAUSAL_RULES.get(diagnosis,())
    intervention=' '+str(candidate.get('intervention','')).lower()+' '
    checks['causal_consistency']=bool(terms)and any(term in intervention for term in terms)
    metric=candidate.get('metric')or{};criterion=metric.get('criterion','')
    checks['falsifiable']=metric.get('evaluator')=='FROZEN_EXISTING'and any(token in criterion for token in ('>','<','=','regression','pass'))
    experiment=candidate.get('experiment')or{};protocol=experiment.get('protocol')
    checks['useful_experiment']=isinstance(protocol,list)and len(protocol)>=3
    checks['authority_respected']=(candidate.get('authority')=='NONE'and experiment.get('execute')is False
                                   and experiment.get('promotion_allowed')is False)
    checks['novel_intervention']=str(candidate.get('intervention','')).strip().lower()!=str(baseline.get('intervention','')).strip().lower()
    return _result(checks)


def _result(checks):
    return {'schema':SCHEMA,'criteria':CRITERIA,'criteria_hash':CRITERIA_HASH,'checks':checks,'score':sum(checks.values()),
            'status':'PASS'if all(checks.values())else'FAIL','authority':'NONE','evaluator_modified_v1':False}
