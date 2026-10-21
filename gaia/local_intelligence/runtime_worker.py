"""Sandbox-side HTTP client/runtime owner. No expected answers, tools or GAIA source mounted."""
import http.client
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import threading
import time


def request(method, path, payload=None, timeout=10):
    c = http.client.HTTPConnection('127.0.0.1', 18765, timeout=timeout)
    try:
        data = json.dumps(payload).encode() if payload is not None else None
        c.request(method, path, body=data, headers={'Content-Type': 'application/json', 'Connection': 'close'})
        r = c.getresponse()
        body = r.read(2**20)
        return r.status, json.loads(body)
    finally:
        c.close()


def monitor(stop, samples):
    job=json.loads(Path('/work/job.json').read_bytes())
    while not stop.is_set():
        rss, peak, victims = 0, 0, []
        for path in Path('/proc').glob('[0-9]*/status'):
            if path.parent.name in (str(os.getpid()),'1'):
                continue
            victims.append(int(path.parent.name))
            try:
                fields = {line.split(':')[0]: int(line.split()[1]) * 1024 for line in path.read_text().splitlines() if line.startswith(('VmRSS:', 'VmHWM:'))}
                rss += fields.get('VmRSS', 0)
                peak = max(peak, fields.get('VmHWM', 0))
            except (OSError, ValueError):
                pass
        samples.append({'offset_s': time.monotonic(), 'descendant_rss_sum_bytes': rss, 'maximum_process_peak_rss_bytes': peak})
        disk=0
        for root in ('/work','/tmp'):
            for path in Path(root).rglob('*'):
                try:
                    if path.is_file()and not path.is_symlink():disk+=path.stat().st_size
                except OSError:pass
        samples[-1]['private_disk_bytes']=disk
        if rss > job['ram_budget'] or disk > job['private_disk_budget_bytes']:
            Path('/work/RAM_LIMIT' if rss>job['ram_budget'] else '/work/DISK_LIMIT').touch()
            for pid in victims:
                try: os.kill(pid,signal.SIGKILL)
                except ProcessLookupError: pass
            return
        stop.wait(.05)


