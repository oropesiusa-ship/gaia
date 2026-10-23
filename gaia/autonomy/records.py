"""Deterministic Annex B experiment record assembled from committed artifacts; no model-written fields."""
from ..provenance import digest

NEXT={'ACCEPTED':'INDEPENDENT_REPLICATION_BEFORE_ANY_PROMOTION','REJECTED':'EXPLORE_OTHER_FACTOR_OR_REGION_NOT_A_GENERAL_BAN',
      'INCONCLUSIVE':'DISCRIMINATE_WITH_ADDITIONAL_INDEPENDENT_EVIDENCE'}


def numpy_metrics(evidence):
    screen=evidence.get('screen')or{};confirm=evidence.get('confirm')or{}
    return ({'screen_cost_s':screen.get('cost_s'),'reference_cost_s':(evidence.get('trial_metrics')or[{}])[0].get('ref_cost_s'),
             'confirmation_pairs':len(confirm.get('champ_costs',[])or[]),'reason':evidence.get('reason')},
            {'final_acc':screen.get('final_acc'),'peak_rss_mb':screen.get('peak_rss_mb'),'gates_passed':evidence.get('overall_gates_passed'),
             'sandbox':screen.get('sandbox'),'promotable':evidence.get('promotable')})


def inference_metrics(evidence):
    c,b=evidence.get('candidate_dimensions')or{},evidence.get('control_dimensions')or{}
    keys=('quality_task_mean_latency_s','latency_s','decode_tokens_per_s')
    return ({**{'candidate_'+k:c.get(k)for k in keys},**{'control_'+k:b.get(k)for k in keys},'reason':evidence.get('reason')},
            {k:{'candidate':c.get(k),'control':b.get(k)}for k in ('quality','structured_output','reliability','tool_intent_accuracy','ram_bytes','vram_increment_bytes','latency_stability')})


def assemble(contract,configuration,iteration,target,plan,hypothesis,materialized,evaluation,classification,assessment,learned,selection):
    evidence=evaluation['evidence'];surface=contract.get('surface','numpy_mlp')
    primary,protection=(inference_metrics if surface=='local_inference'else numpy_metrics)(evidence)
    value={'schema':'gaia_experiment_record_v2','experiment_id':evidence.get('id'),'campaign_id':contract['campaign_id'],
        'lineage_id':contract.get('lineage_id'),'iteration':iteration,'system_version':{'source_identity_hash':configuration['source_identity']['hash'],
        'campaign_schema':contract['schema'],'version_before':evaluation['before_version'],'version_after':evaluation['after_version']},
        'component':target['component_id'],'problem':{'target_class':target['target_class'],'issue_id':hypothesis['issue_id'],
        'diagnosis_hash':hypothesis['diagnosis_hash']},'hypothesis':{k:hypothesis[k]for k in ('hypothesis_id','kind','claim','expected_effect','confidence','missing_evidence','causality')},
        'reference_state':{'baseline_hash':materialized['baseline_hash'],'version':evaluation['before_version']},
        'proposed_change':{'class':materialized['class'],'method':materialized['method'],'changes':materialized['changes'],'ops':materialized['ops'],
        'candidate_hash':materialized['candidate_hash'],'design':materialized.get('design',{}),'reference':materialized.get('reference')},
        'environment':{k:evidence.get(k)for k in ('environment_hash','experiment_manifest_hash','benchmark_hash','host_hash')if evidence.get(k)is not None},
        'screen_reference':evaluation.get('reference_used'),'primary_metrics':primary,'protection_metrics':protection,'result':{'classification':classification,'decision':evidence.get('decision'),
        'hypothesis_assessment':assessment['status'],'note':assessment['note']},
        'decision_reason':evidence.get('reason')or evidence.get('result_code'),'selection':{k:selection.get(k)for k in ('method','selected_plan_id','default_plan_id','advisory_cited_candidates')},
        'uncertainties':['CAUSALITY_NOT_ESTABLISHED','LOCAL_HOST_AND_CONTEXT_ONLY']+(['SINGLE_EXPERIMENT_NOT_REPLICATED']if classification=='ACCEPTED'else[]),
        'artifacts':{'learning_outcome':learned.get('outcome'),'learning_batch':(learned.get('batch')or{}).get('batch_id')if isinstance(learned.get('batch'),dict)else None},
        'reversal':'PREVIOUS_SELECTION_POINTER'if surface=='local_inference'else'EXISTING_V0_1_ROLLBACK_TO_BEFORE_VERSION',
        'next_step':NEXT[classification],'authority':'DETERMINISTIC_ASSEMBLY_NOT_MODEL_TEXT'}
    value['record_hash']=digest(value);return value
