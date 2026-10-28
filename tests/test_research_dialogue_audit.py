from pathlib import Path
import unittest

from tools.audit_research_dialogue import audit


ROOT=Path(__file__).resolve().parents[1]


class AuditTests(unittest.TestCase):
    def test_real_evidence_portable_audit(self):
        value=audit(ROOT/'docs/local_intelligence_evidence/GAIA_1_2_RESEARCH_DIALOGUE_REAL_V1.json',
                    ROOT/'docs/local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json')
        self.assertEqual(value['status'],'PASS',value)


if __name__=='__main__':unittest.main()
