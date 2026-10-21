"""Selected 0.8 backend facade; orchestration never selects a runtime by name."""
import time
from .controller import selected_backend
from .model_adapter import format_prompt


class PrimaryLocalIntelligenceBackend:
    def __init__(self,state,selection='latest'):
        self.adapter,self.selection=selected_backend(state,selection)

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
