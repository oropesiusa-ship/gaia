"""Real fork/setsid fixtures in dedicated disposable processes; no Stage 2 runs."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from tools import stage2_children as ownership

ROOT=Path(__file__).resolve().parents[1]

CONTROLLER=r'''
import os,signal,sys,time,json
from pathlib import Path
from gaia.autonomy.supervisor import proc_info
pid=os.fork()
if pid==0:
    os.setsid()
    pid=os.fork()
    if pid:os._exit(0)
    os.setsid()
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid(),'starttime':proc_info(os.getpid())[7],'sid':os.getsid(0)}))
    time.sleep(60)
    os._exit(0)
if sys.argv[2]=='exit':os._exit(0)
time.sleep(60)
'''

HELPER=r'''
import json,os,subprocess,sys,time
from pathlib import Path
from tools.stage2_children import ChildBoundary,subreaper
from tools.stage2_runtime import FirstSessionSupervisor
from types import SimpleNamespace
from gaia.autonomy.supervisor import proc_info
events=[];original=subreaper();fds=len(os.listdir('/proc/self/fd'))
mode=sys.argv[1];path=Path(sys.argv[2]);controller=sys.argv[3]
def record(event):
    events.append(event)
    if mode=='evidence' and event['kind']=='PRE_CLEANUP':raise OSError('unit evidence filesystem failure')
try:
    with ChildBoundary(record)as boundary:
        boundary.begin()
        proc=subprocess.Popen([sys.executable,'-B','-c',controller,str(path),mode],start_new_session=True)
        boundary.attach(proc)
        deadline=time.monotonic()+5
        while not path.exists():
            if time.monotonic()>deadline:raise RuntimeError('fixture startup timeout')
            time.sleep(.005)
        orphan=json.loads(path.read_text())
        if mode=='interrupt':
            proc.kill();proc.wait(timeout=5)
        elif mode in ('exception','evidence'):raise KeyboardInterrupt('unit supervisor interruption')
        else:proc.wait(timeout=5)
        captured=boundary.collect()
        assert any(r['pid']==orphan['pid'] and r['ppid']==os.getpid() for r in captured),captured
        supervisor=object.__new__(FirstSessionSupervisor)
        supervisor.boundary=boundary
        supervisor.session=SimpleNamespace(root=path.parent/('unit-session-'+mode))
        stopped=supervisor.cleanup(proc,[])
        assert any(r['pid']==orphan['pid'] for r in stopped),stopped
except KeyboardInterrupt:
    assert mode=='exception'
except RuntimeError as exc:
    assert mode=='evidence' and 'SUBREAPER_EVIDENCE_FAILED' in str(exc),str(exc)
assert subreaper()==original
assert len(os.listdir('/proc/self/fd'))==fds
captured=[e for e in events if e['kind']=='CHILD_CAPTURED']
assert any(e['pid']==orphan['pid'] and e['sid']==orphan['pid'] for e in captured),captured
for row in captured:
    info=proc_info(row['pid'])
    assert info is None or info[7]!=row['starttime'],(row,info)
assert boundary.kernel_empty() and not boundary.enabled and not boundary.fds
if mode!='evidence':
    assert any(e['kind']=='CLEANUP_DRAINED' and e['kernel_echild']for e in events)
    assert events[-1]['kind']=='SUBREAPER_RESTORED'
print(json.dumps({'captured':len(captured),'restored':True,'orphan':orphan}))
'''


@unittest.skipUnless(sys.platform=='linux','Linux ownership boundary')
class ChildBoundaryTests(unittest.TestCase):
    def test_reused_parent_pid_cannot_grant_descendant_ownership(self):
        boundary=ownership.ChildBoundary();boundary.pid=100;boundary.active=True
        def info(ppid,start):return (ppid,1,1,0,0,'unit','S',start)
        table={101:info(100,10),102:info(101,12)}
        current={100:info(1,1),101:info(999,11),102:info(101,12)}
        with patch.object(boundary,'verify'),patch.object(ownership,'processes',return_value=table),\
             patch.object(ownership,'proc_info',side_effect=lambda pid:current.get(pid)),\
             patch.object(ownership.os,'pidfd_open',return_value=999)as opened,patch.object(ownership.os,'close'):
            self.assertEqual(boundary.collect(),[])
            opened.assert_called_once_with(101,0)

    def test_rapid_double_fork_setsid_exit_and_interruption_are_drained(self):
        bystander=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True)
        try:
            with tempfile.TemporaryDirectory()as directory:
                for mode in ('exit','interrupt','exception','evidence'):
                    with self.subTest(mode=mode):
                        result=subprocess.run([sys.executable,'-B','-c',HELPER,mode,str(Path(directory)/mode),CONTROLLER],
                            cwd=ROOT,capture_output=True,text=True,timeout=20)
                        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                        data=json.loads(result.stdout);self.assertTrue(data['restored'])
                        self.assertGreaterEqual(data['captured'],2)
                        self.assertIsNone(bystander.poll(),'Unrelated sibling was signalled')
        finally:bystander.terminate();bystander.wait(timeout=5)

    def test_baseline_child_refuses_boundary_without_signalling_it(self):
        script=r'''
import subprocess,sys,json
from tools.stage2_children import ChildBoundary,subreaper
p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
old=subreaper();events=[]
try:
    try:
        with ChildBoundary(events.append):raise AssertionError('entered with unexpected baseline')
    except RuntimeError as exc:assert str(exc)=='UNEXPECTED_BASELINE_CHILDREN',str(exc)
    assert subreaper()==old and p.poll() is None
    assert str(p.pid) in str(events[0]['direct_children'])
    print(json.dumps({'refused':True,'untouched':True}))
finally:p.terminate();p.wait(timeout=5)
'''
        result=subprocess.run([sys.executable,'-B','-c',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(json.loads(result.stdout)['untouched'])

    def test_previous_subreaper_values_are_restored_and_verified(self):
        script=r'''
from tools.stage2_children import ChildBoundary,subreaper
original=subreaper()
try:
    for value in (0,1):
        subreaper(value);events=[]
        with ChildBoundary(events.append)as boundary:
            assert subreaper()==1 and boundary.previous==value
        assert subreaper()==value and events[-1]['verified']
finally:subreaper(original)
'''
        result=subprocess.run([sys.executable,'-B','-c',script],cwd=ROOT,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
