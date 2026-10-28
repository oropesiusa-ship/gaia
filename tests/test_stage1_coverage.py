"""Administrative Stage 1 coverage checks; no real endurance campaign is launched."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import stage1_coverage as coverage
from tools.audit_endurance_session import gaps


class Stage1CoverageTests(unittest.TestCase):
    def test_host_vram_stream_stays_continuous_across_idle_and_campaigns(self):
        rows=[{'clock':{'monotonic':t,'wall':t,'boot_id':'b'},'campaign_id':cid}
              for t,cid in [(0,None),(30,None),(60,'ac1'),(90,'ac1'),(120,'ac1'),(150,None)]]
        self.assertTrue(gaps(rows,30,'campaign_id'))  # the old, incorrect grouping
        self.assertEqual(gaps(rows,30),[])
        self.assertTrue(gaps(rows[:2]+rows[-1:],30))  # a genuine sensor gap still fails

    def test_slots_cover_the_window_without_increasing_campaign_count(self):
        limits={'maximum_wall_s':5400,'maximum_campaigns':5}
        self.assertEqual([coverage.slot_deadline(100,n,limits)for n in range(1,6)],
                         [1180,2260,3340,4420,5500])

    def test_inventory_detects_changed_created_and_removed_files(self):
        with tempfile.TemporaryDirectory()as tmp:
            p=Path(tmp)/'state';p.mkdir();f=p/'evidence';f.write_text('before')
            before=coverage.inventory([p]);f.write_text('after')
            self.assertNotEqual(before,coverage.inventory([p]))
            f.unlink();self.assertEqual(coverage.inventory([p]),{})

    def test_inventory_rejects_symlinks(self):
        with tempfile.TemporaryDirectory()as tmp:
            p=Path(tmp);(p/'link').symlink_to('/nonexistent')
            with self.assertRaisesRegex(ValueError,'SYMLINK'):coverage.inventory([p])

    def test_pacing_keeps_observing_without_extending_the_slot(self):
        supervisor=coverage.PacedSupervisor.__new__(coverage.PacedSupervisor)
        now=[10.];samples=[];heartbeats=[]
        supervisor.root=supervisor.state=Path('/unused')
        supervisor.contract={'limits':{'maximum_wall_s':100,'maximum_campaigns':5,'heartbeat_s':5,'vram_sample_s':30},'freeze':{}}
        supervisor.session=SimpleNamespace(state_view=lambda:{'finished':[{'recovery':'TERMINAL_OK'}],
            'started_clock':{'monotonic':0},'campaigns':['ac1']})
        supervisor.telemetry=SimpleNamespace(append=samples.append);supervisor.vram_sampled=10
        supervisor.heartbeat=lambda **kw:heartbeats.append(kw)
        supervisor.stopping=lambda:False;supervisor.storage_check=lambda:None
        supervisor.sleep=lambda seconds:now.__setitem__(0,now[0]+seconds)
        with patch.object(coverage.Supervisor,'finish',return_value='DONE'),\
             patch.object(coverage,'changes',return_value=[]),\
             patch.object(coverage,'memory',return_value={'available_bytes':10,'below_reserve':False}),\
             patch.object(coverage.time,'monotonic',side_effect=lambda:now[0]):
            self.assertEqual(supervisor.finish('ac1','al1'),'DONE')
        self.assertEqual(now[0],20.)
        self.assertEqual(len(samples),2)
        self.assertTrue(all(x['kind']=='IDLE'for x in samples))
        self.assertTrue(all(x['phase']=='SCHEDULED_IDLE'for x in heartbeats))

    def test_window_requires_duration_continuity_and_same_boot(self):
        def clock(t,boot='a'):return {'monotonic':t,'wall':10000+t,'boot_id':boot}
        store=SimpleNamespace(root=Path('/unused'),read=lambda:{'limits':{'maximum_wall_s':5400}},
            state_view=lambda:{'started_clock':clock(0),'compute_s':1200},
            events=lambda:[{'clock':clock(5400)}])
        rows=[{'kind':'IDLE','clock':clock(t)}for t in range(0,5401,10)]
        with patch('gaia.autonomy.telemetry.Telemetry.samples',return_value=rows):
            self.assertEqual(coverage.window_coverage(store)['status'],'PASS')
            store.events=lambda:[{'clock':clock(5390)}]
            self.assertEqual(coverage.window_coverage(store)['status'],'FAIL')
            store.events=lambda:[{'clock':clock(5400,'b')}]
            self.assertEqual(coverage.window_coverage(store)['status'],'FAIL')
            store.events=lambda:[{'clock':clock(5400)}]
        with patch('gaia.autonomy.telemetry.Telemetry.samples',return_value=rows[:5]+rows[10:]):
            self.assertEqual(coverage.window_coverage(store)['status'],'FAIL')


if __name__=='__main__':unittest.main()
