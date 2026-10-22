"""Level A surface: one-factor variation of the qualified local inference stack, measured by the existing 0.8 harness.

Runtime, model and weights stay fixed by hash. Candidates are compared with a fresh control
benchmark of the current primary in the same experiment; promotion is a transactional
selection pointer and rollback re-points to the previous selection.
"""
import copy
import json
from pathlib import Path
import time
from ..provenance import digest,canonical_json
from .store import durable

KNOBS=('threads','context','gpu_layers','kv','backend')
CONTEXTS=(512,1024,2048,4096)
VARIABLE_KNOBS={'single_factor_to_identify':KNOBS,'parallelism':('threads',)}
ATTEMPTS=32


class NotMaterializable(ValueError):
    def __init__(self,reason):super().__init__(reason);self.reason=reason


def store(state):
    from ..local_intelligence.store import IntelligenceStore
    return IntelligenceStore(state)


def current(state):
    """Current primary selection, honoring the committed pointer when present."""
    from ..local_intelligence.controller import active_limits
    s=store(state);selection=s.read('current','SELECTION')
    profile=s.read(selection['payload']['host_ref']['id'],'HOST_PROFILE')
    return selection,profile,active_limits(state,profile)


def stack_identity(stack):
    core={k:v for k,v in stack.items()if k!='stack_id'}
    return 'stack-'+digest(core)[:16]


def qualified_backends(state,primary):
    values=set()
    for b in store(state).list('BENCHMARK'):
        st=b['payload']['stack']
        if(b['payload']['status']=='QUALIFIED'and b['payload']['backend_verification']['verified']
           and st['runtime_install']==primary['runtime_install']and st['model_hash']==primary['model_hash']):values.add(st['backend'])
    return sorted(values|{primary['backend']})


