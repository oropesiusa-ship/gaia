import unittest
from tools.audit_instruction_adapter import audit

class AdapterAuditTests(unittest.TestCase):
    def test_real_candidate_replays_against_persisted_baseline(self):
        for name in ('GAIA_1_2_CHAT_ADAPTER_V1.json','GAIA_1_2_CHAT_ADAPTER_V2.json','GAIA_1_2_CHAT_ADAPTER_V2_REPLICATION.json'):
            with self.subTest(name=name):
                value=audit('docs/local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json','docs/local_intelligence_evidence/'+name)
                self.assertEqual(value['status'],'PASS',value);self.assertEqual(value['decision'],'RETAIN_EXPERIMENTAL_NOT_PROMOTED')

if __name__=='__main__':unittest.main()
