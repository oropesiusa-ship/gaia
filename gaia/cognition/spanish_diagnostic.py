"""Frozen non-promotional variants for the existing azul/blue failure."""
import copy
import hashlib
import json

from ..provenance import digest

VARIANTS=(
 {'id':'CONTROL_JSON','prompt':'Responde únicamente con el JSON {"color":"azul"}.','expected':{'color':'azul'},'format':'JSON'},
 {'id':'TOKEN_ONLY','prompt':'Copia exactamente esta palabra sin traducirla: azul','expected':'azul','format':'TEXT'},
 {'id':'ENGLISH_JSON','prompt':'Return exactly this JSON without translating its value: {"color":"azul"}','expected':{'color':'azul'},'format':'JSON'},
)

def score(variant,text):
    if not isinstance(text,str):return {'pass':False,'reason':'NON_TEXT'}
    if variant['format']=='TEXT':return {'pass':text.strip()==variant['expected'],'reason':'EXACT_TEXT'}
    try:value=json.loads(text)
    except (TypeError,ValueError):return {'pass':False,'reason':'MALFORMED_JSON'}
    return {'pass':value==variant['expected'],'reason':'STRICT_JSON_EQUAL'}

def compare(rows):
    values={v['variant_id']:v['score']['pass']for v in rows}
    if values['CONTROL_JSON']:diagnosis='ORIGINAL_FAILURE_NOT_REPRODUCED'
    elif values['TOKEN_ONLY']and values['ENGLISH_JSON']:diagnosis='SPANISH_INSTRUCTION_INTERACTION_SUPPORTED'
    elif values['ENGLISH_JSON']:diagnosis='SPANISH_INSTRUCTION_AND_CASING_INTERACTION_SUPPORTED'
    elif values['TOKEN_ONLY']:diagnosis='JSON_OR_INSTRUCTION_INTERACTION_SUPPORTED'
    else:diagnosis='LITERAL_VALUE_PRESERVATION_FAILURE_PERSISTS'
    return {'schema':'gaia_spanish_diagnostic_comparison_v1','diagnosis':diagnosis,'passes':values,'authority':'NONE',
        'promotion_allowed':False,'evaluator_changed':False,'scope':'SINGLE_EXISTING_SPANISH_CASE'}


def augment_observation(observed,raw,source_id):
    if not isinstance(raw,bytes)or len(raw)>2**20:raise ValueError('DIAGNOSTIC_INPUT_BOUND')
    try:value=json.loads(raw)
    except (TypeError,ValueError):raise ValueError('INVALID_DIAGNOSTIC_JSON')from None
    if value.get('schema')!='gaia_1_2_spanish_diagnostic_v2'or value.get('authority')!='NONE':raise ValueError('INVALID_SPANISH_DIAGNOSTIC')
    if value.get('evidence_sha256')!=digest({k:v for k,v in value.items()if k!='evidence_sha256'}):raise ValueError('DIAGNOSTIC_HASH_MISMATCH')
    if value.get('comparison',{}).get('promotion_allowed')is not False or value['comparison'].get('evaluator_changed')is not False:raise ValueError('DIAGNOSTIC_AUTHORITY_ESCALATION')
    expected=[v['id']for v in VARIANTS];rows=value.get('rows')
    if not isinstance(rows,list)or [v.get('variant_id')for v in rows]!=expected:raise ValueError('INVALID_DIAGNOSTIC_ROWS')
    result=copy.deepcopy(observed);source={'id':source_id,'sha256':hashlib.sha256(raw).hexdigest()};refs=[]
    for index,row in enumerate(rows):
        if set(row.get('score',{}))!={'pass','reason'}or type(row['score']['pass'])is not bool:raise ValueError('INVALID_DIAGNOSTIC_SCORE')
        refs.append({'source':source,'pointer':f'/rows/{index}/score'})
    issue=next((v for v in result['issues']if v['task_id']=='spanish'),None)
    if issue is None:raise ValueError('SPANISH_ISSUE_MISSING')
    issue['research_evidence_refs']=refs;issue['diagnostic_details']={'source':source,'diagnosis':value['comparison']['diagnosis'],
        'outcomes':[{'variant_id':r['variant_id'],'observed':r['text'],'pass':r['score']['pass']}for r in rows]}
    result['valid_evidence_refs'].extend(refs);result.setdefault('research_sources',[]).append(source)
    return result
