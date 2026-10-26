#!/usr/bin/env python3
"""Administrative-only preparation and verification for GAIA 1.1 Stage 2.

It never creates, admits, or runs a campaign.  Session execution remains forbidden until
an operator authorizes a later, separately recorded transition.
"""
import argparse,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from gaia.autonomy.clock import stamp
from gaia.autonomy.freeze import changes,freeze,git
from gaia.autonomy.policy import identities
from gaia.autonomy.session import SessionStore,budget
from gaia.autonomy.store import CampaignStore,TERMINAL
from gaia.autonomy.telemetry import filesystem,memory
from gaia.autonomy.catalog import applicability

LIMITS={'campaign_wall_s':1800,'campaign_iterations':5,'campaign_experiments':3,'campaign_disk_bytes':512*2**20,
 'maximum_campaigns':2,'maximum_wall_s':7200,'maximum_compute_s':7200,'maximum_storage_bytes':4*2**30,
 'maximum_research':0,'maximum_restarts':3,'maximum_recoveries':3,'relaunches_per_campaign':2,
 'hang_timeout_s':2700,'heartbeat_s':10,'vram_sample_s':30,'storage_sample_s':60,'minimum_campaign_s':900}
PREREG=ROOT/'docs/endurance_evidence/STAGE2_PREREGISTRATION_AND_RUNBOOK.md'
CONTRACT_KEYS={'schema','stage','status','commit','identity','freeze','limits','lineages','preregistration_sha256','baseline','plan',
 'executor_sha256','runtime','boot_id','resources','inventory','campaigns_authorized','sessions_started',
 'execution_prohibited','clock','hash'}

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def boot_id():
    path=Path('/proc/sys/kernel/random/boot_id');return path.read_text().strip() if path.exists() else 'UNAVAILABLE'
def safe_git(root,*args):
    result=subprocess.run(['git',*args],cwd=root,capture_output=True,text=True)
    if result.returncode:return None
    return result.stdout.strip()
def safe_out(root,out):
    base=(Path(root)/'.gaia'/'stage2').resolve();out=Path(out)
    if out.is_symlink() or any(p.is_symlink() for p in [out.parent,*out.parents] if p.exists()):raise ValueError('SYMLINKED_CONTRACT_PATH')
    if not str(out.resolve().parent).startswith(str(base)+os.sep):raise ValueError('CONTRACT_OUTSIDE_STAGE2_EVIDENCE')
    return out
def inventory(paths):
    result={}
    for base in map(Path,paths):
        if not base.exists():continue
        if base.is_file():
            if base.is_symlink():raise ValueError('SYMLINK_IN_RECONCILIATION_SCOPE')
            result[str(base)]=sha(base);continue
        for p in sorted(base.rglob('*')):
            if '__pycache__' in p.parts or p.suffix=='.pyc':continue
            if p.is_symlink():raise ValueError('SYMLINK_IN_RECONCILIATION_SCOPE')
            if p.is_file():result[str(p)]=sha(p)
    return result
def frozen(root,state,lineages):return freeze(Path(root),Path(state),list(lineages))
def validate_contract(c):
    if not isinstance(c,dict) or set(c)!=CONTRACT_KEYS or c.get('schema')!='gaia_stage2_contract_v1':raise ValueError('INVALID_STAGE2_CONTRACT')
    if c['hash']!=digest({k:v for k,v in c.items()if k!='hash'}):raise ValueError('STAGE2_CONTRACT_HASH_MISMATCH')
    if c['stage']!='stage2' or c['limits']!=LIMITS or c['campaigns_authorized']!=0 or c['sessions_started']!=0 or not c['execution_prohibited']:
        raise ValueError('STAGE2_CONTRACT_SCOPE_INVALID')
    return c

