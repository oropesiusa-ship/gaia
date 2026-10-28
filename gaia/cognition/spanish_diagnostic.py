"""Frozen non-promotional variants for the existing azul/blue failure."""
import json

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
