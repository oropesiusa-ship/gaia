from datetime import datetime,timezone
import re
import uuid
from ..provenance import digest,canonical_json

MODES=('DRY_RUN','SHADOW','CONTROLLED_AUTONOMOUS')
STATES=('CREATED','OBSERVING','DIAGNOSING','PRIORITIZING','RETRIEVING','RESEARCHING','PLANNING','REVIEWING','AUTHORIZING',
        'MATERIALIZING','EXPERIMENTING','EVALUATING','LEARNING','PROMOTING','VERIFYING','ROLLING_BACK','REEVALUATING','COMPLETED','STOPPED','FAILED','PAUSED')
FORBIDDEN=('arbitrary_source_edits','shell','evaluator_edits','benchmark_edits','policy_edits','permission_changes','package_installation','drivers_kernel','frozen_components')
SUPPORTED=('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT','REPLICATION','PARAMETER_LOCAL_SEARCH')
PROFILE={'id':'bounded_numpy_mlp_v1','read_only':True,'network_read':'EXPLICIT_BOUNDED_0_7_ONLY','local_compute':'EXISTING_BWRAP_EVALUATOR_ONLY',
         'surface':'numpy_mlp_genome_hyperparameters','promotion':'EXISTING_PUBLICATION_ONLY','rollback':'EXISTING_ROLLBACK_ONLY','permission_expansion':False,
         'compute_budget_unit':'ELAPSED_LOCAL_CAMPAIGN_SECONDS_INCLUDING_INITIALIZATION_AND_COGNITION_NOT_CPU_SECONDS'}
# v2 closes the 0.6 classes that are materializable on a contracted surface; v1 stays exact for 1.0 audit.
SUPPORTED_V2=SUPPORTED+('EXPLORATION','DISCRIMINATION','KNOWLEDGE_VALIDATION','EXPLOITATION')
PROFILE_INFERENCE={'id':'bounded_inference_config_v1','read_only':True,'network_read':'NONE','local_compute':'EXISTING_0_8_ISOLATED_RUNTIME_ONLY',
         'surface':'local_inference_stack_configuration','promotion':'TRANSACTIONAL_SELECTION_POINTER_ONLY','rollback':'PREVIOUS_SELECTION_POINTER_ONLY',
         'permission_expansion':False,'model_or_weight_changes':False,'downloads_or_installation':False,
         'compute_budget_unit':'ELAPSED_LOCAL_CAMPAIGN_SECONDS_INCLUDING_INITIALIZATION_AND_COGNITION_NOT_CPU_SECONDS'}
STOPPING_V2=['OBJECTIVE_VERIFIED','NO_SIGNIFICANT_TARGET','NO_AUTHORIZED_EXPERIMENT','STOPPED_BUDGET','REPEATED_INCONCLUSIVE','HEALTH_INVALID',
             'NEEDS_HUMAN_AUTHORIZATION','OPERATOR_STOP','NO_PROGRESS','NO_NOVEL_CANDIDATE']
# Closed objective table: objective -> (surface, profile, target classes, components, promotable classes).
OBJECTIVES={
    'VERIFY_NUMPY_MLP_EXISTING_CRITERIA':('numpy_mlp',PROFILE,['CPU_RUNTIME_EFFICIENCY','UNKNOWN_REQUIRES_EVIDENCE','MEASUREMENT_QUALITY'],
        ['cpu_evolution','core','observation'],['PARAMETER_LOCAL_SEARCH','REPLICATION']),
    'IMPROVE_NUMPY_MLP_EXISTING_CRITERIA':('numpy_mlp',PROFILE,['TRAINER_OPTIMIZATION','CPU_RUNTIME_EFFICIENCY','UNKNOWN_REQUIRES_EVIDENCE','MEASUREMENT_QUALITY'],
        ['cpu_evolution','core','observation'],['PARAMETER_LOCAL_SEARCH','REPLICATION','EXPLOITATION']),
    'IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA':('local_inference',PROFILE_INFERENCE,['INFERENCE_CONFIGURATION','MEASUREMENT_QUALITY'],
        ['local_intelligence','observation'],['EXPLORATION','DISCRIMINATION','REPLICATION'])}


