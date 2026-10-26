#!/usr/bin/env python3
"""Administrative Stage 2 preparation and explicitly authorized first-session runner."""
import argparse,hashlib,json,os,signal,subprocess,sys,time
import math
from contextlib import contextmanager
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
ADMIN_FILES=('tools/stage2_executor.py','tools/stage2_runtime.py','tools/stage2_children.py','tools/audit_endurance_session.py',
             'tools/audit_closed_loop.py','tools/stage1_coverage.py','docs/endurance_evidence/STAGE1_FINAL_REPORT.md')
CONTRACT_KEYS={'schema','stage','status','commit','identity','freeze','limits','lineages','preregistration_sha256','baseline','plan',
  'executor_sha256','runtime','boot_id','resources','inventory','campaigns_authorized','sessions_started',
  'execution_prohibited','clock','hash','state_path'}

def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def sha(path):
    with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
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
def inventory(paths,*,include_cache=False):
    result={}
    for base in map(Path,paths):
        if any(p.is_symlink()for p in [base,*base.parents]):raise ValueError('SYMLINK_IN_RECONCILIATION_SCOPE')
        if not base.exists():continue
        if base.is_file():
            if base.is_symlink():raise ValueError('SYMLINK_IN_RECONCILIATION_SCOPE')
            result[str(base)]=sha(base);continue
        for p in sorted(base.rglob('*')):
            if p.is_symlink():raise ValueError('SYMLINK_IN_RECONCILIATION_SCOPE')
            if not include_cache and ('__pycache__' in p.parts or p.suffix=='.pyc'):continue
            if p.is_file():result[str(p)]=sha(p)
    return result
def frozen(root,state,lineages):return freeze(Path(root),Path(state),list(lineages))

def qualify_backend(root,frozen_protocol):
    """Read-only qualification/artifact checks; never load or infer with a model."""
    from gaia.local_intelligence.controller import selected_backend
    selections=frozen_protocol['selections']
    if not selections:raise ValueError('FROZEN_BACKEND_REQUIRED')
    for name,binding in selections.items():
        if not binding['selection']:raise ValueError('QUALIFIED_BACKEND_REQUIRED')
        state=Path(root)/name;adapter,selected=selected_backend(state,'current');stack=adapter.stack
        if {'id':selected['id'],'hash':selected['hash']}!=binding['selection']:raise ValueError('BACKEND_SELECTION_CHANGED')
        runtime=state/'runtimes'/stack['runtime_install']/('mistralrs'if stack['runtime']=='mistralrs'else'koboldcpp')
        expected={runtime:stack['runtime_hash'],state/'artifacts'/stack['model_hash']:stack['model_hash']}
        if stack.get('support_id'):
            if any(p not in ('tokenizer.json','tokenizer_config.json','config.json','special_tokens_map.json')for p in stack['support_hashes']):
                raise ValueError('BACKEND_SUPPORT_PATH_INVALID')
            expected.update({state/'support'/stack['support_id']/p:h for p,h in stack['support_hashes'].items()})
        for path,want in expected.items():
            if any(p.is_symlink()for p in [path,*path.parents])or sha(path)!=want:raise ValueError('BACKEND_ARTIFACT_CHANGED')
def validate_contract(c):
    if not isinstance(c,dict) or set(c)!=CONTRACT_KEYS or c.get('schema')!='gaia_stage2_contract_v2':raise ValueError('INVALID_STAGE2_CONTRACT')
    if c['hash']!=digest({k:v for k,v in c.items()if k!='hash'}):raise ValueError('STAGE2_CONTRACT_HASH_MISMATCH')
    if c['stage']!='stage2' or c['limits']!=LIMITS or c['campaigns_authorized']!=0 or c['sessions_started']!=0 or not c['execution_prohibited']:
        raise ValueError('STAGE2_CONTRACT_SCOPE_INVALID')
    return c

