"""External deterministic validation. Model-selected facts are exact extractive claims."""
import json
from ..provenance import canonical_json
from .schema import safe_text


def strict_json(text):
    if not isinstance(text,str)or len(text)>12000:raise ValueError('MODEL_OUTPUT_BOUND')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    try:value=json.loads(text,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    except RecursionError as exc:raise ValueError('MODEL_JSON_DEPTH_BOUND')from exc
    if not isinstance(value,dict):raise ValueError('MODEL_OBJECT_REQUIRED')
    pending=[(value,0)]
    while pending:
        node,depth=pending.pop()
        if depth>16:raise ValueError('MODEL_JSON_DEPTH_BOUND')
        if isinstance(node,dict):pending.extend((v,depth+1)for v in node.values())
        elif isinstance(node,list):pending.extend((v,depth+1)for v in node)
    return value


def proposal(value,context):
    if set(value)!={'kind','tool_id','arguments','reason','expected_information','authority_required'}or value['kind']!='TOOL':raise ValueError('INVALID_TOOL_PROPOSAL_SCHEMA')
    p={k:v for k,v in value.items()if k!='kind'}
    if not isinstance(p['arguments'],dict)or set(p['arguments'])!={'id'}:raise ValueError('INVALID_TOOL_ARGUMENTS')
    alias=p['arguments']['id']
    if not isinstance(alias,str)or alias not in context['source_aliases']:raise ValueError('INVENTED_SOURCE_REFERENCE')
    p['arguments']={'id':context['source_aliases'][alias]['id']}
    return p


def claims_from(aliases,context):
    if not isinstance(aliases,list)or len(aliases)>8 or len(set(aliases))!=len(aliases)or any(not isinstance(a,str)or a not in context['fact_aliases']for a in aliases):raise ValueError('INVENTED_FACT_REFERENCE')
    claims=[]
    for alias in aliases:
        f=context['fact_aliases'][alias]
        claims.append({'claim':{'field':f['field'],'value':f['value']},'evidence_refs':[f['evidence_ref']],
            'fact_id':f['fact_id'],'source_class':f['source_class'],'support_status':'EXACT_EXTRACTIVE_SUPPORT',
            'confidence':'LOW'if f['source_class']=='EXTERNAL_UNTRUSTED_EVIDENCE'else'MEDIUM',
            'scope':'SOURCE_REPORT_NOT_INDEPENDENT_TRUTH_OR_CAUSALITY'})
    return claims


def final(value,context,task):
    if set(value)!={'kind','status','facts'}or value['kind']!='FINAL'or value['status']not in ('OK','INSUFFICIENT_EVIDENCE'):raise ValueError('INVALID_FINAL_SCHEMA')
    claims=claims_from(value['facts'],context)
    if value['status']=='OK':
        if not claims or len({c['evidence_refs'][0]['id']for c in claims})<task['evidence_requirements']['minimum_sources']:raise ValueError('GROUNDING_REQUIREMENT_NOT_MET')
        if any(not any(c['claim']['field'].startswith(field)for c in claims)for field in task['evidence_requirements']['required_fields']):raise ValueError('REQUIRED_FIELDS_MISSING')
    elif claims:raise ValueError('INSUFFICIENT_RESULT_CANNOT_ASSERT_FACTS')
    if task['task_type']=='PLAN'and value['status']=='OK':raise ValueError('PLAN_REQUIRED')
    return claims
