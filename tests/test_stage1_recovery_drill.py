"""Verdict tests only: no real promotion or fault injection from suite discovery."""
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tools import stage1_recovery_drill as drill
from tools.stage1_recovery_drill import recovery_outcome


class RecoveryVerdictTests(unittest.TestCase):
    def outcome(self,**changes):
        args={'injected':True,'audit':{'status':'PASS'},
              'duplicates':{'unique':True,'intents_reserved':2,'evaluations':2},
              'lineage_state':{'blocked':False},'state_now':{'rollback_count':1},
              'reference':{'reason':'AFTER_ROLLBACK','status':'MEASURED'}}
        return recovery_outcome(**{**args,**changes})

    def test_only_exercised_rollback_with_measured_reference_passes(self):
        self.assertEqual(self.outcome(),'PASS')

    def test_absent_fault_or_rollback_is_not_a_pass(self):
        self.assertEqual(self.outcome(injected=False),'NOT_EXERCISED')
        self.assertEqual(self.outcome(state_now={}), 'NOT_EXERCISED_ROLLBACK')

    def test_safe_block_or_duplicate_is_not_successful_recovery(self):
        self.assertEqual(self.outcome(lineage_state={'blocked':True}),'FAIL')
        self.assertEqual(self.outcome(duplicates={'unique':False,'intents_reserved':2,'evaluations':2}),'FAIL')
        self.assertEqual(self.outcome(duplicates={'unique':True,'intents_reserved':2,'evaluations':1}),'FAIL')

    def test_missing_reference_or_audit_failure_cannot_be_waived(self):
        self.assertEqual(self.outcome(reference=None),'FAIL')
        self.assertEqual(self.outcome(reference={'reason':'CAMPAIGN_ADMISSION','status':'MEASURED'}),'FAIL')
        self.assertEqual(self.outcome(audit={'status':'FAIL'}),'FAIL')


class ContinuationTests(unittest.TestCase):
    def check(self,**changes):
        view={'blocked':False,'open_campaigns':[],'campaigns':['ac_previous'],'experiments':2,**changes}
        store=SimpleNamespace(lock=lambda:nullcontext(),read=lambda:{'objective':'IMPROVE_NUMPY_MLP_EXISTING_CRITERIA',
            'surface':'numpy_mlp','source_identity_hash':'same'},state=lambda:view,events=lambda:[{'hash':'tip'}])
        with patch.object(drill,'LineageStore',return_value=store),\
             patch.object(drill,'identities',return_value={'hash':'same'}),\
             patch.object(drill,'inspect_campaign',return_value={'recovery':'TERMINAL_OK'}),\
             patch.object(drill,'controllers',return_value=[]):
            return drill.continuation_lineage(Path('/project'),Path('/project/state_endurance_stage1_recovery_test'),'al_test')

    def test_continuation_preserves_previous_experiments_and_journal_tip(self):
        result=self.check()
        self.assertEqual(result['previous_experiments'],2)
        self.assertEqual(result['previous_journal_tip'],'tip')
        self.assertEqual(result['previous_campaigns'],['ac_previous'])

    def test_blocked_or_open_lineages_are_not_automatically_repaired(self):
        for changes in ({'blocked':True},{'open_campaigns':['ac_open']},{'campaigns':[]}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.check(**changes)

    def test_normal_endurance_namespace_cannot_be_reused(self):
        with self.assertRaisesRegex(ValueError,'DISPOSABLE_RECOVERY_NAMESPACE_REQUIRED'):
            drill.continuation_lineage(Path('/project'),Path('/project/state_endurance_stage1_attempt2'),'al_test')


if __name__=='__main__':unittest.main()