def admission(c,root=ROOT,state=None):
    """Pure fail-closed preflight; it cannot admit a campaign."""
    c=validate_contract(c);root=Path(root);state=Path(state or root/'state');reasons=[]
    if c['status']!='READY_TO_EXECUTE':reasons.append('TOOLING_NOT_READY')
    if c['state_path']!=str(state.resolve()):reasons.append('STATE_PATH_CHANGED')
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
    if c['plan'].get('administrative_hashes')!={p:sha(ROOT/p)for p in ADMIN_FILES}:reasons.append('ADMINISTRATIVE_DEPENDENCY_CHANGED')
    try:qualify_backend(root,current)
    except (OSError,ValueError,KeyError):reasons.append('BACKEND_QUALIFICATION_FAILED')
    status=safe_git(root,'status','--porcelain')
    if status is None or status:reasons.append('CLEAN_WORKTREE_REQUIRED')
    host,disk=memory(),filesystem(root)
    if host.get('available_bytes')is None or host.get('below_reserve'):reasons.append('HOST_MEMORY_RESERVE')
    if disk.get('free_bytes') is None or disk.get('below_reserve'):reasons.append('FILESYSTEM_RESERVE')
    return {'status':'PASS'if not reasons else'BLOCKED_PREEXECUTION','reasons':reasons,'freeze':current,'resources':{'memory':host,'filesystem':disk}}

def fresh_lineage(root,state,lineages):
    """A preparation contract cannot reuse Stage 0/1 state or a used lineage."""
    from gaia.autonomy.lineage import LineageStore,engine_state_dir
    if len(lineages)!=1:raise ValueError('ONE_FRESH_NUMPY_LINEAGE_REQUIRED')
    lin=LineageStore(state,lineages[0]);value=lin.read();events=lin.events()
    if value['surface']!='numpy_mlp'or len(events)!=1 or events[0]['kind']!='CREATED':
        raise ValueError('FRESH_NUMPY_LINEAGE_REQUIRED')
    if (Path(root)/engine_state_dir(lineages[0])).exists():raise ValueError('EXISTING_ENGINE_STATE')
    expected={str(lin.root/'contract.json'),str(lin.root/'events'/'000001.json')}
    if set(inventory([state],include_cache=True))!=expected:raise ValueError('FRESH_STAGE2_STATE_REQUIRED')
    return value

def read_only_inspection(paths):
    before=inventory(paths);after=inventory(paths)
    return {'status':'PASS'if before==after else'FAIL','manifest':before,'written':before!=after}