def grid(primary,limits,backends):
    layers=primary.get('model_metadata',{}).get(primary['model_family']+'.block_count')or 32
    values={'threads':sorted({t for t in (2,4,6,8,limits['threads'])if 1<=t<=limits['threads']}),
            'context':[c for c in CONTEXTS if 256<=c<=limits['max_context']],'kv':['f16','q8_0'],'backend':list(backends),
            'gpu_layers':sorted({0,layers//3,layers//2,(2*layers)//3,999})if primary['backend']!='CPU'else[0]}
    return values


def candidate(primary,knob,value):
    s=copy.deepcopy(primary);s[knob]=value
    if s['backend']=='CPU':s['gpu_layers']=0
    elif s['gpu_layers']==0:s['gpu_layers']=999
    s['stack_id']=stack_identity(s);return s


def within_budget(stack,limits):
    """The 0.8 adapter refuses stacks outside the active host budget; never propose one."""
    return 1<=stack['threads']<=limits['threads']and 256<=stack['context']<=limits['max_context']


def materialize(contract,target,plan,authorization,primary,limits,backends,*,iteration,seen=(),preview=False):
    if not preview and(authorization is None or authorization['status']!='AUTHORIZED'or authorization['campaign_hash']!=contract['hash']
                       or authorization['plan_id']!=plan['plan_id']or authorization['target_id']!=target['target_id']):raise ValueError('MATERIALIZATION_NOT_AUTHORIZED')
    if plan['candidate_variation']['code']is not None or plan['candidate_variation']['numeric_values']is not None or plan['blocked_by']:raise ValueError('UNSUPPORTED_MATERIALIZATION')
    cls=plan['class'];seed=int(digest({'lineage':contract['lineage_id'],'campaign':contract['campaign_id'],'iteration':iteration,'plan':plan['plan_id']})[:15],16)
    stack=copy.deepcopy(primary);changes=[];method='IDENTICAL_CURRENT_PRIMARY_STACK';attempt=0
    if cls in ('CONTROL_EXPERIMENT','BASELINE_RECONFIRMATION','MEASUREMENT_REFINEMENT'):
        if not within_budget(primary,limits):raise NotMaterializable('STACK_OUTSIDE_QUALIFIED_BUDGET')
    elif cls in ('EXPLORATION','DISCRIMINATION')and plan['candidate_variation']['kind']!='REPEAT_REFERENCE_CONFIGURATION':
        knobs=VARIABLE_KNOBS.get(plan['variables'][0])if len(plan['variables'])==1 else None
        if not knobs:raise NotMaterializable('NOT_MATERIALIZABLE_ON_SURFACE')
        import numpy as np
        values=grid(primary,limits,backends);options=[(k,v)for k in knobs for v in values[k]if v!=primary[k]]
        if not options:raise NotMaterializable('NO_NOVEL_CANDIDATE')
        order=np.random.default_rng(seed).permutation(len(options))
        for attempt,i in enumerate(order[:ATTEMPTS]):
            k,v=options[int(i)];c=candidate(primary,k,v)
            if c['stack_id']not in seen and c['stack_id']!=primary['stack_id']and within_budget(c,limits):
                stack=c;changes=[[k,primary[k],v]];method='ONE_FACTOR_QUALIFIED_STACK_VARIATION';break
        else:raise NotMaterializable('NO_NOVEL_CANDIDATE')
    else:raise NotMaterializable('NOT_MATERIALIZABLE_ON_SURFACE')
    for key in ('runtime','runtime_install','runtime_hash','model_hash','model_family','quantization'):
        if stack[key]!=primary[key]:raise ValueError('INFERENCE_SURFACE_ESCAPE')
    return {'schema':'gaia_materialized_inference_v1','plan_id':plan['plan_id'],'plan_hash':plan['plan_hash'],'target_id':target['target_id'],
        'class':cls,'surface':'local_inference_stack_configuration','stack':stack,'genome_hash':digest(stack),'candidate_hash':stack['stack_id'],
        'ops':[c[0]for c in changes],'changes':changes,'method':method,'seed':seed,'attempt':attempt,'design':{},'intentional_repeat':False,
        'reference':None,'arbitrary_code_generated':False,'model_or_weight_change':False,'authorization':authorization,
        'baseline_hash':primary['stack_id'],'preview':preview}


def decide(control,cand):
    """Existing 0.8 tolerances; quality and reliability guards precede latency, never tok/s alone."""
    from ..local_intelligence.selection import POLICY
    tol,eps=POLICY['quality_tolerance'],POLICY['relative_noise_tolerance']
    if control is None or control['latency_stability']!='STABLE':return 'deferred','CONTROL_NOT_COMPARABLE_UNDER_CURRENT_HOST_NOISE'
    if cand is None:return 'rejected','CANDIDATE_FAILED_QUALIFICATION'
    if any(cand[k]is None or control[k]is None or cand[k]<control[k]-tol for k in ('quality','structured_output','reliability','tool_intent_accuracy')):
        return 'rejected','QUALITY_OR_RELIABILITY_GUARD'
    if cand['latency_stability']!='STABLE':return 'deferred','CANDIDATE_LATENCY_NOT_STABLE'
    a,b=cand['quality_task_mean_latency_s'],control['quality_task_mean_latency_s']
    if a is None or b is None:return 'deferred','LATENCY_UNMEASURED'
    if a<b*(1-eps):return 'accepted','TASK_LATENCY_IMPROVED_BEYOND_NOISE_WITH_GUARDS'
    return 'rejected','NO_VERIFIED_TASK_LATENCY_GAIN'


def experiments_dir(lineage_root):return Path(lineage_root)/'inference'/'experiments'


def recorded(lineage_root,identifier):
    path=experiments_dir(lineage_root)/(identifier+'.json')
    return json.loads(path.read_bytes())if path.exists()else None


def execute(state,lineage_root,m,selection,profile,limits,identifier,promotion_allowed,lineage_id=None):
    """Control re-benchmark + candidate screen/full benchmark; evidence durable before any pointer change."""
    from ..local_intelligence.campaign import run_stack
    from ..local_intelligence.selection import dimensions,select
    s=store(state);start=time.perf_counter();before=selection['id']
    def bench(stack,screen=False):
        value=s.put(run_stack(stack,state,limits,screen=screen))
        dims=None
        if not screen and value['payload']['status']=='QUALIFIED'and value['payload']['backend_verification']['verified']:dims=dimensions(value)
        return value,dims
    control,control_dims=bench(selection['payload']['primary']['stack'])
    screen=None;candidate_ref=None;candidate_dims=None
    if m['candidate_hash']==selection['payload']['primary']['stack']['stack_id']:
        cand,candidate_dims=bench(m['stack']);candidate_ref={'id':cand['id'],'hash':cand['hash']}
    else:
        screen,_=bench(m['stack'],screen=True)
        if screen['payload']['status']=='SCREEN_PASSED':
            cand,candidate_dims=bench(m['stack']);candidate_ref={'id':cand['id'],'hash':cand['hash']}
    decision,reason=decide(control_dims,candidate_dims)
    evidence={'id':identifier,'decision':decision,'reason':reason,'candidate_hash':m['candidate_hash'],'stack':m['stack'],
        'control_ref':{'id':control['id'],'hash':control['hash']},'screen_ref':{'id':screen['id'],'hash':screen['hash']}if screen else None,
        'candidate_ref':candidate_ref,'control_dimensions':control_dims,'candidate_dimensions':candidate_dims,
        'benchmark_hash':control['payload']['benchmark_hash'],'host_hash':selection['payload']['host_ref']['hash'],
        'search_cost_s':time.perf_counter()-start,'promotable':decision=='accepted'and m['class']!='CONTROL_EXPERIMENT','selection_before':before,'lineage_id':lineage_id}
    durable(experiments_dir(lineage_root)/(identifier+'.json'),evidence,True)
    after=before
    if evidence['promotable']and promotion_allowed(evidence):
        previous=s.read('current','SELECTION')
        new=s.put(select([control,cand],profile,coverage=previous['payload']['coverage']))
        if new['payload']['primary']['stack']['stack_id']==m['candidate_hash']:
            s.set_pointer(new,reason='CLOSED_LOOP_PROMOTION',receipt={'experiment_id':identifier,'lineage_id':lineage_id,'candidate_hash':m['candidate_hash'],
                                                                     'previous_selection':{'id':previous['id'],'hash':previous['hash']}})
            after=new['id']
        else:evidence={**evidence,'promotion_note':'EXISTING_SELECTION_POLICY_PREFERS_CONTROL'}
    return {'engine_result':decision,'evidence':evidence,'before_version':before,'after_version':after}


def recover(state,lineage_root,identifier,before,lineage_id=None,candidate_hash=None):
    evidence=recorded(lineage_root,identifier)
    if evidence is None:return None
    if candidate_hash is not None and evidence['candidate_hash']!=candidate_hash:raise ValueError('RECOVERY_EXPERIMENT_IDENTITY_MISMATCH')
    after=before
    # The pointer journal is shared by every lineage of this intelligence state: match lineage, experiment and candidate.
    for entry in store(state).pointer_entries():
        r=entry['receipt']
        if(entry['reason']=='CLOSED_LOOP_PROMOTION'and r.get('experiment_id')==identifier and r.get('lineage_id')==lineage_id
           and r.get('candidate_hash')==evidence['candidate_hash']):after=entry['selection_ref']['id']
    return {'engine_result':'RECOVERED_COMMITTED_EVIDENCE','evidence':evidence,'before_version':before,'after_version':after}


def rollback(state,before,reason):
    s=store(state);target=s.read(before,'SELECTION');current_value=s.read('current','SELECTION')
    if current_value['id']==target['id']:return {'status':'COMPLETED','note':'ALREADY_AT_PREVIOUS_SELECTION'}
    entry=s.set_pointer(target,reason='CLOSED_LOOP_ROLLBACK',receipt={'reason':reason,'from':{'id':current_value['id'],'hash':current_value['hash']}})
    return {'status':'COMPLETED','pointer_entry':entry['hash'],'restored':before}


def verify(root,intelligence_state,local):
    """A-H complete-task benchmark with the promoted selection, in a private store; plus 0.8 selection guards."""
    from ..cognition.benchmark import evaluate,identity
    from ..cognition.orchestrator import CognitiveOrchestrator
    from ..cognition.store import CognitiveStore
    from ..local_intelligence.controller import selected_backend
    from ..local_intelligence.primary import PrimaryLocalIntelligenceBackend
    selected_backend(intelligence_state,'current')
    bundle=json.loads((Path(root)/'docs/cognition_evidence/benchmark-final.json').read_bytes())
    if bundle['benchmark_hash']!=identity():raise ValueError('PROTECTED_COGNITIVE_BENCHMARK_CHANGED')
    source=CognitiveStore(Path(root)/'state_cognition');target=CognitiveStore(local)
    rows=[]
    for row in bundle['cases']:
        case=row['case']
        for r in case['task']['context_refs']:target.put(source.get(r['id'],'EVIDENCE'))
        run=CognitiveOrchestrator(local,backend_factory=lambda:PrimaryLocalIntelligenceBackend(intelligence_state,'current')).run(case['task'])
        tools=[target.get(r['id'],'TOOL_RESULT')['payload']['tool_id']for r in run['result']['payload']['preserved_tool_result_refs']]
        rows.append(evaluate(case,run,tools))
    passed=all(r['status']=='PASS'for r in rows)
    return {'status':'PASS'if passed else'FAIL','cases':len(rows),'passed':sum(r['status']=='PASS'for r in rows),'evaluations':rows,
            'benchmark_hash':identity(),'scope':'PROTECTED_A_H_TASKS_AFTER_SELECTION_PROMOTION'}
