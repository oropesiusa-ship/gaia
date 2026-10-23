"""Hypothesis carried end to end: deterministic expected effect and an assessment from protected evidence only."""

CONTROL_CLASSES=('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT')
REPEAT_CLASSES=('REPLICATION','KNOWLEDGE_VALIDATION')
# Closed table: target class -> expected effect of a non-control candidate.
EXPECTED={'TRAINER_OPTIMIZATION':'COST_TO_TARGET_DECREASES_QUALITY_PRESERVED',
          'CPU_RUNTIME_EFFICIENCY':'COST_TO_TARGET_DECREASES_QUALITY_PRESERVED',
          'UNKNOWN_REQUIRES_EVIDENCE':'COST_TO_TARGET_DECREASES_QUALITY_PRESERVED',
          'MEASUREMENT_QUALITY':'MEASUREMENT_VARIABILITY_CHARACTERIZED',
          'INFERENCE_CONFIGURATION':'TASK_LATENCY_DECREASES_QUALITY_GUARDS_PRESERVED'}


def carried(diagnosis,target,plan):
    """Exact hypothesis lineage from the selected target; nothing is paraphrased by a model."""
    refs=plan['target_ref']['diagnosis_refs']
    if not refs:raise ValueError('PLAN_WITHOUT_HYPOTHESIS_LINEAGE')
    ref=refs[0];hypotheses={h['hypothesis_id']:h for h in diagnosis['hypotheses']}
    h=hypotheses.get(ref['hypothesis_id'])
    if h is None or ref['diagnosis_id']!=diagnosis['diagnosis_id']:raise ValueError('HYPOTHESIS_LINEAGE_MISMATCH')
    if plan['class']in CONTROL_CLASSES:expected='NO_EFFECT_VERSUS_IDENTICAL_BASELINE'if plan['class']!='MEASUREMENT_REFINEMENT'else EXPECTED['MEASUREMENT_QUALITY']
    elif plan['class']in REPEAT_CLASSES:expected='PRIOR_RESULT_REPRODUCES_IN_CURRENT_CONTEXT'
    else:expected=EXPECTED.get(target['target_class'],'COST_TO_TARGET_DECREASES_QUALITY_PRESERVED')
    return {'diagnosis_id':diagnosis['diagnosis_id'],'diagnosis_hash':diagnosis['diagnosis_hash'],'issue_id':ref['issue_id'],
            'hypothesis_id':h['hypothesis_id'],'kind':h['kind'],'claim':h['claim'],'confidence':h['confidence'],
            'missing_evidence':list(h['missing_evidence']),'target_class':target['target_class'],'experiment_class':plan['class'],
            'expected_effect':expected,'causality':'NOT_ESTABLISHED'}


def assess(hypothesis,evaluation,classification):
    """SUPPORTED / NOT_SUPPORTED / INCONCLUSIVE from the evaluator decision; a model never decides this."""
    expected=hypothesis['expected_effect'];evidence=evaluation['evidence']
    if expected=='NO_EFFECT_VERSUS_IDENTICAL_BASELINE':
        # An identical-baseline control that is accepted as a gain signals a measurement artifact.
        status={'REJECTED':'SUPPORTED','ACCEPTED':'NOT_SUPPORTED','INCONCLUSIVE':'INCONCLUSIVE'}[classification]
        note='CONTROL_CONSISTENT'if status=='SUPPORTED'else'CONTROL_ANOMALY_MEASUREMENT_SUSPECT'if status=='NOT_SUPPORTED'else'CONTROL_UNRESOLVED'
    elif expected=='MEASUREMENT_VARIABILITY_CHARACTERIZED':
        status='SUPPORTED'if classification in ('REJECTED','ACCEPTED')and evidence.get('screen',{}).get('status','ok')=='ok'else'INCONCLUSIVE'
        note='MEASUREMENT_RECORDED_UNDER_PROTECTED_PROTOCOL'
    else:
        status={'ACCEPTED':'SUPPORTED','REJECTED':'NOT_SUPPORTED','INCONCLUSIVE':'INCONCLUSIVE'}[classification]
        note='EFFECT_UNDER_EXISTING_ACCEPTANCE_CRITERIA'
    return {'hypothesis_id':hypothesis['hypothesis_id'],'expected_effect':expected,'status':status,'note':note,
            'classification':classification,'decision':evidence.get('decision'),'evidence_id':evidence.get('id'),
            'authority':'PROTECTED_EVALUATOR_DECISION_NOT_MODEL','scope':'LOCAL_CONTRACTED_SURFACE_NOT_CAUSAL_PROOF'}
