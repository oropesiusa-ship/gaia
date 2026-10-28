"""Persistent bounded chat custody; model text remains data with authority NONE."""
import fcntl
import json
from contextlib import contextmanager
from pathlib import Path

from ..provenance import canonical_json,digest
from .schema import ref,safe_text,seal
from .store import CognitiveStore


ROLES=('USER','ASSISTANT')


def project_history(turns,count_tokens,maximum,*,reserve=0):
    """Keep the newest complete turns that fit an exact tokenizer budget."""
    if type(maximum)is not int or type(reserve)is not int or maximum<1 or not 0<=reserve<maximum:
        raise ValueError('INVALID_CHAT_CONTEXT_BUDGET')
    selected=[];excluded=[]
    for turn in reversed(turns):
        candidate=[turn,*selected]
        text=json.dumps([{'role':v['payload']['role'].lower(),'content':v['payload']['content']}
                         for v in candidate],separators=(',',':'),ensure_ascii=True)
        count=count_tokens(text)
        if type(count)is not int or count<1:raise ValueError('EXACT_TOKEN_COUNT_REQUIRED')
        if count+reserve<=maximum:selected=candidate
        else:excluded.append({'id':turn['id'],'reason':'CHAT_CONTEXT_BUDGET'})
    text=json.dumps([{'role':v['payload']['role'].lower(),'content':v['payload']['content']}
                     for v in selected],separators=(',',':'),ensure_ascii=True)
    tokens=count_tokens(text)
    if type(tokens)is not int or tokens<1:raise ValueError('EXACT_TOKEN_COUNT_REQUIRED')
    return {'turns':selected,'included':[ref(v)for v in selected],
            'excluded':list(reversed(excluded)),'input_tokens':tokens,
            'maximum_tokens':maximum,'reserved_output_tokens':reserve,
            'policy':'NEWEST_COMPLETE_TURNS_EXACT_TOKEN_COUNT_NO_SUMMARY_INVENTION'}


class ConversationStore:
    def __init__(self,state):
        self.store=CognitiveStore(state);self.root=Path(state)/'cognition'

    @contextmanager
    def _locked(self,identifier):
        if not isinstance(identifier,str)or not identifier.startswith('cg'):
            raise ValueError('INVALID_CONVERSATION_ID')
        directory=self.root/'conversation-locks';directory.mkdir(parents=True,exist_ok=True)
        path=directory/(identifier+'.lock')
        if path.is_symlink():raise ValueError('CONVERSATION_LOCK_SYMLINK')
        with path.open('a+b')as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)

    def create(self,label):
        safe_text(label,200)
        if not label.strip():raise ValueError('EMPTY_CONVERSATION_LABEL')
        return self.store.put(seal('CONVERSATION',{'label':label,'status':'OPEN',
            'authority':'NONE','model_tool_authority':'NONE','hidden_reasoning_stored':False}))

    def _conversation(self,identifier):
        value=self.store.get(identifier,'CONVERSATION')
        p=value['payload']
        if p.get('status')!='OPEN'or p.get('authority')!='NONE'or p.get('model_tool_authority')!='NONE':
            raise ValueError('INVALID_CONVERSATION_AUTHORITY')
        return value

    def history(self,identifier):
        conversation=self._conversation(identifier);turns=[]
        for value in self.store.list('CHAT_TURN'):
            if value['payload'].get('conversation_ref')==ref(conversation):turns.append(value)
        by_previous={}
        for value in turns:
            previous=value['payload']['previous_ref']['id'] if value['payload']['previous_ref'] else None
            by_previous.setdefault(previous,[]).append(value)
        ordered=[];previous=None
        while previous in by_previous:
            candidates=by_previous.pop(previous)
            if len(candidates)!=1:raise ValueError('AMBIGUOUS_CHAT_HISTORY_FORK')
            value=candidates[0]
            if value['payload']['sequence']!=len(ordered)+1:raise ValueError('CHAT_SEQUENCE_MISMATCH')
            ordered.append(value);previous=value['id']
        if by_previous or len(ordered)!=len(turns):raise ValueError('DISCONNECTED_CHAT_HISTORY')
        return ordered

    def append(self,identifier,role,content):
        if role not in ROLES:raise ValueError('INVALID_CHAT_ROLE')
        safe_text(content,20000)
        if not content.strip():raise ValueError('EMPTY_CHAT_TURN')
        with self._locked(identifier):
            conversation=self._conversation(identifier);history=self.history(identifier)
            previous=ref(history[-1])if history else None
            value=seal('CHAT_TURN',{'conversation_ref':ref(conversation),'sequence':len(history)+1,
                'previous_ref':previous,'role':role,'content':content,'content_sha256':digest(content),
                'authority':'NONE','tool_calls_executed':0,'hidden_reasoning':False})
            return self.store.put(value)

    def context(self,identifier,count_tokens,maximum,*,reserve=0):
        return project_history(self.history(identifier),count_tokens,maximum,reserve=reserve)
