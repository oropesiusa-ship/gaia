"""Linux-only child ownership boundary for a dedicated, single-controller runtime.

No campaign policy changes: subreaping closes the sampling race when descendants
setsid/double-fork and outlive the controller. Never use in a shared worker process.
"""
import ctypes
import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager

from gaia.autonomy.supervisor import processes,proc_info

PR_SET_CHILD_SUBREAPER=36
PR_GET_CHILD_SUBREAPER=37


@contextmanager
def cleanup_signals_blocked():
    """A second ordinary stop signal must not interrupt child draining/restoration."""
    previous=signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGINT,signal.SIGTERM,signal.SIGHUP})
    try:yield
    finally:signal.pthread_sigmask(signal.SIG_SETMASK,previous)


def subreaper(value=None):
    libc=ctypes.CDLL(None,use_errno=True)
    if value is None:
        result=ctypes.c_int()
        rc=libc.prctl(PR_GET_CHILD_SUBREAPER,ctypes.byref(result),0,0,0)
        answer=result.value
    else:
        rc=libc.prctl(PR_SET_CHILD_SUBREAPER,int(value),0,0,0);answer=int(value)
    if rc!=0:raise OSError(ctypes.get_errno(),'PRCTL_SUBREAPER_FAILED')
    return answer


