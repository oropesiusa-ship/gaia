"""Deterministic census/ownership interleavings; no measured campaigns."""
import unittest
import os
import subprocess
import sys
from unittest.mock import Mock,patch
from tools import stage2_runtime as runtime


class OwnershipRaceTests(unittest.TestCase):
    def setUp(self):
        self.info=(20,30,30,100,3,'/runtime/koboldcpp','R',123)
        self.row={'pid':40,'starttime':123,'pidfd':8,'role':'OWNED_CHILD'}
        self.boundary=Mock(record_error=None,owned={},fds={})
        self.owned={}
        census=patch.object(runtime,'processes',return_value={40:self.info})
        self.census=census.start();self.addCleanup(census.stop)
        alive=patch.object(runtime,'alive',return_value=True)
        self.alive=alive.start();self.addCleanup(alive.stop)

    def classify(self):
        return runtime.external_backends(self.owned,self.boundary)

    def capture(self):
        self.boundary.owned={40:self.row};self.boundary.fds={40:8}
        return [self.row]

    def test_child_born_between_census_and_collection_is_verified(self):
        self.boundary.collect.side_effect=self.capture
        self.assertEqual(self.classify(),{})
        self.boundary.collect.assert_called_once()
        self.census.assert_called_once()

    def test_real_foreign_backend_is_still_external(self):
        self.boundary.collect.return_value=[]
        self.assertEqual(self.classify(),{40:self.info})

    def test_pid_reuse_is_not_ownership(self):
        self.owned[40]={**self.row,'starttime':122}
        self.boundary.collect.return_value=[{**self.row,'starttime':124}]
        self.boundary.owned={40:{**self.row,'starttime':124}}
        self.boundary.fds={40:8}
        self.assertEqual(self.classify(),{40:self.info})

    def test_unpinned_or_wrong_descriptor_cannot_clear_candidate(self):
        for descriptors in ({},{40:9}):
            with self.subTest(descriptors=descriptors):
                self.owned={};self.boundary.owned={40:self.row}
                self.boundary.fds=descriptors;self.boundary.collect.return_value=[self.row]
                self.assertEqual(self.classify(),{40:self.info})

    def test_disappearing_candidate_is_not_silently_forgiven(self):
        self.boundary.collect.side_effect=self.capture;self.alive.return_value=False
        self.assertEqual(self.classify(),{40:self.info})

    def test_capture_journal_failure_blocks(self):
        self.boundary.collect.side_effect=self.capture;self.boundary.record_error='disk failure'
        with self.assertRaisesRegex(RuntimeError,'SUBREAPER_EVIDENCE_FAILED'):self.classify()

    def test_previously_owned_identity_needs_no_extra_collection(self):
        self.owned[40]=self.row
        self.assertEqual(self.classify(),{})
        self.boundary.collect.assert_not_called()

    def test_no_boundary_cannot_adopt_candidate(self):
        self.assertEqual(runtime.external_backends({},None),{40:self.info})

    @unittest.skipUnless(sys.platform=='linux'and hasattr(os,'pidfd_open'),'Linux pidfds required')
    def test_real_late_descendant_is_pinned_and_cleanup_drains_it(self):
        script='''import os,subprocess,sys
from tools.stage2_children import ChildBoundary
from tools.stage2_runtime import external_backends
events=[]
controller="import subprocess,sys; print('READY',flush=True); sys.stdin.readline(); p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)','koboldcpp-fixture']); print(p.pid,flush=True); p.wait()"
with ChildBoundary(events.append) as boundary:
    boundary.begin()
    process=subprocess.Popen([sys.executable,'-B','-c',controller],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,start_new_session=True)
    try:
        assert process.stdout.readline().strip()=='READY'
        boundary.attach(process)
        owned={row['pid']:dict(row)for row in boundary.collect()}
        process.stdin.write('GO\\n');process.stdin.flush()
        child=int(process.stdout.readline())
        assert child not in owned
        result=external_backends(owned,boundary)
        assert child not in result,result
        assert child in boundary.fds
        assert any(e.get('kind')=='CHILD_CAPTURED'and e.get('pid')==child for e in events)
    finally:
        process.stdin.close();process.stdout.close();boundary.drain()
    assert boundary.kernel_empty()
assert not boundary.enabled
'''
        result=subprocess.run([sys.executable,'-B','-W','error::ResourceWarning','-c',script],
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
