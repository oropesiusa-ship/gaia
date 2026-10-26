"""Verdict tests only: no real promotion or fault injection from suite discovery."""
import unittest
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


if __name__=='__main__':unittest.main()
