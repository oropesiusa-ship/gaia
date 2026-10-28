"""Selected 0.8 backend facade; orchestration never selects a runtime by name."""
import time
from .controller import selected_backend
from .backend import IsolatedRuntimeAdapter
from .model_adapter import format_prompt


DEFAULT_CHAT_CONTEXT=4096
MAX_TESTED_CONTEXT=16384


class PrimaryLocalIntelligenceBackend:
    def __init__(self,state,selection='latest',*,context=None):
        adapter,self.selection=selected_backend(state,selection)
        if context is not None:
            model_limit=adapter.stack['model_metadata'].get(adapter.stack['model_family']+'.context_length')
            if (type(context)is not int or context<256 or context>MAX_TESTED_CONTEXT
                    or type(model_limit)is not int or context>model_limit):
                raise ValueError('CONTEXT_OUTSIDE_TESTED_MODEL_LIMIT')
            stack=dict(adapter.stack);stack['context']=context
            stack['stack_id']=stack['stack_id']+'-ctx'+str(context)
            budget=dict(adapter.budget);budget['max_context']=max(budget['max_context'],context)
            adapter=IsolatedRuntimeAdapter(stack,state,budget)
        self.adapter=adapter

    def capabilities(self):return self.adapter.capabilities()
    def load(self):return self.adapter.load()
    def unload(self):return self.adapter.unload()
    def health(self):return self.adapter.health()
    def count_tokens(self,text):
        return self.adapter.tokenize(format_prompt(text,self.adapter.stack['model_family']))
    def generate(self,text,max_tokens,timeout=None):
        if timeout is not None:self.adapter._deadline=min(self.adapter._deadline,time.monotonic()+timeout)
        return self.adapter.generate(text,max_tokens=max_tokens)
    def metrics(self):return self.adapter.metrics()