def artifact(kind,payload):
    v={'schema':'gaia_closed_loop_artifact_v1','kind':kind,'created_at':datetime.now(timezone.utc).isoformat(),'payload':payload,'authority':'CAMPAIGN_CONTRACT_ONLY'}
    v['id']='au'+digest(v)[:24];v['hash']=digest(v);return validate_artifact(v)


def validate_artifact(v):
    if set(v)!={'schema','kind','created_at','payload','authority','id','hash'}or v['schema']!='gaia_closed_loop_artifact_v1'or v['authority']!='CAMPAIGN_CONTRACT_ONLY':raise ValueError('INVALID_AUTONOMY_ENVELOPE')
    if v['id']!='au'+digest({k:x for k,x in v.items()if k not in ('id','hash')})[:24]or v['hash']!=digest({k:x for k,x in v.items()if k!='hash'}):raise ValueError('AUTONOMY_HASH_MISMATCH')
    canonical_json(v);return v


def ref(v):return {'id':v['id'],'hash':v['hash']}


def campaign(objective='VERIFY_NUMPY_MLP_EXISTING_CRITERIA',mode='DRY_RUN',*,limits=None,network=False,urls=(),promotion=False,lineage_id=None,
             no_progress_limit=3,replication_cap=2):
    if lineage_id is not None or objective!='VERIFY_NUMPY_MLP_EXISTING_CRITERIA':
        return campaign_v2(objective,mode,lineage_id=lineage_id,limits=limits,network=network,urls=urls,promotion=promotion,
                           no_progress_limit=no_progress_limit,replication_cap=replication_cap)
    budget={'maximum_iterations':3,'maximum_experiments':3,'maximum_wall_time':1800,'maximum_compute_budget':1200,
            'maximum_disk_budget':512*2**20,'maximum_network_research':0,'maximum_trial_seconds':20}
    budget.update(limits or {})
    v={'schema':'gaia_closed_loop_campaign_v1','campaign_id':'ac'+uuid.uuid4().hex[:24],
       'objective':objective,'mode':mode,'initial_observation_refs':[],'authority_profile':dict(PROFILE),
       'allowed_target_classes':['CPU_RUNTIME_EFFICIENCY','UNKNOWN_REQUIRES_EVIDENCE','MEASUREMENT_QUALITY'],
       'allowed_components':['cpu_evolution','core','observation'],'allowed_experiment_classes':list(SUPPORTED),'forbidden_actions':list(FORBIDDEN),
       **budget,'network_authorized':network,'research_urls':list(urls),
       'promotion_policy':{'enabled':promotion,'allowed_classes':['PARAMETER_LOCAL_SEARCH','REPLICATION'],'require_accepted':True,'require_gates':True},
       'rollback_policy':{'enabled':True,'on_regression':True,'on_invalid_health':True,'on_incomplete_publication':True},
       'stopping_conditions':['OBJECTIVE_VERIFIED','NO_SIGNIFICANT_TARGET','NO_AUTHORIZED_EXPERIMENT','STOPPED_BUDGET','REPEATED_INCONCLUSIVE','HEALTH_INVALID','NEEDS_HUMAN_AUTHORIZATION','OPERATOR_STOP'],
       'status':'CREATED','trace_hash':None,'created_at':datetime.now(timezone.utc).isoformat()}
    v['hash']=digest(v);return validate_campaign(v)


def campaign_v2(objective,mode,*,lineage_id,limits=None,network=False,urls=(),promotion=False,no_progress_limit=3,replication_cap=2):
    if objective not in OBJECTIVES:raise ValueError('CAMPAIGN_AUTHORITY_ESCALATION')
    surface,profile,classes,components,promotable=OBJECTIVES[objective]
    budget={'maximum_iterations':5,'maximum_experiments':5,'maximum_wall_time':3600,'maximum_compute_budget':3600,
            'maximum_disk_budget':512*2**20,'maximum_network_research':0,'maximum_trial_seconds':20}
    budget.update(limits or {})
    v={'schema':'gaia_closed_loop_campaign_v2','campaign_id':'ac'+uuid.uuid4().hex[:24],'lineage_id':lineage_id,
       'objective':objective,'surface':surface,'mode':mode,'initial_observation_refs':[],'authority_profile':dict(profile),
       'allowed_target_classes':list(classes),'allowed_components':list(components),'allowed_experiment_classes':list(SUPPORTED_V2),
       'forbidden_actions':list(FORBIDDEN),**budget,'network_authorized':network,'research_urls':list(urls),
       'promotion_policy':{'enabled':promotion,'allowed_classes':list(promotable),'require_accepted':True,'require_gates':True},
       'rollback_policy':{'enabled':True,'on_regression':True,'on_invalid_health':True,'on_incomplete_publication':True},
       'stopping_conditions':list(STOPPING_V2),'no_progress_limit':no_progress_limit,'replication_cap':replication_cap,
       'status':'CREATED','trace_hash':None,'created_at':datetime.now(timezone.utc).isoformat()}
    v['hash']=digest(v);return validate_campaign(v)


