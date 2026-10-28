"""Strict cognitive task and evidence envelopes, without executable model fields."""
from datetime import datetime,timezone
import re
from ..provenance import canonical_json,digest

TYPES=('EXPLAIN','SUMMARIZE','SYNTHESIZE','COMPARE','ANALYZE','PLAN','ANSWER_FROM_EVIDENCE')
AUTHORITIES=('READ_ONLY','NETWORK_READ','LOCAL_COMPUTE','SIDE_EFFECT','PRIVILEGED')
FORBIDDEN=('shell','filesystem','credentials','publication','rollback','mutation','installation','source_edit','evaluator_change','permission_change')
KINDS=('TASK','EVIDENCE','CONTEXT','PROPOSAL','VALIDATION','TOOL_RESULT','MODEL_TURN','PLAN','RESULT','TRACE',
       'CONVERSATION','CHAT_TURN','CHAT_FAILURE','RESEARCH_AGENDA','RESEARCH_DIALOGUE','RESEARCH_COMPARISON','RESEARCH_CAMPAIGN')
SCHEMA='gaia_cognition_artifact_v1'


def safe_text(text,maximum=2000):
    if not isinstance(text,str)or len(text)>maximum or any(ord(c)<32 and c not in '\n\t'for c in text):raise ValueError('INVALID_BOUNDED_TEXT')
    if re.search(r'-----BEGIN .*PRIVATE KEY|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}|\bAKIA[A-Z0-9]{16}\b|(?:password|api_key|access_token|secret)\s*[=:]\s*\S+|/home/[^/\s]+|/Users/[^/\s]+',text,re.I):raise ValueError('PRIVATE_INPUT_REJECTED')
    return text


def seal(kind,payload,created_at=None):
    if kind not in KINDS:raise ValueError('UNKNOWN_COGNITIVE_KIND')
    value={'schema':SCHEMA,'kind':kind,'created_at':created_at or datetime.now(timezone.utc).isoformat(),
           'authority':'DATA_ONLY','payload':payload}
    value['id']='cg'+digest(value)[:24];value['hash']=digest(value)
    return validate(value)


def validate(value):
    if not isinstance(value,dict)or set(value)!={'schema','kind','created_at','authority','payload','id','hash'}or value['schema']!=SCHEMA or value['kind']not in KINDS or value['authority']!='DATA_ONLY':raise ValueError('INVALID_COGNITIVE_ENVELOPE')
    if value['id']!='cg'+digest({k:v for k,v in value.items()if k not in ('id','hash')})[:24]or value['hash']!=digest({k:v for k,v in value.items()if k!='hash'}):raise ValueError('COGNITIVE_HASH_MISMATCH')
    if datetime.fromisoformat(value['created_at']).tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    canonical_json(value);return value


def ref(value):return {'id':value['id'],'hash':value['hash']}


def task(objective,task_type,context_refs,*,allowed_tools=None,resource_budget=None,created_at=None):
    from .policy import settings
    cfg=settings();limits={k:cfg[k]for k in ('max_steps','max_tool_calls','max_input_tokens','max_output_tokens','retry_limit','max_duration')}
    limits.update(resource_budget or {})
    value={'schema':'gaia_cognitive_task_v1','objective':objective,'task_type':task_type,
        'allowed_tools':sorted(set(allowed_tools if allowed_tools is not None else[r['tool_id']for r in context_refs])),
        'forbidden_actions':list(FORBIDDEN),'context_refs':context_refs,
        'evidence_requirements':{'grounding_required':True,'minimum_sources':1,'required_fields':[]},'resource_budget':limits,
        'network_authorization':False,'execution_policy':'BOUNDED_READ_ONLY','result_schema':'gaia_cognitive_result_v1',
        'created_at':created_at or datetime.now(timezone.utc).isoformat()}
    value['task_id']='ct'+digest(value)[:24];value['hash']=digest(value);return validate_task(value)


def validate_task(value):
    from .policy import settings
    keys={'schema','task_id','objective','task_type','allowed_tools','forbidden_actions','context_refs','evidence_requirements','resource_budget','network_authorization','execution_policy','result_schema','created_at','hash'}
    if not isinstance(value,dict)or set(value)!=keys or value['schema']!='gaia_cognitive_task_v1'or value['task_type']not in TYPES:raise ValueError('INVALID_TASK_SCHEMA')
    safe_text(value['objective'],1200)
    if not value['objective'].strip():raise ValueError('EMPTY_OBJECTIVE')
    if value['forbidden_actions']!=list(FORBIDDEN)or value['execution_policy']!='BOUNDED_READ_ONLY'or value['network_authorization']is not False or value['result_schema']!='gaia_cognitive_result_v1':raise ValueError('TASK_AUTHORITY_ESCALATION')
    if not isinstance(value['allowed_tools'],list)or len(value['allowed_tools'])>7 or len(set(value['allowed_tools']))!=len(value['allowed_tools'])or any(not isinstance(x,str)or not re.fullmatch(r'[a-z_]+\.[a-z_]+',x)for x in value['allowed_tools']):raise ValueError('INVALID_TOOL_SET')
    if not isinstance(value['context_refs'],list)or len(value['context_refs'])>24:raise ValueError('CONTEXT_REFERENCE_BOUND')
    for r in value['context_refs']:
        if set(r)!={'tool_id','id','hash'}or r['tool_id']not in value['allowed_tools']or not re.fullmatch(r'cg[a-f0-9]{24}',r['id'])or not re.fullmatch(r'[a-f0-9]{64}',r['hash']):raise ValueError('INVALID_TASK_REFERENCE')
    if len({r['id']for r in value['context_refs']})!=len(value['context_refs']):raise ValueError('DUPLICATE_CONTEXT_REFERENCE')
    e=value['evidence_requirements']
    if set(e)!={'grounding_required','minimum_sources','required_fields'}or e['grounding_required']is not True or type(e['minimum_sources'])is not int or not 1<=e['minimum_sources']<=8:raise ValueError('INVALID_GROUNDING_POLICY')
    if not isinstance(e['required_fields'],list)or len(e['required_fields'])>8 or any(not isinstance(v,str)or not re.fullmatch(r'[A-Za-z0-9_.]{1,150}',v)for v in e['required_fields']):raise ValueError('INVALID_REQUIRED_FIELDS')
    cfg=settings();b=value['resource_budget']
    if set(b)!={'max_steps','max_tool_calls','max_input_tokens','max_output_tokens','retry_limit','max_duration'}or any(type(v)is not int or not (0 if k=='retry_limit'else 1)<=v<=cfg[k]for k,v in b.items()):raise ValueError('INVALID_TASK_BUDGET')
    if datetime.fromisoformat(value['created_at']).tzinfo is None:raise ValueError('TIMEZONE_REQUIRED')
    if value['task_id']!='ct'+digest({k:v for k,v in value.items()if k not in ('task_id','hash')})[:24]or value['hash']!=digest({k:v for k,v in value.items()if k!='hash'}):raise ValueError('TASK_HASH_MISMATCH')
    return value
