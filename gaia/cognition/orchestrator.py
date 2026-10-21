"""Bounded model proposal -> external validation -> read-only tool -> final loop."""
import time
import json
from ..provenance import digest,canonical_json
from .schema import validate_task,seal,ref
from .store import CognitiveStore
from .tools import ToolRegistry
from .context import ContextBuilder
from .validator import strict_json,proposal,final
from .planner import validate_plan
from .uncertainty import assess


class CognitiveOrchestrator:
    def __init__(self,state,backend_factory=None,*,configuration=None,intelligence_state=None):
        from .policy import settings
        self.settings=settings(configuration);self.store=CognitiveStore(state)
        if backend_factory is None:
            from ..local_intelligence.primary import PrimaryLocalIntelligenceBackend
            backend_factory=lambda:PrimaryLocalIntelligenceBackend(intelligence_state or state)
        self.backend_factory=backend_factory

    def run(self,task):
        task=json.loads(canonical_json(validate_task(task)))
        if any(task['resource_budget'][k]>self.settings[k]for k in task['resource_budget']):raise ValueError('TASK_EXCEEDS_OPERATOR_POLICY')
        start=time.monotonic();deadline=start+task['resource_budget']['max_duration'];events=[];tool_refs=[];facts=[];called=set();claims=[];plan=None
        status='FAILED';reason=None;backend=None;correction=None;retries=0;calls=0;steps=0;model_time=0.;tool_time=0.;output_reserved=0;token_usage=[];ttft=[]
        task_record=self.store.save_task(task);registry=ToolRegistry(self.store)
        def event(kind,payload):
            record=self.store.put(seal(kind,payload));events.append(ref(record));return record
        try:
            # Validate every task-bound source before any model process starts.
            for r in task['context_refs']:
                record=self.store.get(r['id'],'EVIDENCE')
                if ref(record)!={'id':r['id'],'hash':r['hash']}:raise ValueError('TASK_EVIDENCE_HASH_MISMATCH')
            backend=self.backend_factory();backend.load()
            for step in range(task['resource_budget']['max_steps']):
                steps=step+1
                if time.monotonic()>=deadline:reason='DURATION_BUDGET';break
                ctx=ContextBuilder().build(task,backend,registry,facts,called,correction)
                context_record=event('CONTEXT',{k:v for k,v in ctx.items()if k not in ('fact_aliases','source_aliases')})
                if time.monotonic()>=deadline:reason='DURATION_BUDGET';break
                remaining=task['resource_budget']['max_output_tokens']-output_reserved
                n=min(ctx['reserved_output_tokens'],remaining)
                if n<16:reason='OUTPUT_TOKEN_BUDGET';break
                output_reserved+=n;t=time.monotonic()
                response=backend.generate(ctx['prompt'],max_tokens=n,timeout=max(.01,deadline-time.monotonic()))
                model_time+=time.monotonic()-t
                if not isinstance(response,dict):raise ValueError('INVALID_BACKEND_RESPONSE')
                if response.get('ttft_s')is not None:ttft.append(response['ttft_s'])
                token_usage.append({'input_tokens':ctx['input_tokens'],'reserved_output_tokens':n,'reported_usage':response.get('usage',{})})
                turn=event('MODEL_TURN',{'step':steps,'attempt':retries+1,'context_ref':ref(context_record),'request_hash':digest(ctx['prompt']),
                    'response_sha256':digest(response.get('text','')),'status':response.get('status'),'max_tokens':n,
                    'raw_output_stored':False,'chain_of_thought_requested':False,'ttft_s':response.get('ttft_s'),'latency_s':response.get('latency_s')})
                if time.monotonic()>deadline:reason='DURATION_BUDGET';break
                if response.get('status')!='OK':reason='MODEL_INFERENCE_FAILED';break
                try:
                    value=strict_json(response.get('text',''))
                    if value.get('kind')=='TOOL':
                        p=proposal(value,ctx)
                        if calls>=task['resource_budget']['max_tool_calls']:raise ValueError('TOOL_CALL_BUDGET')
                        registry.validate(p,task)
                        if p['arguments']['id']in called:raise ValueError('DUPLICATE_TOOL_CALL')
                        prop=event('PROPOSAL',{'model_turn_ref':ref(turn),'proposal':p})
                        validation=event('VALIDATION',{'proposal_ref':ref(prop),'decision':'ACCEPT','authority':'READ_ONLY'})
                        result,elapsed=registry.execute(p,task);tool_time+=elapsed;calls+=1;called.add(p['arguments']['id'])
                        tool_refs.append(ref(event('TOOL_RESULT',{'proposal_ref':ref(prop),'validation_ref':ref(validation),'tool_id':p['tool_id'],'result':result,'duration_s':elapsed,'side_effects':[]})))
                        facts.extend(result['facts']);correction=None
                    elif value.get('kind')=='FINAL':
                        claims=final(value,ctx,task);status=value['status'];event('VALIDATION',{'model_turn_ref':ref(turn),'decision':'ACCEPT_FINAL','selected_fact_ids':[c['fact_id']for c in claims]});break
                    elif value.get('kind')=='PLAN':
                        plan,claims=validate_plan(value,ctx,task,registry);event('PLAN',plan);status='OK';break
                    else:raise ValueError('UNSUPPORTED_MODEL_DECISION')
                except (ValueError,KeyError,TypeError)as exc:
                    code=str(exc)if isinstance(exc,ValueError)and str(exc).isupper()and len(str(exc))<100 else'INVALID_STRUCTURED_DECISION'
                    correction='Rejected: '+code+'. Return a valid JSON object using only listed tools or facts.'
                    event('VALIDATION',{'model_turn_ref':ref(turn),'decision':'REJECT','reason':code,'attempt':retries+1,'correction_instruction':correction})
                    retries+=1
                    if retries>task['resource_budget']['retry_limit']:reason='RETRY_LIMIT';break
            else:reason='STEP_BUDGET'
        except (OSError,ValueError,KeyError,TypeError,TimeoutError)as exc:
            reason=str(exc)if isinstance(exc,ValueError)and str(exc).isupper()and len(str(exc))<100 else type(exc).__name__
        finally:
            if backend is not None:
                try:backend.unload()
                except (OSError,ValueError,TimeoutError):reason='BACKEND_UNLOAD_FAILED';status='FAILED'
        if status=='FAILED':claims=[];plan=None
        uncertainty=assess(status,claims,facts,[reason]if reason else None)
        result=self.store.put(seal('RESULT',{'schema':'gaia_cognitive_result_v1','task_ref':ref(task_record),'task_id':task['task_id'],
            'status':status,'reason':reason,'claims':claims,'plan':plan,'uncertainty':uncertainty,'output_boundary':'UNTRUSTED_COGNITIVE_DATA',
            'authority':'NONE','tool_calls':calls,'preserved_tool_result_refs':tool_refs,
            'performance':{'total_latency_s':time.monotonic()-start,'model_time_s':model_time,'tool_overhead_s':tool_time,
                'ttft_s':ttft,'ttft_scope':'FIRST_CONTENT_EVENT_UPPER_BOUND_FROM_0_8','steps':steps,'retries':retries,'token_usage':token_usage,'output_tokens_reserved':output_reserved},
            'backend_selection_ref':({'id':backend.selection['id'],'hash':backend.selection['hash']}if backend is not None and isinstance(getattr(backend,'selection',None),dict)else None),
            'backend_capabilities':backend.capabilities()if backend is not None else None,
            'forbidden_actions_executed':0,'network_requests':0,'source_changes':0,'hidden_chain_of_thought_stored':False}))
        trace=self.store.put(seal('TRACE',{'task_ref':ref(task_record),'events':events,'result_ref':ref(result),
            'tool_results_preserved_on_failure':True,'model_internal_reasoning_stored':False}))
        return {'result':result,'trace':trace}