def validate_campaign_v2(v):
    keys={*campaign_keys(),'lineage_id','surface','no_progress_limit','replication_cap'}
    if not isinstance(v,dict)or set(v)!=keys or not re.fullmatch(r'ac[a-f0-9]{24}',v['campaign_id']):raise ValueError('INVALID_CAMPAIGN_SCHEMA')
    if v['lineage_id']is not None and not re.fullmatch(r'al[a-f0-9]{24}',v['lineage_id']):raise ValueError('INVALID_LINEAGE_ID')
    if v['objective']not in OBJECTIVES or v['mode']not in MODES or v['forbidden_actions']!=list(FORBIDDEN):raise ValueError('CAMPAIGN_AUTHORITY_ESCALATION')
    surface,profile,classes,components,promotable=OBJECTIVES[v['objective']]
    if v['surface']!=surface or v['authority_profile']!=profile:raise ValueError('CAMPAIGN_AUTHORITY_ESCALATION')
    if v['surface']=='local_inference'and v['lineage_id']is None:raise ValueError('INFERENCE_SURFACE_REQUIRES_LINEAGE')
    for key,maximum in [('maximum_iterations',5),('maximum_experiments',5),('maximum_wall_time',3600),('maximum_compute_budget',3600),('maximum_disk_budget',2*2**30),('maximum_network_research',4),('maximum_trial_seconds',30)]:
        if type(v[key])is not int or not (0 if key=='maximum_network_research'else 1)<=v[key]<=maximum:raise ValueError('INVALID_CAMPAIGN_BUDGET')
    for key,maximum in [('no_progress_limit',5),('replication_cap',3)]:
        if type(v[key])is not int or not 1<=v[key]<=maximum:raise ValueError('INVALID_CAMPAIGN_BUDGET')
    if v['maximum_compute_budget']>v['maximum_wall_time']:raise ValueError('COMPUTE_BUDGET_EXCEEDS_WALL')
    if not set(v['allowed_experiment_classes'])<=set(SUPPORTED_V2)or not set(v['allowed_components'])<=set(components)or not set(v['allowed_target_classes'])<=set(classes):raise ValueError('CAMPAIGN_SURFACE_ESCALATION')
    if type(v['network_authorized'])is not bool or(not v['network_authorized']and v['maximum_network_research'])or(surface=='local_inference'and v['network_authorized']):raise ValueError('NETWORK_NOT_AUTHORIZED')
    if not isinstance(v['research_urls'],list)or len(v['research_urls'])>4:raise ValueError('RESEARCH_URL_BOUND')
    from ..external_research.network import normalize_url
    for url in v['research_urls']:normalize_url(url)
    p=v['promotion_policy']
    if set(p)!={'enabled','allowed_classes','require_accepted','require_gates'}or type(p['enabled'])is not bool or p['require_accepted']is not True or p['require_gates']is not True or not set(p['allowed_classes'])<=set(promotable):raise ValueError('PROMOTION_POLICY_ESCALATION')
    if v['rollback_policy']!={'enabled':True,'on_regression':True,'on_invalid_health':True,'on_incomplete_publication':True}:raise ValueError('ROLLBACK_CANNOT_BE_DISABLED')
    if v['status']!='CREATED'or v['trace_hash']is not None or v['initial_observation_refs']!=[]:raise ValueError('NEW_CAMPAIGN_REQUIRED')
    if v['stopping_conditions']!=STOPPING_V2:raise ValueError('STOPPING_POLICY_CHANGED')
    if datetime.fromisoformat(v['created_at']).tzinfo is None or v['hash']!=digest({k:x for k,x in v.items()if k!='hash'}):raise ValueError('CAMPAIGN_HASH_MISMATCH')
    return v


