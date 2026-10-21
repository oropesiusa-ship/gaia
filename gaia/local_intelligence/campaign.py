"""Controlled non-evolutionary qualification; independent protected scoring and honest metric scopes."""
import re
import time
import hashlib
from pathlib import Path

from ..observation.stability import summarize
from .backend import IsolatedRuntimeAdapter
from .benchmark import jobs, evaluate, identity as benchmark_identity
from .schema import artifact


def backend_verified(stack, telemetry):
    text = telemetry.get('runtime_stderr_tail','')+'\n'+telemetry.get('runtime_stdout_tail','')
    if stack['backend']=='CPU':
        return {'verified':True,'reason':'CPU_FLAG_AND_NO_GPU_DEVICE_MOUNTS'}
    if stack['backend']=='CUDA' and re.search(r'failed to initialize CUDA|CUDA error|no CUDA',text,re.I):
        return {'verified':False,'reason':'CUDA_INITIALIZATION_FAILED_NO_ACCELERATION_CLAIM'}
    expected='Vulkan0' if stack['backend']=='VULKAN' else 'CUDA0'
    return {'verified':expected in text and bool(re.search(r'offloaded\s+[1-9][0-9]*/[0-9]+ layers to GPU',text)),
            'reason':'DEVICE_AND_NONZERO_OFFLOAD_LOG_REQUIRED'}


def run_stack(stack, state, budget, *, screen=False):
    start=time.perf_counter()
    adapter=IsolatedRuntimeAdapter(stack,state,budget)
    responses=[]; telemetry={}; failure=None
    try:
        adapter.load()
        tasks=jobs(stack['model_family'],repeats=1 if screen else budget['repeats'])
        if screen: tasks=tasks[:2]+[t for t in tasks if t['id']=='throughput']
        for task in tasks:
            if time.perf_counter()-start>budget['benchmark_timeout_seconds']:
                failure='CAMPAIGN_DURATION_BUDGET'; break
            value=adapter.generate(task['prompt'],raw=True,max_tokens=task['max_tokens'],identifier=task['id'],repeat=task['repeat'],category=task['category'])
            responses.append(value)
            if value['status']!='OK':
                failure='INFERENCE_FAILED'; break
    except (OSError,ValueError,TimeoutError) as exc:
        failure=type(exc).__name__
    finally:
        if adapter.process is not None:
            try: telemetry=adapter.unload()
            except (OSError,ValueError,TimeoutError): adapter.close_failed(); telemetry=adapter.metrics()
        else: telemetry=adapter.metrics()
    verified=backend_verified(stack,telemetry)
    if not verified['verified']: failure=verified['reason']
    evaluation=evaluate(responses)
    expected_count=(3 if screen else len(jobs(stack['model_family'],repeats=budget['repeats'])))
    complete=len(responses)==expected_count
    statistics={}
    for metric in ('ttft_s','latency_s','decode_tokens_per_s','prompt_processing_tokens_per_s','effective_prefill_tokens_per_s'):
        statistics[metric]=summarize([r.get(metric) for r in responses if r['id']=='throughput' and r['status']=='OK'])
    # Stability is across repetitions of the same performance workload, never across heterogeneous tasks.
    equality={}
    for identifier in {r['id'] for r in responses}:
        equality[identifier]=len({r.get('text') for r in responses if r['id']==identifier})==1
    # Keep only bounded neutral log evidence, not entire option dumps or upstream build paths.
    logtext=telemetry.get('runtime_stderr_tail','')+'\n'+telemetry.get('runtime_stdout_tail','')
    lines=[l for l in logtext.splitlines() if any(k in l for k in ('offloaded','model buffer size','KV buffer size','KV cache','failed to initialize CUDA','using device','compute buffer size','K ('))]
    safe_telemetry={k:v for k,v in telemetry.items() if k not in ('runtime_stderr_tail','runtime_stdout_tail','stack')}
    safe_telemetry['backend_log_evidence']=lines[-20:]
    error_lines=[re.sub(r'/home/\S+','<upstream-build-path>',l) for l in logtext.splitlines() if l.startswith(('Error:','error:','memory allocation'))]
    safe_telemetry['native_failure_evidence']=error_lines[-5:]
    kv=re.search(r'K \(([^)]+)\).*V \(([^)]+)\)',logtext)
    safe_telemetry['kv_effective']={'K':kv.group(1),'V':kv.group(2)} if kv else None
    success=not failure and complete and evaluation['quality_guard']
    implementations={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('runtime_worker.py','backend.py','campaign.py','benchmark.py','model_adapter.py')}
    return artifact('SMOKE' if screen else 'BENCHMARK',{'stack':stack,'benchmark_hash':benchmark_identity(),'implementation_hashes':implementations,'evaluation':evaluation,'responses':responses,
        'statistics':statistics,'repeat_output_equality':equality,'telemetry':safe_telemetry,'backend_verification':verified,
        'status':'QUALIFIED' if success and not screen else 'SCREEN_PASSED' if success else 'QUALIFICATION_FAILED',
        'failure_reason':failure or ('QUALITY_GUARD' if not evaluation['quality_guard'] else 'INCOMPLETE_MEASUREMENTS' if not complete else None),
        'duration_s':time.perf_counter()-start,'comparability':'COMPARABLE_APPROXIMATELY',
        'comparability_reasons':['same model file/raw prompts/greedy generation/context in runtime comparisons; seed support and KV implementations differ',
                                 'TTFT is first content delivery upper bound; buffered SSE cannot measure exact first token time',
                                 'native throughput metrics distinguished from external stream proxies; missing telemetry stays missing']})
