"""Endurance session (1.1 §2): an immutable contract with aggregate budgets over sequential campaigns of fixed lineages."""
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import uuid
from ..provenance import digest
from .store import durable
from .lineage import LineageStore,engine_state_dir
from .policy import disk_bytes

EVENTS=('CREATED','CAMPAIGN_STARTED','CAMPAIGN_RELAUNCHED','CAMPAIGN_FINISHED','HANG_DETECTED','CHILD_EXITED','LINEAGE_SKIPPED',
        'STOP_REQUESTED','STORAGE_GATE','RESOURCE_RESERVE','SUPERVISOR_STARTED','STOPPED')
LIMITS={'campaign_wall_s':(60,3600),'campaign_iterations':(1,5),'campaign_experiments':(1,5),'campaign_disk_bytes':(2**20,2*2**30),
        'vram_sample_s':(1,3600),'storage_sample_s':(1,3600),'maximum_campaigns':(1,500),'maximum_wall_s':(60,30*86400),'maximum_compute_s':(60,30*86400),'maximum_storage_bytes':(1,64*2**30),
        'maximum_restarts':(0,100),'maximum_recoveries':(0,100),'maximum_research':(0,0),'relaunches_per_campaign':(0,2),
        'hang_timeout_s':(60,6*3600),'heartbeat_s':(1,600),'minimum_campaign_s':(60,3600)}
# Plan cadences (heartbeat 10 s, processes with each heartbeat, VRAM 30 s, disk 60 s) and recovery limits (2/campaign, 3/session).
DEFAULTS={'campaign_wall_s':3600,'campaign_iterations':5,'campaign_experiments':5,'campaign_disk_bytes':512*2**20,'vram_sample_s':30,
          'storage_sample_s':60,'maximum_campaigns':4,'maximum_wall_s':4*3600,'maximum_compute_s':4*3600,'maximum_storage_bytes':2**30,'maximum_restarts':3,
          'maximum_recoveries':3,'maximum_research':0,'relaunches_per_campaign':2,'hang_timeout_s':2700,'heartbeat_s':10,'minimum_campaign_s':900}
CAMPAIGN_CAP_S=3600


def session_contract(lineages,*,stage,mode='CONTROLLED_AUTONOMOUS',promotion=False,limits=None,frozen=None):
    if not lineages or len(set(lineages))!=len(lineages):raise ValueError('SESSION_LINEAGES_REQUIRED')
    if not isinstance(frozen,dict)or 'hash'not in frozen:raise ValueError('PROTOCOL_FREEZE_REQUIRED')
    value={'schema':'gaia_endurance_session_v1','session_id':'as'+uuid.uuid4().hex[:24],'stage':stage,'lineages':list(lineages),'freeze':frozen,
        'mode':mode,'allow_promotion':bool(promotion),'limits':{**DEFAULTS,**(limits or{})},'created_at':datetime.now(timezone.utc).isoformat(),
        'scope':'SEQUENTIAL_CAMPAIGNS_AGGREGATE_BUDGETS_COMPUTE_IS_SUM_OF_CAMPAIGN_WALL_TIME'}
    value['hash']=digest(value);return validate_session(value)


def validate_session(v):
    keys={'schema','session_id','stage','lineages','freeze','mode','allow_promotion','limits','created_at','scope','hash'}
    if not isinstance(v,dict)or set(v)!=keys or v['schema']!='gaia_endurance_session_v1'or not re.fullmatch(r'as[a-f0-9]{24}',v['session_id']):raise ValueError('INVALID_SESSION_SCHEMA')
    if not isinstance(v['stage'],str)or not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}',v['stage']):raise ValueError('INVALID_SESSION_STAGE')
    if v['mode']not in ('DRY_RUN','SHADOW','CONTROLLED_AUTONOMOUS')or not all(isinstance(x,str)and re.fullmatch(r'al[a-f0-9]{24}',x)for x in v['lineages']):raise ValueError('INVALID_SESSION_SCOPE')
    if set(v['limits'])!=set(LIMITS)or any(type(v['limits'][k])is not int or not lo<=v['limits'][k]<=hi for k,(lo,hi)in LIMITS.items()):raise ValueError('SESSION_LIMIT_ESCALATION')
    if not isinstance(v['freeze'],dict)or v['freeze'].get('hash')!=digest({k:x for k,x in v['freeze'].items()if k!='hash'})or set(v['freeze']['lineages'])!=set(v['lineages']):
        raise ValueError('INVALID_PROTOCOL_FREEZE')
    if v['hash']!=digest({k:x for k,x in v.items()if k!='hash'}):raise ValueError('SESSION_HASH_MISMATCH')
    return v


