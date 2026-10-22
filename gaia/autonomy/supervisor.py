"""Endurance supervisor (1.1 §1): one long-lived process driving a session's campaigns as child process groups.

It checks liveness from the outside, detects hangs from journal progress, identifies and stops only its own
processes, preserves evidence before any cleanup and relaunches a campaign only when the read-only inspection
classifies it RECOVERABLE. It never edits campaign or lineage state: campaigns recover through their own run()."""
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
from .session import SessionStore,budget
from .store import CampaignStore,durable
from .telemetry import Telemetry,storage_by_owner,filesystem,gates,bound_log

ROLES=(('gaia.autonomy.regression','MATRIX'),('autonomy-run','CONTROLLER'),('runtime_worker','BACKEND'),('koboldcpp','BACKEND'),
       ('llama','BACKEND'),('bwrap','WORKER'),('worker','WORKER'))
TERMINATE_GRACE_S=30


def proc_info(pid):
    """(ppid, pgid, sid, rss_bytes, fds, cmdline) of a live process, or None."""
    try:
        stat=Path(f'/proc/{pid}/stat').read_text();fields=stat[stat.rindex(')')+2:].split()
        cmd=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace').strip()
        rss=int(fields[21])*os.sysconf('SC_PAGE_SIZE')
        try:fds=len(os.listdir(f'/proc/{pid}/fd'))
        except OSError:fds=None
        return int(fields[1]),int(fields[2]),int(fields[3]),rss,fds,cmd
    except (OSError,ValueError,IndexError):return None


def role(cmd):return next((r for token,r in ROLES if token in cmd),'OTHER')


def tree(root_pid):
    """The live descendants of root_pid (any session or group), classified by role."""
    children={}
    for entry in os.listdir('/proc'):
        if entry.isdigit():
            info=proc_info(int(entry))
            if info:children.setdefault(info[0],[]).append((int(entry),info))
    rows=[];pending=[root_pid];top=proc_info(root_pid)
    if top:rows.append((root_pid,top))
    while pending:
        for pid,info in children.get(pending.pop(),[]):rows.append((pid,info));pending.append(pid)
    return [{'pid':pid,'ppid':i[0],'pgid':i[1],'sid':i[2],'rss_bytes':i[3],'fds':i[4],'role':role(i[5]),'cmd':i[5][:200]}for pid,i in rows]


def alive(pid):return proc_info(pid)is not None


class Adopted:
    """A campaign controller left running by a previous supervisor (its own process group, reparented): polled, not waited."""
    def __init__(self,pid):self.pid=pid;self.returncode=None
    def poll(self):
        if self.returncode is None and not alive(self.pid):self.returncode=-1
        return self.returncode


