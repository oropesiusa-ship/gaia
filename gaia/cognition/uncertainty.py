"""Conservative external confidence; exact citations do not establish general truth."""


def assess(status,claims,all_facts,missing=None):
    by_field={};contradictions=[]
    for f in all_facts:
        key=f['field'];value=f['value']
        if key in by_field and by_field[key]['value']!=value:
            contradictions.append({'field':key,'fact_refs':[by_field[key]['fact_id'],f['fact_id']],
                'status':'POTENTIAL_CROSS_SOURCE_OR_TEMPORAL_DIFFERENCE_NOT_CAUSAL_PROOF'})
        by_field[key]=f
    return {'confidence':'LOW'if status!='OK'or contradictions or any(c['source_class']=='EXTERNAL_UNTRUSTED_EVIDENCE'for c in claims)else'MEDIUM',
        'unsupported_claims':[],'missing_evidence':missing or(['TASK_NOT_SUPPORTED_BY_AVAILABLE_EVIDENCE']if status=='INSUFFICIENT_EVIDENCE'else[]),
        'contradictions':contradictions[:12],'unresolved_questions':['Semantic completeness beyond extractive support is not established.'],
        'confidence_scope':'DETERMINISTIC_SUPPORT_POLICY_NOT_MODEL_SELF_CERTIFICATION'}
