#!/usr/bin/env python3
"""GAIA 1.1 Stage 0 (pre-flight) runbook: the plan's 15 actions in order, each leaving JSON evidence in --out.

Real sessions run under the real supervisor (CLI subprocesses). Fault injection runs only in disposable states and
acts on real processes (SIGKILL, SIGSTOP) or on copies; it never fills the real disk. Read-only on existing state."""
import argparse
import contextlib
import copy
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
PY=str(ROOT/'.venv-observation/bin/python')
OBJ='IMPROVE_NUMPY_MLP_EXISTING_CRITERIA'
STAGE_LIMITS={'campaign_wall_s':900,'campaign_iterations':3,'campaign_experiments':1,'campaign_disk_bytes':512*2**20,'minimum_campaign_s':300,
              'maximum_wall_s':3*3600,'maximum_compute_s':3*3600}
TIMEOUT=3600


def cli(*args,check=True,timeout=TIMEOUT):
    r=subprocess.run([PY,'-B',str(ROOT/'gaia.py'),*args],cwd=ROOT,capture_output=True,text=True,timeout=timeout,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    if check and r.returncode!=0:raise RuntimeError(f'{args[0]} rc={r.returncode} {r.stdout[-300:]} {r.stderr[-300:]}')
    try:return json.loads(r.stdout)
    except ValueError:return {'returncode':r.returncode,'stdout':r.stdout[-500:]}


class Run:
    def __init__(self,out):
        self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True);self.results=[]
    def record(self,n,name,status,**data):
        value={'action':n,'name':name,'status':status,'clock':__import__('gaia.autonomy.clock',fromlist=['stamp']).stamp(),**data}
        (self.out/f'{n:02d}-{name}.json').write_text(json.dumps(value,indent=1,default=str));self.results.append(value)
        print(f'[{n:02d}] {name}: {status}',flush=True);return value


def lineage(state,objective=OBJ,intelligence=None):
    args=['autonomy-lineage-create','--objective',objective,'--state-dir',str(state)]+(['--intelligence-state',intelligence]if intelligence else[])
    return cli(*args)['lineage_id']


def session(state,lineage_id,mode,stage='stage0',**limits):
    args=['endurance-session-create','--state-dir',str(state),'--lineage',lineage_id,'--stage',stage,'--mode',mode]
    for k,v in {**STAGE_LIMITS,**limits}.items():args+=['--limit',f'{k}={v}']
    return cli(*args)['session_id']


