import unittest
from pathlib import Path

from tools.audit_gaia_1_2_final_quality import audit


class FinalQualityAuditTests(unittest.TestCase):
    def test_preregistered_final_sources_recompute_pass(self):
        value=audit(Path('docs/local_intelligence_evidence'))
        self.assertEqual(value['status'],'PASS',value)
        self.assertEqual(value['objective']['passed'],22)
        self.assertEqual(value['objective']['total'],26)
        self.assertTrue(all(value['checks'].values()))
        self.assertEqual(value['claims']['cognitive_improvement'],'NOT_CLAIMED')


if __name__=='__main__':unittest.main()
