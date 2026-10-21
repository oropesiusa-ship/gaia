"""Locked, fsynced campaign journal; current is a recoverable projection of committed events."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
import time
from ..atomic_publish import fsync_directory
from ..provenance import canonical_json,digest
from .schema import validate_campaign,validate_artifact,artifact,ref,STATES

NEXT={'CREATED':{'OBSERVING'},'OBSERVING':{'DIAGNOSING'},'DIAGNOSING':{'PRIORITIZING'},'PRIORITIZING':{'RETRIEVING'},
      'RETRIEVING':{'RESEARCHING'},'RESEARCHING':{'PLANNING'},'PLANNING':{'REVIEWING'},'REVIEWING':{'AUTHORIZING'},
      'AUTHORIZING':{'MATERIALIZING'},'MATERIALIZING':{'EXPERIMENTING'},'EXPERIMENTING':{'EVALUATING'},'EVALUATING':{'LEARNING'},
      'LEARNING':{'PROMOTING','REEVALUATING'},'PROMOTING':{'VERIFYING'},'VERIFYING':{'ROLLING_BACK','REEVALUATING'},
      'ROLLING_BACK':{'REEVALUATING'},'REEVALUATING':{'OBSERVING'}}
TERMINAL={'COMPLETED','STOPPED','FAILED'}


def durable(path,value,immutable=False):
    path=Path(path)
    if path.is_symlink()or path.parent.is_symlink():raise ValueError('AUTONOMY_SYMLINK_DENIED')
    path.parent.mkdir(parents=True,exist_ok=True);raw=canonical_json(value)
    if immutable and path.exists():
        if path.read_bytes()!=raw:raise ValueError('IMMUTABLE_CONFLICT')
        return
    fd,tmp=tempfile.mkstemp(prefix='.pending-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb')as f:f.write(raw);f.flush();os.fsync(f.fileno());os.fchmod(f.fileno(),0o444 if immutable else 0o600)
        if immutable:os.link(tmp,path)
        else:os.replace(tmp,path)
        fsync_directory(path.parent)
    finally:Path(tmp).unlink(missing_ok=True)


class CampaignStore:
    def __init__(self,state,identifier):
        if not re.fullmatch(r'ac[a-f0-9]{24}',identifier):raise ValueError('INVALID_CAMPAIGN_ID')
        self.root=Path(state)/'autonomy'/'campaigns'/identifier
        if any(p.is_symlink()for p in (Path(state),self.root.parent.parent,self.root.parent,self.root)):raise ValueError('AUTONOMY_SYMLINK_DENIED')

    def create(self,contract,configuration):
        validate_campaign(contract)
        if self.root.exists():raise FileExistsError('CAMPAIGN_EXISTS')
        self.root.mkdir(parents=True)
        durable(self.root/'contract.json',contract,True);durable(self.root/'configuration.json',configuration,True)
        durable(self.root/'control.json',{'request':'RUN'})
        self.event('CREATED',{'iteration':0,'experiments':0,'research_calls':0,'compute_reserved_s':0,'started_at':None,'reason':None})

    @contextmanager
    def lock(self):
        if not self.root.is_dir():raise ValueError('CAMPAIGN_NOT_CREATED')
        path=self.root/'.lock'
        if path.is_symlink():raise ValueError('LOCK_SYMLINK')
        with path.open('a+b')as f:
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:yield self
            finally:fcntl.flock(f,fcntl.LOCK_UN)

    def read(self,name):
        if name not in ('contract','configuration','current','control'):raise ValueError('INVALID_CAMPAIGN_DOCUMENT')
        path=self.root/(name+'.json')
        if path.is_symlink():raise ValueError('AUTONOMY_SYMLINK_DENIED')
        return json.loads(path.read_bytes())

    def put(self,kind,payload):
        value=artifact(kind,payload);durable(self.root/'artifacts'/(value['id']+'.json'),value,True);return ref(value)

    def get(self,r):
        if not isinstance(r,dict)or set(r)!={'id','hash'}or not re.fullmatch(r'au[a-f0-9]{24}',r['id']):raise ValueError('INVALID_ARTIFACT_REF')
        path=self.root/'artifacts'/(r['id']+'.json')
        if path.is_symlink():raise ValueError('AUTONOMY_SYMLINK_DENIED')
        v=validate_artifact(json.loads(path.read_bytes()))
        if ref(v)!=r:raise ValueError('ARTIFACT_REF_MISMATCH')
        return v['payload']

    def events(self):
        result=[];previous=None
        for i,path in enumerate(sorted((self.root/'events').glob('*.json')),1):
            if path.is_symlink():raise ValueError('EVENT_SYMLINK')
            v=json.loads(path.read_bytes())
            if v['sequence']!=i or v['previous_hash']!=previous or v['hash']!=digest({k:x for k,x in v.items()if k!='hash'}):raise ValueError('JOURNAL_CORRUPTED')
            previous=v['hash'];result.append(v)
        return result

    def current(self):
        events=self.events()
        if not events:raise ValueError('EMPTY_JOURNAL')
        expected=events[-1]['state']
        # Commit point is immutable event; repair only the derived cursor.
        if not(self.root/'current.json').exists()or self.read('current')!=expected:durable(self.root/'current.json',expected)
        return expected

    def event(self,phase,updates=None):
        events=self.events();prior=events[-1]['state']if events else{}
        old=prior.get('phase')
        resumed=old=='PAUSED'and phase==prior.get('resume_phase')
        if phase not in STATES or(not old and phase!='CREATED')or(old and not resumed and phase!=old and phase not in NEXT.get(old,set())and phase not in TERMINAL|{'PAUSED'}):raise ValueError('INVALID_STATE_TRANSITION')
        if old in TERMINAL:raise ValueError('CAMPAIGN_ALREADY_TERMINAL')
        state={**prior,**(updates or {}),'phase':phase}
        value={'sequence':len(events)+1,'previous_hash':events[-1]['hash']if events else None,'timestamp':time.time(),'state':state}
        value['hash']=digest(value)
        durable(self.root/'events'/f"{value['sequence']:06d}.json",value,True);durable(self.root/'current.json',state);return state

    def control(self,request):
        if request not in ('RUN','PAUSE','STOP'):raise ValueError('INVALID_CONTROL')
        with (self.root/'.control.lock').open('a+b')as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            receipt=artifact('OPERATOR_CONTROL',{'request':request})
            durable(self.root/'controls'/(receipt['id']+'.json'),receipt,True)
            durable(self.root/'control.json',{'request':request})
