"""Stage2-only adapter instrumentation. Never deletes or adopts scratch.

Every allocation belongs to a fresh attempt/backend-work, never the backend's
historical work directory. Historical scratch is irrelevant to this operational
scope and remains untouched, not adopted. Terminal directories are retained.
Direct gaia.py invocations are deliberately outside this guarantee.
"""
import hashlib
import json
import os
import time
import uuid
import sys
from pathlib import Path
from contextlib import contextmanager
from types import SimpleNamespace
from gaia.autonomy.supervisor import proc_info


def safe(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('SCRATCH_SYMLINK')
    return path


def durable_directory(path):
    path=safe(path)
    if path!=path.parent:durable_directory(path.parent)
    if not path.exists():
        path.mkdir()
    # Publish both newly created and previously non-fsynced ancestors before
    # a CREATE_INTENT can be acknowledged.
    for directory in (path,path.parent):
        fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def identity(pid):
    row=proc_info(pid)
    if row is None:raise ValueError('SCRATCH_PROCESS_IDENTITY_UNAVAILABLE')
    return {'pid':pid,'start_time':row[7],
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def directory_identity(path):
    path=safe(path)
    if path!=path.resolve() or not path.is_dir():raise ValueError('SCRATCH_ROOT_INVALID')
    info=path.stat()
    return {'device':info.st_dev,'inode':info.st_ino}


def check_scratch_root(path,expected,*,empty=False):
    path=safe(path)
    if directory_identity(path)!=expected:raise ValueError('SCRATCH_ROOT_REPLACED')
    if empty and any(path.iterdir()):raise ValueError('OPERATIONAL_BACKEND_SCRATCH_BUSY')
    return path


class Lifecycle:
    """Append evidence with a durable pending latch.

    A journal is not admissible while its .pending sibling exists, even if
    every visible row parses. Never repair/truncate a failed append here.
    """
    def __init__(self,journal,session,campaign,scratch_root,scratch_identity):
        self.scratch_root=check_scratch_root(scratch_root,scratch_identity)
        self.scratch_identity=dict(scratch_identity)
        self.journal=safe(journal)
        if self.journal.is_relative_to(self.scratch_root):raise ValueError('JOURNAL_INSIDE_SCRATCH')
        durable_directory(self.journal.parent)
        self.pending=safe(self.journal.with_name(self.journal.name+'.pending'))
        self.failed=False
        if self.pending.exists():raise ValueError('SCRATCH_JOURNAL_UNRESOLVED')
        if self.journal.exists():
            data=self.journal.read_bytes()
            if data and not data.endswith(b'\n'):raise ValueError('SCRATCH_JOURNAL_PARTIAL_ROW')
            for line in data.splitlines():
                if not isinstance(json.loads(line),dict):raise ValueError('SCRATCH_JOURNAL_INVALID_ROW')
        self.context={'session_id':session,'campaign_id':campaign,'owner':identity(os.getpid()),
                      'scratch_root':str(self.scratch_root),'scratch_identity':self.scratch_identity}

    def event(self,kind,work,**fields):
        if self.failed:raise ValueError('SCRATCH_JOURNAL_UNRESOLVED')
        try:return self._append(kind,work,**fields)
        except BaseException:
            self.failed=True
            raise

    def sync_directory(self):
        fd=os.open(self.journal.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)

    def _append(self,kind,work,**fields):
        check_scratch_root(self.scratch_root,self.scratch_identity)
        work=safe(work)
        if work.parent!=self.scratch_root or not work.name.startswith('inference-'):
            raise ValueError('SCRATCH_OUTSIDE_OPERATIONAL_ROOT')
        if self.journal.is_relative_to(work):raise ValueError('JOURNAL_INSIDE_SCRATCH')
        record={**self.context,'event':kind,'work':str(work),
                'wall_time_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),**fields}
        # An interrupted/failed append must block reopening even when a full
        # success-looking row reached page cache but its fsync failed.
        fd=os.open(safe(self.pending),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:os.fsync(fd)
        finally:os.close(fd)
        self.sync_directory()
        fd=os.open(safe(self.journal),os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        try:
            data=(json.dumps(record,sort_keys=True)+'\n').encode()
            while data:
                n=os.write(fd,data)
                if n<=0:raise OSError('SCRATCH_JOURNAL_SHORT_WRITE')
                data=data[n:]
            os.fsync(fd)
        finally:os.close(fd)
        self.sync_directory()
        self.pending.unlink()
        self.sync_directory()
        return record


@contextmanager
def instrument(lifecycle):
    """Process-local patch; creation evidence is fsynced before worker Popen.

    No subprocess arguments, environment, sandbox or authority are changed.
    A crash leaves CREATED/ACTIVE evidence unresolved, never terminal by guess.
    """
    from gaia.local_intelligence import backend as b
    cls=b.IsolatedRuntimeAdapter
    original={name:getattr(cls,name) for name in ('load','unload','close_failed')}
    tempfile_module,subprocess_module=b.tempfile,b.subprocess
    current=[]

    def event(adapter,kind,**fields):
        if getattr(adapter,'_stage2_unresolved',False):
            raise ValueError('SCRATCH_LIFECYCLE_UNRESOLVED')
        try:
            return lifecycle.event(kind,adapter._stage2_work,
                original_source_parent=adapter._stage2_source_parent,
                stack_hash=digest(adapter.stack),job_hash=adapter._stage2_job_hash,**fields)
        except BaseException:
            adapter._stage2_unresolved=True
            raise

    def failed_event(adapter,kind,exc):
        # Evidence is best-effort on an exception path, never a prerequisite
        # for cleanup and never allowed to replace the initiating exception.
        if hasattr(adapter,'_stage2_work') and not getattr(adapter,'_stage2_unresolved',False):
            try:event(adapter,kind,error=repr(exc),state='UNRESOLVED_RETAINED')
            except BaseException as evidence_error:
                exc.add_note('Stage2 failure evidence unavailable: '+repr(evidence_error))

    def cleanup(adapter,exc):
        try:original['close_failed'](adapter)
        except BaseException as cleanup_error:
            adapter._stage2_unresolved=True
            exc.add_note('Stage2 adapter cleanup failed: '+repr(cleanup_error))

    def create(*args,**kwargs):
        if not current or kwargs.get('prefix')!='inference-':
            raise ValueError('UNBOUND_STAGE2_SCRATCH_CREATION')
        adapter=current[-1]
        parent=check_scratch_root(lifecycle.scratch_root,lifecycle.scratch_identity)
        if safe(kwargs['dir'])!=parent:raise ValueError('UNBOUND_STAGE2_SCRATCH_PARENT')
        work=parent/('inference-'+uuid.uuid4().hex)
        job={**{k:adapter.stack[k] for k in ('runtime','threads','context','backend','gpu_layers','kv')},
             'interactive':True,'tasks':[],'ram_budget':adapter.budget['worker_ram_bytes'],
             'load_timeout':adapter.budget['smoke_timeout_seconds'],
             'private_disk_budget_bytes':min(2*2**30,adapter.budget['disk_budget_bytes']//4)}
        if adapter.stack.get('support_id'):job['tokenizer']='/support/tokenizer.json'
        job_hash=hashlib.sha256(json.dumps(job).encode()).hexdigest()
        adapter._stage2_job_hash=job_hash
        # Intent precedes mkdir: even interruption at the allocation boundary
        # leaves an externally durable owner binding, never anonymous scratch.
        lifecycle.event('CREATE_INTENT',work,stack_hash=digest(adapter.stack),
                        job_hash=job_hash,original_source_parent=adapter._stage2_source_parent,state='RESERVED')
        os.mkdir(work,0o700)
        adapter._stage2_work=work
        fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        record=lifecycle.event('CREATED',work,stack_hash=digest(adapter.stack),
                               job_hash=job_hash,original_source_parent=adapter._stage2_source_parent,state='OWNED_PENDING_JOB')
        fd=os.open(work/'stage2-owner.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(record,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
        fd=os.open(work,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)
        return str(work)

    def popen(*args,**kwargs):
        adapter=current[-1];work=adapter._stage2_work
        job_path=safe(work/'job.json')
        with job_path.open('rb') as stream:
            job=stream.read();os.fsync(stream.fileno())
        fd=os.open(work,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(fd)
        finally:os.close(fd)
        if hashlib.sha256(job).hexdigest()!=adapter._stage2_job_hash:
            raise ValueError('STAGE2_JOB_CHANGED_BEFORE_LAUNCH')
        lifecycle.event('LAUNCH_INTENT',work,job_hash=hashlib.sha256(job).hexdigest(),
                        stack_hash=digest(adapter.stack),original_source_parent=adapter._stage2_source_parent,state='ACTIVE')
        proc=subprocess_module.Popen(*args,**kwargs)
        # Save before journaling so adapter failure handling can still stop it.
        adapter.process=proc
        event(adapter,'CHILD',child=identity(proc.pid),state='ACTIVE')
        return proc

    def load(adapter):
        source_state=adapter.state
        adapter._stage2_source_parent=str(source_state.absolute()/'work')
        # Only the /work path operation is redirected. This prevents the
        # original parent.mkdir from creating or touching historical work,
        # even when that original directory is absent. Artifact paths and
        # all qualification/hash checks still use the original state.
        class OperationalState(type(Path())):
            def __truediv__(self,key):
                if self==source_state and str(key)=='work':return lifecycle.scratch_root
                return super().__truediv__(key)
        current.append(adapter)
        try:
            check_scratch_root(lifecycle.scratch_root,lifecycle.scratch_identity)
            adapter.state=OperationalState(source_state)
            result=original['load'](adapter)
            event(adapter,'LOADED',state='ACTIVE')
            return result
        except BaseException as exc:
            cleanup(adapter,exc)
            failed_event(adapter,'LOAD_FAILED',exc)
            adapter._stage2_unresolved=True
            raise
        finally:
            adapter.state=source_state
            current.pop()

    def close(adapter):
        primary=sys.exc_info()[1]
        try:result=original['close_failed'](adapter)
        except BaseException as exc:
            failed_event(adapter,'RELEASE_FAILED',exc)
            adapter._stage2_unresolved=True
            if primary is not None:
                primary.add_note('Stage2 adapter cleanup failed: '+repr(exc))
                return None
            raise
        if hasattr(adapter,'_stage2_work'):
            if primary is None and not getattr(adapter,'_stage2_unresolved',False):
                try:event(adapter,'RELEASED',state='TERMINAL_RETAINED')
                except BaseException as exc:
                    if primary is None:raise
                    primary.add_note('Stage2 release evidence unavailable: '+repr(exc))
        return result

    def unload(adapter):
        try:result=original['unload'](adapter)
        except BaseException as exc:
            cleanup(adapter,exc)
            failed_event(adapter,'UNLOAD_FAILED',exc)
            adapter._stage2_unresolved=True
            raise
        if hasattr(adapter,'_stage2_work'):
            event(adapter,'UNLOADED',state='TERMINAL_RETAINED_SUCCESS')
        return result

    b.tempfile=SimpleNamespace(mkdtemp=create)
    b.subprocess=SimpleNamespace(**{k:getattr(subprocess_module,k) for k in ('PIPE',)},Popen=popen)
    cls.load,cls.unload,cls.close_failed=load,unload,close
    try:
        yield
        # The campaign may catch backend errors. A swallowed journal failure
        # must nevertheless make the administrative entrypoint fail closed.
        if lifecycle.failed:raise ValueError('SCRATCH_JOURNAL_UNRESOLVED')
    finally:
        b.tempfile,b.subprocess=tempfile_module,subprocess_module
        for name,method in original.items():setattr(cls,name,method)