def supported(contract):return SUPPORTED_V2 if contract.get('schema')=='gaia_closed_loop_campaign_v2'else SUPPORTED


def validate_campaign(v):
    if isinstance(v,dict)and v.get('schema')=='gaia_closed_loop_campaign_v2':return validate_campaign_v2(v)
    expected=set(campaign_keys())
    if not isinstance(v,dict)or set(v)!=expected or v['schema']!='gaia_closed_loop_campaign_v1'or not re.fullmatch(r'ac[a-f0-9]{24}',v['campaign_id']):raise ValueError('INVALID_CAMPAIGN_SCHEMA')
    if v['objective']!='VERIFY_NUMPY_MLP_EXISTING_CRITERIA'or v['mode']not in MODES or v['authority_profile']!=PROFILE or v['forbidden_actions']!=list(FORBIDDEN):raise ValueError('CAMPAIGN_AUTHORITY_ESCALATION')
    for key,maximum in [('maximum_iterations',5),('maximum_experiments',5),('maximum_wall_time',3600),('maximum_compute_budget',3600),('maximum_disk_budget',2*2**30),('maximum_network_research',4),('maximum_trial_seconds',30)]:
        if type(v[key])is not int or not (0 if key=='maximum_network_research'else 1)<=v[key]<=maximum:raise ValueError('INVALID_CAMPAIGN_BUDGET')
    if v['maximum_compute_budget']>v['maximum_wall_time']:raise ValueError('COMPUTE_BUDGET_EXCEEDS_WALL')
    if not set(v['allowed_experiment_classes'])<=set(SUPPORTED)or not set(v['allowed_components'])<={'cpu_evolution','core','observation'}or not set(v['allowed_target_classes'])<={'CPU_RUNTIME_EFFICIENCY','UNKNOWN_REQUIRES_EVIDENCE','MEASUREMENT_QUALITY'}:raise ValueError('CAMPAIGN_SURFACE_ESCALATION')
    if type(v['network_authorized'])is not bool or(not v['network_authorized']and v['maximum_network_research']):raise ValueError('NETWORK_NOT_AUTHORIZED')
    if not isinstance(v['research_urls'],list)or len(v['research_urls'])>4:raise ValueError('RESEARCH_URL_BOUND')
    from ..external_research.network import normalize_url
    for url in v['research_urls']:normalize_url(url)
    p=v['promotion_policy']
    if set(p)!={'enabled','allowed_classes','require_accepted','require_gates'}or type(p['enabled'])is not bool or p['require_accepted']is not True or p['require_gates']is not True or not set(p['allowed_classes'])<={'PARAMETER_LOCAL_SEARCH','REPLICATION'}:raise ValueError('PROMOTION_POLICY_ESCALATION')
    if v['rollback_policy']!={'enabled':True,'on_regression':True,'on_invalid_health':True,'on_incomplete_publication':True}:raise ValueError('ROLLBACK_CANNOT_BE_DISABLED')
    if v['status']!='CREATED'or v['trace_hash']is not None or v['initial_observation_refs']!=[]:raise ValueError('NEW_CAMPAIGN_REQUIRED')
    if v['stopping_conditions']!=['OBJECTIVE_VERIFIED','NO_SIGNIFICANT_TARGET','NO_AUTHORIZED_EXPERIMENT','STOPPED_BUDGET','REPEATED_INCONCLUSIVE','HEALTH_INVALID','NEEDS_HUMAN_AUTHORIZATION','OPERATOR_STOP']:raise ValueError('STOPPING_POLICY_CHANGED')
    if datetime.fromisoformat(v['created_at']).tzinfo is None or v['hash']!=digest({k:x for k,x in v.items()if k!='hash'}):raise ValueError('CAMPAIGN_HASH_MISMATCH')
    return v


def campaign_keys():
    return ('schema','campaign_id','objective','mode','initial_observation_refs','authority_profile','allowed_target_classes','allowed_components',
            'allowed_experiment_classes','forbidden_actions','maximum_iterations','maximum_experiments','maximum_wall_time','maximum_compute_budget',
            'maximum_disk_budget','maximum_network_research','maximum_trial_seconds','network_authorized','research_urls','promotion_policy','rollback_policy',
            'stopping_conditions','status','trace_hash','created_at','hash')
