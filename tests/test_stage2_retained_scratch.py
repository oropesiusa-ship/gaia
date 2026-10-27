"""Disposable lifecycle fixtures; never launch measured campaigns."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from tools import stage2_boundary as boundary


class RetainedScratchTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.scratch=self.root/'scratch';self.scratch.mkdir()
        self.work=self.scratch/'inference-fixture';self.work.mkdir()
        (self.work/'job.json').write_text('{}')
        self.journal=self.root/'session/evidence/scratch-lifecycle.jsonl'
        self.journal.parent.mkdir(parents=True)
        self.contract={'boot_id':'boot','plan':{'scratch_identity':{'device':1,'inode':2}}}
        base={'work':str(self.work),'scratch_root':str(self.scratch),
              'scratch_identity':self.contract['plan']['scratch_identity'],
              'session_id':'sid','campaign_id':'cid','owner':{'pid':100,'start_time':10,'boot_id':'boot'},
              'job_hash':boundary.ex.sha(self.work/'job.json'),'stack_hash':'stack'}
        self.rows=[{**copy.deepcopy(base),'event':event}for event in
                   ('CREATE_INTENT','CREATED','LAUNCH_INTENT','CHILD','LOADED','RELEASED','UNLOADED')]
        self.rows[3]['child']={'pid':101,'start_time':11,'boot_id':'boot'}
        self.rows[-1]['state']='TERMINAL_RETAINED_SUCCESS'
        (self.work/'stage2-owner.json').write_text(json.dumps(self.rows[1]))
        self.save()
        store=Mock(root=self.root/'session')
        store.state_view.return_value={'running':None,'stopped':True,'finished':['cid'],'campaigns':['cid']}
        for name,value in [('SessionStore',store),('alive',False),('ex.operational_scratch',self.scratch)]:
            mock=patch('tools.stage2_boundary.'+name,return_value=value)
            setattr(self,name.split('.')[-1]+'_mock',mock.start());self.addCleanup(mock.stop)

    def save(self):
        self.journal.write_text(''.join(json.dumps(row)+'\n'for row in self.rows))

    def inspect(self):
        return boundary.retained_scratch(self.contract,self.root,['sid'])

    def test_terminal_retention_is_read_only(self):
        before=boundary.ex.inventory([self.root],include_cache=True)
        self.assertEqual(self.inspect()['retained_directories'],1)
        self.assertEqual(before,boundary.ex.inventory([self.root],include_cache=True))

    def test_live_owner_or_child_blocks(self):
        self.alive_mock.return_value=True
        with self.assertRaisesRegex(ValueError,'STILL_ALIVE'):self.inspect()

    def test_unknown_directory_blocks(self):
        (self.scratch/'unknown').mkdir()
        with self.assertRaisesRegex(ValueError,'UNEXPLAINED'):self.inspect()

    def test_partial_or_pending_journal_blocks(self):
        self.journal.write_bytes(self.journal.read_bytes().rstrip(b'\n'))
        with self.assertRaisesRegex(ValueError,'PARTIAL'):self.inspect()
        self.save();self.journal.with_name(self.journal.name+'.pending').touch()
        with self.assertRaisesRegex(ValueError,'UNRESOLVED'):self.inspect()

    def test_tampered_job_or_owner_receipt_blocks(self):
        (self.work/'job.json').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'JOB_CHANGED'):self.inspect()
        (self.work/'job.json').write_text('{}')
        (self.work/'stage2-owner.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'RECEIPT_CHANGED'):self.inspect()

    def test_nonterminal_lifecycle_blocks(self):
        self.rows.pop();self.save()
        with self.assertRaisesRegex(ValueError,'NOT_SUCCESSFULLY_TERMINAL'):self.inspect()

    def test_symlinked_scratch_file_blocks(self):
        (self.work/'foreign').symlink_to(self.work/'job.json')
        with self.assertRaises(ValueError):self.inspect()
