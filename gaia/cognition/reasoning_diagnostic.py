"""Frozen non-promotional diagnostic variants for the existing 17*23 failure."""
import copy
import hashlib
import json

from ..provenance import digest


VARIANTS=(
 {'id':'CONTROL_JSON','operation':'17*23','prompt':'Calcula 17 por 23. Responde únicamente JSON {"resultado":391}.','expected':391,'format':'JSON'},
 {'id':'NUMERIC_ONLY','operation':'17*23','prompt':'Calcula 17 por 23. Responde únicamente con el número, sin explicación.','expected':391,'format':'INTEGER'},
 {'id':'DECOMPOSE_JSON','operation':'17*23','prompt':'Calcula 17 por 23 descomponiendo mentalmente 23 en 20 y 3. Responde únicamente JSON con la clave resultado.','expected':391,'format':'JSON'},
)

SYMBOLIC_VARIANTS=(
 VARIANTS[0],
 {'id':'SYMBOLIC_JSON','operation':'17*23','prompt':'Calcula 17 * 23. Responde únicamente JSON con la clave resultado.','expected':391,'format':'JSON'},
 {'id':'ENGLISH_JSON','operation':'17*23','prompt':'Compute 17 times 23. Return only JSON with the key resultado.','expected':391,'format':'JSON'},
)


def score(variant,text):
    if not isinstance(text,str):return {'pass':False,'reason':'NON_TEXT'}
    if variant['format']=='INTEGER':
        value=text.strip()
        if value!=str(variant['expected']):return {'pass':False,'reason':'WRONG_VALUE'if value.replace('-','',1).replace('.','',1).isdigit()else'FORMAT'}
        return {'pass':True,'reason':'EXACT_INTEGER'}
    try:value=json.loads(text)
    except (TypeError,ValueError):return {'pass':False,'reason':'MALFORMED_JSON'}
    return {'pass':value=={'resultado':variant['expected']},'reason':'STRICT_JSON_EQUAL'}


def compare(rows):
    values={v['variant_id']:v['score']['pass']for v in rows}
    if values.get('CONTROL_JSON'):diagnosis='ORIGINAL_FAILURE_NOT_REPRODUCED'
    elif values.get('SYMBOLIC_JSON')or values.get('ENGLISH_JSON'):diagnosis='LANGUAGE_OR_OPERATOR_REPRESENTATION_SUPPORTED'
    elif values.get('NUMERIC_ONLY'):diagnosis='FORMAT_OR_INSTRUCTION_INTERACTION_SUPPORTED'
    elif values.get('DECOMPOSE_JSON'):diagnosis='DECOMPOSITION_SCAFFOLD_SUPPORTED'
    else:diagnosis='ARITHMETIC_FAILURE_PERSISTS'
    return {'schema':'gaia_reasoning_diagnostic_comparison_v1','diagnosis':diagnosis,'passes':values,'authority':'NONE',
            'promotion_allowed':False,'evaluator_changed':False,'scope':'SINGLE_EXISTING_ARITHMETIC_CASE'}


def augment_observation(observed,raw,source_id):
    """Attach independently scored diagnostic rows without rewriting original evidence."""
    if not isinstance(raw,bytes)or len(raw)>2**20:raise ValueError('DIAGNOSTIC_INPUT_BOUND')
    try:value=json.loads(raw)
    except (TypeError,ValueError):raise ValueError('INVALID_DIAGNOSTIC_JSON')from None
    if value.get('schema')!='gaia_1_2_reasoning_symbolic_diagnostic_v2'or value.get('authority')!='NONE':raise ValueError('INVALID_REASONING_DIAGNOSTIC')
    if value.get('evidence_sha256')!=digest({k:v for k,v in value.items()if k!='evidence_sha256'}):raise ValueError('DIAGNOSTIC_HASH_MISMATCH')
    if value.get('comparison',{}).get('promotion_allowed')is not False or value['comparison'].get('evaluator_changed')is not False:raise ValueError('DIAGNOSTIC_AUTHORITY_ESCALATION')
    expected=[v['id']for v in SYMBOLIC_VARIANTS];rows=value.get('rows')
    if not isinstance(rows,list)or [v.get('variant_id')for v in rows]!=expected:raise ValueError('INVALID_DIAGNOSTIC_ROWS')
    result=copy.deepcopy(observed);source={'id':source_id,'sha256':hashlib.sha256(raw).hexdigest()};refs=[]
    for index,row in enumerate(rows):
        if set(row.get('score',{}))!={'pass','reason'}or type(row['score']['pass'])is not bool:raise ValueError('INVALID_DIAGNOSTIC_SCORE')
        refs.append({'source':source,'pointer':f'/rows/{index}/score'})
    issue=next((v for v in result['issues']if v['task_id']=='reasoning'),None)
    if issue is None:raise ValueError('REASONING_ISSUE_MISSING')
    issue['research_evidence_refs']=refs;issue['diagnostic_details']={'source':source,'diagnosis':value['comparison']['diagnosis'],
        'outcomes':[{'variant_id':r['variant_id'],'observed':r['text'],'pass':r['score']['pass']}for r in rows]}
    result['valid_evidence_refs'].extend(refs);result['research_sources']=[source]
    return result
