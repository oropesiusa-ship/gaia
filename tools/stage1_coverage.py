"""Administrative Stage 1 scheduling and terminal replay checks; no evaluator changes."""
import hashlib
from pathlib import Path
import time

from gaia.autonomy.clock import interval
from gaia.autonomy.freeze import changes
from gaia.autonomy.lineage import engine_state_dir
from gaia.autonomy.session import SessionStore
from gaia.autonomy.supervisor import Supervisor
from gaia.autonomy.telemetry import memory,vram


def slot_deadline(started,ordinal,limits):
    """Five evenly spaced admission slots, without extending the session window."""
    return started+ordinal*limits['maximum_wall_s']/limits['maximum_campaigns']


class PacedSupervisor(Supervisor):
    """Same supervisor; idle between campaigns is actively observed and separately labelled."""
    def finish(self,campaign_id,lineage_id,*args):
        outcome=super().finish(campaign_id,lineage_id,*args)
        view=self.session.state_view()
        if outcome!='DONE'or view['finished'][-1]['recovery']!='TERMINAL_OK':return outcome
        target=slot_deadline(view['started_clock']['monotonic'],len(view['campaigns']),self.contract['limits'])
        while time.monotonic()<target:
            if self.stopping():break
            if changes(self.root,self.state,self.contract['freeze']):raise RuntimeError('IDLE_PROTOCOL_CHANGED')
            host=memory()
            if host['available_bytes']is None or host['below_reserve']:raise RuntimeError('IDLE_HOST_MEMORY_RESERVE')
            if self.storage_check():raise RuntimeError('IDLE_STORAGE_RESERVE')
            self.heartbeat(phase='SCHEDULED_IDLE',next_slot_monotonic=target)
            self.telemetry.append({'kind':'IDLE','host_memory':host,'ordinal':len(view['campaigns']),
                'next_slot_monotonic':target})
            if self.vram_sampled is None or time.monotonic()-self.vram_sampled>=self.contract['limits']['vram_sample_s']:
                self.telemetry.append({'kind':'VRAM','phase':'SCHEDULED_IDLE',**vram()});self.vram_sampled=time.monotonic()
            self.sleep(min(self.contract['limits']['heartbeat_s'],max(0.,target-time.monotonic())))
        return outcome


def inventory(paths):
    result={}
    for base in paths:
        for p in sorted(Path(base).rglob('*')):
            if p.is_symlink():raise ValueError('SYMLINK_IN_REPLAY_SCOPE')
            if p.is_file():
                with p.open('rb')as f:result[str(p)]=hashlib.file_digest(f,'sha256').hexdigest()
    return result


def terminal_replay(root,state,sid,cli):
    """Replay every terminal campaign and the stopped session, checking all owned bytes."""
    store=SessionStore(state,sid);contract=store.read();view=store.state_view()
    if not view['stopped']or view['running']:raise ValueError('SESSION_NOT_TERMINAL')
    paths=[Path(state),*[Path(root)/engine_state_dir(lin)for lin in contract['lineages']]]
    before=inventory(paths);results=[]
    for cid in view['campaigns']:
        result=cli('autonomy-run',cid,'--state-dir',str(state),'--authorize-campaign')
        results.append({'campaign_id':cid,'status':result.get('status'),'stopping_reason':result.get('stopping_reason')})
    result=cli('endurance-session-run',sid,'--state-dir',str(state))
    after=inventory(paths)
    return {'status':'PASS'if before==after and len(results)==len(view['finished'])else'FAIL',
            'files_before':len(before),'files_after':len(after),'campaigns':results,'session_result':result,
            'changed_paths':[p for p in sorted(before.keys()|after.keys())if before.get(p)!=after.get(p)]}


def window_coverage(store):
    from gaia.autonomy.telemetry import Telemetry
    view=store.state_view();events=store.events();start=view['started_clock']
    end=events[-1]['clock'];duration,reboot=interval(start,end)
    rows=Telemetry(store.root/'telemetry').samples()
    clocks=[start,*[r['clock']for r in rows if r['kind']in ('PROCESS','IDLE')],end]
    clocks=sorted(clocks,key=lambda c:c['monotonic'])
    largest=max((b['monotonic']-a['monotonic']for a,b in zip(clocks,clocks[1:])),default=duration)
    same_boot=not reboot and all(c.get('boot_id')==start.get('boot_id')for c in clocks)
    required=store.read()['limits']['maximum_wall_s']
    passed=duration>=required and same_boot and largest<25 and all(c['monotonic']<=end['monotonic']for c in clocks)
    return {'status':'PASS'if passed else'FAIL','observed_wall_s':duration,'largest_observation_gap_s':largest,
            'same_boot':same_boot,'scheduled_idle_samples':sum(r['kind']=='IDLE'for r in rows),
            'campaign_compute_s':view['compute_s'],'scope':'REAL_WALL_WINDOW_ACTIVE_AND_SCHEDULED_IDLE_NOT_CONTINUOUS_EXPERIMENTATION'}
