"""Frozen objective chat workload; subjective samples are reported, never scored."""
import json


OBJECTIVE_TASKS=(
 {'id':'spanish','category':'SPANISH','prompt':'Responde únicamente con el JSON {"color":"azul"}.','expected':{'color':'azul'}},
 {'id':'instruction','category':'INSTRUCTION','prompt':'Escribe exactamente: TRES-PALABRAS-AHORA','exact':'TRES-PALABRAS-AHORA'},
 {'id':'reasoning','category':'REASONING','prompt':'Calcula 17 por 23. Responde únicamente JSON {"resultado":391}.','expected':{'resultado':391}},
 {'id':'coding','category':'CODING','prompt':'¿Qué imprime Python con print(sum([2,5,8]))? Responde únicamente JSON {"salida":15}.','expected':{'salida':15}},
 {'id':'hallucination','category':'HALLUCINATION','prompt':'Sin consultar fuentes ni inventar: ¿cuál es el número de serie privado de este equipo? Responde exactamente NO_SE.','exact':'NO_SE'},
)

SUBJECTIVE_TASKS=(
 {'id':'explanation','category':'SPANISH_EXPLANATION','prompt':'Explica en español qué es la recursión en dos frases para una persona principiante.'},
 {'id':'code_help','category':'CODE_HELP','prompt':'Sugiere una mejora breve para esta función Python: def doble(x): return x+x'},
)


def objective_score(task,text):
    if not isinstance(text,str):return {'pass':False,'reason':'NON_TEXT'}
    if 'exact'in task:return {'pass':text.strip()==task['exact'],'reason':'EXACT_MATCH'}
    try:value=json.loads(text)
    except (TypeError,ValueError):return {'pass':False,'reason':'MALFORMED_JSON'}
    return {'pass':value==task['expected'],'reason':'STRICT_JSON_EQUAL'}


def recall_score(text,expected,*obsolete):
    if not isinstance(text,str):return {'pass':False,'format_pass':False,'reason':'NON_TEXT'}
    normalized=text.strip()
    return {'pass':expected in normalized and not any(value in normalized for value in obsolete),
            'format_pass':normalized==expected,'reason':'EXPECTED_PRESENT_OBSOLETE_ABSENT'}
