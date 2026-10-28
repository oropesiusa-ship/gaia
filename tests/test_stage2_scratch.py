"""Disposable filesystem and real child fixtures; no campaign/model execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch,Mock
from gaia.local_intelligence import backend as b
from tools.stage2_scratch import Lifecycle,instrument,check_scratch_root
from tools.stage2_executor import scratch_plan,operational_scratch,ADMIN_FILES


class ScratchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.state=self.root/'backend';self.state.mkdir()
        binary=self.state/'runtimes'/'fixture'/'koboldcpp';binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture')
        h=hashlib.sha256(b'fixture').hexdigest()
        model=self.state/'artifacts'/h;model.parent.mkdir();model.write_bytes(b'fixture')
        self.stack=dict(runtime='koboldcpp',backend='CPU',runtime_install='fixture',runtime_hash=h,model_hash=h,
                        context=256,threads=1,gpu_layers=0,kv='f16',model_family='qwen3')
        self.budget=dict(max_context=256,threads=1,benchmark_timeout_seconds=15,worker_ram_bytes=2**28,
                         smoke_timeout_seconds=2,disk_budget_bytes=2**24)
        self.plan=scratch_plan(self.root);self.scratch=Path(self.plan['scratch_root'])
        self.life=self.new_lifecycle(self.root/'evidence'/'journal.jsonl','session-fixture','campaign-fixture')

    def new_lifecycle(self,journal,session,campaign):
        return Lifecycle(journal,session,campaign,self.scratch,self.plan['scratch_identity'])

    def rows(self):return [json.loads(s) for s in self.life.journal.read_text().splitlines()]

    def test_creation_active_release_real_child_and_authority(self):
        historical=self.state/'work';historical.mkdir()
        old=historical/'inference-historical';old.mkdir();(old/'retain.txt').write_text('historical scratch')
        def history():
            return {str(p):(p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns)
                    for p in (historical,*historical.rglob('*'))}
        before=history()
        code="import json,sys; print(json.dumps({'status':'READY','load_s':0,'security':{'network_namespace':-1,'pid_namespace':-1,'host_home_visible':False,'root_read_only':True,'runtime_read_only':True,'model_read_only':True}}),flush=True); sys.stdin.readline(); print('{}',flush=True)"
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        real_popen=subprocess.Popen;seen=[]
        def spawn(*args,**kwargs):
            rows=self.rows();self.assertEqual(rows[-1]['event'],'LAUNCH_INTENT')
            owner=json.loads((adapter.work/'stage2-owner.json').read_text())
            self.assertEqual(owner['owner']['pid'],os.getpid())
            self.assertEqual(owner['campaign_id'],'campaign-fixture')
            seen.append((args,kwargs))
            return real_popen(*args,**kwargs)
        command=[sys.executable,'-u','-c',code]
        with patch.object(b,'command',return_value=command),patch.object(b,'limits',return_value=None),patch.object(subprocess,'Popen',side_effect=spawn):
            # Capture the unpatched callable separately: the instrumentation keeps
            # the original module object, but our fixture spy is intentional.
            with instrument(self.life):
                adapter.load()
                self.assertEqual(self.rows()[-1]['state'],'ACTIVE')
                adapter.unload()
        rows=self.rows()
        self.assertEqual(rows[-1]['state'],'TERMINAL_RETAINED_SUCCESS')
        self.assertTrue(adapter.work.exists())
        self.assertEqual(seen[0][0][0],command)
        self.assertEqual(seen[0][1]['env']['HOME'],'/work')
        self.assertEqual(seen[0][1]['env']['HF_HUB_OFFLINE'],'1')
        child=next(r['child'] for r in rows if r['event']=='CHILD')
        self.assertIsNotNone(child['start_time']);self.assertTrue(child['boot_id'])
        self.assertEqual(rows[0]['stack_hash'],hashlib.sha256(json.dumps(self.stack,sort_keys=True).encode()).hexdigest())
        self.assertEqual(next(r['job_hash'] for r in rows if r['event']=='LAUNCH_INTENT'),hashlib.sha256((adapter.work/'job.json').read_bytes()).hexdigest())
        for row in rows:
            for key in ('session_id','campaign_id','owner','work','stack_hash','job_hash','wall_time_ns','monotonic_ns','state','original_source_parent','scratch_root','scratch_identity'):
                self.assertIn(key,row)
            self.assertEqual(row['job_hash'],rows[0]['job_hash'])
            self.assertEqual(row['stack_hash'],rows[0]['stack_hash'])
            self.assertIsInstance(row['owner']['start_time'],int)
            self.assertTrue(row['owner']['boot_id'])
            self.assertEqual(row['original_source_parent'],str(self.state/'work'))
            self.assertEqual(Path(row['work']).parent,self.scratch)
        self.assertEqual(history(),before)
        self.assertEqual((old/'retain.txt').read_text(),'historical scratch')
        self.assertEqual(adapter.state,self.state)
        self.assertEqual(adapter.stack,self.stack)

    def test_load_failure_retains_creation(self):
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        with patch.object(b,'command',side_effect=ValueError('fixture launch failure')):
            with instrument(self.life):
                with self.assertRaises(ValueError):adapter.load()
        self.assertEqual([r['event'] for r in self.rows()],['CREATE_INTENT','CREATED','LOAD_FAILED'])
        self.assertTrue((adapter.work/'stage2-owner.json').exists())

    def test_evidence_failure_prevents_creation_and_worker(self):
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        with patch.object(self.life,'event',side_effect=OSError('fixture fsync failure')),patch.object(subprocess,'Popen') as spawn:
            with instrument(self.life):
                with self.assertRaises(OSError):adapter.load()
        spawn.assert_not_called()
        self.assertEqual(list(self.scratch.iterdir()),[])
        self.assertFalse((self.state/'work').exists())

    def test_operational_work_symlink_prevents_creation(self):
        outside=self.root/'outside';outside.mkdir()
        self.scratch.rename(self.root/'original-root')
        self.scratch.symlink_to(outside)
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        with instrument(self.life):
            with self.assertRaisesRegex(ValueError,'SYMLINK'):adapter.load()
        self.assertEqual(list(outside.iterdir()),[])

    def test_replaced_operational_root_prevents_creation(self):
        self.scratch.rename(self.root/'original-root');self.scratch.mkdir()
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        with patch.object(subprocess,'Popen') as spawn:
            with instrument(self.life):
                with self.assertRaisesRegex(ValueError,'ROOT_REPLACED'):adapter.load()
        spawn.assert_not_called()
        self.assertEqual(list(self.scratch.iterdir()),[])
        self.assertFalse((self.state/'work').exists())

    def test_allocation_never_uses_historical_symlink(self):
        outside=self.root/'external-history';outside.mkdir();(outside/'data').write_text('preserve')
        history=self.state/'work';history.symlink_to(outside,target_is_directory=True)
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        with patch.object(b,'command',side_effect=ValueError('stop after allocation')):
            with instrument(self.life):
                with self.assertRaisesRegex(ValueError,'stop after allocation'):adapter.load()
        self.assertTrue(history.is_symlink())
        self.assertEqual([p.name for p in outside.iterdir()],['data'])
        self.assertEqual((outside/'data').read_text(),'preserve')
        self.assertEqual(adapter.work.parent,self.scratch)
        self.assertEqual(self.rows()[0]['original_source_parent'],str(history))

    def test_journal_rejects_event_outside_owned_operational_root(self):
        historical=self.state/'work'/'inference-historical';historical.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'OUTSIDE_OPERATIONAL_ROOT'):
            self.life.event('CREATED',historical,state='OWNED_PENDING_JOB')
        self.assertFalse(self.life.journal.exists())
        self.assertTrue(self.life.failed)

    def test_supervisor_uses_wrapper_and_original_log_boundary(self):
        from tools import stage2_runtime as rt
        from types import SimpleNamespace
        supervisor=rt.FirstSessionSupervisor.__new__(rt.FirstSessionSupervisor)
        supervisor.root=self.root;supervisor.state=self.state
        session=self.root/'session';session.mkdir();(session/'evidence').mkdir()
        supervisor.session=SimpleNamespace(root=session,identifier='session-fixture')
        supervisor.stage_contract={'plan':self.plan}
        supervisor.boundary=Mock();supervisor.guard=Mock();supervisor.now=lambda:1
        supervisor.owned={}
        proc=Mock(pid=os.getpid())
        with patch.object(rt.subprocess,'Popen',return_value=proc) as spawn:
            self.assertIs(supervisor.launch_run('campaign-fixture'),proc)
        args,kwargs=spawn.call_args
        self.assertIn('tools.stage2_campaign',args[0])
        self.assertIn('autonomy-run',args[0])
        self.assertIn(str(session/'evidence'/'scratch-lifecycle.jsonl'),args[0])
        self.assertIn('--scratch-root',args[0]);self.assertIn(str(self.scratch),args[0])
        self.assertTrue(kwargs['start_new_session'])
        self.assertTrue(kwargs['stdout'].closed);self.assertTrue(kwargs['stderr'].closed)
        self.assertTrue((session/'logs'/'campaign-fixture.out').exists())
        supervisor.boundary.attach.assert_called_once_with(proc)

    def test_release_failure_is_unresolved(self):
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        work=self.scratch/'inference-fixture';work.mkdir()
        adapter._stage2_work=work
        adapter._stage2_job_hash='f'*64
        adapter._stage2_source_parent=str(self.state/'work')
        with patch.object(b.IsolatedRuntimeAdapter,'close_failed',side_effect=OSError('fixture release')):
            with instrument(self.life):
                with self.assertRaises(OSError):adapter.close_failed()
        self.assertEqual(self.rows()[-1]['state'],'UNRESOLVED_RETAINED')
        self.assertTrue(work.exists())

    def test_real_popen_failure_preserves_original_exception(self):
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        original_event=self.life.event
        evidence_error=OSError('failure evidence unavailable')
        def record(kind,*args,**kwargs):
            if kind=='LOAD_FAILED':raise evidence_error
            return original_event(kind,*args,**kwargs)
        with patch.object(b,'command',return_value=[str(self.root/'missing-executable')]),patch.object(b,'limits',return_value=os.setsid),patch.object(self.life,'event',side_effect=record):
            with instrument(self.life):
                with self.assertRaises(FileNotFoundError) as caught:adapter.load()
                adapter.close_failed()
        self.assertIn('missing-executable',str(caught.exception))
        self.assertIsNone(adapter.process)
        self.assertTrue(adapter._stderr.closed)
        self.assertTrue(adapter._stage2_unresolved)
        self.assertFalse(any(r['state'].startswith('TERMINAL') for r in self.rows()))

    def test_job_hash_mismatch_prevents_worker_launch(self):
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        def command(*args,**kwargs):
            (adapter.work/'job.json').write_text('{"tampered":true}')
            return [sys.executable,'-c','pass']
        with patch.object(b,'command',side_effect=command),patch.object(b,'limits',return_value=None),patch.object(subprocess,'Popen') as spawn:
            with instrument(self.life):
                with self.assertRaisesRegex(ValueError,'JOB_CHANGED_BEFORE_LAUNCH'):adapter.load()
        spawn.assert_not_called()
        self.assertIsNone(adapter.process)
        self.assertTrue(adapter._stderr.closed)
        self.assertEqual(self.rows()[-1]['state'],'UNRESOLVED_RETAINED')
        self.assertFalse(any(r['state'].startswith('TERMINAL') for r in self.rows()))

    def check_live_child_journal_failure(self,kind):
        adapter=b.IsolatedRuntimeAdapter(self.stack,self.state,self.budget)
        code="import json,time; print(json.dumps({'status':'READY','load_s':0,'security':{'network_namespace':-1,'pid_namespace':-1,'host_home_visible':False,'root_read_only':True,'runtime_read_only':True,'model_read_only':True}}),flush=True); time.sleep(120)"
        children=[];real_popen=subprocess.Popen;real_append=self.life._append;real_fsync=os.fsync
        failure=OSError('fixture '+kind+' fsync failure')
        def spawn(*args,**kwargs):
            proc=real_popen(*args,**kwargs);children.append(proc)
            return proc
        def append(event,*args,**kwargs):
            if event!=kind:return real_append(event,*args,**kwargs)
            self.assertEqual(len(children),1)
            self.assertIsNone(children[0].poll(),'child must be alive at evidence failure')
            def fsync(fd):
                if os.readlink('/proc/self/fd/'+str(fd))==str(self.life.journal):raise failure
                return real_fsync(fd)
            with patch.object(os,'fsync',side_effect=fsync):return real_append(event,*args,**kwargs)
        try:
            with patch.object(b,'command',return_value=[sys.executable,'-u','-c',code]),patch.object(b,'limits',return_value=os.setsid),patch.object(subprocess,'Popen',side_effect=spawn),patch.object(self.life,'_append',side_effect=append):
                with self.assertRaisesRegex(ValueError,'UNRESOLVED'):
                    with instrument(self.life):
                        with self.assertRaises(OSError) as caught:adapter.load()
                        self.assertIs(caught.exception,failure)
                        self.assertIsNotNone(children[0].poll(),'adapter cleanup must reap child before returning')
                        self.assertFalse(Path('/proc/'+str(children[0].pid)).exists())
                        self.assertIsNone(adapter.process)
                        self.assertTrue(adapter._stderr.closed)
                        self.assertTrue(children[0].stdin.closed)
                        self.assertTrue(children[0].stdout.closed)
                        adapter.close_failed()
                        with self.assertRaisesRegex(ValueError,'UNRESOLVED'):adapter.unload()
            self.assertTrue(self.life.failed)
            self.assertTrue(self.life.pending.exists())
            with self.assertRaisesRegex(ValueError,'UNRESOLVED'):self.life.event('UNLOADED',adapter.work,state='TERMINAL_RETAINED_SUCCESS')
            with self.assertRaisesRegex(ValueError,'UNRESOLVED'):self.new_lifecycle(self.life.journal,'session-fixture','campaign-fixture')
            self.assertFalse(any(r['state'].startswith('TERMINAL') for r in self.rows()))
        finally:
            for proc in children:
                if proc.poll() is None:proc.kill()
                proc.wait()

    def test_child_journal_fsync_failure_reaps_real_child(self):
        self.check_live_child_journal_failure('CHILD')

    def test_loaded_journal_fsync_failure_reaps_real_child(self):
        self.check_live_child_journal_failure('LOADED')

    def test_partial_append_latches_unresolved_and_blocks_reopening(self):
        work=self.scratch/'inference-fixture';work.mkdir()
        real_write=os.write
        def partial(fd,data):
            real_write(fd,data[:17])
            raise OSError('fixture partial append')
        with patch.object(os,'write',side_effect=partial):
            with self.assertRaisesRegex(OSError,'partial append'):self.life.event('CREATED',work)
        self.assertFalse(self.life.journal.read_bytes().endswith(b'\n'))
        before=self.life.journal.read_bytes()
        with self.assertRaisesRegex(ValueError,'UNRESOLVED'):self.life.event('UNLOADED',work,state='TERMINAL_RETAINED_SUCCESS')
        self.assertEqual(self.life.journal.read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'UNRESOLVED'):self.new_lifecycle(self.life.journal,'s','c')

    def test_existing_partial_journal_is_not_extended(self):
        self.life.journal.write_bytes(b'{"event":')
        with self.assertRaisesRegex(ValueError,'PARTIAL_ROW'):self.new_lifecycle(self.life.journal,'s','c')

    def test_symlinks_rejected_and_isolated_preflight(self):
        contract={'plan':self.plan}
        operational_scratch(contract,empty=True)
        work=self.state/'work';work.mkdir();(work/'inference-old').mkdir()
        operational_scratch(contract,empty=True)  # Historical scratch is irrelevant, not adopted.
        (self.scratch/'inference-retained').mkdir()
        with self.assertRaisesRegex(ValueError,'SCRATCH_BUSY'):operational_scratch(contract,empty=True)
        link=self.root/'link';link.symlink_to(self.root/'evidence',target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'SYMLINK'):self.new_lifecycle(link/'journal','s','c')

    def test_tools_frozen_and_patches_restored(self):
        self.assertIn('tools/stage2_scratch.py',ADMIN_FILES)
        self.assertIn('tools/stage2_campaign.py',ADMIN_FILES)
        load=b.IsolatedRuntimeAdapter.load;temp=b.tempfile;sub=b.subprocess
        with instrument(self.life):pass
        self.assertIs(load,b.IsolatedRuntimeAdapter.load);self.assertIs(temp,b.tempfile);self.assertIs(sub,b.subprocess)

    def test_new_journal_ancestors_are_fsynced_before_allocation(self):
        target=self.root/'new'/'nested'/'journal.jsonl'
        synced=[];real_fsync=os.fsync
        def sync(fd):
            synced.append(os.readlink('/proc/self/fd/'+str(fd)))
            return real_fsync(fd)
        with patch.object(os,'fsync',side_effect=sync):
            self.new_lifecycle(target,'session-fixture','campaign-fixture')
        for path in (self.root,self.root/'new',self.root/'new/nested'):
            self.assertIn(str(path),synced)
        self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