def terminal_noop(state,campaign_id,paths,*,root=ROOT,replay=None):
    """Guard terminal state, then exercise the real CLI and compare owned evidence.

    ``replay`` is a disposable-fixture seam, not a substitute for CLI evidence.
    A matching manifest alone is insufficient: the CLI must return the existing report.
    """
    from gaia.autonomy.lineage import engine_state_dir
    from gaia.autonomy.supervisor import controllers
    store=CampaignStore(state,campaign_id);view=store.inspect()['state'];phase=view['phase']
    if phase not in TERMINAL:return {'status':'FAIL','reason':'NONTERMINAL_REOPEN_REFUSED','writes':False}
    if controllers(campaign_id):return {'status':'FAIL','reason':'LIVE_TERMINAL_CONTROLLER','writes':False}
    c=store.read('contract');scope=[*paths,Path(state)]
    if c.get('lineage_id'):scope.append(Path(root)/engine_state_dir(c['lineage_id']))
    before=inventory(scope,include_cache=True)
    if not view.get('report_ref'):return {'status':'FAIL','reason':'MISSING_TERMINAL_REPORT','writes':False}
    expected=store.get(view['report_ref'])
    try:
        if replay is None:
            result=subprocess.run([sys.executable,'-B',str(Path(root)/'gaia.py'),'autonomy-run',campaign_id,
                '--state-dir',str(Path(state).resolve()),'--authorize-campaign'],cwd=root,
                capture_output=True,text=True,timeout=60,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            if result.returncode:raise ValueError('TERMINAL_CLI_FAILED:'+str(result.returncode))
            output=json.loads(result.stdout)
        else:output=replay(campaign_id)
        error=None
    except (OSError,ValueError,subprocess.TimeoutExpired)as exc:output=None;error=str(exc)
    after=inventory(scope,include_cache=True)
    changed=sorted(p for p in set(before)|set(after)if before.get(p)!=after.get(p))
    passed=not changed and output==expected and error is None and not controllers(campaign_id)
    return {'status':'PASS'if passed else'FAIL','result':'TERMINAL_NOOP'if passed else'TERMINAL_REPLAY_FAILED',
            'changed_paths':changed,'writes':bool(changed),'error':error,'report_matches':output==expected,
            'execution_path':'REAL_CLI'if replay is None else'UNIT_FIXTURE',
            'child_creation_claim':'NOT_EXERCISED'}

def aggregate_preserved(store,root,previous=None):
    c=store.read();v=store.state_view();remaining,reasons=budget(c,v,store.storage(root,c),stamp())
    snapshot={'compute_s':v['compute_s'],'campaigns':v['campaigns'],'restarts':v['restarts'],'recoveries':v['recoveries'],'research':v['research']}
    preserved=previous is None or all(snapshot[k]>=previous[k] if isinstance(snapshot[k],(int,float)) else snapshot[k][:len(previous[k])]==previous[k] for k in snapshot)
    return {'status':'PASS'if v['compute_s']>=0 and preserved else'FAIL','compute_s':v['compute_s'],'campaigns':len(v['campaigns']),
            'remaining_s':remaining,'reasons':reasons,'snapshot':snapshot,'aggregate_snapshot':digest(snapshot)}
def learning(reference,binding):
    value=applicability(reference,binding);return {'status':'PASS'if value['status']in('EXACT','INCOMPATIBLE')else'FAIL','applicability':value}

class StageBudget:
    """Append-only cross-session reservations; ambiguous work never refunds compute.

    Hold exclusive() for the entire administrative operation/session. Storage is
    absolute owned bytes, not growth relative to a resettable session baseline.
    Ownership roots must include stage evidence, persistent state and engine state.
    """
    def __init__(self,path,contract_hash,owned_paths):
        self.path=Path(path);self.contract_hash=contract_hash
        self.owned_paths=[Path(p).absolute()for p in owned_paths];self.locked=False
        self.check_paths()
        if not self.owned_paths or not any(self.path.resolve().is_relative_to(p)for p in self.owned_paths):
            raise ValueError('STAGE_LEDGER_NOT_OWNED')

    def check_paths(self):
        for base in [self.path,*self.owned_paths]:
            for p in [base,*base.parents]:
                if p.is_symlink():raise ValueError('STAGE_LEDGER_SYMLINK')

    @contextmanager
    def exclusive(self):
        import fcntl
        self.check_paths();self.path.mkdir(parents=True,exist_ok=True)
        lock=self.path/'.lock'
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'a+b')as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);self.locked=True
            try:yield self
            finally:self.locked=False;fcntl.flock(stream,fcntl.LOCK_UN)

    def events(self):
        self.check_paths();rows=[];previous=None
        for index,p in enumerate(sorted(self.path.glob('*.json')),1):
            if p.is_symlink():raise ValueError('STAGE_LEDGER_SYMLINK')
            row=json.loads(p.read_bytes())
            if (p.name!=f'{index:06d}.json' or row.get('sequence')!=index
                or row.get('previous_hash')!=previous or row.get('contract_hash')!=self.contract_hash
                or row.get('hash')!=digest({k:v for k,v in row.items()if k!='hash'})):
                raise ValueError('STAGE_LEDGER_CORRUPT')
            rows.append(row);previous=row['hash']
        return rows

    def view(self):
        reservations={};sessions=[];bindings={};charges={}
        for e in self.events():
            p=e['payload']
            if e['kind']=='SESSION':
                if p['session_id']in sessions or len(sessions)>=2:raise ValueError('STAGE_SESSION_MISMATCH')
                sessions.append(p['session_id'])
            elif e['kind']=='RESERVE':
                if p['role']in reservations or p['session_id']not in sessions:raise ValueError('STAGE_RESERVATION_MISMATCH')
                if p['role']not in ('S1-C1','S1-C2','S2-C3','S2-C4'):raise ValueError('STAGE_ROLE_INVALID')
                if type(p['seconds'])is not int or not 0<p['seconds']<=1800:raise ValueError('STAGE_RESERVATION_INVALID')
                reservations[p['role']]=p
            elif e['kind']=='BIND':
                if p['role']not in reservations or p['role']in bindings or p['campaign_id']in bindings.values():raise ValueError('STAGE_BIND_MISMATCH')
                bindings[p['role']]=p['campaign_id']
            elif e['kind']=='FINISH':
                if bindings.get(p['role'])!=p['campaign_id']or p['role']in charges:raise ValueError('STAGE_FINISH_MISMATCH')
                if type(p['wall_s'])not in (int,float)or not math.isfinite(p['wall_s'])or p['wall_s']<0:raise ValueError('STAGE_CHARGE_INVALID')
                charges[p['role']]=p['wall_s']
            else:raise ValueError('STAGE_EVENT_INVALID')
        charged=sum(p['seconds']for p in reservations.values())
        if charged>7200:raise ValueError('STAGE_COMPUTE_EXCEEDED')
        return {'sessions':sessions,'reservations':reservations,'bindings':bindings,'charges':charges,
                'reserved_compute_s':charged,'remaining_compute_s':7200-charged,
                'actual_compute_s':sum(charges.values()),'overrun':any(v>reservations[k]['seconds']for k,v in charges.items())}

    def ownership(self):
        self.check_paths()
        # Collapse overlapping roots so shared lineage/catalogue bytes count once.
        roots=[p for p in set(self.owned_paths)if not any(p!=q and p.is_relative_to(q)for q in self.owned_paths)]
        owners={}
        for root in roots:
            total=0;count=0
            for p in ([root]if root.is_file()else root.rglob('*')):
                if p.is_symlink():raise ValueError('STAGE_STORAGE_SYMLINK')
                if p.is_file():total+=p.stat().st_size;count+=1
            owners[str(root)]={'bytes':total,'files':count}
        return owners

    def storage(self):return sum(v['bytes']for v in self.ownership().values())

    def append(self,kind,payload):
        if not self.locked:raise ValueError('STAGE_LOCK_REQUIRED')
        from gaia.autonomy.store import durable
        rows=self.events();row={'sequence':len(rows)+1,'previous_hash':rows[-1]['hash']if rows else None,
            'contract_hash':self.contract_hash,'kind':kind,'payload':payload,'clock':stamp()}
        row['hash']=digest(row)
        if self.storage()+len(json.dumps(row).encode())+4096>=4*2**30:raise ValueError('STAGE_STORAGE_BUDGET')
        durable(self.path/f'{len(rows)+1:06d}.json',row,True)
        return row

    def start_session(self,session_id):
        v=self.view()
        if session_id in v['sessions']or len(v['sessions'])>=2:raise ValueError('STAGE_SESSION_BUDGET')
        if v['overrun']or (v['sessions']and (len(v['reservations'])!=2 or len(v['charges'])!=2)):
            raise ValueError('STAGE_BOUNDARY_NOT_RECONCILED')
        self.append('SESSION',{'session_id':session_id})

    def reserve(self,session_id,role,seconds=1800):
        v=self.view()
        if v['overrun']:raise ValueError('STAGE_COMPUTE_OVERRUN')
        if session_id not in v['sessions']:raise ValueError('UNKNOWN_STAGE_SESSION')
        ordinal=v['sessions'].index(session_id)+1
        expected=f'S{ordinal}-C{len(v["reservations"])+1}'
        if role!=expected or role in v['reservations']or role not in ('S1-C1','S1-C2','S2-C3','S2-C4'):
            raise ValueError('STAGE_ROLE_ORDER')
        if type(seconds)is not int or not 900<=seconds<=1800 or seconds>v['remaining_compute_s']:
            raise ValueError('STAGE_COMPUTE_BUDGET')
        self.append('RESERVE',{'session_id':session_id,'role':role,'seconds':seconds})
        return self.view()

    def bind(self,role,campaign_id):
        v=self.view()
        if role not in v['reservations']or role in v['bindings']or campaign_id in v['bindings'].values():raise ValueError('STAGE_BIND_MISMATCH')
        self.append('BIND',{'role':role,'campaign_id':campaign_id})

    def finish(self,role,campaign_id,wall_s):
        v=self.view()
        if v['bindings'].get(role)!=campaign_id or role in v['charges']:raise ValueError('STAGE_FINISH_MISMATCH')
        if type(wall_s)not in (int,float)or not math.isfinite(wall_s)or wall_s<0:raise ValueError('STAGE_CHARGE_INVALID')
        self.append('FINISH',{'role':role,'campaign_id':campaign_id,'wall_s':wall_s})