def admission(c,root=ROOT,state=None):
    """Pure fail-closed preflight; it cannot admit a campaign."""
    c=validate_contract(c);root=Path(root);state=Path(state or root/'state');reasons=[]
    current=frozen(root,state,c['lineages'])
    if c['commit']!=git(root,'rev-parse','HEAD'):reasons.append('COMMIT_CHANGED')
    if c['identity']!=identities(root):reasons.append('SOURCE_IDENTITY_CHANGED')
    if c['freeze']!=current:reasons.append('FROZEN_PROTOCOL_CHANGED')
    if changes(root,state,c['freeze']):reasons.append('PROTOCOL_CHANGED')
    if c['preregistration_sha256']!=sha(PREREG) or c['executor_sha256']!=sha(__file__):reasons.append('ADMINISTRATIVE_HASH_CHANGED')
    if c['boot_id']!=boot_id() or c['boot_id']=='UNAVAILABLE':reasons.append('BOOT_ID_CHANGED')
    runtime={'python':sys.version,'executable':sys.executable}
    if c['runtime']!=runtime:reasons.append('RUNTIME_CHANGED')
    if c['inventory']!=inventory([root/'gaia',root/'gaia.py']):reasons.append('INVENTORY_CHANGED')
    host,disk=memory(),filesystem(root)
    if host.get('available_bytes')is None or host.get('below_reserve'):reasons.append('HOST_MEMORY_RESERVE')
    if disk.get('free_bytes') is None or disk.get('below_reserve'):reasons.append('FILESYSTEM_RESERVE')
    return {'status':'PASS'if not reasons else'BLOCKED_PREEXECUTION','reasons':reasons,'freeze':current,'resources':{'memory':host,'filesystem':disk}}

def read_only_inspection(paths):
    before=inventory(paths);after=inventory(paths)
    return {'status':'PASS'if before==after else'FAIL','manifest':before,'written':before!=after}

def terminal_noop(state,campaign_id,paths):
    """Read-only terminal verification; this preparation tool never invokes a campaign."""
    store=CampaignStore(state,campaign_id);phase=store.inspect()['state']['phase']
    if phase not in TERMINAL:return {'status':'FAIL','reason':'NONTERMINAL_REOPEN_REFUSED','writes':False}
    scope=[*paths,Path(state)/'autonomy'/'campaigns'/campaign_id];before=inventory(scope);after=inventory(scope)
    changed=sorted(p for p in set(before)|set(after)if before.get(p)!=after.get(p))
    return {'status':'PASS'if not changed else'FAIL','result':'TERMINAL_NOOP','changed_paths':changed,'writes':bool(changed)}

def aggregate_preserved(store,root,previous=None):
    c=store.read();v=store.state_view();remaining,reasons=budget(c,v,store.storage(root,c),stamp())
    snapshot={'compute_s':v['compute_s'],'campaigns':v['campaigns'],'restarts':v['restarts'],'recoveries':v['recoveries'],'research':v['research']}
    preserved=previous is None or all(snapshot[k]>=previous[k] if isinstance(snapshot[k],(int,float)) else snapshot[k][:len(previous[k])]==previous[k] for k in snapshot)
    return {'status':'PASS'if v['compute_s']>=0 and preserved else'FAIL','compute_s':v['compute_s'],'campaigns':len(v['campaigns']),
            'remaining_s':remaining,'reasons':reasons,'snapshot':snapshot,'aggregate_snapshot':digest(snapshot)}
def learning(reference,binding):
    value=applicability(reference,binding);return {'status':'PASS'if value['status']in('EXACT','INCOMPATIBLE')else'FAIL','applicability':value}
def reconcile(store,owned_paths,require_terminal=True):
    """Read-only ledger/intents/receipts reconciliation; no repair path exists."""
    try:
        c=store.read();events=store.events();v=store.state_view();fail=[]
        if not events or v['started_clock']is None:fail.append('MISSING_SESSION_JOURNAL')
        if require_terminal and (v['running'] or not v['stopped'] or len(v['finished'])!=len(v['campaigns'])):fail.append('SESSION_NOT_TERMINAL')
        started=[e['payload']['campaign_id']for e in events if e['kind']=='CAMPAIGN_STARTED']
        finished=[e['payload'].get('campaign_id') for e in events if e['kind']=='CAMPAIGN_FINISHED']
        if len(started)!=len(set(started)):fail.append('DUPLICATE_CAMPAIGN_START')
        if any(x not in started for x in finished) or (require_terminal and set(started)!=set(finished)):fail.append('CAMPAIGN_FINISH_MISMATCH')
        for cid in v['campaigns']:
            state=CampaignStore(store.state,cid).inspect()['state']
            if require_terminal and state['phase']not in TERMINAL:fail.append('CAMPAIGN_NOT_TERMINAL:'+cid)
            if any(state.get(k)for k in ('execution_intent','initialization_intent','research_intent','rollback_intent')):fail.append('UNRECONCILED_INTENT:'+cid)
        required=[store.root/'telemetry',store.root/'evidence']
        if require_terminal and any(not p.exists() for p in required):fail.append('MISSING_TELEMETRY_OR_EVIDENCE')
        return {'status':'PASS'if not fail else'FAIL','failures':fail,'events':len(events),'campaigns':len(v['campaigns']),
                'finished':len(v['finished']),'manifest':inventory(owned_paths),'session_hash':c['hash']}
    except (OSError,ValueError,KeyError,json.JSONDecodeError)as exc:return {'status':'FAIL','reason':'LEDGER_INTENT_RECEIPT_RECONCILIATION_FAILED','error':str(exc)}