class Supervisor:
    def __init__(self,root,state,session_id,*,launch=None,create=None,sleep=time.sleep):
        self.root=Path(root);self.state=Path(state);self.session=SessionStore(state,session_id);self.contract=self.session.read()
        self.launch=launch or self.launch_run;self.create=create or self.create_campaign;self.sleep=sleep;self.cursor=0
        self.telemetry=Telemetry(self.session.root/'telemetry');self.sampled=None

    # ------------------------------------------------------------------ process control
    def launch_run(self,campaign_id):
        logs=self.session.root/'logs';logs.mkdir(exist_ok=True)
        out=(logs/f'{campaign_id}.out').open('ab');err=(logs/f'{campaign_id}.err').open('ab')
        try:
            return subprocess.Popen([sys.executable,'-B',str(self.root/'gaia.py'),'autonomy-run',campaign_id,'--state-dir',str(self.state),'--authorize-campaign'],
                cwd=self.root,stdout=out,stderr=err,stdin=subprocess.DEVNULL,start_new_session=True,
                env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        finally:out.close();err.close()

    def terminate(self,proc,snapshot):
        """Stop only this campaign's process group and the descendants seen in the evidence snapshot."""
        mine={row['pid']for row in snapshot}|{proc.pid}
        for sig in (signal.SIGTERM,signal.SIGKILL):
            try:os.killpg(proc.pid,sig)
            except ProcessLookupError:pass
            for pid in mine-{proc.pid}:
                info=proc_info(pid)
                if info and info[1]!=proc.pid:
                    try:os.kill(pid,sig)
                    except ProcessLookupError:pass
            deadline=time.monotonic()+TERMINATE_GRACE_S
            while time.monotonic()<deadline and proc.poll()is None:self.sleep(.2)
            if proc.poll()is not None and not any(alive(p)for p in mine-{proc.pid}):break
        return proc.poll()

    # ------------------------------------------------------------------ campaigns
    def create_campaign(self,lineage_id,seconds):
        from .controller import create_campaign
        from .schema import campaign
        lineage=LineageStore(self.state,lineage_id).read()
        c=campaign(lineage['objective'],mode=self.contract['mode'],promotion=self.contract['allow_promotion'],lineage_id=lineage_id,
                   limits={'maximum_wall_time':int(seconds),'maximum_compute_budget':int(seconds)})
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

    def last_heartbeat(self):
        path=self.session.root/'heartbeat.json'
        return json.loads(path.read_bytes())if path.exists()else None

    def control(self):
        path=self.session.root/'control.json'
        return json.loads(path.read_bytes())['request']if path.exists()else'RUN'

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

    def watch(self,proc,campaign_id):
        """Poll until the child exits or stops progressing; heartbeat each period. Returns how it ended."""
        limits=self.contract['limits'];last=None;progress=time.monotonic();stop_sent=False
        while proc.poll()is None:
            info=inspect_campaign(self.state,campaign_id);snapshot=tree(proc.pid)
            if info.get('events')!=last:last=info.get('events');progress=time.monotonic()
            idle=time.monotonic()-progress
            sample=dict(campaign_id=campaign_id,child_pid=proc.pid,phase=info.get('phase'),events=info.get('events'),seconds_without_progress=idle,
                processes={r:sum(1 for x in snapshot if x['role']==r)for r in sorted({x['role']for x in snapshot})},
                child_rss_bytes=sum(x['rss_bytes']for x in snapshot),child_fds=sum(x['fds']or 0 for x in snapshot),
                controller_alive=any(x['role']=='CONTROLLER'for x in snapshot)or proc.poll()is None,
                backend_processes=sum(1 for x in snapshot if x['role']=='BACKEND'))
            self.heartbeat(**sample);self.telemetry.append({'kind':'PROCESS',**sample,'supervisor_rss_bytes':(proc_info(os.getpid())or(0,0,0,0))[3]})
            storage=None
            if self.sampled is None or time.monotonic()-self.sampled>=self.contract['limits']['storage_sample_s']:storage=self.storage_check(campaign_id)
            if storage and not stop_sent:
                # A storage gate stops the campaign at its next safe boundary; the session then stops.
                CampaignStore(self.state,campaign_id).control('STOP');stop_sent=True
                if not self.session.state_view()['stop_requested']:self.session.event('STOP_REQUESTED',{'campaign_id':campaign_id,'reason':storage})
            if self.control()=='STOP'and not stop_sent:
                CampaignStore(self.state,campaign_id).control('STOP');stop_sent=True
                if not self.session.state_view()['stop_requested']:self.session.event('STOP_REQUESTED',{'campaign_id':campaign_id})
            if idle>limits['hang_timeout_s']:
                evidence=self.session.root/'evidence'/f'{campaign_id}-hang-{int(time.time())}.json'
                durable(evidence,{'campaign_id':campaign_id,'inspection':info,'processes':snapshot,'clock':stamp(),'seconds_without_progress':idle})
                self.session.event('HANG_DETECTED',{'campaign_id':campaign_id,'seconds_without_progress':idle,'evidence':evidence.name,
                    'processes':len(snapshot)})
                code=self.terminate(proc,snapshot)
                self.session.event('CHILD_EXITED',{'campaign_id':campaign_id,'returncode':code,'cause':'TERMINATED_AFTER_HANG'})
                return 'HANG'
            self.sleep(limits['heartbeat_s'])
        self.session.event('CHILD_EXITED',{'campaign_id':campaign_id,'returncode':proc.returncode,'cause':'EXITED'})
        for name in ('out','err'):bound_log(self.session.root/'logs'/f'{campaign_id}.{name}')
        return 'EXITED'

    def supervise(self,campaign_id,lineage_id,adopted=None):
        relaunches=0
        while True:
            proc=adopted or self.launch(campaign_id);adopted=None;self.watch(proc,campaign_id)
            info=inspect_campaign(self.state,campaign_id);view=self.session.state_view()
            if info['recovery']=='RECOVERABLE'and relaunches<self.contract['limits']['relaunches_per_campaign']and view['restarts']<self.contract['limits']['maximum_restarts']and self.control()!='STOP':
                relaunches+=1;self.session.event('CAMPAIGN_RELAUNCHED',{'campaign_id':campaign_id,'lineage_id':lineage_id,'relaunch':relaunches,'reason':info['reason']})
                continue
            return info

    def finish(self,campaign_id,lineage_id,info):
        store=CampaignStore(self.state,campaign_id);report=None
        try:
            state=store.inspect()['state']
            if state.get('report_ref'):report=store.get(state['report_ref'])
        except (OSError,ValueError):pass
        metrics=(report or{}).get('metrics',{})
        self.session.event('CAMPAIGN_FINISHED',{'campaign_id':campaign_id,'lineage_id':lineage_id,'recovery':info['recovery'],'reason':info['reason'],
            'stopping_reason':info.get('stopping_reason'),'wall_s':metrics.get('total_wall_time'),'research_calls':metrics.get('research_calls',0),
            'experiments':metrics.get('experiments'),'report_status':(report or{}).get('status')})
        if info['recovery']!='TERMINAL_OK'and lineage_id not in self.session.state_view()['skipped']:
            self.session.event('LINEAGE_SKIPPED',{'lineage_id':lineage_id,'reason':'CAMPAIGN_'+info['recovery']})

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

    def run(self):
        with self.lock():
            view=self.session.state_view()
            if view['stopped']:return view['stopped']
            # A supervisor restart finds the campaign it was running; the campaign recovers through its own run().
            if view['running']:
                lineage=next(e['payload']['lineage_id']for e in reversed(self.session.events())if e['kind']=='CAMPAIGN_STARTED')
                beat=self.last_heartbeat();child=beat.get('child_pid')if beat and beat.get('campaign_id')==view['running']else None
                info=proc_info(child)if child else None
                adopted=Adopted(child)if info and 'autonomy-run'in info[5]and view['running']in info[5]else None
                self.finish(view['running'],lineage,self.supervise(view['running'],lineage,adopted))
            while True:
                view=self.session.state_view()
                if self.control()=='STOP'or view['stop_requested']:return self.stop('OPERATOR_STOP')
                from .freeze import changes
                changed=changes(self.root,self.state,self.contract['freeze'])
                if changed:return self.stop('PROTOCOL_CHANGED',changes=changed)
                storage=self.storage_check()
                if storage:return self.stop(storage)
                seconds,reasons=budget(self.contract,view,self.session.storage(self.root),stamp())
                if reasons:return self.stop(reasons[0],reasons=reasons)
                lineage=self.next_lineage(view)
                if lineage is None:return self.stop('NO_ELIGIBLE_LINEAGE')
                campaign_id=self.create(lineage,seconds)
                self.session.event('CAMPAIGN_STARTED',{'campaign_id':campaign_id,'lineage_id':lineage,'campaign_seconds':int(seconds)})
                self.finish(campaign_id,lineage,self.supervise(campaign_id,lineage))


def status(state,session_id):
    """Pure session inspection: contract, journal fold, heartbeat age and the running campaign's recovery class."""
    session=SessionStore(state,session_id);view=session.state_view();path=session.root/'heartbeat.json'
    beat=json.loads(path.read_bytes())if path.exists()else None
    age=interval(beat['clock'],stamp())[0]if beat else None
    return {'contract':session.read(),'state':view,'heartbeat':beat,'heartbeat_age_s':age,
            'supervisor_alive':bool(beat and alive(beat['supervisor_pid'])),
            'running_campaign':inspect_campaign(state,view['running'])if view['running']else None,
            'telemetry_last':(Telemetry(session.root/'telemetry').samples()or[None])[-1],'inspection':'READ_ONLY_NO_LOCK_NO_REPAIR'}
