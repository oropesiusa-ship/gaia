"""Visible dimensions, guarded selection and an epsilon-Pareto frontier, not a universal winner."""
from ..provenance import digest
from .benchmark import evaluate,jobs,identity as benchmark_identity
from ..observation.stability import summarize
from .schema import artifact,ref,validate

POLICY={'version':'local_intelligence_selection_v1','relative_noise_tolerance':.05,'quality_tolerance':.005,
        'minimum_runtime_families_for_comparative_claim':2,'minimum_models_for_comparative_claim':2,
        'claim_ceiling':'BEST_BALANCED_TESTED','primary_requires_stable_latency':True}


def dimensions(result):
    validate(result)
    p=result['payload'];evaluation=evaluate(p['responses'])
    if p['benchmark_hash']!=benchmark_identity() or evaluation!=p['evaluation']:raise ValueError('Protected benchmark evidence inconsistent')
    expected={(t['id'],t['repeat'],t['category'])for t in jobs(p['stack']['model_family'],repeats=3)}
    actual=[(r['id'],r['repeat'],r['category'])for r in p['responses']]
    if len(actual)!=len(expected)or set(actual)!=expected:raise ValueError('Incomplete or duplicated protected workload')
    for metric,statistic in p['statistics'].items():
        if summarize([r.get(metric)for r in p['responses']if r['id']=='throughput'and r['status']=='OK'])!=statistic:
            raise ValueError('Benchmark statistics do not reproduce')
    stat=p['statistics']; telemetry=p['telemetry'];stack=p['stack']
    throughput=stat['decode_tokens_per_s']['median'];latency=stat['latency_s']['median']
    quality_latencies=[r['latency_s'] for r in p['responses'] if r.get('status')=='OK' and r['category']=='QUALITY']
    intents=[d for d in evaluation['details'] if d['id']=='tool_intent']
    inputs=[r.get('usage',{}).get('prompt_tokens') for r in p['responses'] if r.get('usage',{}).get('prompt_tokens') is not None]
    ram=telemetry.get('peak_rss_sum_bytes')
    vram=telemetry.get('peak_device_vram_increment_bytes') if stack['backend']!='CPU' else 0
    return {'stack_id':stack['stack_id'],'quality':evaluation['quality'],'structured_output':evaluation['json_reliability'],
            'latency_s':latency,'quality_task_mean_latency_s':sum(quality_latencies)/len(quality_latencies) if quality_latencies else None,
            'decode_tokens_per_s':throughput,'ram_bytes':ram,'vram_increment_bytes':vram,'context':stack['context'],
            'reliability':1.0 if all(r['status']=='OK' for r in p['responses']) else 0.0,
            'tool_intent_accuracy':sum(d['correct'] for d in intents)/len(intents) if intents else 0,
            'maximum_observed_input_tokens':max(inputs) if inputs else None,
            'latency_stability':stat['latency_s']['stability'],'maintenance':'CURRENT_UPSTREAM_RELEASE_RESEARCHED',
            'install_complexity':'OFFICIAL_PREBUILT_HASH_VERIFIED','quality_guard':evaluation['quality_guard'],
            'metric_scope':'VRAM incremental sampled whole-device, RAM descendant RSS sum; not perfectly attributable or cross-runtime equivalent'}


def dominates(a,b):
    eps=POLICY['relative_noise_tolerance']
    no_worse=True;strict=False
    for key,higher in (('quality',True),('structured_output',True),('reliability',True),('latency_s',False),('ram_bytes',False),('vram_increment_bytes',False)):
        x,y=a[key],b[key]
        if x is None or y is None:return False
        tolerance=POLICY['quality_tolerance'] if key in ('quality','structured_output','reliability') else max(abs(y)*eps,1e-9)
        diff=(x-y) if higher else (y-x)
        no_worse &= diff>=-tolerance
        strict |= diff>tolerance
    return no_worse and strict