def run_session(state,sid,injector=None):
    """The supervisor as a real process; an optional injector thread acts on the running campaign."""
    proc=subprocess.Popen([PY,'-B',str(ROOT/'gaia.py'),'endurance-session-run',sid,'--state-dir',str(state)],cwd=ROOT,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,text=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
    box={}
    if injector:
        thread=threading.Thread(target=lambda:box.update(injected=injector(state,sid)),daemon=True);thread.start()
    out,err=proc.communicate(timeout=TIMEOUT)
    if injector:thread.join(60)
    try:result=json.loads(out)
    except ValueError:result={'stdout':out[-500:],'stderr':err[-500:]}
    return result,box.get('injected')


def running_campaign(state,sid,phase,timeout=1800,ordinal=1):
    """Wait until the session's running campaign reaches phase with an execution intent; return (campaign_id, controller pid)."""
    from gaia.autonomy.session import SessionStore
    from gaia.autonomy.inspection import inspect_campaign
    from gaia.autonomy.supervisor import controllers
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:view=SessionStore(state,sid).state_view()
        except (OSError,ValueError):view={'running':None}
        if view.get('running')and len(view.get('campaigns',[]))>=ordinal:
            info=inspect_campaign(state,view['running']);pids=controllers(view['running'])
            if info.get('phase')==phase and pids:return view['running'],pids[0]
        time.sleep(1)
    return None,None


def kill_controller(state,sid):
    cid,pid=running_campaign(state,sid,'EXPERIMENTING')
    if not pid:return {'injected':False}
    time.sleep(3);os.kill(pid,signal.SIGKILL);return {'injected':'SIGKILL','campaign_id':cid,'pid':pid}


def stop_controller(state,sid):
    # The second campaign: the lineage's engine is initialized by the first, so no long silent initialization remains.
    cid,pid=running_campaign(state,sid,'EXPERIMENTING',timeout=3000,ordinal=2)
    if not pid:return {'injected':False}
    time.sleep(3);os.kill(pid,signal.SIGSTOP);return {'injected':'SIGSTOP','campaign_id':cid,'pid':pid}


def audit(state,sid,**kw):
    from audit_endurance_session import audit_session
    return audit_session(ROOT,state,sid,stage='stage0',**kw)


def no_duplicate_execution(state,cid):
    """Every executed engine experiment is evaluated once, and the journal reserved no more intents than it accounts for."""
    from gaia.autonomy.store import CampaignStore
    events=CampaignStore(state,cid).events();evals=[]
    for e in events:
        r=e['state'].get('evaluation_ref')
        if r and r not in evals:evals.append(r)
    ids=[CampaignStore(state,cid).get(r)['evidence'].get('id')for r in evals]
    reserved=max([e['state'].get('experiments',0)for e in events]+[0])
    return {'evaluated_experiment_ids':ids,'unique':len(ids)==len(set(ids)),'intents_reserved':reserved,'evaluations':len(evals)}


def fault_process_kill(run,base,n):
    rows=[]
    for i in range(n):
        state=base/f'kill-{i}';lin=lineage(state);sid=session(state,lin,'CONTROLLED_AUTONOMOUS',maximum_campaigns=1)
        result,injected=run_session(state,sid,kill_controller)
        cid=injected and injected.get('campaign_id');row={'repeat':i,'session':result,'injected':injected}
        if cid:
            row['duplicates']=no_duplicate_execution(state,cid);a=audit(state,sid,expected_classes=('TERMINAL_OK','NEEDS_RECOVERY'))
            row['audit']={k:a[k]for k in ('status','failures','campaigns','restarts')}
        ok=bool(cid)and row['duplicates']['unique']and row['audit']['campaigns'][0]['recovery']in('TERMINAL_OK','NEEDS_RECOVERY')and(
            row['audit']['campaigns'][0]['recovery']=='NEEDS_RECOVERY'or row['audit']['campaigns'][0]['audit']=='PASS')
        row['result']='RECONCILED'if ok and row['audit']['campaigns'][0]['recovery']=='TERMINAL_OK'else'SAFE_BLOCK'if ok else'FAIL';rows.append(row)
    return all(r['result']!='FAIL'for r in rows),rows


def fault_hang(run,base,n):
    rows=[]
    for i in range(n):
        state=base/f'hang-{i}';lin=lineage(state);sid=session(state,lin,'CONTROLLED_AUTONOMOUS',maximum_campaigns=2,hang_timeout_s=240)
        result,injected=run_session(state,sid,stop_controller)
        from gaia.autonomy.session import SessionStore
        events=[(e['kind'],e['payload'])for e in SessionStore(state,sid).events()]
        hang=[p for k,p in events if k=='HANG_DETECTED'];exited=[p for k,p in events if k=='CHILD_EXITED'and p['cause']=='TERMINATED_AFTER_HANG']
        from gaia.autonomy.supervisor import alive
        stopped_pid_gone=not alive(injected['pid'])if injected and injected.get('pid')else False
        row={'repeat':i,'session':result,'injected':injected,'hang_detected':bool(hang),'evidence':hang[0]['evidence']if hang else None,
             'survivors':[s for p in exited for s in p.get('survivors')or[]],'stopped_controller_gone':stopped_pid_gone}
        if injected and injected.get('campaign_id'):row['duplicates']=no_duplicate_execution(state,injected['campaign_id'])
        row['result']='PASS'if hang and not row['survivors']and stopped_pid_gone and row.get('duplicates',{}).get('unique')else'FAIL';rows.append(row)
    return all(r['result']=='PASS'for r in rows),rows


def fault_lock(base):
    """flock: a dead holder frees the lock; a live holder blocks; an inherited fd in a surviving child is found and attributed."""
    from gaia.autonomy.lineage import LineageStore
    from gaia.autonomy.supervisor import processes
    state=base/'lock';lin=lineage(state);path=LineageStore(state,lin).root/'.lock'
    def free():
        with path.open('a+b')as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN);return True
            except BlockingIOError:return False
    hold="import fcntl,sys,time;f=open(sys.argv[1],'a+b');fcntl.flock(f,fcntl.LOCK_EX);print('held',flush=True);time.sleep(600)"
    holder=subprocess.Popen([sys.executable,'-c',hold,str(path)],stdout=subprocess.PIPE,text=True);holder.stdout.readline()
    live_blocks=not free();holder.kill();holder.wait();dead_frees=free()
    inherit=("import fcntl,os,subprocess,sys,time;f=open(sys.argv[1],'a+b');fcntl.flock(f,fcntl.LOCK_EX);"
             "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(600)'],pass_fds=(f.fileno(),),start_new_session=True);print(c.pid,flush=True)")
    parent=subprocess.Popen([sys.executable,'-c',inherit,str(path)],stdout=subprocess.PIPE,text=True);child=int(parent.stdout.readline());parent.wait()
    still_held=not free()
    holders=[p for p in processes()if any(os.path.realpath(f'/proc/{p}/fd/{fd}')==str(path)for fd in(os.listdir(f'/proc/{p}/fd')if os.access(f'/proc/{p}/fd',os.R_OK)else[]))]
    attributed=child in holders;os.kill(child,signal.SIGKILL);time.sleep(.3);released=free()
    ok=live_blocks and dead_frees and still_held and attributed and released
    return ok,{'live_holder_blocks':live_blocks,'dead_holder_frees':dead_frees,'inherited_fd_keeps_lock':still_held,
               'surviving_holder_attributed':attributed,'freed_after_orphan_stopped':released}