def generate(task, model, runtime):
    payload = {'model': model, 'prompt': task['prompt'], 'max_tokens': task['max_tokens'], 'temperature': 0.0,
               'top_p': 1.0, 'top_k': 0, 'min_p': 0.0, 'seed': 17, 'frequency_penalty': 0.0, 'presence_penalty': 0.0,
               'repeat_penalty': 1.0, 'stream': True, 'stream_options': {'include_usage': True}, 'stop': ['<|im_end|>', '<|endoftext|>', '<turn|>', '<eos>']}
    if runtime=='mistralrs':
        payload.pop('seed')  # This CPU build explicitly rejects candle CPU set_seed.
    c = http.client.HTTPConnection('127.0.0.1',18765,timeout=90)
    start, first, pieces, usage, events = time.perf_counter(), None, [], {}, 0
    try:
        c.request('POST','/v1/completions',body=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Connection':'close'})
        r=c.getresponse()
        if r.status != 200:
            return {**{k:task[k] for k in ('id','repeat','category')},'status':'ERROR','http_status':r.status,'error_data':r.read(4096).decode(errors='replace')}
        while True:
            line=r.readline(65536)
            if not line:
                break
            if not line.startswith(b'data:'):
                continue
            data=line[5:].strip()
            if data==b'[DONE]':
                break
            value=json.loads(data)
            if value.get('usage'): usage=value['usage']
            for choice in value.get('choices',[]):
                text=choice.get('text') or choice.get('delta',{}).get('content') or ''
                if text:
                    if first is None: first=time.perf_counter()-start
                    pieces.append(text); events+=1
            if sum(map(len,pieces))>32768: raise ValueError('output limit')
        elapsed=time.perf_counter()-start
        performance=None
        if runtime=='koboldcpp':
            try:
                status,data=request('GET','/api/extra/perf')
                if status==200: performance=data
            except (OSError,ValueError,TimeoutError): pass
        return {**{k:task[k] for k in ('id','repeat','category')}, 'status':'OK','text':''.join(pieces), 'ttft_s':first,'latency_s':elapsed,
                'usage':usage,'stream_content_events':events, 'max_tokens':task['max_tokens'],'runtime_performance':performance,
                'generation_config':{k:v for k,v in payload.items() if k not in ('model','prompt')},
                'seed':payload.get('seed'),'ttft_scope':'FIRST_CONTENT_EVENT_UPPER_BOUND_MAY_BE_BUFFERED'}
    except (OSError,ValueError,TimeoutError) as exc:
        return {**{k:task[k] for k in ('id','repeat','category')},'status':'ERROR','reason':type(exc).__name__,'latency_s':time.perf_counter()-start}
    finally:
        c.close()


def count_tokens(text, runtime):
    paths = [('/api/extra/tokencount', {'prompt':text})] if runtime=='koboldcpp' else [('/tokenize',{'text':text}),('/v1/tokenize',{'text':text})]
    for path, payload in paths:
        try:
            status, data=request('POST',path,payload)
            if status==200:
                if type(data.get('value')) is int: return data['value']
                for key in ('tokens','token_ids','ids'):
                    if isinstance(data.get(key),list): return len(data[key])
        except (OSError,ValueError,TimeoutError): pass
    return None


def main():
    job=json.loads(Path('/work/job.json').read_bytes())
    runtime=job['runtime']; threads=job['threads']; context=job['context']; backend=job['backend']
    if runtime=='mistralrs':
        if backend!='CPU': raise ValueError('unqualified accelerator package')
        args=['/runtime/mistralrs','--token-source','none','serve','-f','/models/model.gguf','--cpu','--host','127.0.0.1','--port','18765',
              '--max-model-len',str(context),'--max-seqs','1','--prefix-cache-n','0','--no-ui','--disable-access-log','--agent-permission','deny',
              '--sandbox','on','--sandbox-profile','restricted','--sandbox-network','none','--hf-cache','/work/hf']
        if job.get('tokenizer'): args+=['--tokenizer',job['tokenizer']]
    elif runtime=='koboldcpp':
        args=['/runtime/koboldcpp','--model','/models/model.gguf','--contextsize',str(context),'--threads',str(threads),'--blasthreads',str(threads),
              '--host','127.0.0.1','--port','18765','--skiplauncher','--quiet','--rpcmode','disabled','--quantkv',job.get('kv','f16'),'--noshift','--nofastforward']
        if backend=='CPU': args+=['--usecpu','--gpulayers','0']
        elif backend=='CUDA': args+=['--usecuda','0','--gpulayers',str(job['gpu_layers']),'--noflashattention']
        elif backend=='VULKAN': args+=['--usevulkan','0','--gpulayers',str(job['gpu_layers'])]
        else: raise ValueError('unknown backend')
    else: raise ValueError('unknown runtime')
    env={**os.environ,'RAYON_NUM_THREADS':str(threads),'OMP_NUM_THREADS':str(threads),'CUDA_VISIBLE_DEVICES':'0'}
    start=time.perf_counter(); samples=[]; stop=threading.Event(); sampler=threading.Thread(target=monitor,args=(stop,samples),daemon=True)
    result={'status':'FAILED','load_s':None,'responses':[],'execution_authority':'NONE','outbound_network':'ISOLATED_NAMESPACE'}
    with open('/work/runtime.stdout','wb') as out,open('/work/runtime.stderr','wb') as err:
        process=subprocess.Popen(args,stdout=out,stderr=err,env=env)
        sampler.start()
        try:
            model=None
            while time.perf_counter()-start<job['load_timeout']:
                if process.poll() is not None: break
                if Path('/work/RAM_LIMIT').exists(): raise MemoryError('RSS budget')
                try:
                    status,data=request('GET','/v1/models')
                    if status==200 and data.get('data'):
                        model=data['data'][0]['id']; break
                except (OSError,ValueError,TimeoutError): pass
                time.sleep(.1)
            if model is None:
                result['reason']='RUNTIME_NOT_READY'
                return result
            result['load_s']=time.perf_counter()-start
            if job.get('interactive'):
                security={'network_namespace':os.stat('/proc/self/ns/net').st_ino,'pid_namespace':os.stat('/proc/self/ns/pid').st_ino,
                          'root_read_only':bool(os.statvfs('/').f_flag&os.ST_RDONLY),'host_home_visible':Path('/home').exists(),
                          'runtime_read_only':bool(os.statvfs('/runtime').f_flag&os.ST_RDONLY),'model_read_only':bool(os.statvfs('/models/model.gguf').f_flag&os.ST_RDONLY)}
                print(json.dumps({'status':'READY','load_s':result['load_s'],'security':security}),flush=True)
                for line in sys.stdin:
                    command=json.loads(line)
                    if command['type']=='UNLOAD':
                        result['status']='OK'; return result
                    if Path('/work/RAM_LIMIT').exists(): raise MemoryError('RSS budget')
                    if command['type']=='GENERATE':
                        task=command['task']; n=count_tokens(task['prompt'],runtime)
                        if n is not None and n+task['max_tokens']>context:
                            response={**{k:task[k]for k in ('id','repeat','category')},'status':'ERROR','reason':'INPUT_CONTEXT_BUDGET','text':'','input_tokens':n}
                        else:response=generate(task,model,runtime)
                        if n is not None: response['input_tokens']=n
                        response['output_tokens']=response.get('usage',{}).get('completion_tokens')
                        print(json.dumps(response),flush=True)
                    elif command['type']=='TOKENIZE':
                        print(json.dumps({'count':count_tokens(command['text'],runtime)}),flush=True)
                    elif command['type']=='HEALTH':
                        print(json.dumps({'status':'READY' if process.poll() is None else 'FAILED'}),flush=True)
                    else: raise ValueError('unknown protocol command')
                result['status']='OK'; return result
            for task in job['tasks']:
                if Path('/work/RAM_LIMIT').exists(): raise MemoryError('RSS budget')
                response=generate(task,model,runtime)
                result['responses'].append(response)
                if response['status']!='OK': break
            result['status']='OK' if len(result['responses'])==len(job['tasks']) and all(r['status']=='OK' for r in result['responses']) else 'FAILED'
            return result
        finally:
            stop.set(); sampler.join(timeout=1)
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            result['runtime_returncode']=process.returncode
            result['peak_rss_sum_bytes']=max((s['descendant_rss_sum_bytes'] for s in samples),default=0)
            result['peak_single_process_rss_bytes']=max((s['maximum_process_peak_rss_bytes'] for s in samples),default=0)
            result['peak_private_disk_bytes']=max((s.get('private_disk_bytes',0) for s in samples),default=0)
            result['resource_scope']='runtime descendants in isolated PID namespace; RSS sum may include shared pages'
            result['duration_s']=time.perf_counter()-start
            result['runtime_stderr_tail']=Path('/work/runtime.stderr').read_text(errors='replace')[-6000:]
            result['runtime_stdout_tail']=Path('/work/runtime.stdout').read_text(errors='replace')[-10000:]


if __name__=='__main__':
    try: value=main()
    except Exception as exc: value={'status':'FAILED','reason':type(exc).__name__}
    print(json.dumps(value,allow_nan=False))
