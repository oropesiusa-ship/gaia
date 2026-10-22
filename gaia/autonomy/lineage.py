"""Persistent experimental lineage shared by successive bounded campaigns, one active campaign at a time."""
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import json
from pathlib import Path
import re
import time
import uuid
from ..provenance import digest
from .store import durable
from .schema import OBJECTIVES

EVENTS=('CREATED','CAMPAIGN_ADMITTED','CAMPAIGN_CLOSED','BLOCKED','UNBLOCKED','BASELINE_OBSERVATION','EXPERIMENT_RECORDED','META_TUNE','HEALTH_CHECK',
        'REFERENCE_MEASURED','REGRESSION_SIGNAL')


class LineageBusy(RuntimeError):pass


def engine_state_dir(identifier):return 'state_closed_loop_lineage_'+identifier[2:]


def lineage_contract(objective,source_identity,intelligence_state):
    if objective not in OBJECTIVES:raise ValueError('UNSUPPORTED_LINEAGE_OBJECTIVE')
    surface=OBJECTIVES[objective][0];identifier='al'+uuid.uuid4().hex[:24]
    v={'schema':'gaia_closed_loop_lineage_v1','lineage_id':identifier,'objective':objective,'surface':surface,
       'source_identity_hash':source_identity['hash'],'protected_hash':source_identity['protected_hash'],
       'engine_state_dir':engine_state_dir(identifier)if surface=='numpy_mlp'else None,'intelligence_state':intelligence_state,
       'scope':'ONE_SURFACE_ONE_SOURCE_IDENTITY_SEQUENTIAL_CAMPAIGNS','created_at':datetime.now(timezone.utc).isoformat()}
    v['hash']=digest(v);return validate_lineage(v)


def validate_lineage(v):
    keys={'schema','lineage_id','objective','surface','source_identity_hash','protected_hash','engine_state_dir','intelligence_state','scope','created_at','hash'}
    if not isinstance(v,dict)or set(v)!=keys or v['schema']!='gaia_closed_loop_lineage_v1'or not re.fullmatch(r'al[a-f0-9]{24}',v['lineage_id']):raise ValueError('INVALID_LINEAGE_SCHEMA')
    if v['objective']not in OBJECTIVES or v['surface']!=OBJECTIVES[v['objective']][0]:raise ValueError('INVALID_LINEAGE_OBJECTIVE')
    if v['engine_state_dir']!=(engine_state_dir(v['lineage_id'])if v['surface']=='numpy_mlp'else None):raise ValueError('ENGINE_STATE_SCOPE_ESCAPE')
    if Path(v['intelligence_state']).is_absolute()or len(Path(v['intelligence_state']).parts)!=1:raise ValueError('LOCAL_INTELLIGENCE_STATE_REQUIRED')
    if v['hash']!=digest({k:x for k,x in v.items()if k!='hash'}):raise ValueError('LINEAGE_HASH_MISMATCH')
    return v


class LineageStore:
    def __init__(self,state,identifier):
        if not isinstance(identifier,str)or not re.fullmatch(r'al[a-f0-9]{24}',identifier):raise ValueError('INVALID_LINEAGE_ID')
        self.identifier=identifier;self.root=Path(state)/'autonomy'/'lineages'/identifier
        if any(p.is_symlink()for p in (Path(state),self.root.parent.parent,self.root.parent,self.root)):raise ValueError('AUTONOMY_SYMLINK_DENIED')
        self.subsystems=self.root/'subsystems'

    def create(self,contract):
        validate_lineage(contract)
        if contract['lineage_id']!=self.identifier:raise ValueError('LINEAGE_ID_MISMATCH')
        if self.root.exists():raise FileExistsError('LINEAGE_EXISTS')
        self.root.mkdir(parents=True);durable(self.root/'contract.json',contract,True);self.event('CREATED',{'lineage_hash':contract['hash']})
        return contract

    def read(self):
        path=self.root/'contract.json'
        if path.is_symlink():raise ValueError('AUTONOMY_SYMLINK_DENIED')
        return validate_lineage(json.loads(path.read_bytes()))

    def events(self):
        result=[];previous=None
        for i,path in enumerate(sorted((self.root/'events').glob('*.json')),1):
            if path.is_symlink():raise ValueError('EVENT_SYMLINK')
            v=json.loads(path.read_bytes())
            if v['sequence']!=i or v['previous_hash']!=previous or v['kind']not in EVENTS or v['hash']!=digest({k:x for k,x in v.items()if k!='hash'}):raise ValueError('LINEAGE_JOURNAL_CORRUPTED')
            previous=v['hash'];result.append(v)
        return result

    def event(self,kind,payload):
        if kind not in EVENTS:raise ValueError('INVALID_LINEAGE_EVENT')
        events=self.events()
        value={'sequence':len(events)+1,'previous_hash':events[-1]['hash']if events else None,'timestamp':time.time(),'kind':kind,'payload':payload}
        value['hash']=digest(value);durable(self.root/'events'/f"{value['sequence']:06d}.json",value,True);return value

    def state(self):
        """Pure fold of the committed journal; inspection never repairs or locks."""
        s={'blocked':False,'block':None,'campaigns':[],'open_campaigns':[],'baseline':None,'experiments':0,'records':[],'meta_tunes':0,
           'experiments_at_last_tune':0,'health_checks':0,'reference':None,'regression_signals':0}
        for ev in self.events():
            k,p=ev['kind'],ev['payload']
            if k=='CAMPAIGN_ADMITTED':s['campaigns'].append(p['campaign_id']);s['open_campaigns'].append(p['campaign_id'])
            elif k=='CAMPAIGN_CLOSED':s['open_campaigns']=[c for c in s['open_campaigns']if c!=p['campaign_id']]
            elif k=='BLOCKED':s['blocked'],s['block']=True,p
            elif k=='UNBLOCKED':s['blocked'],s['block']=False,None
            elif k=='BASELINE_OBSERVATION':s['baseline']={'observation_id':p['observation_id'],'observation_hash':p['observation_hash']}
            elif k=='EXPERIMENT_RECORDED':s['experiments']+=1;s['records'].append(p['record_ref'])
            elif k=='META_TUNE':s['meta_tunes']+=1;s['experiments_at_last_tune']=s['experiments']
            elif k=='HEALTH_CHECK':s['health_checks']+=1
            elif k=='REFERENCE_MEASURED':s['reference']=p
            elif k=='REGRESSION_SIGNAL':s['regression_signals']+=1
        return s

    @contextmanager
    def lock(self):
        if not self.root.is_dir():raise ValueError('LINEAGE_NOT_CREATED')
        path=self.root/'.lock'
        if path.is_symlink():raise ValueError('LOCK_SYMLINK')
        with path.open('a+b')as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:raise LineageBusy('LINEAGE_BUSY')from exc
            try:yield self
            finally:fcntl.flock(f,fcntl.LOCK_UN)


def create_lineage(root,state,objective,*,intelligence_state='state_local_intelligence'):
    from .policy import identities
    contract=lineage_contract(objective,identities(root),intelligence_state)
    return LineageStore(state,contract['lineage_id']).create(contract)


@contextmanager
def host_experiment_lock(root):
    """Never measure a numpy trial and an inference benchmark concurrently on this host."""
    path=Path(root)/'.gaia'/'locks'/'experiment.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError('LOCK_SYMLINK')
    with path.open('a+b')as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise LineageBusy('HOST_EXPERIMENT_BUSY')from exc
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)