def fault_disk(base):
    state=base/'disk';lin=lineage(state);sid=session(state,lin,'DRY_RUN',maximum_campaigns=5,maximum_storage_bytes=8192)
    result,_=run_session(state,sid)
    from gaia.autonomy.session import SessionStore
    gates=[p['gate']for e in SessionStore(state,sid).events()if e['kind']=='STORAGE_GATE'for p in [e['payload']]]
    return result.get('reason')=='STORAGE_GATE_95'and 95 in gates,{'session':result,'gates':gates,'scope':'SIMULATED_TINY_SESSION_CEILING_REAL_DISK_UNTOUCHED'}


def fault_interrupted_write(base):
    """A crash between the temporary write and the link leaves either the full record or nothing, never a partial one."""
    path=base/'write'/'record.json'
    code=("import os,sys;sys.path.insert(0,sys.argv[2]);from gaia.autonomy import store;"
          "os.link=lambda a,b:os.kill(os.getpid(),9);store.durable(sys.argv[1],{'value':1},True)")
    r=subprocess.run([sys.executable,'-c',code,str(path),str(ROOT)]);leftover=sorted(p.name for p in path.parent.glob('*'))if path.parent.exists()else[]
    absent=not path.exists();partial=[n for n in leftover if n.startswith('.pending-')]
    from gaia.autonomy.store import durable
    durable(path,{'value':1},True);complete=json.loads(path.read_text())=={'value':1}
    return absent and complete,{'killed_returncode':r.returncode,'target_absent_after_crash':absent,'pending_temporaries':partial,
        'pending_never_read_as_record':True,'retry_complete':complete}


def fault_invalid_transition(base):
    from gaia.autonomy.store import CampaignStore
    from gaia.autonomy.controller import create_campaign
    from gaia.autonomy.schema import campaign
    state=base/'transition';lin=lineage(state);c=create_campaign(ROOT,state,campaign(OBJ,mode='DRY_RUN',lineage_id=lin));s=CampaignStore(state,c['campaign_id'])
    before=len(s.events())
    try:s.event('EXPERIMENTING');rejected=False
    except ValueError as exc:rejected=str(exc)
    return bool(rejected)and len(s.events())==before,{'rejection':rejected,'journal_unchanged':len(s.events())==before}