def reconcile(store,owned_paths,require_terminal=True,*,root=ROOT):
    """Read-only ledger/intents/receipts reconciliation; no repair path exists."""
    try:
        c=store.read();events=store.events();v=store.state_view();fail=[]
        if not events or v['started_clock']is None:fail.append('MISSING_SESSION_JOURNAL')
        if require_terminal and (v['running'] or not v['stopped'] or len(v['finished'])!=len(v['campaigns'])):fail.append('SESSION_NOT_TERMINAL')
        started=[e['payload']['campaign_id']for e in events if e['kind']=='CAMPAIGN_STARTED']
        finished=[e['payload'].get('campaign_id') for e in events if e['kind']=='CAMPAIGN_FINISHED']
        if len(started)!=len(set(started)):fail.append('DUPLICATE_CAMPAIGN_START')
        if len(finished)!=len(set(finished)):fail.append('DUPLICATE_CAMPAIGN_FINISH')
        if any(x not in started for x in finished) or (require_terminal and set(started)!=set(finished)):fail.append('CAMPAIGN_FINISH_MISMATCH')
        running=None;stopped=False
        for e in events:
            if stopped:fail.append('EVENT_AFTER_SESSION_STOP')
            if e['kind']=='CAMPAIGN_STARTED':
                if running is not None:fail.append('OVERLAPPING_CAMPAIGNS')
                running=e['payload']['campaign_id']
            elif e['kind']=='CAMPAIGN_FINISHED':
                if running!=e['payload'].get('campaign_id'):fail.append('OUT_OF_ORDER_FINISH')
                running=None
                wall=e['payload'].get('wall_s')
                if type(wall)not in (int,float)or not math.isfinite(wall)or wall<0:fail.append('INVALID_COMPUTE_CHARGE')
            elif e['kind']=='STOPPED':stopped=True
        for cid in v['campaigns']:
            campaign_store=CampaignStore(store.state,cid);state=campaign_store.inspect()['state']
            if require_terminal and state['phase']not in TERMINAL:fail.append('CAMPAIGN_NOT_TERMINAL:'+cid)
            if any(state.get(k)for k in ('execution_intent','initialization_intent','research_intent','rollback_intent')):fail.append('UNRECONCILED_INTENT:'+cid)
            if require_terminal:
                from audit_closed_loop import audit_campaign
                audit=audit_campaign(root,store.state,cid)
                if audit['status']!='PASS':fail.append('CAMPAIGN_AUDIT:'+cid)
                if not state.get('report_ref'):fail.append('MISSING_CAMPAIGN_REPORT:'+cid)
                else:
                    report=campaign_store.get(state['report_ref']);metrics=report['metrics']
                    charges=[e['payload']for e in events if e['kind']=='CAMPAIGN_FINISHED'and e['payload'].get('campaign_id')==cid]
                    if len(charges)==1:
                        charge=charges[0];expected=max(charge.get('supervised_s',0),metrics.get('total_wall_time')or 0)
                        if charge.get('wall_s')!=expected:fail.append('COMPUTE_REPORT_MISMATCH:'+cid)
                    if metrics.get('network_requests')or metrics.get('research_calls'):fail.append('UNAUTHORIZED_RESEARCH:'+cid)
        required=[store.root/'telemetry',store.root/'evidence']
        if require_terminal and any(not p.exists() for p in required):fail.append('MISSING_TELEMETRY_OR_EVIDENCE')
        return {'status':'PASS'if not fail else'FAIL','failures':fail,'events':len(events),'campaigns':len(v['campaigns']),
                'finished':len(v['finished']),'manifest':inventory(owned_paths),'session_hash':c['hash']}
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError)as exc:return {'status':'FAIL','reason':'LEDGER_INTENT_RECEIPT_RECONCILIATION_FAILED','error':str(exc)}
def classify(*,freeze_ok=True,environment_ok=True,executed=False,claim_exercised=True,integrity_ok=True):
    if not freeze_ok:return'BLOCKED_PREEXECUTION'
    if not environment_ok:return'INCONCLUSIVE_ENVIRONMENT'
    if not integrity_ok:return'FAIL'
    return'PASS'if executed and claim_exercised else'NOT_EXERCISED'