class SessionStore:
    def __init__(self,state,identifier):
        if not isinstance(identifier,str)or not re.fullmatch(r'as[a-f0-9]{24}',identifier):raise ValueError('INVALID_SESSION_ID')
        self.state=Path(state);self.identifier=identifier;self.root=self.state/'autonomy'/'sessions'/identifier
        if any(p.is_symlink()for p in (self.state,self.root.parent,self.root)):raise ValueError('AUTONOMY_SYMLINK_DENIED')

    def create(self,contract,root):
        validate_session(contract)
        if contract['session_id']!=self.identifier:raise ValueError('SESSION_ID_MISMATCH')
        if self.root.exists():raise FileExistsError('SESSION_EXISTS')
        for lineage in contract['lineages']:LineageStore(self.state,lineage).read()
        self.root.mkdir(parents=True);durable(self.root/'contract.json',contract,True)
        self.event('CREATED',{'session_hash':contract['hash'],'baseline_storage_bytes':self.storage(root,contract)})
        return contract

    def read(self):return validate_session(json.loads((self.root/'contract.json').read_bytes()))

    def events(self):
        result=[];previous=None
        for i,path in enumerate(sorted((self.root/'events').glob('*.json')),1):
            if path.is_symlink():raise ValueError('EVENT_SYMLINK')
            v=json.loads(path.read_bytes())
            if v['sequence']!=i or v['previous_hash']!=previous or v['kind']not in EVENTS or v['hash']!=digest({k:x for k,x in v.items()if k!='hash'}):raise ValueError('SESSION_JOURNAL_CORRUPTED')
            previous=v['hash'];result.append(v)
        return result

    def event(self,kind,payload):
        if kind not in EVENTS:raise ValueError('INVALID_SESSION_EVENT')
        from .clock import stamp
        events=self.events();clock=stamp()
        value={'sequence':len(events)+1,'previous_hash':events[-1]['hash']if events else None,'timestamp':clock['wall'],'clock':clock,'kind':kind,'payload':payload}
        value['hash']=digest(value);durable(self.root/'events'/f"{value['sequence']:06d}.json",value,True);return value

    def storage(self,root,contract=None):
        """Bytes owned by the session: its directory, its campaigns, and its lineages (journals, shared subsystems, numpy engine state)."""
        contract=contract or self.read();total=disk_bytes(self.root)if self.root.exists()else 0
        if self.root.exists():
            for campaign in {e['payload']['campaign_id']for e in self.events()if e['kind']=='CAMPAIGN_STARTED'}:
                path=self.state/'autonomy'/'campaigns'/campaign
                if path.exists():total+=disk_bytes(path)
        for lineage in contract['lineages']:
            total+=disk_bytes(LineageStore(self.state,lineage).root)
            engine=Path(root)/engine_state_dir(lineage)
            if engine.exists():total+=disk_bytes(engine)
        return total

    def state_view(self):
        """Pure fold of the session journal."""
        s={'campaigns':[],'running':None,'finished':[],'compute_s':0.,'restarts':0,'recoveries':0,'research':0,'skipped':{},'stopped':None,
           'stop_requested':False,'stop_reason':None,'started_clock':None,'baseline_storage_bytes':None,'supervisor_starts':0}
        for ev in self.events():
            k,p=ev['kind'],ev['payload']
            if k=='CREATED':s['started_clock']=ev['clock'];s['baseline_storage_bytes']=p['baseline_storage_bytes']
            elif k=='CAMPAIGN_STARTED':s['campaigns'].append(p['campaign_id']);s['running']=p['campaign_id']
            # A relaunch after a supervisor restart is already counted by that SUPERVISOR_STARTED.
            elif k=='CAMPAIGN_RELAUNCHED':s['restarts']+=0 if p.get('reason')=='SUPERVISOR_RESTART'else 1;s['recoveries']+=1;s['running']=p['campaign_id']
            elif k=='CAMPAIGN_FINISHED':
                s['finished'].append(p);s['running']=None;s['compute_s']+=p.get('wall_s')or 0.;s['research']+=p.get('research_calls')or 0
            elif k=='LINEAGE_SKIPPED':s['skipped'][p['lineage_id']]=p['reason']
            elif k=='STOP_REQUESTED':s['stop_requested']=True;s['stop_reason']=s['stop_reason']or p.get('reason')
            elif k=='SUPERVISOR_STARTED':s['supervisor_starts']+=1
            elif k=='STORAGE_GATE':s['storage_gate']=max(s.get('storage_gate')or 0,p['gate'])
            elif k=='STOPPED':s['stopped']=p
        return s


def restarts_used(view):
    """Campaign relaunches plus supervisor restarts beyond the first start."""
    return view['restarts']+max(0,view.get('supervisor_starts',0)-1)


def budget(contract,view,storage_bytes,now_clock):
    """Aggregate session budget: (remaining campaign seconds, reasons that forbid starting another campaign)."""
    from .clock import interval
    limits=contract['limits'];reasons=[]
    wall=interval(view['started_clock'],now_clock)[0]if view['started_clock']else 0.
    remaining=min(limits['maximum_wall_s']-wall,limits['maximum_compute_s']-view['compute_s'],CAMPAIGN_CAP_S,limits['campaign_wall_s'])
    if len(view['campaigns'])>=limits['maximum_campaigns']:reasons.append('SESSION_CAMPAIGN_BUDGET')
    if limits['maximum_wall_s']-wall<limits['minimum_campaign_s']:reasons.append('SESSION_WALL_BUDGET')
    if limits['maximum_compute_s']-view['compute_s']<limits['minimum_campaign_s']:reasons.append('SESSION_COMPUTE_BUDGET')
    if storage_bytes-(view['baseline_storage_bytes']or 0)>=limits['maximum_storage_bytes']:reasons.append('SESSION_STORAGE_BUDGET')
    # Campaign relaunches and supervisor restarts beyond the first start share the restart budget.
    if restarts_used(view)>limits['maximum_restarts']or view['recoveries']>limits['maximum_recoveries']:
        reasons.append('SESSION_RESTART_BUDGET')
    if view['research']>limits['maximum_research']:reasons.append('SESSION_RESEARCH_BUDGET')
    return max(0.,remaining),reasons
