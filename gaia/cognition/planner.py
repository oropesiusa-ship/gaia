"""Declarative plans only; no action dispatcher consumes a CognitivePlan."""
from .schema import safe_text
from .validator import claims_from


def validate_plan(value,context,task,registry):
    if task['task_type']!='PLAN'or set(value)!={'kind','steps'}or value['kind']!='PLAN'or not isinstance(value['steps'],list)or not 1<=len(value['steps'])<=3:raise ValueError('INVALID_PLAN_SCHEMA')
    claims=[]
    for i,step in enumerate(value['steps']):
        if not isinstance(step,dict)or set(step)!={'objective','required_evidence','proposed_tool','dependency','stop_condition'}:raise ValueError('INVALID_PLAN_STEP')
        safe_text(step['objective'],160);safe_text(step['stop_condition'],160)
        if not step['objective']or not step['stop_condition']:raise ValueError('EMPTY_PLAN_STEP')
        if step['proposed_tool']not in task['allowed_tools']or step['proposed_tool']not in registry.contracts:raise ValueError('PLAN_TOOL_DENIED')
        if registry.contracts[step['proposed_tool']].authority_level!='READ_ONLY':raise ValueError('PLAN_AUTHORITY_DENIED')
        dependencies=step['dependency']
        if not isinstance(dependencies,list)or any(type(d)is not int or not 0<=d<i for d in dependencies):raise ValueError('PLAN_DEPENDENCY_CYCLE')
        supported=claims_from(step['required_evidence'],context)
        if not supported:raise ValueError('PLAN_EVIDENCE_REQUIRED')
        claims.extend(supported)
    if len({c['evidence_refs'][0]['id']for c in claims})<task['evidence_requirements']['minimum_sources']:raise ValueError('PLAN_GROUNDING_REQUIRED')
    if any(not any(c['claim']['field'].startswith(k)for c in claims)for k in task['evidence_requirements']['required_fields']):raise ValueError('PLAN_REQUIRED_FIELDS_MISSING')
    return {'schema':'gaia_cognitive_plan_v1','steps':value['steps'],'executed':False,'authority':'DECLARATIVE_ONLY'},claims