def cleanup_pids(rows,*,launched=None):
    """Stop only live direct children held by this executor as Popen handles.

    Serialized assertions (including owner_verified) confer no signal authority.
    Revalidate /proc identity, parent, session and group before *each* signal.
    Callers must preserve their process snapshot before invoking cleanup.
    """
    from gaia.autonomy.supervisor import alive,proc_info
    stopped=[]
    launched=launched or {}
    def owned(r):
        proc=launched.get(r.get('pid'));info=proc_info(r.get('pid'))
        return (isinstance(proc,subprocess.Popen) and proc.pid==r.get('pid') and proc.poll()is None and info is not None
            and info[0]==os.getpid() and info[1]==info[2]==proc.pid
            and info[7]==r.get('start_time') and r.get('process_group')==proc.pid)
    if any(not owned(r) for r in rows):
        return {'status':'FAIL','reason':'UNVERIFIED_PROCESS_OWNER','stopped':stopped}
    evidence=[dict(r) for r in rows]
    for r in rows:
        if owned(r):
            try:os.killpg(r['process_group'],signal.SIGTERM);stopped.append(r['pid'])
            except ProcessLookupError:pass
    deadline=time.monotonic()+2
    while time.monotonic()<deadline and any(alive(r['pid'],r.get('start_time'))for r in rows):time.sleep(.02)
    for r in rows:
        if owned(r):
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
    if '**STAGE_1_ENDURANCE = PASS**'not in (ROOT/'docs/endurance_evidence/STAGE1_FINAL_REPORT.md').read_text():raise ValueError('STAGE1_NOT_PASS')
    fresh_lineage(root,state,lineages)
    resources={'memory':memory(),'filesystem':filesystem(root)}
    if resources['memory'].get('available_bytes')is None or resources['filesystem'].get('free_bytes') is None or resources['memory'].get('below_reserve')or resources['filesystem'].get('below_reserve')or boot_id()=='UNAVAILABLE':raise ValueError('RESOURCE_RESERVE_UNAVAILABLE')
    from gaia.autonomy.telemetry import vram
    baseline={'resources':resources,'vram':vram(),'supervisor':{'pid':os.getpid(),'fds':len(os.listdir('/proc/self/fd'))},'boot_id':boot_id()}
    from gaia import provenance
    if not provenance.bwrap_capability().get('verified'):raise ValueError('SANDBOX_UNAVAILABLE')
    from tools.stage2_children import subreaper
    subreaper()  # Capability check only; adoption is enabled in the dedicated runtime.
    fd=os.pidfd_open(os.getpid(),0)
    try:signal.pidfd_send_signal(fd,0)
    finally:os.close(fd)
    protocol=frozen(root,state,lineages);qualify_backend(root,protocol)
    plan={'sessions':2,'max_campaigns_per_session':2,'maximum_campaigns_total':4,'campaign_roles':['S1-C1','S1-C2','S2-C3','S2-C4'],
          'administrative_hashes':{p:sha(ROOT/p)for p in ADMIN_FILES},'slot_s':3600,'campaign_execution_s':1740,
          'process_ownership':'DEDICATED_LINUX_SUBREAPER_PIDFD','storage_enforcement':'POLLING_NOT_PHYSICAL_QUOTA',
          'final_pass_blockers':['ZERO_EPHEMERAL_CHILDREN_NOT_PROVEN','SESSION_2_NOT_EXERCISED','FULL_DRIFT_ATTRIBUTION_NOT_EXERCISED',
                                 'CATALOGUE_REFERENCE_DECISION_COVERAGE_NOT_PROVEN','LOCK_HOLDER_ATTRIBUTION_NOT_EXERCISED']}
    value={'schema':'gaia_stage2_contract_v2','stage':'stage2','status':'READY_TO_EXECUTE','commit':head,'state_path':str(state.resolve()),
      'identity':identities(root),'freeze':protocol,'limits':LIMITS,'lineages':list(lineages),
      'preregistration_sha256':sha(PREREG),'baseline':baseline,'plan':plan,'executor_sha256':sha(__file__),'runtime':{'python':sys.version,'executable':sys.executable},
      'boot_id':boot_id(),'resources':resources,'inventory':inventory([root/'gaia',root/'gaia.py']),
      'campaigns_authorized':0,'sessions_started':0,'execution_prohibited':True,'clock':stamp()}
    from gaia.autonomy.store import durable
    value['hash']=digest(value);out.parent.mkdir(parents=True,exist_ok=True);durable(out,value,True);return validate_contract(value)

