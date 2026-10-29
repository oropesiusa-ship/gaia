import unittest
from pathlib import Path

from tools.audit_gaia_1_2_certification import audit


class Gaia12CertificationAuditTests(unittest.TestCase):
    def test_all_approved_gates_certify_without_release_authority(self):
        value=audit(Path('docs/local_intelligence_evidence'))
        self.assertEqual(value['status'],'CERTIFIED',value)
        self.assertTrue(all(value['checks'].values()))
        self.assertFalse(value['merge_tag_release_authorized'])


if __name__=='__main__':unittest.main()
