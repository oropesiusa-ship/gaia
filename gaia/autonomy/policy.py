"""Deterministic gate; cognition/research cannot mint authority."""
import hashlib
from pathlib import Path
import time
from ..provenance import digest,bwrap_capability
from .schema import validate_campaign,SUPPORTED


def identities(root):
    root=Path(root);paths=set((root/'gaia').rglob('*.py'))
    for part in ('protected','autonomy','cognition','diagnosis','prioritization','learning','experiment_strategy','external_research','local_intelligence','observation'):
        paths.update((root/'gaia'/part).glob('*.py'))
    paths.add(root/'gaia.py');files={}
    for path in sorted(paths):
        if path.is_symlink():raise ValueError('SOURCE_SYMLINK')
        files[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'files':files,'hash':digest(files),'protected_hash':digest({k:v for k,v in files.items()if k.startswith('gaia/protected/')})}


def disk_bytes(path):
    total=0
    for p in Path(path).rglob('*'):
        if p.is_symlink():raise ValueError('CAMPAIGN_DISK_SYMLINK')
        if p.is_file():total+=p.stat().st_size
    return total


class BudgetExceeded(ValueError):pass


def budget_check(contract,current,state_path,engine_path=None,now=None):
    validate_campaign(contract);now=time.time()if now is None else now
    if current.get('started_at')is not None:
        elapsed=now-current['started_at']
        if elapsed<0 or elapsed>=min(contract['maximum_wall_time'],contract['maximum_compute_budget']):raise BudgetExceeded('STOPPED_BUDGET')
    if current.get('iteration',0)>contract['maximum_iterations']or current.get('experiments',0)>contract['maximum_experiments']or current.get('research_calls',0)>contract['maximum_network_research']or current.get('compute_reserved_s',0)>contract['maximum_compute_budget']:raise BudgetExceeded('STOPPED_BUDGET')
    if disk_bytes(state_path)+(disk_bytes(engine_path)if engine_path and Path(engine_path).exists()else 0)>=contract['maximum_disk_budget']:raise BudgetExceeded('STOPPED_BUDGET')
    return True


def authorize(contract,target,plan,review,*,remaining,integrity,sandbox):
    validate_campaign(contract);reasons=[]
    from ..experiment_strategy.model import finish_plan,GUARDS
    fields={'plan_id','plan_hash','target_ref','knowledge_refs','class','mode','design','variables','controlled_variables','baseline','candidate_variation','metrics','guards','discriminates','stopping_rules','estimates','novelty','duplication','blocked_by','rationale','rule_ids','confidence','execution','utility'}
    if set(plan)!=fields or finish_plan(plan)!=plan:return {'status':'REJECTED','reasons':['INVALID_OR_EXPANDED_PLAN_SCHEMA'],'campaign_hash':contract['hash'],'target_id':target['target_id'],'plan_id':plan.get('plan_id')}
    if plan['guards']!=GUARDS or plan['execution']!={'mode':'SHADOW','authorized':False,'executed':False,'code_generated':False}:
        reasons.append('PLAN_REQUESTS_PROTECTED_OR_AUTHORITY_CHANGE')
    if target['component_id']not in contract['allowed_components']or target['component_id']in ('gpu','appliance','protected_evaluator'):reasons.append('COMPONENT_NOT_ALLOWED')
    if target['target_class']not in contract['allowed_target_classes']or target['blocked_by']or target['priority']=='DEFER':reasons.append('TARGET_NOT_AUTHORIZED')
    if plan['class']not in contract['allowed_experiment_classes']or plan['class']not in SUPPORTED or plan['blocked_by']:reasons.append('EXPERIMENT_CLASS_NOT_AUTHORIZED')
    if plan['target_ref']['target_id']!=target['target_id']:reasons.append('TARGET_PLAN_MISMATCH')
    if plan['candidate_variation']['code']is not None or plan['candidate_variation']['numeric_values']is not None:reasons.append('FREE_FORM_EXECUTION_FORBIDDEN')
    if plan['estimates']['risk']=='HIGH'or plan['estimates']['reversibility']not in ('EASY','MODERATE'):reasons.append('RISK_OR_REVERSIBILITY')
    if plan['class']in ('REPLICATION','PARAMETER_LOCAL_SEARCH')and any(k['stale']or k['effective_status']=='CONTRADICTED'or k['applicability']!='EXACT_CONTEXT'for k in plan['knowledge_refs']):reasons.append('KNOWLEDGE_NOT_QUALIFIED')
    if not remaining:reasons.append('STOPPED_BUDGET')
    if not integrity:reasons.append('PROTECTED_OR_SOURCE_CHANGED')
    if not sandbox:reasons.append('SANDBOX_REQUIRED')
    if review.get('status')!='OK'or review.get('authority')!='NONE':reasons.append('COGNITIVE_REVIEW_INSUFFICIENT')
    return {'status':'AUTHORIZED'if not reasons else'NEEDS_HUMAN_AUTHORIZATION'if any(r in reasons for r in ('PROTECTED_OR_SOURCE_CHANGED','SANDBOX_REQUIRED','RISK_OR_REVERSIBILITY'))else'REJECTED',
            'reasons':reasons,'campaign_hash':contract['hash'],'target_id':target['target_id'],'plan_id':plan['plan_id'],
            'surface':'numpy_mlp_genome_hyperparameters','authority_source':'DETERMINISTIC_CAMPAIGN_POLICY_NOT_LLM','network_escalation':False}