def prepare(root,out):
    """Create only fresh administrative state/lineage and freeze; never run a campaign."""
    from gaia.autonomy.lineage import create_lineage
    root,out=Path(root).resolve(),Path(out).resolve();safe_out(root,out/'contract.json')
    if out.exists():raise FileExistsError('STAGE_ATTEMPT_EXISTS')
    if safe_git(root,'status','--porcelain')!='':raise ValueError('CLEAN_WORKTREE_REQUIRED')
    state=out/'state'
    lin=create_lineage(root,state,'IMPROVE_NUMPY_MLP_EXISTING_CRITERIA')
    return contract(root,out/'contract.json',[lin['lineage_id']],state)

def run_first_session(root,contract_path,*,authorize=False):
    if not authorize:raise ValueError('EXPLICIT_STAGE2_S1_AUTHORIZATION_REQUIRED')
    # The subreaper must never share this caller's managed subprocesses.
    result=subprocess.run([sys.executable,'-B','-m','tools.stage2_runtime','--contract',str(Path(contract_path).resolve()),
        '--authorize-stage2-s1'],cwd=Path(root),capture_output=True,text=True,
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    if result.returncode:raise RuntimeError('DEDICATED_STAGE2_RUNTIME_FAILED:'+result.stderr[-2000:])
    return json.loads(result.stdout)

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--out',required=True)
    run=sub.add_parser('run-first-session');run.add_argument('--contract',required=True)
    run.add_argument('--authorize-stage2-s1',action='store_true')
    a=p.parse_args()
    result=prepare(ROOT,a.out)if a.command=='prepare'else run_first_session(ROOT,a.contract,authorize=a.authorize_stage2_s1)
    print(json.dumps(result,indent=2));return 0 if result.get('status')in ('READY_TO_EXECUTE','S1_OBSERVED')else 2
if __name__=='__main__':raise SystemExit(main())
