"""Independent causal-consistency confirmation; does not modify the seven-criterion evaluator."""


def causal_consistency(issue,hypothesis):
    diagnosis=(issue.get('diagnostic_details')or{}).get('diagnosis')
    intervention=str(hypothesis.get('intervention','')).lower()
    if diagnosis=='LANGUAGE_OR_OPERATOR_REPRESENTATION_SUPPORTED':
        terms=('operator','symbolic','language','multiplication','times',' por ','representation')
        passed=any(term in ' '+intervention+' ' for term in terms)
    else:passed=bool(intervention.strip())
    return {'pass':passed,'diagnosis':diagnosis,'rule':'PRE_REGISTERED_CAUSAL_CONSISTENCY_V1','evaluator_modified':False}
