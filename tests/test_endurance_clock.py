"""1.1 §3: monotonic intervals within a boot, boot changes detected, conservative budgets and the time breakdown."""
import time
import unittest
from unittest.mock import patch

from gaia.autonomy import clock
from gaia.autonomy.policy import budget_check,BudgetExceeded
from gaia.autonomy.lineage import LineageStore
from test_autonomy_integration import Fixture,FakeV2


class ClockTests(unittest.TestCase):
    def test_interval_is_monotonic_within_a_boot_and_flagged_across_reboots(self):
        a={'wall':1000.,'monotonic':50.,'boot_id':'b1'}
        self.assertEqual(clock.interval(a,{'wall':900.,'monotonic':80.,'boot_id':'b1'}),(30.,False))  # wall stepped back
        self.assertEqual(clock.interval(a,{'wall':1100.,'monotonic':5.,'boot_id':'b2'}),(100.,True))
        self.assertEqual(clock.interval(a,{'wall':900.,'monotonic':5.,'boot_id':'b2'}),(0.,True))
    def test_stamp_has_utc_boot_and_cpu(self):
        s=clock.stamp();self.assertTrue(s['utc'].endswith('+00:00'));self.assertIsInstance(s['cpu_s'],float)
        self.assertEqual(s['boot_id'],clock.boot_id());self.assertTrue(s['boot_id'])
    def test_backwards_wall_step_neither_stops_nor_extends_a_campaign(self):
        started=clock.stamp();state={'started_at':started['wall'],'started_clock':started}
        with patch('gaia.autonomy.clock.time.monotonic',return_value=started['monotonic']+100),patch('gaia.autonomy.clock.time.time',return_value=started['wall']-500):
            self.assertAlmostEqual(clock.elapsed(state),100.)
        with patch('gaia.autonomy.clock.time.monotonic',return_value=started['monotonic']+100),patch('gaia.autonomy.clock.time.time',return_value=started['wall']+400):
            self.assertAlmostEqual(clock.elapsed(state),400.)  # a forward step is charged: budgets stay conservative
    def test_reboot_uses_wall_time(self):
        started=clock.stamp();state={'started_at':started['wall']-60,'started_clock':{**started,'boot_id':'previous-boot'}}
        self.assertGreaterEqual(clock.elapsed(state),60.)
    def test_budget_check_uses_the_conservative_elapsed(self):
        from gaia.autonomy.schema import campaign
        c=campaign();started=clock.stamp();state={'started_at':started['wall'],'started_clock':started,'iteration':0}
        with patch('gaia.autonomy.clock.time.time',return_value=started['wall']-10**6):
            self.assertTrue(budget_check(c,state,'/nonexistent'))  # the old wall-only check raised STOPPED_BUDGET here
        with patch('gaia.autonomy.clock.time.monotonic',return_value=started['monotonic']+c['maximum_wall_time']+1),self.assertRaises(BudgetExceeded):
            budget_check(c,state,'/nonexistent')


class TimeBreakdownTests(Fixture):
    def test_events_and_lineage_events_are_stamped(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);self.go(loop)
        for e in loop.store.events()+LineageStore(self.state,lin['lineage_id']).events():
            self.assertEqual(set(e['clock']),{'utc','wall','monotonic','boot_id','cpu_s'});self.assertEqual(e['timestamp'],e['clock']['wall'])
        self.assertIn('started_clock',loop.store.current())
    def test_report_breaks_time_down(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);r=self.go(loop);t=r['metrics']['time']
        self.assertEqual((t['controller_runs'],t['boots'],t['clock_discontinuities']),(1,1,0))
        self.assertGreater(t['active_s'],0);self.assertLessEqual(t['active_s'],t['wall_s']+1e-6);self.assertGreaterEqual(t['experiment_s'],0)
        self.assertAlmostEqual(t['idle_s'],max(0.,t['wall_s']-t['active_s']),places=6)
    def test_restarts_and_pauses_are_not_active_time(self):
        class Pausing(FakeV2):
            def learn(self,e):self.store.control('PAUSE');return super().learn(e)
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Pausing);self.assertEqual(self.go(loop)['status'],'PAUSED')
        time.sleep(.3);loop.store.control('RUN');loop.services.__class__=FakeV2
        r=self.go(loop);t=r['metrics']['time']
        self.assertEqual(t['controller_runs'],2);self.assertGreaterEqual(t['between_runs_s']+t['paused_s'],.3)
        self.assertGreaterEqual(t['idle_s'],.3)
    def test_boot_change_is_a_counted_discontinuity(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);calls=[0];real=clock.boot_id
        def boot():
            calls[0]+=1;return real()if calls[0]<40 else'rebooted-'+real()
        with patch('gaia.autonomy.clock.boot_id',side_effect=boot):r=self.go(loop)
        t=r['metrics']['time'];self.assertEqual(t['boots'],2);self.assertGreaterEqual(t['clock_discontinuities'],1)


if __name__=='__main__':unittest.main()


class ProgressTests(Fixture):
    def test_no_progress_stop_is_replayed_and_counters_are_reported(self):
        lin=self.lineage();loop=self.loop(lin['lineage_id']);r=self.go(loop);p=r['metrics']['progress']
        self.assertEqual(r['stopping_reason'],'NO_PROGRESS');self.assertIs(p['stopping_condition_met'],True)
        self.assertEqual(p['experiments'],r['metrics']['experiments']);self.assertEqual(p['redundant_experiments'],0)
        self.assertEqual(p['longest_streak_without_acceptance'],p['experiments'])
        self.assertEqual(p['informative_experiments']+p['inconclusive_experiments'],p['experiments'])
    def test_inconclusive_experiments_are_not_informative(self):
        class Unsure(FakeV2):decisions=('deferred',)
        lin=self.lineage();r=self.go(self.loop(lin['lineage_id'],factory=Unsure));p=r['metrics']['progress']
        self.assertEqual(r['stopping_reason'],'REPEATED_INCONCLUSIVE');self.assertIs(p['stopping_condition_met'],True)
        self.assertEqual((p['informative_experiments'],p['inconclusive_experiments']),(0,2))
    def test_acceptance_resets_the_streak(self):
        class Mixed(FakeV2):decisions=('rejected','accepted','rejected')
        lin=self.lineage();loop=self.loop(lin['lineage_id'],factory=Mixed);p=self.go(loop)['metrics']['progress']
        outcomes=[x['result']['classification']for x in self.records(loop)];self.assertIn('ACCEPTED',outcomes)
        runs=''.join('A'if o=='ACCEPTED'else'r'for o in outcomes).split('A')
        self.assertEqual((p['longest_streak_without_acceptance'],p['current_streak_without_acceptance']),(max(map(len,runs)),len(runs[-1])))
