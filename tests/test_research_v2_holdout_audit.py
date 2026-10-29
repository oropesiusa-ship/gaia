import unittest
from pathlib import Path

from tools.audit_research_v2_holdout import audit


class ResearchV2HoldoutAuditTests(unittest.TestCase):
    def test_two_real_v7_runs_pass_frozen_holdout(self):
        root=Path('docs/local_intelligence_evidence')
        value=audit(root/'GAIA_1_2_RESEARCH_V2_HOLDOUT_V7_PREREGISTRATION.json',
                    [root/'GAIA_1_2_RESEARCH_V2_HOLDOUT_V7_RUN1.json',root/'GAIA_1_2_RESEARCH_V2_HOLDOUT_V7_RUN2.json'])
        self.assertEqual(value['status'],'PASS',value)
        self.assertTrue(value['checks']['semantic_replica'])
        self.assertEqual(value['scores'],[8,8])


if __name__=='__main__':unittest.main()