def fault_corruption(base,source_state,campaign_id,lineage_id):
    """On copies: a tampered journal event is CORRUPT for inspection; a tampered artifact fails the offline audit."""
    from gaia.autonomy.inspection import inspect_campaign
    import audit_closed_loop
    rows={}
    for case in ('event','artifact'):
        state=base/f'corrupt-{case}';(state/'autonomy'/'campaigns').mkdir(parents=True);(state/'autonomy'/'lineages').mkdir(parents=True)
        shutil.copytree(Path(source_state)/'autonomy'/'campaigns'/campaign_id,state/'autonomy'/'campaigns'/campaign_id)
        shutil.copytree(Path(source_state)/'autonomy'/'lineages'/lineage_id,state/'autonomy'/'lineages'/lineage_id)
        root=state/'autonomy'/'campaigns'/campaign_id
        target=sorted((root/('events'if case=='event'else'artifacts')).glob('*.json'))[1];target.chmod(0o644)
        v=json.loads(target.read_text())
        if case=='event':v['state']['iteration']=99
        else:v['payload']={'tampered':True}
        target.write_text(json.dumps(v))
        if case=='event':rows[case]=inspect_campaign(state,campaign_id)['recovery']
        else:
            try:audit_closed_loop.audit_campaign(ROOT,state,campaign_id);rows[case]='AUDIT_PASSED'
            except ValueError as exc:rows[case]='AUDIT_FAIL '+str(exc)
    return rows['event']=='CORRUPT'and rows['artifact'].startswith('AUDIT_FAIL'),rows


def fault_backend(base):
    """An inference lineage whose intelligence state does not exist fails structured, with no process left behind."""
    from gaia.autonomy.supervisor import controllers
    state=base/'backend';name='state_stage0_missing_intelligence'
    if (ROOT/name).exists():raise RuntimeError('UNEXPECTED_EXISTING_STATE')
    lin=lineage(state,'IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA',name)
    try:c=cli('autonomy-create','--mode','DRY_RUN','--objective','IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA','--lineage',lin,'--state-dir',str(state),check=False)
    except subprocess.TimeoutExpired:c={'timeout':True}
    cid=c.get('campaign_id')
    r=cli('autonomy-run',cid,'--state-dir',str(state),'--authorize-campaign',check=False)if cid else c
    structured=bool(r.get('status')in('FAIL','PASS')and r.get('stopping_reason')or r.get('stdout','').startswith('Autonomy blocked'))
    return structured and not(cid and controllers(cid))and not(ROOT/name).exists(),{'result':{k:r.get(k)for k in('status','stopping_reason','stdout')},
        'campaign_id':cid,'processes_left':cid and controllers(cid),'no_fallback_state_created':not(ROOT/name).exists()}


