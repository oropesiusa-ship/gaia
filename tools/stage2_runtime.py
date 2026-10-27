"""Administrative S1 orchestration. Importing this module never starts work."""
import json
import math
import os
from pathlib import Path
import signal
import time
import argparse
import subprocess
import sys
from tools.stage2_children import ChildBoundary
from tools.stage2_fds import with_owned_pidfds

from tools import stage2_executor as ex
from gaia.autonomy.clock import stamp
from gaia.autonomy.inspection import inspect_campaign
from gaia.autonomy.catalog import catalog
from gaia.autonomy.lineage import engine_state_dir
from gaia.autonomy.session import SessionStore,session_contract
from gaia.autonomy.store import CampaignStore,durable
from gaia.autonomy.supervisor import Supervisor,proc_info,tree,alive,processes
from gaia.autonomy.telemetry import Telemetry,memory,filesystem,vram,storage_by_owner
from tools.stage1_coverage import slot_deadline,window_coverage
from tools.audit_endurance_session import audit_session

HEADROOM=64*2**20


def charge_wall(report_wall,supervised):
    values=[supervised]if report_wall is None else[report_wall,supervised]
    if any(type(v)not in (int,float)or not math.isfinite(v)or v<0 for v in values):
        raise ValueError('INVALID_CAMPAIGN_WALL')
    return max(values)


class EvidenceTelemetry(Telemetry):
    """Same reader/format as the existing auditor, without evidence-deleting rotation."""
    def __init__(self,directory,fd_provider=None):
        super().__init__(directory);self.fd_provider=fd_provider

    def append(self,sample):
        if sample.get('kind')=='PROCESS'and self.fd_provider is not None:
            measured=self.fd_provider()
            sample={**sample,'supervisor_fds_before_heartbeat':sample.get('supervisor_fds'),
                    'supervisor_fds':measured['fds'],'supervisor_pid':measured['pid'],
                    'supervisor_start_time':measured['start_time'],
                    'supervisor_fd_accounting':measured['fd_accounting']}
        self.directory.mkdir(parents=True,exist_ok=True)
        path=self.directory/'samples-000001.jsonl'
        if path.is_symlink():raise ValueError('TELEMETRY_SYMLINK')
        line=json.dumps({'session_id':self.directory.parent.name,'campaign_id':None,'quality':'MEASURED',
                         **sample,'clock':sample.get('clock')or stamp()},sort_keys=True)+'\n'
        with path.open('a')as stream:stream.write(line);stream.flush();os.fsync(stream.fileno())


