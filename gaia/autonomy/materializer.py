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


# --------------------------------------------------------------------------- v2
# Every 0.6 class materializes through existing genome operators on the contracted
# hyperparameter surface. Previews are pure and use the same seed as execution.
HP_OPS=[name for name,op in mutate.OPS.items()if op['family']=='hp']
VARIABLE_OPS={'learning_rate':['lr'],'batch_size':['batch'],'weight_decay':['wd'],'single_factor_to_identify':HP_OPS}
INTENTIONAL=('REPLICATION','KNOWLEDGE_VALIDATION','DISCRIMINATION')
ATTEMPTS=32


class NotMaterializable(ValueError):
    def __init__(self,reason):super().__init__(reason);self.reason=reason


def hp_random_genome(base):
    """Global sampler restricted to hyperparameters of the current slots (used only for surface-bound strategy tuning)."""
    import math
    def sample(rng):
        g=copy.deepcopy(base)
        for k,choices in G.HP_CHOICES.items():g['hp'][k]=choices[rng.integers(len(choices))]
        for k,(lo,hi,mode)in G.HP_RANGES.items():
            v=math.exp(rng.uniform(math.log(lo),math.log(hi)))if mode=='log'else rng.uniform(lo,hi)
            g['hp'][k]=float(f'{v:.4g}')
        g['lits'],g['drops']={},[]
        return G.normalize(g)
    return sample


def qualified_records(plan,knowledge_records,*,exact=True):
    hashes={k['hash']for k in plan['knowledge_refs']if not exact or(not k['stale']and k['applicability']=='EXACT_CONTEXT'and k['effective_status']!='CONTRADICTED')}
    ids={rid for k in knowledge_records if k['hash']in hashes for rid in k['claim'].get('record_refs',[])}
    return [r for r in knowledge_records if r['kind']=='record'and(r['hash']in hashes or r['learning_id']in ids)]


def reference_genome(plan,records,baseline,*,accepted=False):
    target=plan['candidate_variation']['reference_configuration_hash']
    pool=[r for r in records if(not accepted or r['claim']['outcome']=='ACCEPTED')and(target is None or r['claim']['configuration_hash']==target)]
    pool.sort(key=lambda r:(r['claim']['outcome']!='ACCEPTED',r['learning_id']))
    if not pool:raise NotMaterializable('QUALIFIED_REFERENCE_CONFIGURATION_MISSING')
    cfg=pool[0]['claim']['configuration'];g=G.new_genome(cfg['hp'],cfg['slots'])
    if digest(g)!=cfg['genome_hash']or project_configuration(g)['code_variation_hash']!=cfg['code_variation_hash']:raise NotMaterializable('REFERENCE_REQUIRES_UNSUPPORTED_CODE_VARIATION')
    if g['slots']!=baseline['slots']:raise NotMaterializable('REFERENCE_OUTSIDE_HYPERPARAMETER_SURFACE')
    return g,pool[0]


def one_factor(parent,names,seed,seen,hist,strategy):
    """ONE_FACTOR variation via existing operators; operator choice uses v0.1 learned weights over the allowed subset."""
    from ..search import Strategy
    for attempt in range(ATTEMPTS):
        rng=np.random.default_rng(seed+attempt)
        weights=Strategy(strategy,rng,op_names=names)._op_weights(hist)if hist is not None else np.ones(len(names))/len(names)
        name=names[rng.choice(len(names),p=weights)]
        try:g,detail=mutate.apply(name,parent,rng)
        except (ValueError,IndexError):continue
        h=G.genome_hash(g)
        if h!=G.genome_hash(parent)and h not in seen:return g,[name],attempt
    raise NotMaterializable('NO_NOVEL_CANDIDATE')


def factorial_cell(reference,seen):
    """Fixed 2x2 lr/wd design around the reference; one untested cell per experiment."""
    lo,hi,_=G.HP_RANGES['lr'];lr=reference['hp']['lr']
    for lr_level in (max(lo,float(f'{lr*.5:.4g}')),min(hi,float(f'{lr*2:.4g}'))):
        for wd_level in (0.0,1e-4):
            g=G.normalize({**copy.deepcopy(reference),'hp':{**reference['hp'],'lr':lr_level,'wd':wd_level}})
            if G.genome_hash(g)not in seen:return g,['lr','wd'],{'lr':lr_level,'wd':wd_level}
    raise NotMaterializable('FACTORIAL_DESIGN_COMPLETE')