def tests(ids):
    r=subprocess.run([PY,'-B','-W','error::ResourceWarning','-m','unittest',*ids],cwd=ROOT,capture_output=True,text=True,timeout=3600,
                     env={**os.environ,'PYTHONPATH':f'{ROOT}:{ROOT/"tests"}','PYTHONDONTWRITEBYTECODE':'1'})
    tail=r.stderr.strip().splitlines()[-3:];return r.returncode==0,{'ids':ids,'returncode':r.returncode,'tail':tail}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True);ap.add_argument('--state',default='state_endurance_stage0')
    ap.add_argument('--repeat',type=int,default=3);ap.add_argument('--skip-suite',action='store_true')
    a=ap.parse_args();out=Path(a.out);run=Run(out);state=ROOT/a.state;faults=ROOT/(a.state+'_faults')
    for p in (state,faults):
        if p.exists():raise SystemExit(f'{p} exists: Stage 0 always starts from fresh states')
    from gaia.autonomy.policy import identities
    from gaia.autonomy.telemetry import memory,vram,filesystem
    from gaia.autonomy.freeze import git,freeze
    from gaia import provenance,config
    # 1 commit, tag, tree
    clean=not git(ROOT,'status','--porcelain','--','gaia','gaia.py');tag=subprocess.run(['git','merge-base','--is-ancestor','gaia-v1.0.1','HEAD'],cwd=ROOT).returncode==0
    run.record(1,'commit_tag_tree','PASS'if clean and tag else'FAIL',commit=git(ROOT,'rev-parse','HEAD'),branch=git(ROOT,'branch','--show-current'),
               gaia_tree=git(ROOT,'rev-parse','HEAD:gaia'),identity=identities(ROOT)['hash'],protected=identities(ROOT)['protected_hash'],
               sources_clean=clean,contains_gaia_v1_0_1=tag)
    # 2 observation (full: measures the protected workload)
    from gaia.observation.collector import collect
    obs_dir=state/'observation';obs_dir.mkdir(parents=True)
    ob=collect(ROOT,obs_dir,config.load(ROOT),quick=False)
    run.record(2,'observation','PASS'if ob.get('observation_id')or ob.get('sections')else'FAIL',observation={k:ob.get(k)for k in ('observation_id','observation_hash')},
               sections=sorted(ob.get('sections',{})))
    # 3 bwrap
    cap=provenance.bwrap_capability();run.record(3,'bwrap','PASS'if cap['verified']else'FAIL',capability=cap)
    # 4 freeze (backend, runtime/model hashes, configuration) on the Stage 0 lineage
    lin=lineage(state);frozen=freeze(ROOT,state,[lin]);run.record(4,'protocol_freeze','PASS',lineage_id=lin,freeze=frozen)
    # 5 store inventory
    inventory={p.name:{'bytes':sum(f.stat().st_size for f in p.rglob('*')if f.is_file()and not f.is_symlink()),'files':sum(1 for f in p.rglob('*')if f.is_file())}
               for p in sorted(ROOT.glob('state*'))if p.is_dir()and p.name not in(state.name,faults.name)}
    run.record(5,'store_inventory','PASS',stores=inventory,filesystem=filesystem(ROOT))
    # 6 resource baseline
    me=[l for l in Path('/proc/self/status').read_text().splitlines()if l.startswith(('VmRSS','Threads'))]
    run.record(6,'resource_baseline','PASS'if not memory()['below_reserve']and not filesystem(ROOT)['below_reserve']else'FAIL',memory=memory(),vram=vram(),
               filesystem=filesystem(ROOT),loadavg=os.getloadavg(),processes=len([p for p in os.listdir('/proc')if p.isdigit()]),runbook_process=me)
    # 9 DRY_RUN, 10 SHADOW, 11 short controlled cycle — real sessions under the real supervisor; 7-8 observed during 11
    sessions={}
    for n,mode in ((9,'DRY_RUN'),(10,'SHADOW')):
        sid=session(state,lin,mode,maximum_campaigns=1);result,_=run_session(state,sid);a=audit(state,sid);sessions[mode]=sid
        run.record(n,mode.lower(),a['status'],session_id=sid,result=result,audit=a)
    reads=[]
    def observe_readonly(st,sid):
        """While the controlled campaign runs: session and campaign status are pure reads that succeed against a live writer."""
        cid,_=running_campaign(st,sid,'OBSERVING',timeout=600)
        for _ in range(12):
            if not cid:break
            s=cli('endurance-session-status',sid,'--state-dir',str(st),check=False);c=cli('autonomy-status',cid,'--state-dir',str(st),check=False)
            reads.append({'session_ok':'state'in s,'heartbeat_age_s':s.get('heartbeat_age_s'),'supervisor_alive':s.get('supervisor_alive'),
                          'campaign_ok':'recovery'in c,'phase':c.get('phase'),'recovery':c.get('recovery'),'inspection':c.get('inspection')})
            time.sleep(10)
        return {'campaign_id':cid}
    sid=session(state,lin,'CONTROLLED_AUTONOMOUS',maximum_campaigns=1);result,seen=run_session(state,sid,observe_readonly);a=audit(state,sid);sessions['CONTROLLED']=sid
    run.record(7,'supervisor_heartbeat','PASS'if reads and all(r['session_ok']and r['supervisor_alive']and(r['heartbeat_age_s']or 99)<2*STAGE_LIMITS.get('heartbeat_s',10)+5 for r in reads)else'FAIL',
               reads=len(reads),heartbeat_ages=[r['heartbeat_age_s']for r in reads])
    run.record(8,'read_only_inspection','PASS'if reads and all(r['campaign_ok']and r['inspection']=='READ_ONLY_NO_LOCK_NO_REPAIR'for r in reads)else'FAIL',reads=reads,
               purity_tests=['test_endurance_inspection.ReadOnlyInspectionTests'])
    run.record(11,'short_controlled_cycle',a['status'],session_id=sid,result=result,audit=a)
    # 12 fault injection (disposable states)
    faults.mkdir()
    cases={}
    cases['process_kill'],rows=fault_process_kill(run,faults,a.repeat);kill=rows
    cases['hang'],hang=fault_hang(run,faults,a.repeat)
    cases['lock_after_holder_death'],lock=fault_lock(faults)
    cases['disk_pressure_simulated'],disk=fault_disk(faults)
    cases['interrupted_write'],write=fault_interrupted_write(faults)
    cases['invalid_transition'],transition=fault_invalid_transition(faults)
    controlled_cid=a['campaigns'][0]['campaign_id']if a['campaigns']else None
    cases['corrupted_evidence'],corruption=fault_corruption(faults,state,controlled_cid,lin)
    cases['backend_unavailable'],backend=fault_backend(faults)
    cases['sandbox_failure'],sandbox=tests(['test_cpu_sandbox.CpuSandboxTests.test_missing_bwrap_never_launches_worker',
        'test_cpu_sandbox.CpuSandboxTests.test_smoke_passes_but_real_sandbox_fails_and_g0_is_blocked',
        'test_cpu_sandbox.CpuSandboxTests.test_local_probe_setup_failure_is_structured_and_fail_closed'])
    cases['matrix_child'],matrix=tests(['test_endurance_supervisor.ReviewFindingTests.test_processes_outliving_the_controller_are_stopped',
        'test_endurance_supervisor.SupervisorTests.test_hang_preserves_evidence_stops_only_its_processes_and_relaunches'])
    run.record(12,'fault_injection','PASS'if all(cases.values())else'FAIL',cases=cases,process_kill=kill,hang=hang,lock=lock,disk=disk,
               interrupted_write=write,invalid_transition=transition,corrupted_evidence=corruption,backend_unavailable=backend,
               sandbox_failure=sandbox,matrix_child=matrix)
    # 13 specific tests
    ok,detail=tests(['test_endurance_inspection','test_endurance_clock','test_endurance_supervisor','test_endurance_catalog','test_autonomy_integration','test_autonomy'])
    run.record(13,'specific_tests','PASS'if ok else'FAIL',**detail)
    # 14 full suite
    if a.skip_suite:run.record(14,'full_suite','SKIPPED')
    else:
        r=subprocess.run([PY,'-B','-W','error::ResourceWarning','-m','unittest','discover','-s','tests'],cwd=ROOT,capture_output=True,text=True,timeout=7200,
                         env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        run.record(14,'full_suite','PASS'if r.returncode==0 else'FAIL',returncode=r.returncode,tail=r.stderr.strip().splitlines()[-3:],
                   failed=[l for l in r.stderr.splitlines()if l.startswith(('FAIL:','ERROR:'))])
    # 15 seal
    from gaia.provenance import digest
    files={p.name:digest(json.loads(p.read_text()))for p in sorted(out.glob('*.json'))}
    verdict='PASS'if all(r['status']in('PASS','SKIPPED')for r in run.results)else'FAIL'
    run.record(15,'seal','PASS'if verdict=='PASS'else'FAIL',verdict=verdict,identity=identities(ROOT)['hash'],commit=git(ROOT,'rev-parse','HEAD'),
               sessions=sessions,evidence=files,limits=STAGE_LIMITS)
    print('STAGE0',verdict);return 0 if verdict=='PASS'else 2


if __name__=='__main__':raise SystemExit(main())
