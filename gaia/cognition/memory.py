"""Deterministic cross-conversation recall over immutable user turns."""
import re
from .schema import ref


STOP={'a','al','and','de','del','el','en','es','for','la','las','lo','los','mi','of','que','the','to','un','una','y'}


def terms(text):
    return {v for v in re.findall(r'[^\W_]{2,}',text.casefold(),re.UNICODE) if v not in STOP}


def retrieve(store,conversation,query,*,limit=3,maximum_chars=1600):
    """Return bounded same-owner user memories; never infer or summarize."""
    if type(limit)is not int or not 0<=limit<=10 or type(maximum_chars)is not int or not 0<=maximum_chars<=10000:
        raise ValueError('INVALID_MEMORY_BUDGET')
    owner=conversation['payload'].get('owner_id','local');wanted=terms(query);candidates=[]
    if not wanted or not limit:return []
    owners={value['id']:value['payload'].get('owner_id','local') for value in store.list('CONVERSATION')}
    for turn in store.list('CHAT_TURN'):
        payload=turn['payload'];conversation_id=payload.get('conversation_ref',{}).get('id')
        if (payload.get('role')!='USER'or conversation_id==conversation['id']
                or owners.get(conversation_id)!=owner):continue
        overlap=wanted&terms(payload.get('content',''))
        if overlap:candidates.append((-len(overlap),-payload.get('sequence',0),turn['id'],turn))
    result=[];used=0
    for _,_,_,turn in sorted(candidates):
        content=turn['payload']['content']
        if used+len(content)>maximum_chars:continue
        result.append({'turn_ref':ref(turn),'content':content,'authority':'NONE','match_terms':sorted(wanted&terms(content))})
        used+=len(content)
        if len(result)==limit:break
    return result