class ChildBoundary:
    """All new direct children belong to this *dedicated* process, not a PGID.

    Baseline children are refused, never adopted or signalled. During an active
    controller epoch no unrelated asynchronous subprocess may be launched. Synchronous
    git/sensor probes must be waited before calling collect(). pidfds pin signal
    targets; start times are checked before opening them. Kernel waitid(ECHILD), not
    an empty /proc sample, is the final proof that no adopted child remains.
    """
    def __init__(self,record=lambda event:None):
        self.recorder=record;self.record_error=None;self.pid=os.getpid();self.previous=None;self.enabled=False
        self.controller=None;self.owned={};self.fds={};self.active=False
        self.last_signalled={}

    def record(self,event):
        # Evidence failure must prevent launch, but must never prevent signalling
        # and reaping an already-owned tree (e.g. a full evidence filesystem).
        if self.record_error is not None:return
        try:self.recorder(event)
        except BaseException as exc:self.record_error=f'{type(exc).__name__}: {exc}'

    def direct(self):
        return {pid:info for pid,info in processes().items()if info[0]==self.pid}

    def kernel_empty(self):
        try:os.waitid(os.P_ALL,0,os.WEXITED|os.WNOHANG|os.WNOWAIT)
        except ChildProcessError:return True
        return False

    def verify(self):
        if os.getpid()!=self.pid or not self.enabled or subreaper()!=1:
            raise RuntimeError('SUBREAPER_BOUNDARY_LOST')
        if threading.active_count()!=1:raise RuntimeError('DEDICATED_RUNTIME_THREADS_REQUIRED')

    def __enter__(self):
        if threading.active_count()!=1:raise RuntimeError('DEDICATED_RUNTIME_THREADS_REQUIRED')
        if not hasattr(os,'pidfd_open')or not hasattr(signal,'pidfd_send_signal')or not hasattr(os,'WNOWAIT'):
            raise RuntimeError('LINUX_PIDFD_WAITID_REQUIRED')
        self.previous=subreaper();baseline=self.direct()
        self.record({'kind':'SUBREAPER_BASELINE','pid':self.pid,'previous':self.previous,'direct_children':baseline})
        if self.record_error is not None:raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:'+self.record_error)
        if baseline or not self.kernel_empty():raise RuntimeError('UNEXPECTED_BASELINE_CHILDREN')
        try:
            subreaper(1);self.enabled=True
            self.verify()
            if self.direct()or not self.kernel_empty():raise RuntimeError('UNEXPECTED_BOUNDARY_CHILDREN')
        except BaseException:
            subreaper(self.previous);self.enabled=False
            if subreaper()!=self.previous:raise RuntimeError('SUBREAPER_RESTORE_FAILED')
            raise
        self.record({'kind':'SUBREAPER_ENABLED','pid':self.pid,'verified':True})
        if self.record_error is not None:
            subreaper(self.previous);self.enabled=False
            if subreaper()!=self.previous:raise RuntimeError('SUBREAPER_RESTORE_FAILED')
            raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:'+self.record_error)
        return self

    def begin(self):
        self.verify()
        if self.record_error is not None:raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:'+self.record_error)
        if self.active or self.direct()or not self.kernel_empty():raise RuntimeError('UNEXPECTED_CHILD_BEFORE_CONTROLLER')
        self.owned={};self.last_signalled={};self.controller=None;self.active=True

    def attach(self,proc):
        self.verify()
        if not self.active or self.controller is not None or not isinstance(proc,subprocess.Popen):
            raise RuntimeError('CONTROLLER_BOUNDARY_MISMATCH')
        self.controller=proc
        # A rapid controller may already be a zombie, with adopted children present.
        self.collect()
        if self.record_error is not None:raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:'+self.record_error)

    def collect(self):
        self.verify()
        if not self.active:
            if self.direct()or not self.kernel_empty():raise RuntimeError('UNEXPECTED_IDLE_CHILDREN')
            return []
        table=processes();pending=[self.pid];seen=set()
        me=proc_info(self.pid)
        if me is None:raise RuntimeError('SUBREAPER_IDENTITY_UNAVAILABLE')
        verified_start={self.pid:me[7]}
        while pending:
            parent=pending.pop()
            for pid,info in table.items():
                if info[0]!=parent or pid in seen or info[7]<verified_start[parent]:continue
                old=self.owned.get(pid)
                if old and old['starttime']==info[7]and pid in self.fds:
                    current=proc_info(pid)
                    if current is None or current[7]!=info[7]or current[0]not in (parent,self.pid):continue
                    seen.add(pid);pending.append(pid);verified_start[pid]=info[7]
                    if (old['ppid'],old['pgid'],old['sid'])!=(info[0],info[1],info[2]):
                        self.record({'kind':'CHILD_REPARENTED_OR_DETACHED','pid':pid,'starttime':info[7],
                                     'ppid':info[0],'pgid':info[1],'sid':info[2]})
                    old.update(ppid=info[0],pgid=info[1],sid=info[2],state=info[6])
                    continue
                try:fd=os.pidfd_open(pid,0)
                except ProcessLookupError:continue
                current=proc_info(pid)
                if current is None or current[7]!=info[7]or current[0]not in (parent,self.pid):os.close(fd);continue
                # Only a verified edge may seed further traversal. A stale /proc
                # parent PID must not grant authority over a reused PID's children.
                seen.add(pid);pending.append(pid);verified_start[pid]=info[7]
                # Pin only processes whose sampled ancestry reached this boundary.
                if pid in self.fds:os.close(self.fds.pop(pid))
                descriptor=os.fstat(fd)
                row={'pid':pid,'starttime':info[7],'ppid':info[0],'pgid':info[1],
                     'sid':info[2],'state':info[6],'role':'OWNED_CHILD',
                     'pidfd':fd,'pidfd_identity':[descriptor.st_dev,descriptor.st_ino],
                     'custodian_pid':self.pid,'custodian_starttime':me[7]}
                self.owned[pid]=row;self.fds[pid]=fd
                self.record({'kind':'CHILD_CAPTURED',**row})
        # Do not retain pidfds for already-reaped processes across a long campaign.
        # Historical identities remain in owned/evidence, never in signal authority.
        for pid,fd in list(self.fds.items()):
            info=proc_info(pid)
            if info is None or info[7]!=self.owned[pid]['starttime']:
                os.close(fd);del self.fds[pid]
        return list(self.owned.values())

    def _reap(self):
        if self.controller is not None:self.controller.poll()
        for pid,row in list(self.owned.items()):
            if self.controller is not None and pid==self.controller.pid:continue
            info=proc_info(pid)
            if info is not None and info[0]==self.pid and info[7]==row['starttime']:
                try:
                    reaped,status=os.waitpid(pid,os.WNOHANG)
                    if reaped:self.record({'kind':'CHILD_REAPED','pid':pid,'starttime':row['starttime'],'status':status})
                except ChildProcessError:pass

    def empty(self):
        self.collect();self._reap()
        try:
            os.waitid(os.P_ALL,0,os.WEXITED|os.WNOHANG|os.WNOWAIT)
        except ChildProcessError:
            # No direct children in the kernel: no live orphan can still reparent
            # through a direct ancestor. Also check pinned descendants defensively.
            for pid,row in self.owned.items():
                info=proc_info(pid)
                if info is not None and info[7]==row['starttime']:return False
            return True
        return False

    def drain(self,grace=2):
        with cleanup_signals_blocked():return self._drain(grace)

    def _drain(self,grace):
        self.verify()
        if not self.active:
            if self.direct()or not self.kernel_empty():raise RuntimeError('UNEXPECTED_IDLE_CHILDREN')
            return []
        self.collect();before=list(self.owned.values())
        # Preserve the boundary snapshot before the first signal, including new
        # adoptees discovered after each signal. Repeated scans catch fork races.
        self.record({'kind':'PRE_CLEANUP','children':before})
        sent=set()
        for sig in (signal.SIGTERM,signal.SIGKILL):
            deadline=time.monotonic()+grace
            while True:
                self.collect()
                for pid,fd in list(self.fds.items()):
                    info=proc_info(pid);row=self.owned[pid]
                    if info is None or info[7]!=row['starttime']or info[6]=='Z':continue
                    key=(pid,row['starttime'],sig)
                    if key in sent:continue
                    try:
                        signal.pidfd_send_signal(fd,sig)
                        sent.add(key)
                        self.last_signalled[pid]=dict(row)
                        self.record({'kind':'CHILD_SIGNALLED','pid':pid,'starttime':row['starttime'],'signal':int(sig)})
                    except ProcessLookupError:pass
                if self.empty():
                    captured=list(self.owned.values());self.active=False;self.controller=None
                    for fd in self.fds.values():os.close(fd)
                    self.fds={}
                    self.record({'kind':'CLEANUP_DRAINED','children':captured,'kernel_echild':True})
                    return captured
                if time.monotonic()>=deadline:break
                time.sleep(.01)
        self.record({'kind':'CLEANUP_FAILED','children':list(self.owned.values()),'direct_children':self.direct()})
        raise RuntimeError('SUBREAPER_CHILDREN_SURVIVED_CLEANUP')

    def __exit__(self,typ,value,tb):
        with cleanup_signals_blocked():self._exit()

    def _exit(self):
        # Do not disable adoption while a child remains: fail closed, no next epoch.
        unexpected=not self.active and bool(self.direct())
        if not self.active and not self.kernel_empty():unexpected=True;self.active=True
        if self.active:self.drain()
        self.verify()
        if self.direct()or not self.kernel_empty():raise RuntimeError('SUBREAPER_RESTORE_WITH_CHILDREN_REFUSED')
        subreaper(self.previous)
        if subreaper()!=self.previous:raise RuntimeError('SUBREAPER_RESTORE_FAILED')
        self.enabled=False
        self.record({'kind':'SUBREAPER_RESTORED','value':self.previous,'verified':True})
        if unexpected:raise RuntimeError('UNEXPECTED_IDLE_CHILDREN_CLEANED')
        if self.record_error is not None:raise RuntimeError('SUBREAPER_EVIDENCE_FAILED:'+self.record_error)