def select(results,profile,*,coverage):
    # Latest attempt per exact declared stack, not cherry-picking the fastest repeat.
    latest={}
    for result in sorted(results,key=lambda v:(v['created_at'],v['id'])):
        if result['kind']=='BENCHMARK':latest[result['payload']['stack']['stack_id']]=result
    qualified=[r for r in latest.values() if r['payload']['status']=='QUALIFIED' and r['payload']['backend_verification']['verified']]
    points=[dimensions(r) for r in qualified]
    if not points:raise ValueError('No stack meets quality/reliability guards')
    frontier=[p['stack_id'] for p in points if not any(dominates(other,p) for other in points if other is not p)]
    candidates=[p for p in points if p['latency_stability']=='STABLE']
    if not candidates:raise ValueError('No primary selection without repeatable latency evidence')
    # Quality/reliability and structured/tool output precede latency, not tok/s alone.
    ordered=sorted(candidates,key=lambda p:(-p['quality'],-p['reliability'],-p['structured_output'],-p['tool_intent_accuracy'],
                                           p['quality_task_mean_latency_s'],p['latency_s'],p['ram_bytes'],p['stack_id']))
    by_id={r['payload']['stack']['stack_id']:r for r in qualified}
    best=ordered[0]
    equivalent=[p for p in ordered if p['quality']==best['quality']and p['structured_output']==best['structured_output']
                and p['tool_intent_accuracy']==best['tool_intent_accuracy']
                and p['quality_task_mean_latency_s']<=best['quality_task_mean_latency_s']*(1+POLICY['relative_noise_tolerance'])]
    # A sub-noise speed difference does not establish a winner. Prefer the default
    # unquantized KV configuration in this equivalence band, then deterministic ID.
    primary=min(equivalent,key=lambda p:(by_id[p['stack_id']]['payload']['stack']['kv']!='f16',p['ram_bytes'],p['stack_id']))
    primary_result=by_id[primary['stack_id']]
    families={('candle' if r['payload']['stack']['runtime']=='mistralrs' else 'ggml-llama-derived') for r in qualified}
    models={r['payload']['stack']['model_hash'] for r in qualified}
    comparative=len(families)>=2 and len(models)>=2
    harnesses={digest(r['payload'].get('implementation_hashes',{}))for r in qualified}
    comparative=comparative and len(harnesses)==1
    secondary=[]
    cpu=[p for p in points if by_id[p['stack_id']]['payload']['stack']['backend']=='CPU']
    if cpu:
        c=min(cpu,key=lambda p:(-p['quality'],-p['structured_output'],p['quality_task_mean_latency_s']))
        if c['stack_id']!=primary['stack_id']:secondary.append({'role':'SECONDARY_CPU','stack':by_id[c['stack_id']]['payload']['stack'],'benchmark_ref':ref(by_id[c['stack_id']])})
    low=[p for p in points if p['vram_increment_bytes'] is not None and p['vram_increment_bytes']>0 and p['vram_increment_bytes']<primary['vram_increment_bytes']*.75]
    if low:
        c=min(low,key=lambda p:(-p['quality'],p['vram_increment_bytes'],p['quality_task_mean_latency_s']))
        secondary.append({'role':'SECONDARY_LOW_VRAM','stack':by_id[c['stack_id']]['payload']['stack'],'benchmark_ref':ref(by_id[c['stack_id']])})
    return artifact('SELECTION',{'policy':{**POLICY,'hash':digest(POLICY)},'host_ref':ref(profile),'coverage':coverage,
        'claim':'BEST_BALANCED_TESTED' if comparative else 'ONLY_QUALIFIED_CANDIDATE' if len(points)==1 else 'BEST_BALANCED_WITH_LIMITED_RUNTIME_OR_MODEL_COVERAGE',
        'primary':{'role':'PRIMARY','stack':primary_result['payload']['stack'],'benchmark_ref':ref(primary_result),'dimensions':primary},
        'secondary':secondary,'pareto_frontier':frontier,'dimensions':points,'result_refs':[ref(r) for r in qualified],
        'rationale':['quality/reliability/JSON/tool readiness first; stable measured task latency then memory',
                     'no BEST_AVAILABLE assertion; static ecosystem coverage and measured finalist coverage are different',
                     'backend measurements, not a prior assumption that CPU/CUDA/Vulkan must win'],
         'runtime_families_qualified':sorted(families),'models_qualified':len(models),'best_available_claim':False})
