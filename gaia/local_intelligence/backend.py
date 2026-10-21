"""Stable local-intelligence API over an isolated runtime adapter, never a tool executor."""
from abc import ABC, abstractmethod
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import threading
import re

from .artifacts import file_hash
from .isolation import command, limits
from .model_adapter import format_prompt


class LocalIntelligenceBackend(ABC):
    @abstractmethod
    def load(self): ...
    @abstractmethod
    def unload(self): ...
    @abstractmethod
    def generate(self, text, **kwargs): ...
    @abstractmethod
    def tokenize(self, text): ...
    @abstractmethod
    def health(self): ...

    def structured_generate(self, text, **kwargs):
        response = self.generate(text, **kwargs)
        return {"generation": response, "value": json.loads(response["text"])}


class IsolatedRuntimeAdapter(LocalIntelligenceBackend):
    def __init__(self, stack, state, budget):
        self.stack, self.state, self.budget = dict(stack), Path(state), dict(budget)
        if stack['runtime'] not in ('mistralrs','koboldcpp') or stack['backend'] not in ('CPU','CUDA','VULKAN'):
            raise ValueError('Unqualified runtime adapter')
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',stack['runtime_install']) or any(not re.fullmatch(r'[a-f0-9]{64}',stack[k]) for k in ('runtime_hash','model_hash'))
                or type(stack['context']) is not int or type(stack['threads']) is not int or type(stack['gpu_layers']) is not int
                or not 0<=stack['gpu_layers']<=1000 or stack['kv'] not in ('f16','q8_0') or stack['model_family'] not in ('qwen3','smollm3','gemma4')):
            raise ValueError('Unsafe or unsupported stack fields')
        if not 256 <= stack['context'] <= budget['max_context'] or not 1 <= stack['threads'] <= budget['threads']:
            raise ValueError('Stack outside qualification budget')
        self.process, self.work, self.telemetry, self._buffer = None, None, {}, b''
        self._gpu_samples=[]; self._gpu_stop=threading.Event(); self._gpu_thread=None

    def _gpu_monitor(self):
        from ..observation.gpu import collect
        while not self._gpu_stop.is_set():
            try:
                data=collect()
                used=sum(d['vram_total_bytes']-d['vram_available_bytes'] for d in data.get('devices',[]) if d.get('vram_total_bytes') is not None and d.get('vram_available_bytes') is not None)
                self._gpu_samples.append(used)
            except Exception:
                pass
            self._gpu_stop.wait(.5)

    def _receive(self, timeout):
        end = time.monotonic() + timeout
        if hasattr(self,'_deadline'):end=min(end,self._deadline)
        fd = self.process.stdout.fileno()
        while b'\n' not in self._buffer:
            left = end-time.monotonic()
            if left<=0: raise TimeoutError('Isolated runtime protocol deadline')
            ready,_,_=select.select([fd],[],[],left)
            if not ready: continue
            block=os.read(fd,65536)
            if not block: raise ValueError('Runtime worker exited')
            self._buffer+=block
            if len(self._buffer)>2**20: raise ValueError('Runtime protocol output bound')
        line,self._buffer=self._buffer.split(b'\n',1)
        return json.loads(line)

    def _send(self, value):
        self.process.stdin.write((json.dumps(value)+'\n').encode()); self.process.stdin.flush()

    def load(self):
        if self.process is not None: raise ValueError('Backend already loaded')
        load_start=time.perf_counter()
        self._deadline=time.monotonic()+self.budget['benchmark_timeout_seconds']
        self._buffer=b'';self._gpu_stop.clear();self._gpu_samples=[];self.telemetry={}
        runtime_dir = self.state / 'runtimes' / self.stack['runtime_install']
        if runtime_dir.is_symlink() or not runtime_dir.resolve().is_relative_to((self.state/'runtimes').resolve()):
            raise ValueError('Runtime installation escapes state')
        binary = runtime_dir / ('mistralrs' if self.stack['runtime']=='mistralrs' else 'koboldcpp')
        model = self.state / 'artifacts' / self.stack['model_hash']
        if file_hash(binary)!=self.stack['runtime_hash'] or file_hash(model)!=self.stack['model_hash']:
            raise ValueError('Runtime/model artifact hash mismatch')
        parent=self.state/'work'; parent.mkdir(exist_ok=True)
        self.work=Path(tempfile.mkdtemp(prefix='inference-',dir=parent))
        job={**{k:self.stack[k] for k in ('runtime','threads','context','backend','gpu_layers','kv')},'interactive':True,'tasks':[],
             'ram_budget':self.budget['worker_ram_bytes'],'load_timeout':self.budget['smoke_timeout_seconds'],
             'private_disk_budget_bytes':min(2*2**30,self.budget['disk_budget_bytes']//4)}
        support=self.state/'support'/self.stack['support_id'] if self.stack.get('support_id') else None
        if support:
            if support.is_symlink() or not support.resolve().is_relative_to((self.state/'support').resolve()): raise ValueError('Support escapes state')
            for name,h in self.stack['support_hashes'].items():
                if name not in ('tokenizer.json','tokenizer_config.json','config.json','special_tokens_map.json') or file_hash(support/name)!=h:
                    raise ValueError('Model support identity mismatch')
            job['tokenizer']='/support/tokenizer.json'
        (self.work/'job.json').write_text(json.dumps(job))
        interpreter=str(Path(sys.executable).resolve())
        args=command(runtime_dir,self.work,[interpreter,'-B','-I','/worker.py'],model=model,gpu=self.stack['backend']!='CPU',worker=Path(__file__).with_name('runtime_worker.py'),support=support)
        env={'PATH':'/usr/bin:/bin','HOME':'/work','TMPDIR':'/tmp','LC_ALL':'C','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
             'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':str(self.stack['threads']),'RAYON_NUM_THREADS':str(self.stack['threads'])}
        self._stderr=(self.work/'worker.stderr').open('wb')
        if self.stack['backend']!='CPU':
            self._gpu_thread=threading.Thread(target=self._gpu_monitor,daemon=True); self._gpu_thread.start()
        # Address space includes mmap plus unpacked/native buffers, not just RSS.
        # The worker independently kills runtime descendants at the physical RSS budget.
        ram=self.budget['worker_ram_bytes']*(2 if self.stack['backend']=='CPU' else 4)
        try:
            self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self._stderr,env=env,
                                          preexec_fn=limits(ram,(self.budget['benchmark_timeout_seconds']+30)*self.stack['threads']))
            ready=self._receive(self.budget['smoke_timeout_seconds']+10)
            self.telemetry.update(ready)
            if ready.get('status')!='READY': raise ValueError('Runtime not ready: '+str(ready))
            security=ready['security']
            if (security['network_namespace']==os.stat('/proc/self/ns/net').st_ino or security['pid_namespace']==os.stat('/proc/self/ns/pid').st_ino
                    or security['host_home_visible'] or not all(security[k]for k in ('root_read_only','runtime_read_only','model_read_only'))):
                raise ValueError('Qualification isolation attestation failed')
            self.telemetry={'load_s':ready['load_s'],'load_total_api_s':time.perf_counter()-load_start,'stack':self.stack,'model_tool_authority':'NONE',
                            'isolation':{'network_namespace_isolated':True,'pid_namespace_isolated':True,'root_read_only':True,'runtime_read_only':True,
                                         'model_read_only':True,'host_home_visible':False}}
            return self.telemetry
        except BaseException:
            self.close_failed()
            raise

    def generate(self, text, *, max_tokens=80, raw=False, identifier='generation', repeat=0, category='COGNITIVE'):
        if self.process is None: raise ValueError('Backend not loaded')
        if not isinstance(text,str) or len(text)>200000 or not 1 <= max_tokens <= self.budget['max_generation_tokens']:
            raise ValueError('Inference request bounds')
        prompt=text if raw else format_prompt(text,self.stack['model_family'])
        start=time.perf_counter()
        self._send({'type':'GENERATE','task':{'id':identifier,'prompt':prompt,'repeat':repeat,'category':category,'max_tokens':max_tokens}})
        value=self._receive(120)
        value['total_api_latency_s']=time.perf_counter()-start
        value['backend_id']=self.stack['stack_id']
        value.setdefault('generation_config',{'temperature':0,'seed':value.get('seed'),'max_tokens':max_tokens})
        n=value.get('output_tokens')
        value['decode_tokens_per_s']=n/max(.000001,value['latency_s']-(value.get('ttft_s') or 0)) if n is not None and value.get('latency_s') is not None and value.get('stream_content_events',0)>1 else None
        value['effective_prefill_tokens_per_s']=value.get('input_tokens',value.get('usage',{}).get('prompt_tokens'))/value['ttft_s'] if value.get('ttft_s') and (value.get('input_tokens') is not None or value.get('usage',{}).get('prompt_tokens') is not None) else None
        perf=value.get('runtime_performance') or {}
        value['decode_metric_source']='RUNTIME_REPORTED' if perf.get('last_eval_speed') else 'STREAM_INTERVAL_APPROXIMATION' if value['decode_tokens_per_s'] is not None else 'MISSING_EVIDENCE'
        if perf.get('last_eval_speed'):
            value['decode_tokens_per_s']=perf['last_eval_speed']
        value['prompt_processing_tokens_per_s']=perf.get('last_process_speed')
        value['prefill_metric_source']='RUNTIME_REPORTED' if perf.get('last_process_speed') else 'MISSING_EVIDENCE'
        return value

    def tokenize(self, text):
        self._send({'type':'TOKENIZE','text':text}); return self._receive(20)['count']

    def health(self):
        if self.process is None: return {'status':'UNLOADED'}
        self._send({'type':'HEALTH'}); return self._receive(5)

    def capabilities(self):
        return {'generate':True,'structured_generate':'PARSE_AND_VALIDATE_NOT_GUARANTEED_GRAMMAR','count_tokens':'WHEN_RUNTIME_ENDPOINT_AVAILABLE',
                'tools':'FORMAT_ONLY_NO_EXECUTION','outbound_network':False,'stream_metrics':True,
                'max_context_tokens':self.stack['context'],'max_generation_tokens':self.budget['max_generation_tokens']}

    def metrics(self):
        return dict(self.telemetry)

    def unload(self):
        if self.process is None: return self.telemetry
        try:
            self._send({'type':'UNLOAD'}); final=self._receive(10)
            self.process.wait(timeout=10); self.telemetry.update(final)
        finally:
            self.close_failed()
        return self.telemetry

    def close_failed(self):
        if self.process is not None:
            if self.process.poll() is None:
                os.killpg(self.process.pid,signal.SIGKILL)
            self.process.wait(timeout=10)
            self.process.stdin.close(); self.process.stdout.close(); self._stderr.close()
            self.process=None
        if hasattr(self,'_stderr') and not self._stderr.closed:self._stderr.close()
        self._gpu_stop.set()
        if self._gpu_thread is not None:
            self._gpu_thread.join(timeout=5)
        if self._gpu_samples:
            self.telemetry['peak_device_used_vram_bytes']=max(self._gpu_samples)
            self.telemetry['device_used_vram_baseline_bytes']=self._gpu_samples[0]
            self.telemetry['vram_scope']='whole observed device, includes other processes; baseline/increment are not exact process attribution'
            self.telemetry['peak_device_vram_increment_bytes']=max(0,max(self._gpu_samples)-self._gpu_samples[0])