def classify(*,freeze_ok=True,environment_ok=True,executed=False,claim_exercised=True,integrity_ok=True):
    if not freeze_ok:return'BLOCKED_PREEXECUTION'
    if not environment_ok:return'INCONCLUSIVE_ENVIRONMENT'
    if not integrity_ok:return'FAIL'
    return'PASS'if executed and claim_exercised else'NOT_EXERCISED'
def cleanup_pids(rows):
    """Only verified, recorded campaign process-group leaders may be terminated."""
    from gaia.autonomy.supervisor import alive
    stopped=[]
    if any(not r.get('owner_verified') or not r.get('start_time') or r.get('pid')!=r.get('process_group') for r in rows):
        return {'status':'FAIL','reason':'UNVERIFIED_PROCESS_OWNER','stopped':stopped}
    evidence=[dict(r) for r in rows]
    for r in rows:
        if alive(r['pid'],r.get('start_time')):
            try:os.killpg(r['process_group'],signal.SIGTERM);stopped.append(r['pid'])
            except ProcessLookupError:pass
    deadline=time.monotonic()+2
    while time.monotonic()<deadline and any(alive(r['pid'],r.get('start_time'))for r in rows):time.sleep(.02)
    for r in rows:
        if alive(r['pid'],r.get('start_time')):
            try:os.killpg(r['process_group'],signal.SIGKILL)
            except ProcessLookupError:pass
    return {'status':'PASS'if all(not alive(r['pid'],r.get('start_time'))for r in rows)else'FAIL','stopped':stopped,'evidence':evidence}
def contract(root,out,lineages,state):
    root,state,out=Path(root),Path(state),Path(out)
    out=safe_out(root,out)
    if out.exists():raise FileExistsError('STAGE2_CONTRACT_EXISTS')
    head=safe_git(root,'rev-parse','HEAD');status=safe_git(root,'status','--porcelain')
    if not head or status is None:raise ValueError('GIT_VERIFICATION_UNAVAILABLE')
    if status:raise ValueError('CLEAN_WORKTREE_REQUIRED')
    resources={'memory':memory(),'filesystem':filesystem(root)}
    if resources['memory'].get('available_bytes')is None or resources['filesystem'].get('free_bytes') is None or resources['memory'].get('below_reserve')or resources['filesystem'].get('below_reserve')or boot_id()=='UNAVAILABLE':raise ValueError('RESOURCE_RESERVE_UNAVAILABLE')
    from gaia.autonomy.telemetry import vram
    baseline={'resources':resources,'vram':vram(),'supervisor':{'pid':os.getpid(),'fds':len(os.listdir('/proc/self/fd'))},'boot_id':boot_id()}
    plan={'sessions':2,'max_campaigns_per_session':2,'maximum_campaigns_total':4,'campaign_roles':['S1-C1','S1-C2','S2-C3','S2-C4']}
    value={'schema':'gaia_stage2_contract_v1','stage':'stage2','status':'READY_TO_EXECUTE','commit':head,
      'identity':identities(root),'freeze':frozen(root,state,lineages),'limits':LIMITS,'lineages':list(lineages),
      'preregistration_sha256':sha(PREREG),'baseline':baseline,'plan':plan,'executor_sha256':sha(__file__),'runtime':{'python':sys.version,'executable':sys.executable},
      'boot_id':boot_id(),'resources':resources,'inventory':inventory([root/'gaia',root/'gaia.py']),
      'campaigns_authorized':0,'sessions_started':0,'execution_prohibited':True,'clock':stamp()}
    value['hash']=digest(value);out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(value,indent=2));return validate_contract(value)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--contract-out',required=True);p.add_argument('--lineage',action='append',required=True);p.add_argument('--state',required=True)
    a=p.parse_args();print(json.dumps(contract(ROOT,a.contract_out,a.lineage,a.state),indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
