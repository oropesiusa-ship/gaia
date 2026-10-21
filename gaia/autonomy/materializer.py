"""Closed symbolic plans -> existing genome mechanisms, never generated executable text."""
import copy
import hashlib
import json
import numpy as np
from .. import genome as G,mutate
from ..provenance import digest,canonical_json
from ..learning.ingestion import project_configuration
from .schema import SUPPORTED


class ExperimentMaterializer:
    def materialize(self,contract,target,plan,authorization,baseline,knowledge_records,*,iteration):
        if authorization['status']!='AUTHORIZED'or authorization['campaign_hash']!=contract['hash']or authorization['plan_id']!=plan['plan_id']or authorization['target_id']!=target['target_id']:raise ValueError('MATERIALIZATION_NOT_AUTHORIZED')
        if plan['class']not in SUPPORTED or plan['candidate_variation']['code']is not None or plan['blocked_by']:raise ValueError('UNSUPPORTED_MATERIALIZATION')
        if baseline.get('lits')or baseline.get('drops'):raise ValueError('CODE_VARIATIONS_NOT_IN_1_0_SURFACE')
        g=copy.deepcopy(baseline);ops=[];method='IDENTICAL_CURRENT_BASELINE';seed=int(digest({'campaign':contract['campaign_id'],'iteration':iteration})[:16],16)
        if plan['class']in ('REPLICATION','PARAMETER_LOCAL_SEARCH'):
            hashes={k['hash']for k in plan['knowledge_refs']if not k['stale']and k['applicability']=='EXACT_CONTEXT'and k['effective_status']!='CONTRADICTED'}
            records=[r for r in knowledge_records if r['hash']in hashes or r['learning_id']in{rid for k in knowledge_records if k['hash']in hashes for rid in k['claim'].get('record_refs',[])}]
            record=next((r for r in records if r['kind']=='record'and r['claim']['outcome']=='ACCEPTED'),None)
            if record is None:raise ValueError('QUALIFIED_REFERENCE_CONFIGURATION_MISSING')
            cfg=record['claim']['configuration'];g=G.new_genome(cfg['hp'],cfg['slots'])
            if digest(g)!=cfg['genome_hash']or project_configuration(g)['code_variation_hash']!=cfg['code_variation_hash']:raise ValueError('REFERENCE_REQUIRES_UNSUPPORTED_CODE_VARIATION')
            method='EXACT_QUALIFIED_LEARNING_REFERENCE'
            if plan['class']=='PARAMETER_LOCAL_SEARCH':
                if plan['variables']!=['learning_rate']:raise ValueError('UNSUPPORTED_LOCAL_FACTOR')
                g,detail=mutate.apply('lr',g,np.random.default_rng(seed));ops=['lr'];method='EXISTING_LR_OPERATOR_NO_WINNER_INJECTION'
        # G.render embeds a dict repr. Freeze insertion order to the canonical
        # artifact representation before hashing and before any Engine call.
        g=json.loads(canonical_json(g));source=G.render(g)
        if g['lits']or g['drops']or g['slots']!=baseline['slots']:raise ValueError('MATERIALIZER_SURFACE_ESCAPE')
        changes=[list(x)for x in G.diff(baseline,g)]
        if any(not str(x[0]).startswith('hp.')for x in changes):raise ValueError('MATERIALIZER_SURFACE_ESCAPE')
        return {'schema':'gaia_materialized_experiment_v1','plan_id':plan['plan_id'],'plan_hash':plan['plan_hash'],'target_id':target['target_id'],
            'class':plan['class'],'surface':'numpy_mlp_genome_hyperparameters','genome':g,'genome_hash':digest(g),
            'trainer_hash':hashlib.sha256(source.encode()).hexdigest(),'ops':ops,'changes':changes,'method':method,'seed':seed,
            'arbitrary_code_generated':False,'authorization':authorization,'baseline_hash':digest(baseline)}


def rejected_duplicate(materialized,views):
    for v in views:
        k=v['item']
        if v['applicability_assessment']['transferability']!='EXACT_CONTEXT'or v['effective_status']in ('CONTRADICTED','SUPERSEDED'):continue
        if materialized['genome_hash']in k['claim'].get('tested_configurations',[]):
            strong=k['claim_type']=='REJECTED_DIRECTION'and k['claim'].get('negative_reuse_scope')=='EXACT_CANDIDATE_EQUIVALENT_CONTEXT_ONLY'
            return {'learning_id':k['learning_id'],'hash':k['hash'],
                'reason':'EXACT_REJECTED_CONFIGURATION_AVOIDED'if strong else'BUDGETED_REPEAT_DEFERRED_USING_EXISTING_LEARNING',
                'scope':'EQUIVALENT_EXPERIMENT_CONTEXT_ONLY_NOT_A_GENERAL_NEGATIVE_OR_ACCEPTANCE_PROOF',
                'claim_type':k['claim_type'],'negative_reuse_scope':k['claim'].get('negative_reuse_scope')}
    return None
