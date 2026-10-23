"""Endurance supervisor (1.1 §1): one long-lived process driving a session's campaigns as child process groups.

It checks liveness from the outside, detects hangs from journal progress, identifies and stops only its own
processes (pid and start time), preserves evidence before any cleanup, and relaunches a campaign only when the
read-only inspection classifies it RECOVERABLE and a relaunch can make progress. It never edits campaign or
lineage state: campaigns recover through their own run()."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from .clock import stamp,interval
from .inspection import inspect_campaign
from .lineage import LineageStore,LineageBusy
from .session import SessionStore,budget,restarts_used
from .store import CampaignStore,durable
from .telemetry import Telemetry,storage_by_owner,filesystem,gates,bound_log,memory,vram

ROLES=(('gaia.autonomy.regression','MATRIX'),('autonomy-run','CONTROLLER'),('runtime_worker','BACKEND'),('koboldcpp','BACKEND'),
       ('llama','BACKEND'),('bwrap','WORKER'),('worker','WORKER'))
TERMINATE_GRACE_S=30
LOCK_WAIT_POLL_S=5


def proc_info(pid):
    """(ppid, pgid, sid, rss_bytes, fds, cmdline, state, starttime) of an existing process, or None."""
    try:
        stat=Path(f'/proc/{pid}/stat').read_text();fields=stat[stat.rindex(')')+2:].split()
        cmd=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace').strip()
        rss=int(fields[21])*os.sysconf('SC_PAGE_SIZE')
        try:fds=len(os.listdir(f'/proc/{pid}/fd'))
        except OSError:fds=None
        return int(fields[1]),int(fields[2]),int(fields[3]),rss,fds,cmd,fields[0],int(fields[19])
    except (OSError,ValueError,IndexError):return None


def alive(pid,starttime=None):
    """Running (not a zombie) and, when given, still the same process (start time) — never a reused pid."""
    info=proc_info(pid)
    return bool(info)and info[6]!='Z'and(starttime is None or info[7]==starttime)


def role(cmd):return next((r for token,r in ROLES if token in cmd),'OTHER')


def processes():
    rows={}
    for entry in os.listdir('/proc'):
        if entry.isdigit():
            info=proc_info(int(entry))
            if info:rows[int(entry)]=info
    return rows


def tree(root_pid):
    """The live descendants of root_pid (any session or group), classified by role, with their start times."""
    table=processes();children={}
    for pid,info in table.items():children.setdefault(info[0],[]).append(pid)
    rows=[root_pid]if root_pid in table else[];pending=list(rows)
    while pending:
        for pid in children.get(pending.pop(),[]):rows.append(pid);pending.append(pid)
    return [{'pid':p,'ppid':table[p][0],'pgid':table[p][1],'sid':table[p][2],'rss_bytes':table[p][3],'fds':table[p][4],'role':role(table[p][5]),
             'cmd':table[p][5][:200],'state':table[p][6],'starttime':table[p][7]}for p in rows if table[p][6]!='Z']


def controllers(campaign_id):
    """Live autonomy-run processes for this campaign, whoever started them."""
    return sorted(p for p,i in processes().items()if i[6]!='Z'and'autonomy-run'in i[5]and campaign_id in i[5].split())


class Adopted:
    """A campaign controller left running by a previous supervisor (its own process group, reparented): polled, not waited."""
    def __init__(self,pid):
        info=proc_info(pid);self.pid=pid;self.starttime=info[7]if info else None;self.returncode=None
    def poll(self):
        if self.returncode is None and not alive(self.pid,self.starttime):self.returncode=-1
        return self.returncode


class Supervisor:
    def __init__(self,root,state,session_id,*,launch=None,create=None,sleep=time.sleep):
        self.root=Path(root);self.state=Path(state);self.session=SessionStore(state,session_id);self.contract=self.session.read()
        self.launch=launch or self.launch_run;self.create=create or self.create_campaign;self.sleep=sleep;self.cursor=0
        self.telemetry=Telemetry(self.session.root/'telemetry');self.sampled=None;self.vram_sampled=None

    # ------------------------------------------------------------------ process control
    def launch_run(self,campaign_id):
        logs=self.session.root/'logs';logs.mkdir(exist_ok=True)
        out=(logs/f'{campaign_id}.out').open('ab');err=(logs/f'{campaign_id}.err').open('ab')
        try:
            return subprocess.Popen([sys.executable,'-B',str(self.root/'gaia.py'),'autonomy-run',campaign_id,'--state-dir',str(self.state),'--authorize-campaign'],
                cwd=self.root,stdout=out,stderr=err,stdin=subprocess.DEVNULL,start_new_session=True,
                env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        finally:out.close();err.close()

    def kill_rows(self,proc,rows,grace=TERMINATE_GRACE_S):
        """SIGTERM then SIGKILL the child's group and the given rows that are still the same processes (pid + start time)."""
        mine=[r for r in rows if r['pid']!=proc.pid]
        for sig in (signal.SIGTERM,signal.SIGKILL):
            # The group is signalled only while its leader is ours or members of it remain (no reused group id).
            if proc.poll()is None or any(i[1]==proc.pid and i[6]!='Z'for i in processes().values()):
                try:os.killpg(proc.pid,sig)
                except (ProcessLookupError,PermissionError):pass
            for r in mine:
                if alive(r['pid'],r['starttime']):
                    try:os.kill(r['pid'],sig)
                    except ProcessLookupError:pass
            deadline=time.monotonic()+grace
            while time.monotonic()<deadline and(proc.poll()is None or any(alive(r['pid'],r['starttime'])for r in mine)):self.sleep(.2)
            if proc.poll()is not None and not any(alive(r['pid'],r['starttime'])for r in mine):break
        return [r['pid']for r in mine if alive(r['pid'],r['starttime'])]

    def cleanup(self,proc,snapshot):
        """After any child exit: processes of its tree that outlived it (a regression matrix, a backend) are stopped."""
        left=[r for r in snapshot if r['pid']!=proc.pid and alive(r['pid'],r['starttime'])]
        seen={r['pid']for r in left}
        # Members of its process group count too: they may have started after the last snapshot.
        left+=[{'pid':p,'starttime':i[7],'role':role(i[5])}for p,i in processes().items()if i[1]==proc.pid and p!=proc.pid and p not in seen and i[6]!='Z']
        if not left:return []
        self.kill_rows(proc,left,grace=10)
        return [{'pid':r['pid'],'role':r['role']}for r in left]

    # ------------------------------------------------------------------ campaigns
    def create_campaign(self,lineage_id,seconds):
        from .controller import create_campaign
        from .schema import campaign
        lineage=LineageStore(self.state,lineage_id).read()
        limits=self.contract['limits']
        c=campaign(lineage['objective'],mode=self.contract['mode'],promotion=self.contract['allow_promotion'],lineage_id=lineage_id,
                   limits={'maximum_wall_time':int(seconds),'maximum_compute_budget':int(seconds),'maximum_iterations':limits['campaign_iterations'],
                           'maximum_experiments':limits['campaign_experiments'],'maximum_disk_budget':limits['campaign_disk_bytes']})
        return create_campaign(self.root,self.state,c,intelligence_state=lineage['intelligence_state'])['campaign_id']

    def next_lineage(self,view):
        lineages=self.contract['lineages']
        for k in range(len(lineages)):
            candidate=lineages[(self.cursor+k)%len(lineages)]
            if candidate in view['skipped']:continue
            if LineageStore(self.state,candidate).state()['blocked']:
                self.session.event('LINEAGE_SKIPPED',{'lineage_id':candidate,'reason':'LINEAGE_BLOCKED_NEEDS_REVIEW'});continue
            self.cursor=(self.cursor+k+1)%len(lineages);return candidate
        return None

    def locks_free(self,lineage_id):
        """Whether the lineage lock and (for measured modes) the host experiment lock are free right now."""
        paths=[LineageStore(self.state,lineage_id).root/'.lock']
        if self.contract['mode']=='CONTROLLED_AUTONOMOUS':paths.append(self.root/'.gaia'/'locks'/'experiment.lock')
        for path in paths:
            if not path.exists():continue
            with path.open('a+b')as f:
                try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(f,fcntl.LOCK_UN)
                except BlockingIOError:return False
        return True

    def wait_for_locks(self,lineage_id):
        """A lock held by another process is waited for (bounded by the hang timeout), never retried as a relaunch."""
        deadline=time.monotonic()+self.contract['limits']['hang_timeout_s']
        while not self.locks_free(lineage_id):
            if time.monotonic()>=deadline:return False
            self.sleep(min(LOCK_WAIT_POLL_S,self.contract['limits']['heartbeat_s']or LOCK_WAIT_POLL_S))
        return True

    def last_heartbeat(self):
        path=self.session.root/'heartbeat.json'
        return json.loads(path.read_bytes())if path.exists()else None

    def control(self):
        path=self.session.root/'control.json'
        return json.loads(path.read_bytes())['request']if path.exists()else'RUN'

    def stopping(self):return self.control()=='STOP'or self.session.state_view()['stop_requested']

    def heartbeat(self,**fields):
        durable(self.session.root/'heartbeat.json',{'session_id':self.contract['session_id'],'supervisor_pid':os.getpid(),'clock':stamp(),
            'supervisor':{k:v for k,v in zip(('ppid','pgid','sid','rss_bytes','fds'),(proc_info(os.getpid())or(None,)*5)[:5])},**fields})

    def storage_check(self,campaign_id=None):
        """§6: storage by owner against the session ceiling (gates 70/85/95 %) and the host filesystem reserve."""
        owners=storage_by_owner(self.root,self.state,self.session);used=sum(owners.values())-(self.session.state_view()['baseline_storage_bytes']or 0)
        fs=filesystem(self.state);gate,percent=gates(max(0,used),self.contract['limits']['maximum_storage_bytes'])
        view=self.session.state_view()
        if gate and gate>(view.get('storage_gate')or 0):self.session.event('STORAGE_GATE',{'gate':gate,'percent':percent,'campaign_id':campaign_id,'owners':owners})
        self.telemetry.append({'kind':'STORAGE','owners':owners,'session_growth_bytes':used,'ceiling_percent':percent,'filesystem':fs,'campaign_id':campaign_id})
        self.sampled=time.monotonic()
        return 'FILESYSTEM_RESERVE'if fs['below_reserve']else'STORAGE_GATE_95'if gate==95 else None

    def request_stop(self,campaign_id,reason):
        CampaignStore(self.state,campaign_id).control('STOP')
        if not self.session.state_view()['stop_requested']:self.session.event('STOP_REQUESTED',{'campaign_id':campaign_id,'reason':reason})

    def watch(self,proc,campaign_id):
        """Poll until the child exits or stops progressing; heartbeat each period. Returns (how it ended, seconds watched)."""
        limits=self.contract['limits'];last=None;started=progress=time.monotonic();stop_sent=False;snapshot=[]
        while proc.poll()is None:
            info=inspect_campaign(self.state,campaign_id);current=tree(proc.pid);snapshot=current or snapshot
            if info.get('events')!=last:last=info.get('events');progress=time.monotonic()
            idle=time.monotonic()-progress
            sample=dict(campaign_id=campaign_id,child_pid=proc.pid,phase=info.get('phase'),events=info.get('events'),seconds_without_progress=idle,
                processes={r:sum(1 for x in current if x['role']==r)for r in sorted({x['role']for x in current})},
                child_rss_bytes=sum(x['rss_bytes']for x in current),child_fds=sum(x['fds']or 0 for x in current),
                controller_alive=proc.poll()is None,backend_processes=sum(1 for x in current if x['role']=='BACKEND'))
            host=memory();me=proc_info(os.getpid())or(0,0,0,0,0)
            self.heartbeat(**sample);self.telemetry.append({'kind':'PROCESS',**sample,'supervisor_rss_bytes':me[3],'supervisor_fds':me[4],'host_memory':host})
            if self.vram_sampled is None or time.monotonic()-self.vram_sampled>=limits['vram_sample_s']:
                self.telemetry.append({'kind':'VRAM','campaign_id':campaign_id,**vram()});self.vram_sampled=time.monotonic()
            if host['below_reserve']and not stop_sent:
                # Host memory reserve: max(2 GiB, 15 % RAM). The campaign stops at a safe boundary and the session stops.
                if not any(e['kind']=='RESOURCE_RESERVE'for e in self.session.events()):self.session.event('RESOURCE_RESERVE',{'campaign_id':campaign_id,'memory':host})
                self.request_stop(campaign_id,'HOST_MEMORY_RESERVE');stop_sent=True
            storage=None
            if self.sampled is None or time.monotonic()-self.sampled>=limits['storage_sample_s']:storage=self.storage_check(campaign_id)
            if storage and not stop_sent:self.request_stop(campaign_id,storage);stop_sent=True
            if self.control()=='STOP'and not stop_sent:self.request_stop(campaign_id,'OPERATOR_STOP');stop_sent=True
            if idle>limits['hang_timeout_s']:
                evidence=self.session.root/'evidence'/f'{campaign_id}-hang-{int(time.time())}.json'
                durable(evidence,{'campaign_id':campaign_id,'inspection':info,'processes':current,'clock':stamp(),'seconds_without_progress':idle})
                self.session.event('HANG_DETECTED',{'campaign_id':campaign_id,'seconds_without_progress':idle,'evidence':evidence.name,'processes':len(current)})
                survivors=self.kill_rows(proc,current)
                self.session.event('CHILD_EXITED',{'campaign_id':campaign_id,'returncode':proc.poll(),'cause':'TERMINATED_AFTER_HANG','survivors':survivors})
                self.bound_logs(campaign_id);return 'HANG',time.monotonic()-started
            self.sleep(limits['heartbeat_s'])
        orphans=self.cleanup(proc,snapshot)
        self.session.event('CHILD_EXITED',{'campaign_id':campaign_id,'returncode':proc.returncode,'cause':'EXITED','orphans_stopped':orphans})
        self.bound_logs(campaign_id);return 'EXITED',time.monotonic()-started

    def bound_logs(self,campaign_id):
        for name in ('out','err'):bound_log(self.session.root/'logs'/f'{campaign_id}.{name}')

    def supervise(self,campaign_id,lineage_id,adopted=None):
        """Run a campaign to a final class. Returns (inspection, outcome, supervised seconds); outcome is DONE, PAUSED or LOCK_BUSY."""
        relaunches=0;supervised=0.;lock_deadline=time.monotonic()+self.contract['limits']['hang_timeout_s']
        while True:
            if adopted is None and not self.wait_for_locks(lineage_id):
                return inspect_campaign(self.state,campaign_id),'LOCK_BUSY',supervised
            before=inspect_campaign(self.state,campaign_id).get('events')
            proc=adopted or self.launch(campaign_id);adopted=None
            _,seconds=self.watch(proc,campaign_id);supervised+=seconds
            info=inspect_campaign(self.state,campaign_id);view=self.session.state_view()
            if info.get('phase')=='PAUSED'and CampaignStore(self.state,campaign_id).read('control')['request']!='RUN':
                # A stop the session itself requested also leaves the campaign paused: that is a session stop, not an operator pause.
                return info,'STOPPED'if self.stopping()else'PAUSED',supervised
            if info['recovery']!='RECOVERABLE':return info,'DONE',supervised
            if info.get('events')==before and proc.poll()==0:
                # A clean exit without progress is a lock refusal (BLOCKED): retried within one cumulative wait, never a relaunch.
                if time.monotonic()>=lock_deadline:return info,'LOCK_BUSY',supervised
                self.sleep(min(LOCK_WAIT_POLL_S,self.contract['limits']['heartbeat_s']or LOCK_WAIT_POLL_S));continue
            if relaunches<self.contract['limits']['relaunches_per_campaign']and restarts_used(view)<self.contract['limits']['maximum_restarts']and not self.stopping():
                relaunches+=1;self.session.event('CAMPAIGN_RELAUNCHED',{'campaign_id':campaign_id,'lineage_id':lineage_id,'relaunch':relaunches,'reason':info['reason']})
                continue
            return info,'DONE',supervised

    def finish(self,campaign_id,lineage_id,info,outcome,supervised):
        store=CampaignStore(self.state,campaign_id);report=None
        try:
            state=store.inspect()['state']
            if state.get('report_ref'):report=store.get(state['report_ref'])
        except (OSError,ValueError):pass
        metrics=(report or{}).get('metrics',{})
        # Compute is always charged: the campaign's own wall time, or the supervised time when it left no report.
        wall=metrics.get('total_wall_time');charged=wall if wall is not None else supervised
        self.session.event('CAMPAIGN_FINISHED',{'campaign_id':campaign_id,'lineage_id':lineage_id,'recovery':info['recovery'],'reason':info['reason'],
            'stopping_reason':info.get('stopping_reason'),'wall_s':charged,'campaign_wall_s':wall,'supervised_s':supervised,'outcome':outcome,
            'research_calls':metrics.get('research_calls',0),'experiments':metrics.get('experiments'),'report_status':(report or{}).get('status')})
        if outcome=='DONE'and info['recovery']!='TERMINAL_OK'and lineage_id not in self.session.state_view()['skipped']:
            self.session.event('LINEAGE_SKIPPED',{'lineage_id':lineage_id,'reason':'CAMPAIGN_'+info['recovery']})
        return outcome

    # ------------------------------------------------------------------ session loop
    @contextmanager
    def lock(self):
        path=self.session.root/'.lock'
        with path.open('a+b')as f:
            try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:raise LineageBusy('SESSION_BUSY')from exc
            try:yield
            finally:fcntl.flock(f,fcntl.LOCK_UN)

    def stop(self,reason,**extra):
        value=self.session.event('STOPPED',{'reason':reason,**extra});self.heartbeat(stopped=reason);return value['payload']

    def ended(self,outcome):
        if outcome=='PAUSED':return self.stop('CAMPAIGN_PAUSED_BY_OPERATOR')
        if outcome=='LOCK_BUSY':return self.stop('LOCK_BUSY_OUTSIDE_SESSION')
        return None

    def resume_running(self,view):
        """After a supervisor restart: adopt a live controller of the running campaign, or relaunch it only if RECOVERABLE."""
        campaign_id=view['running'];lineage=next(e['payload']['lineage_id']for e in reversed(self.session.events())if e['kind']=='CAMPAIGN_STARTED')
        live=controllers(campaign_id)
        if live:return self.finish(campaign_id,lineage,*self.supervise(campaign_id,lineage,Adopted(live[0])))
        info=inspect_campaign(self.state,campaign_id)
        if info['recovery']!='RECOVERABLE'or restarts_used(view)>self.contract['limits']['maximum_restarts']:return self.finish(campaign_id,lineage,info,'DONE',0.)
        self.session.event('CAMPAIGN_RELAUNCHED',{'campaign_id':campaign_id,'lineage_id':lineage,'relaunch':0,'reason':'SUPERVISOR_RESTART'})
        return self.finish(campaign_id,lineage,*self.supervise(campaign_id,lineage))

    def run(self):
        with self.lock():
            view=self.session.state_view()
            if view['stopped']:return view['stopped']
            self.session.event('SUPERVISOR_STARTED',{'pid':os.getpid(),'clock':stamp()})
            if view['running']:
                outcome=self.resume_running(view)
                if self.ended(outcome):return self.session.state_view()['stopped']
            while True:
                view=self.session.state_view()
                if self.stopping():return self.stop(view.get('stop_reason')or'OPERATOR_STOP')
                from .freeze import changes
                changed=changes(self.root,self.state,self.contract['freeze'])
                if changed:return self.stop('PROTOCOL_CHANGED',changes=changed)
                storage=self.storage_check()
                if storage:return self.stop(storage)
                if memory()['below_reserve']:return self.stop('HOST_MEMORY_RESERVE',memory=memory())
                seconds,reasons=budget(self.contract,view,self.session.storage(self.root),stamp())
                if reasons:return self.stop(reasons[0],reasons=reasons)
                lineage=self.next_lineage(view)
                if lineage is None:return self.stop('NO_ELIGIBLE_LINEAGE')
                campaign_id=self.create(lineage,seconds)
                from .freeze import git
                self.session.event('CAMPAIGN_STARTED',{'campaign_id':campaign_id,'lineage_id':lineage,'campaign_seconds':int(seconds),'commit':git(self.root,'rev-parse','HEAD')})
                if self.ended(self.finish(campaign_id,lineage,*self.supervise(campaign_id,lineage))):return self.session.state_view()['stopped']


def status(state,session_id):
    """Pure session inspection: contract, journal fold, heartbeat age and the running campaign's recovery class."""
    session=SessionStore(state,session_id);view=session.state_view();path=session.root/'heartbeat.json'
    try:beat=json.loads(path.read_bytes())if path.exists()else None
    except ValueError:beat=None
    age=interval(beat['clock'],stamp())[0]if beat else None
    return {'contract':session.read(),'state':view,'heartbeat':beat,'heartbeat_age_s':age,
            'supervisor_alive':bool(beat and alive(beat['supervisor_pid'])),
            'running_campaign':inspect_campaign(state,view['running'])if view['running']else None,
            'telemetry_last':(Telemetry(session.root/'telemetry').samples()or[None])[-1],'inspection':'READ_ONLY_NO_LOCK_NO_REPAIR'}
