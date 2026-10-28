import json
import tempfile
import unittest
from pathlib import Path
from tools.audit_chat_quality import audit


class ChatQualityAuditTests(unittest.TestCase):
    def test_committed_evidence_replays_and_tampering_fails(self):
        source=Path(__file__).resolve().parents[1]/'docs/local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json'
        self.assertEqual(audit(source)['status'],'PASS')
        value=json.loads(source.read_text());value['memory']['objective']['passed']=8
        with tempfile.TemporaryDirectory()as root:
            path=Path(root)/'bad.json';path.write_text(json.dumps(value))
            self.assertEqual(audit(path)['status'],'FAIL')