def process_metrics(pid):
    info=proc_info(pid)
    if not info:return {'pid':pid,'quality':'PROCESS_GONE'}
    result={'pid':pid,'start_time':info[7],'rss_bytes':info[3],'fds':info[4],
            'ppid':info[0],'pgid':info[1],'sid':info[2],'quality':'MEASURED'}
    try:
        fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        result['cpu_s']=(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
        for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
            if line.startswith('Pss:'):result['pss_bytes']=int(line.split()[1])*1024
    except (OSError,ValueError,IndexError):result['quality']='PARTIAL_PROC_SAMPLE'
    return result


def audit_aggregate(store,aggregate):
    view=aggregate.view();session=store.state_view();fail=[]
    bindings=[view['bindings'].get(role)for role in ('S1-C1','S1-C2')]
    if view['sessions']!=[store.identifier]:fail.append('STAGE_SESSION_LINK_MISMATCH')
    if bindings!=session['campaigns']:fail.append('STAGE_CAMPAIGN_LINK_MISMATCH')
    if len(view['charges'])!=2:fail.append('UNRECONCILED_STAGE_RESERVATION')
    for role,cid in view['bindings'].items():
        charges=[r['wall_s']for r in session['finished']if r.get('campaign_id')==cid]
        if charges!=[view['charges'].get(role)]:fail.append('STAGE_SESSION_CHARGE_MISMATCH:'+role)
    if view['overrun']or view['actual_compute_s']>7200:fail.append('STAGE_COMPUTE_EXCEEDED')
    if aggregate.storage()>=4*2**30:fail.append('STAGE_STORAGE_EXCEEDED')
    return {'status':'FAIL'if fail else'PASS','failures':fail,'snapshot':view,'owners':aggregate.ownership()}


class FirstSessionSupervisor(Supervisor):
    """Two sequential NumPy campaigns; remaining slot time is observed idle.

    No automatic adoption, repair, restart or recovery in S1. An interrupted
    reservation blocks another S1 launch and remains charged until offline review.
    """
    def __init__(self,root,state,sid,stage_contract,aggregate,*,sleep=time.sleep,now=time.monotonic,boundary=None):
        super().__init__(root,state,sid,sleep=sleep)
        self.stage_contract=stage_contract;self.aggregate=aggregate;self.now=now
        self.boundary=boundary
        self.telemetry=EvidenceTelemetry(self.session.root/'telemetry',fd_provider=self.fd_metrics)
        self.child=None;self.child_started=None;self.owned={};self.last_extra=None
        self.roles={};self.baseline=self.fd_metrics();self.last_fd_snapshot=self.baseline
        self.benchmark=None
        self.environment_evidence=[]
        durable(self.session.root/'evidence'/'baseline.json',{'clock':stamp(),'supervisor':self.baseline,
            'memory':memory(),'vram':vram(),'storage_bytes':aggregate.storage()},True)

    def fd_metrics(self):
        return with_owned_pidfds(process_metrics(os.getpid()),self.boundary)

    def guard(self):
        current_boot=ex.boot_id()
        if current_boot!=self.stage_contract['boot_id']:
            self.environment_evidence.append({'clock':stamp(),'reason':'BOOT_ID_CHANGED','observed_boot_id':current_boot})
            raise RuntimeError('BOOT_ID_CHANGED')
        if self.stage_contract['commit']!=ex.git(self.root,'rev-parse','HEAD'):raise RuntimeError('COMMIT_CHANGED')
        if self.stage_contract['preregistration_sha256']!=ex.sha(ex.PREREG):raise RuntimeError('PREREGISTRATION_CHANGED')
        if self.stage_contract['plan']['administrative_hashes']!={p:ex.sha(ex.ROOT/p)for p in ex.ADMIN_FILES}:raise RuntimeError('ADMINISTRATIVE_TOOL_CHANGED')
        ex.operational_scratch(self.stage_contract)
        if ex.changes(self.root,self.state,self.contract['freeze']):raise RuntimeError('PROTOCOL_CHANGED')
        if self.benchmark is not None:
            path,expected=self.benchmark
            if not path.exists()or ex.sha(path)!=expected:raise RuntimeError('BENCHMARK_CHANGED')
        if self.stopping():raise RuntimeError('OPERATOR_STOP')
        if self.boundary is not None:
            for row in self.boundary.collect():self.owned[row['pid']]=row
            if self.boundary.record_error is not None:raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:'+self.boundary.record_error)
        me=proc_info(os.getpid())
        if me is None or me[4]is None:raise RuntimeError('SUPERVISOR_METRICS_UNAVAILABLE')
        baseline_rss=self.baseline.get('rss_bytes');baseline_fds=self.baseline.get('fds')
        if baseline_rss is None or baseline_fds is None:raise RuntimeError('SUPERVISOR_BASELINE_UNAVAILABLE')
        if me[3]>baseline_rss+max(64*2**20,.2*baseline_rss):raise RuntimeError('SUPERVISOR_RSS_BAND')
        self.last_fd_snapshot=self.fd_metrics()
        if self.last_fd_snapshot['fd_accounting']['unaccounted_fds']>baseline_fds+5:raise RuntimeError('SUPERVISOR_FD_BAND')
        if self.child is not None and self.child.poll()is None:
            for row in tree(self.child.pid):self.owned[row['pid']]=row
        allowed={pid for pid,row in self.owned.items()if alive(pid,row['starttime'])}
        external={pid:i for pid,i in processes().items()if pid not in allowed and i[6]!='Z'
                  and any(token in i[5]for token in ('runtime_worker','koboldcpp','llama-server'))}
        if external:
            self.environment_evidence.append({'clock':stamp(),'reason':'EXTERNAL_BACKEND_BUSY','processes':external})
            raise RuntimeError('EXTERNAL_BACKEND_BUSY')
        host=memory()
        if host.get('available_bytes')is None or host.get('below_reserve'):raise RuntimeError('HOST_MEMORY_RESERVE')
        for path in (self.root,self.state):
            disk=filesystem(path)
            if disk.get('free_bytes')is None or disk.get('below_reserve'):raise RuntimeError('FILESYSTEM_RESERVE')
        if self.aggregate.storage()>=4*2**30-HEADROOM:raise RuntimeError('STAGE_STORAGE_HEADROOM')
        if self.aggregate.view()['overrun']:raise RuntimeError('STAGE_COMPUTE_OVERRUN')
        if self.child is not None and self.child.poll()is None and self.now()-self.child_started>=1770:
            raise RuntimeError('CAMPAIGN_SUPERVISION_DEADLINE')

    def sample(self,phase,campaign_id=None):
        self.guard();current=[]
        if self.child is not None and self.child.poll()is None:
            current=tree(self.child.pid)
            for row in current:self.owned[row['pid']]=row
        self.telemetry.append({'kind':'STAGE2_METRICS','session_id':self.session.identifier,'campaign_id':campaign_id,
            'phase':phase,'quality':'MEASURED','supervisor':self.fd_metrics(),
            'descendants':[process_metrics(r['pid'])for r in current],
            'stage_storage_bytes':self.aggregate.storage(),'stage_owners':self.aggregate.ownership(),
            'lock_files':[{'path':str(p),'bytes':p.stat().st_size,'held':'NOT_MEASURED'}
                          for p in self.state.rglob('*.lock')if not p.is_symlink()],
            'stage_budget':self.aggregate.view()})
        self.last_extra=self.now()

    def heartbeat(self,**fields):
        self.guard();super().heartbeat(**fields)
        if self.last_extra is None or self.now()-self.last_extra>=10:
            self.sample(fields.get('phase','ACTIVE'),fields.get('campaign_id'))

    def storage_check(self,campaign_id=None):
        # Keep the shared auditor's owner breakdown, but never subtract a session baseline.
        owners=storage_by_owner(self.root,self.state,self.session);used=self.aggregate.storage()
        disk=filesystem(self.state)
        self.telemetry.append({'kind':'STORAGE','owners':owners,'stage_storage_bytes':used,
            'filesystem':disk,'campaign_id':campaign_id,'session_id':self.session.identifier,'quality':'MEASURED'})
        self.sampled=self.now()
        if disk.get('free_bytes')is None or disk.get('below_reserve'):return 'FILESYSTEM_RESERVE'
        return 'STAGE_STORAGE_HEADROOM'if used>=4*2**30-HEADROOM else None

    def create_campaign(self,lineage_id,seconds):
        self.guard();view=self.session.state_view();ordinal=len(view['campaigns'])+1
        if ordinal>2 or view['running']:raise RuntimeError('S1_CAMPAIGN_ORDER')
        if self.aggregate.storage()+512*2**20+HEADROOM>=4*2**30:raise RuntimeError('STAGE_STORAGE_ADMISSION')
        role=f'S1-C{ordinal}'
        # Reserve the full cap before create_campaign can write any campaign state.
        self.aggregate.reserve(self.session.identifier,role,1800)
        catalogue=catalog(self.state,self.contract['lineages'],self.root)
        durable(self.session.root/'evidence'/f'{role}-catalogue-before.json',{'clock':stamp(),'catalogue':catalogue,
            'interpretation':'no_eligible_record'if not catalogue['references']else'ELIGIBILITY_AND_DECISION_NOT_YET_PROVEN',
            'reason':'NO_VERIFIED_REFERENCES_IN_PERSISTED_CATALOGUE'if not catalogue['references']else'REQUIRES_CAMPAIGN_BINDING_AND_DECISION_TRACE'},True)
        cid=super().create_campaign(lineage_id,min(1740,int(seconds)))
        self.aggregate.bind(role,cid);self.roles[cid]=role
        return cid

    def launch_run(self,campaign_id):
        self.guard()
        if self.boundary is None:raise RuntimeError('DEDICATED_SUBREAPER_REQUIRED')
        self.boundary.begin()
        scratch=ex.operational_scratch(self.stage_contract)
        binding=self.stage_contract['plan']['scratch_identity']
        logs=self.session.root/'logs';logs.mkdir(exist_ok=True)
        with (logs/f'{campaign_id}.out').open('ab') as out,(logs/f'{campaign_id}.err').open('ab') as err:
            proc=subprocess.Popen([sys.executable,'-B','-m','tools.stage2_campaign','autonomy-run',
                '--session',self.session.identifier,'--campaign',campaign_id,'--state-dir',str(self.state),
                '--scratch-root',str(scratch),'--scratch-device',str(binding['device']),'--scratch-inode',str(binding['inode']),
                '--journal',str(self.session.root/'evidence'/'scratch-lifecycle.jsonl')],
                cwd=self.root,stdout=out,stderr=err,stdin=subprocess.DEVNULL,start_new_session=True,
                env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        self.child=proc;self.child_started=self.now()
        self.boundary.attach(proc)
        info=proc_info(proc.pid)
        if info is None and proc.poll()is None:
            proc.kill();proc.wait();raise RuntimeError('CHILD_IDENTITY_UNAVAILABLE')
        if info:self.owned[proc.pid]={'pid':proc.pid,'starttime':info[7]}
        durable(self.session.root/'evidence'/f'{campaign_id}-launch.json',
            {'clock':stamp(),'pid':proc.pid,'starttime':info[7]if info else None,'campaign_id':campaign_id},True)
        return proc

    def kill_rows(self,proc,rows,grace=5):
        if self.boundary is None:raise RuntimeError('DEDICATED_SUBREAPER_REQUIRED')
        self.boundary.drain(grace=min(grace,2))
        return []

    def cleanup(self,proc,snapshot):
        if self.boundary is None:raise RuntimeError('DEDICATED_SUBREAPER_REQUIRED')
        current=self.boundary.collect()
        left=[r for r in current if r['pid']!=proc.pid and alive(r['pid'],r['starttime'])]
        durable(self.session.root/'evidence'/f'{proc.pid}-precleanup.json',{'clock':stamp(),'processes':current},True)
        self.boundary.drain()
        stopped={r['pid']:r for r in left}
        stopped.update({pid:row for pid,row in self.boundary.last_signalled.items()if pid!=proc.pid})
        return list(stopped.values())

    def bound_logs(self,campaign_id):
        # Preserve logs verbatim; storage gates stop further execution instead of truncating evidence.
        return None

    def supervise(self,campaign_id,lineage_id,adopted=None):
        if adopted is not None:raise RuntimeError('S1_ADOPTION_FORBIDDEN')
        if not self.locks_free(lineage_id):raise RuntimeError('LOCK_BUSY_OUTSIDE_SESSION')
        started=self.now();proc=None
        try:
            proc=self.launch(campaign_id)
            _,seconds=self.watch(proc,campaign_id)
            return inspect_campaign(self.state,campaign_id),'DONE',max(seconds,self.now()-started)
        except BaseException as exc:
            proc=proc or self.child
            try:
                durable(self.session.root/'evidence'/f'{campaign_id}-interrupted.json',
                    {'clock':stamp(),'reason':str(exc),'supervisor':self.last_fd_snapshot,'inspection':inspect_campaign(self.state,campaign_id),
                     'processes':list(self.owned.values()),'aggregate':self.aggregate.view(),
                     'external_backend_processes':{pid:i for pid,i in processes().items()
                         if pid not in self.owned and i[6]!='Z'and any(t in i[5]for t in ('runtime_worker','koboldcpp','llama-server'))}},True)
            finally:
                survivors=self.kill_rows(proc,list(self.owned.values()))if proc is not None else[]
            self.session.event('CHILD_EXITED',{'campaign_id':campaign_id,'returncode':proc.poll()if proc else None,'survivors':survivors,'cause':'STAGE2_GUARD'})
            raise
        finally:self.child=None

    def observe_until(self,target):
        while self.now()<target:
            self.guard();self.heartbeat(phase='SCHEDULED_IDLE',next_slot_monotonic=target)
            self.telemetry.append({'kind':'IDLE','phase':'SCHEDULED_IDLE','session_id':self.session.identifier,
                'host_memory':memory(),'supervisor_rss_bytes':proc_info(os.getpid())[3],
                'supervisor_fds':proc_info(os.getpid())[4],'quality':'MEASURED'})
            if self.sampled is None or self.now()-self.sampled>=60:self.storage_check()
            if self.vram_sampled is None or self.now()-self.vram_sampled>=30:
                self.telemetry.append({'kind':'VRAM','phase':'SCHEDULED_IDLE',**vram()});self.vram_sampled=self.now()
            self.sleep(min(10,max(0,target-self.now())))

    def finish(self,campaign_id,lineage_id,info,outcome,supervised):
        store=CampaignStore(self.state,campaign_id);state=store.inspect()['state']
        report=store.get(state['report_ref'])if state.get('report_ref')else{}
        metrics=report.get('metrics',{});wall=charge_wall(metrics.get('total_wall_time'),supervised)
        self.session.event('CAMPAIGN_FINISHED',{'campaign_id':campaign_id,'lineage_id':lineage_id,
            'recovery':info['recovery'],'reason':info['reason'],'stopping_reason':info.get('stopping_reason'),
            'wall_s':wall,'campaign_wall_s':metrics.get('total_wall_time'),'supervised_s':supervised,'outcome':outcome,
            'research_calls':metrics.get('research_calls',0),'experiments':metrics.get('experiments'),'report_status':report.get('status')})
        self.aggregate.finish(self.roles[campaign_id],campaign_id,wall)
        manifest=ex.inventory([store.root],include_cache=True)
        benchmark=self.root/engine_state_dir(lineage_id)/'benchmark.json'
        if self.benchmark is not None and (not benchmark.exists()or ex.sha(benchmark)!=self.benchmark[1]):raise RuntimeError('BENCHMARK_CHANGED')
        if benchmark.exists()and self.benchmark is None:self.benchmark=(benchmark,ex.sha(benchmark))
        durable(self.session.root/'evidence'/f'{campaign_id}-terminal.json',{'clock':stamp(),'manifest':manifest,
            'aggregate':self.aggregate.view(),'session':self.session.state_view(),
            'lineage_manifest':ex.inventory([self.state/'autonomy'/'lineages'/lineage_id],include_cache=True),
            'benchmark_sha256':self.benchmark[1]if self.benchmark else None},True)
        durable(self.session.root/'evidence'/f'{campaign_id}-learning.json',{'clock':stamp(),
            'catalogue':catalog(self.state,self.contract['lineages'],self.root),
            'learning_reused':metrics.get('learning_reused',0),'learning_refs':report.get('learning_refs',[]),
            'reuse_refs':report.get('learning_reuse_refs',[]),'coverage_refs':report.get('knowledge_coverage_refs',[]),
            'catalogue_reference_decision_claim':'NOT_EXERCISED'},True)
        if info['recovery']!='TERMINAL_OK'or wall>1800:raise RuntimeError('CAMPAIGN_NOT_TERMINAL_WITHIN_RESERVATION')
        exits=[e['payload']for e in self.session.events()if e['kind']=='CHILD_EXITED']
        if any(e.get('orphans_stopped')or e.get('survivors')for e in exits):raise RuntimeError('UNEXPECTED_DESCENDANTS')
        self.sample('POST_CLEANUP',campaign_id)
        view=self.session.state_view()
        self.observe_until(slot_deadline(view['started_clock']['monotonic'],len(view['campaigns']),self.contract['limits']))
        return outcome

    def stop(self,reason,**extra):
        # A STOP request must not prevent recording the terminal heartbeat/evidence.
        value=self.session.event('STOPPED',{'reason':reason,**extra})
        Supervisor.heartbeat(self,stopped=reason)
        return value['payload']


def administrative_sandbox_probe(boundary):
    """Approved master-plan exception: contain the trusted bwrap smoke probe.

    bwrap may leave an adopted zombie even after subprocess.run waited for its
    leader. This is an explicit administrative epoch, never a campaign epoch.
    Live leftover children or an unverified probe still fail closed; every path
    drains owned children before the idle-child gate can admit a campaign.
    """
    from gaia import provenance
    boundary.begin()
    try:
        boundary.record({'kind':'ADMINISTRATIVE_PROBE_BEGIN','probe':'BWRAP_CAPABILITY'})
        if boundary.record_error is not None:raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:'+boundary.record_error)
        capability=provenance.bwrap_capability()
        children=boundary.collect()
        if any(row['state']!='Z'for row in children):raise RuntimeError('LIVE_ADMINISTRATIVE_PROBE_CHILDREN')
        if not capability.get('verified'):raise ValueError('SANDBOX_UNAVAILABLE')
        return capability
    finally:
        boundary.drain()
        if not boundary.kernel_empty():raise RuntimeError('ADMINISTRATIVE_PROBE_CLEANUP_INCOMPLETE')
        boundary.record({'kind':'ADMINISTRATIVE_PROBE_END','probe':'BWRAP_CAPABILITY',
                         'kernel_echild':True})
        if boundary.record_error is not None:raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:'+boundary.record_error)


def _run_first(root,contract_path,boundary):
    root=root.resolve();contract_path=ex.safe_out(root,contract_path).resolve();out=contract_path.parent
    c=ex.validate_contract(json.loads(contract_path.read_bytes()));state=Path(c['state_path'])
    if state!=out/'state':raise ValueError('CANONICAL_STAGE2_STATE_REQUIRED')
    scratch=[ex.operational_scratch(c)]
    roots=[out,state,*[root/engine_state_dir(lin)for lin in c['lineages']],*scratch]
    aggregate=ex.StageBudget(out/'budget',c['hash'],roots)
    with aggregate.exclusive():
        if aggregate.events():raise ValueError('S1_ALREADY_STARTED_OR_AMBIGUOUS_NO_AUTOMATIC_RETRY')
        preflight=ex.admission(c,root,state)
        if preflight['status']!='PASS':raise ValueError('BLOCKED_PREEXECUTION:'+','.join(preflight['reasons']))
        ex.fresh_lineage(root,state,c['lineages'])
        ex.operational_scratch(c,empty=True)
        if any(i[6]!='Z'and any(token in i[5]for token in ('runtime_worker','koboldcpp','llama-server'))for i in processes().values()):
            raise ValueError('EXTERNAL_BACKEND_BUSY')
        administrative_sandbox_probe(boundary)
        session=session_contract(c['lineages'],stage='stage2',limits=ex.LIMITS,frozen=c['freeze'])
        sid=session['session_id'];aggregate.start_session(sid)
        durable(out/'authorization-s1.json',{'clock':stamp(),'contract_hash':c['hash'],
            'session_id':sid,'scope':'S1_ONLY_TWO_SEQUENTIAL_NUMPY_CAMPAIGNS'},True)
        store=SessionStore(state,sid);store.create(session,root)
        supervisor=FirstSessionSupervisor(root,state,sid,c,aggregate,boundary=boundary)
        error=None
        try:supervisor.run()
        except BaseException as exc:
            error=f'{type(exc).__name__}: {exc}'
            if not store.state_view()['stopped']:supervisor.stop('STAGE2_SAFETY_STOP',error=error)
        # Audit failures are evidence, not reasons to retry or repair a campaign.
        try:
            audit=audit_session(root,state,sid,stage='stage2')
            reconciliation=ex.reconcile(store,roots,root=root)
            stage_audit=audit_aggregate(store,aggregate)
            coverage=window_coverage(store)
            replay=[]
            for cid in store.state_view()['campaigns']:
                boundary.begin()
                try:row=ex.terminal_noop(state,cid,[state],root=root)
                finally:
                    extra=boundary.collect()
                    boundary.drain()
                if extra:
                    row.update(status='FAIL',child_creation_claim='FAIL',unexpected_children=extra)
                replay.append(row)
            good=(not error and len(replay)==2 and all(r['status']=='PASS'for r in replay)
                and audit['status']==reconciliation['status']==coverage['status']==stage_audit['status']=='PASS'
                and not aggregate.view()['overrun'])
            environmental=bool(error and supervisor.environment_evidence and any(t in error for t in ('BOOT_ID_CHANGED','EXTERNAL_BACKEND_BUSY')))
            result={'status':'S1_OBSERVED'if good else'INCONCLUSIVE_ENVIRONMENT'if environmental else'FAIL','session_id':sid,'error':error,
                'audit':audit,'reconciliation':reconciliation,'coverage':coverage,'terminal_replays':replay,
                'aggregate':aggregate.view(),'aggregate_audit':stage_audit,
                'final_stage2_status':'INCONCLUSIVE_ENVIRONMENT'if environmental else'NOT_EXERCISED',
                'environment_evidence':supervisor.environment_evidence,
                'final_pass_blockers':c['plan']['final_pass_blockers']}
        except Exception as exc:
            result={'status':'FAIL','session_id':sid,'error':error,'audit_error':str(exc),'aggregate':aggregate.view(),
                'final_stage2_status':'NOT_EXERCISED'}
        return result


def run_first(root,contract_path):
    """Only the dedicated CLI process may own a production subreaper boundary."""
    if __name__!='__main__':raise RuntimeError('DEDICATED_RUNTIME_CLI_REQUIRED')
    root=Path(root).resolve();contract_path=ex.safe_out(root,Path(contract_path)).resolve()
    path=contract_path.parent/'subreaper.jsonl'
    if path.exists():raise ValueError('SUBREAPER_EVIDENCE_ALREADY_EXISTS')
    def record(event):
        with path.open('a')as stream:
            stream.write(json.dumps({'clock':stamp(),**event},sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
    with ChildBoundary(record)as boundary:
        result=_run_first(root,contract_path,boundary)
    result['subreaper']={'status':'PASS','restored_value':boundary.previous,'kernel_children_drained':True}
    result['storage_enforcement']='POLLING_NOT_PHYSICAL_QUOTA'
    durable(contract_path.parent/'result-s1.json',result,True)
    c=json.loads(contract_path.read_bytes())
    roots=[contract_path.parent,Path(c['state_path']),*[root/engine_state_dir(lin)for lin in c['lineages']],
           Path(c['plan']['scratch_root'])]
    durable(contract_path.parent/'manifest-s1.json',ex.inventory(roots,include_cache=True),True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--contract',required=True)
    parser.add_argument('--authorize-stage2-s1',action='store_true');args=parser.parse_args()
    if not args.authorize_stage2_s1:parser.error('EXPLICIT_STAGE2_S1_AUTHORIZATION_REQUIRED')
    def stop(signum,frame):raise KeyboardInterrupt(f'STAGE2_RUNTIME_SIGNAL_{signum}')
    previous={sig:signal.signal(sig,stop)for sig in (signal.SIGTERM,signal.SIGHUP)}
    try:print(json.dumps(run_first(ex.ROOT,Path(args.contract))))
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)


if __name__=='__main__':main()