def materialize_v2(contract,target,plan,authorization,baseline,knowledge_records,*,iteration,seen=(),hist=None,strategy=None,preview=False):
    if not preview and(authorization is None or authorization['status']!='AUTHORIZED'or authorization['campaign_hash']!=contract['hash']
                       or authorization['plan_id']!=plan['plan_id']or authorization['target_id']!=target['target_id']):raise ValueError('MATERIALIZATION_NOT_AUTHORIZED')
    from .schema import SUPPORTED_V2
    if plan['class']not in SUPPORTED_V2 or plan['candidate_variation']['code']is not None or plan['candidate_variation']['numeric_values']is not None or plan['blocked_by']:raise ValueError('UNSUPPORTED_MATERIALIZATION')
    if baseline.get('lits')or baseline.get('drops'):raise ValueError('CODE_VARIATIONS_NOT_IN_HYPERPARAMETER_SURFACE')
    seen=set(seen);cls=plan['class'];g=copy.deepcopy(baseline);ops=[];design={}
    seed=int(digest({'lineage':contract.get('lineage_id'),'campaign':contract['campaign_id'],'iteration':iteration,'plan':plan['plan_id']})[:15],16)
    attempt=0;reference=None
    if cls in ('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT'):method='IDENTICAL_CURRENT_BASELINE'
    elif cls=='EXPLORATION':
        names=VARIABLE_OPS.get(plan['variables'][0])if len(plan['variables'])==1 else None
        if not names:raise NotMaterializable('NOT_MATERIALIZABLE_ON_SURFACE')
        g,ops,attempt=one_factor(baseline,names,seed,seen,hist,strategy or {});method='EXISTING_HP_OPERATOR_FROM_CURRENT_CHAMPION'
    elif cls=='DISCRIMINATION'and plan['design']=='CONTROLLED_FACTORIAL':
        ref_g,reference=reference_genome(plan,qualified_records(plan,knowledge_records,exact=False),baseline)
        g,ops,design=factorial_cell(ref_g,seen);method='FIXED_FACTORIAL_CELL_FROM_REFERENCE'
    elif cls=='DISCRIMINATION'and plan['candidate_variation']['kind']!='REPEAT_REFERENCE_CONFIGURATION':raise NotMaterializable('NOT_MATERIALIZABLE_ON_SURFACE')
    elif cls in ('REPLICATION','DISCRIMINATION','KNOWLEDGE_VALIDATION'):
        exact=cls=='REPLICATION'
        g,reference=reference_genome(plan,qualified_records(plan,knowledge_records,exact=exact),baseline,accepted=exact);method='EXACT_LEARNING_REFERENCE_REPEAT'
    elif cls in ('PARAMETER_LOCAL_SEARCH','EXPLOITATION'):
        ref_g,reference=reference_genome(plan,qualified_records(plan,knowledge_records),baseline,accepted=True)
        names=VARIABLE_OPS.get(plan['variables'][0],HP_OPS)if plan['variables']else HP_OPS
        g,ops,attempt=one_factor(ref_g,names,seed,seen,hist,strategy or {});method='EXISTING_HP_OPERATOR_FROM_QUALIFIED_REFERENCE'
    else:raise NotMaterializable('NOT_MATERIALIZABLE_ON_SURFACE')
    g=json.loads(canonical_json(g));source=G.render(g)
    if g['lits']or g['drops']or g['slots']!=baseline['slots']:raise ValueError('MATERIALIZER_SURFACE_ESCAPE')
    changes=[list(x)for x in G.diff(baseline,g)]
    if any(not str(x[0]).startswith('hp.')for x in changes):raise ValueError('MATERIALIZER_SURFACE_ESCAPE')
    return {'schema':'gaia_materialized_experiment_v2','plan_id':plan['plan_id'],'plan_hash':plan['plan_hash'],'target_id':target['target_id'],
        'class':cls,'surface':'numpy_mlp_genome_hyperparameters','genome':g,'genome_hash':digest(g),'candidate_hash':G.genome_hash(g),
        'trainer_hash':hashlib.sha256(source.encode()).hexdigest(),'ops':ops,'changes':changes,'method':method,'seed':seed,'attempt':attempt,
        'design':design,'intentional_repeat':cls in INTENTIONAL and method=='EXACT_LEARNING_REFERENCE_REPEAT',
        'reference':{'learning_id':reference['learning_id'],'hash':reference['hash']}if reference else None,
        'arbitrary_code_generated':False,'authorization':authorization,'baseline_hash':digest(baseline),'preview':preview}


CONTROLS=('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT')


def duplicate_v2(materialized,views,seen,repeats,cap,controls_done=()):
    """Unintended repeats are avoided; intentional repeats are capped; one control per champion and lineage."""
    if materialized['class']in CONTROLS and materialized['baseline_hash']in controls_done:
        return {'reason':'CONTROL_ALREADY_EXECUTED_FOR_CURRENT_CHAMPION','candidate_hash':materialized['candidate_hash'],
                'scope':'EQUIVALENT_EXPERIMENT_CONTEXT_ONLY_NOT_A_GENERAL_NEGATIVE_OR_ACCEPTANCE_PROOF'}
    if materialized['intentional_repeat']:
        if repeats.get(materialized['candidate_hash'],0)>=cap:
            return {'reason':'INTENTIONAL_REPEAT_CAP_REACHED','candidate_hash':materialized['candidate_hash'],'cap':cap,
                    'scope':'EQUIVALENT_EXPERIMENT_CONTEXT_ONLY_NOT_A_GENERAL_NEGATIVE_OR_ACCEPTANCE_PROOF'}
        return None
    found=rejected_duplicate(materialized,views)
    if found:return found
    if materialized['class']not in ('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT')and materialized['candidate_hash']in seen:
        return {'reason':'CONFIGURATION_ALREADY_EVALUATED_IN_LINEAGE','candidate_hash':materialized['candidate_hash'],
                'scope':'EQUIVALENT_EXPERIMENT_CONTEXT_ONLY_NOT_A_GENERAL_NEGATIVE_OR_ACCEPTANCE_PROOF'}
    return None
