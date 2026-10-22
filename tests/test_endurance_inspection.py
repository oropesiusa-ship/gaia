"""1.1 §4/§5: read-only inspection and the unambiguous recovery classification, on committed journals only."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gaia.autonomy.schema import campaign
from gaia.autonomy.store import CampaignStore,NEXT
from gaia.autonomy.controller import create_campaign,ClosedLoop
from gaia.autonomy.inspection import inspect_campaign,classify,CLASSES
from gaia.autonomy.lineage import LineageStore,create_lineage
from gaia.autonomy import cli

IMPROVE='IMPROVE_NUMPY_MLP_EXISTING_CRITERIA'
ORDER=('CREATED','OBSERVING','DIAGNOSING','PRIORITIZING','RETRIEVING','RESEARCHING','PLANNING','REVIEWING','AUTHORIZING','MATERIALIZING',
       'EXPERIMENTING','EVALUATING','LEARNING','PROMOTING','VERIFYING','ROLLING_BACK','REEVALUATING')


def snapshot(root):
    return {str(p.relative_to(root)):(p.stat().st_mtime_ns,p.read_bytes())for p in Path(root).rglob('*')if p.is_file()}


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        (self.root/'gaia/protected').mkdir(parents=True);(self.root/'gaia.py').write_text('# unit root\n')
        (self.root/'gaia/protected/evaluator.py').write_text('# protected unit fixture\n');self.state=self.root/'state'
    def campaign(self,lineage=False,**kwargs):
        lin=create_lineage(self.root,self.state,IMPROVE)['lineage_id']if lineage else None
        c=create_campaign(self.root,self.state,campaign(IMPROVE,'CONTROLLED_AUTONOMOUS',lineage_id=lin,**kwargs))
        return CampaignStore(self.state,c['campaign_id']),lin
    def walk(self,store,target,**updates):
        """Commit the normal phase sequence up to target (each a valid transition)."""
        for phase in ORDER[1:ORDER.index(target)+1]:store.event(phase)
        if updates:store.event(target,updates)
    def status(self,store):return inspect_campaign(self.state,store.root.name)


class ReadOnlyInspectionTests(Fixture):
    def test_status_works_while_the_campaign_lock_is_held_and_writes_nothing(self):
        store,_=self.campaign();self.walk(store,'PLANNING')
        with store.lock():
            before=snapshot(self.state);out=io.StringIO()
            with contextlib.redirect_stdout(out):code=cli.run(self.root,'autonomy-status',type('A',(),{'state_dir':self.state,'campaign_id':store.root.name})())
            self.assertEqual(snapshot(self.state),before)
        self.assertEqual(code,0);value=json.loads(out.getvalue())
        self.assertEqual((value['recovery'],value['inspection']),('RECOVERABLE','READ_ONLY_NO_LOCK_NO_REPAIR'))
    def test_stale_or_missing_cursor_is_reported_not_repaired(self):
        store,_=self.campaign();self.walk(store,'OBSERVING')
        cursor=store.root/'current.json';cursor.write_text(json.dumps({'phase':'CREATED'}))
        before=snapshot(self.state);self.assertEqual(self.status(store)['cursor'],'STALE');self.assertEqual(snapshot(self.state),before)
        cursor.unlink();self.assertEqual(self.status(store)['cursor'],'MISSING');self.assertFalse(cursor.exists())
    def test_cursor_repair_is_explicit_and_only_under_the_lock(self):
        store,_=self.campaign();self.walk(store,'OBSERVING');(store.root/'current.json').unlink()
        with store.lock(),self.assertRaises(BlockingIOError):store.repair_cursor()
        self.assertEqual(store.repair_cursor(),{'cursor_before':'MISSING','cursor_after':'CONSISTENT'})
    def test_run_on_a_terminal_campaign_does_not_repair_the_cursor_without_lock(self):
        store,_=self.campaign();store.event('STOPPED',{'reason':'NO_PROGRESS','report_ref':store.put('REPORT',{'status':'PASS'})})
        (store.root/'current.json').write_text(json.dumps({'phase':'CREATED'}));loop=ClosedLoop(self.root,self.state,store.root.name)
        loop.run(authorized=True);self.assertEqual(json.loads((store.root/'current.json').read_text()),{'phase':'CREATED'})
    def test_lineage_inspection_stays_pure(self):
        store,lin=self.campaign(lineage=True);self.walk(store,'OBSERVING');before=snapshot(self.state)
        self.assertFalse(self.status(store)['lineage_blocked']);self.assertEqual(snapshot(self.state),before)


class RecoveryClassificationTests(Fixture):
    def terminal(self,phase,reason,before=None):
        store,_=self.campaign()
        if before:self.walk(store,before)
        store.event(phase,{'reason':reason});return self.status(store)
    def test_classification_table(self):
        cases=[(('COMPLETED','DRY_RUN_COMPLETE_NO_EXPERIMENT_EXECUTED'),'TERMINAL_OK'),(('STOPPED','NO_PROGRESS','REEVALUATING'),'TERMINAL_OK'),
               (('STOPPED','STOPPED_BUDGET','REEVALUATING'),'TERMINAL_OK'),(('STOPPED','POST_PROMOTION_REGRESSION_ROLLED_BACK','ROLLING_BACK'),'TERMINAL_OK'),
               (('STOPPED','NEEDS_RECOVERY','EXPERIMENTING'),'NEEDS_RECOVERY'),(('STOPPED','HEALTH_INVALID'),'NEEDS_RECOVERY'),
               (('STOPPED','REFERENCE_DRIFT','MATERIALIZING'),'NEEDS_RECOVERY'),(('FAILED','ROLLBACK_FAILED','ROLLING_BACK'),'NEEDS_RECOVERY'),
               (('STOPPED','STOPPED_BUDGET','LEARNING'),'NEEDS_RECOVERY'),(('FAILED','MATERIALIZATION_NONDETERMINISTIC','MATERIALIZING'),'NON_RECOVERABLE'),
               (('FAILED','PROTECTED_OR_SOURCE_CHANGED'),'NON_RECOVERABLE')]
        for args,expected in cases:
            with self.subTest(args=args):
                value=self.terminal(*args);self.assertEqual(value['recovery'],expected);self.assertEqual(value['resumable'],False)
    def test_interrupted_in_flight_is_never_terminal_ok(self):
        value=self.terminal('STOPPED','STOPPED_BUDGET','VERIFYING')
        self.assertEqual((value['recovery'],value['reason']),('NEEDS_RECOVERY','INTERRUPTED_IN_FLIGHT_VERIFYING'))
    def test_non_terminal_states(self):
        store,_=self.campaign();self.walk(store,'EXPERIMENTING',execution_intent=True)
        self.assertEqual(self.status(store)['recovery'],'RECOVERABLE');self.assertEqual(self.status(store)['action'],'RUN')
        for intent in ('rollback_intent','research_intent','initialization_intent'):
            with self.subTest(intent=intent):
                s,_=self.campaign();self.walk(s,'OBSERVING',**{intent:True})
                value=self.status(s);self.assertEqual((value['recovery'],value['reason']),('NEEDS_RECOVERY','AMBIGUOUS_'+intent.upper()))
        s,_=self.campaign();self.walk(s,'PLANNING');s.event('PAUSED',{'resume_phase':'PLANNING'})
        self.assertEqual((self.status(s)['recovery'],self.status(s)['action']),('RECOVERABLE','RESUME_THEN_RUN'))
    def test_blocked_lineage_makes_a_resumable_campaign_need_recovery(self):
        store,lin=self.campaign(lineage=True);self.walk(store,'PLANNING')
        LineageStore(self.state,lin).event('BLOCKED',{'campaign_id':'other','reason':'HEALTH_INVALID','phase':'CREATED','resolution':'EXPLICIT_HUMAN_REVIEW_REQUIRED'})
        value=self.status(store);self.assertEqual((value['recovery'],value['reason'],value['lineage_blocked']),('NEEDS_RECOVERY','LINEAGE_BLOCKED',True))
    def test_corruption_is_classified_not_raised(self):
        store,_=self.campaign();self.walk(store,'OBSERVING')
        path=sorted((store.root/'events').glob('*.json'))[0];v=json.loads(path.read_bytes());v['state']['iteration']=99
        path.chmod(0o644);path.write_text(json.dumps(v))
        value=self.status(store);self.assertEqual((value['recovery'],value['reason'],value['resumable']),('CORRUPT','JOURNAL_CORRUPTED',False))
        empty,_=self.campaign()
        for p in (empty.root/'events').glob('*.json'):p.chmod(0o644);p.unlink()
        self.assertEqual(self.status(empty)['recovery'],'CORRUPT')
    def test_every_class_is_reachable_and_closed(self):
        self.assertEqual(set(CLASSES),{'TERMINAL_OK','RECOVERABLE','NEEDS_RECOVERY','CORRUPT','NON_RECOVERABLE'})
        self.assertTrue(set(ORDER[1:])<=set(NEXT)|{'REEVALUATING'})


if __name__=='__main__':unittest.main()
