"""Experimental prompt-only adapter; never changes expected outputs or evaluators."""
import re

POLICIES=('ORIGINAL','LITERAL_AND_OPERATOR_V1','EXACT_OUTPUT_AND_OPERATOR_V2','TARGETED_EXACT_AND_OPERATOR_V3')

def adapt(prompt,policy='ORIGINAL'):
    if policy not in POLICIES or not isinstance(prompt,str):raise ValueError('INVALID_INSTRUCTION_ADAPTER')
    if policy=='ORIGINAL':return {'prompt':prompt,'changes':[]}
    if policy in ('EXACT_OUTPUT_AND_OPERATOR_V2','TARGETED_EXACT_AND_OPERATOR_V3'):
        literal=re.fullmatch(r'\s*Responde únicamente con el JSON\s+(\{.*\})\s*\.?\s*',prompt,re.I)
        if literal:
            prompt='Return exactly this JSON without translating any value: '+literal.group(1)
            changes=['EXACT_JSON_WRAPPER_NORMALIZED']
        else:changes=[]
    else:changes=[]
    additions=[]
    if policy!='TARGETED_EXACT_AND_OPERATOR_V3':
        additions.append('Follow literal output tokens exactly without translating their values.');changes.append('LITERAL_OUTPUT_GUARD')
    match=re.search(r'\b([0-9]+)\s+por\s+([0-9]+)\b',prompt,re.I)
    if match:
        additions.append(f"The arithmetic operator is multiplication: {match.group(1)} * {match.group(2)}.")
        changes.append('SPANISH_MULTIPLICATION_RESTATEMENT')
    return {'prompt':prompt+('\n'+' '.join(additions) if additions else ''),'changes':changes}
