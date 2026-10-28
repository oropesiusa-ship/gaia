import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import stage2_c3_recovery as recovery


class C3RecoveryContractTests(unittest.TestCase):
    def prefix(self):
        return {'session_id': 'as' + '1' * 24, 'campaign_id': 'ac' + '2' * 24,
                'lineage_id': 'al' + '3' * 24, 'campaign': {'recovery': 'RECOVERABLE'},
                'budget_prefix': {'events': 8, 'tip': 'a' * 64, 'view': {}},
                'session_prefix': {'events': 6, 'tip': 'b' * 64, 'view': {}},
                'evidence': {'e': 'c' * 64}, 'ledger_contract_hash': 'd' * 64}

    def test_authorization_precedes_qualification(self):
        with patch.object(recovery, 'qualify') as qualify:
            with self.assertRaisesRegex(ValueError, 'EXPLICIT_C3'):
                recovery.create('.', '.', '.', '/tmp/unused')
        qualify.assert_not_called()

    def test_execution_authorization_precedes_contract_read(self):
        with patch.object(recovery, 'validate') as validate:
            with self.assertRaisesRegex(ValueError, 'EXPLICIT_C3_RECOVERY_EXECUTION'):
                recovery.execute('.', 'missing')
        validate.assert_not_called()

    def test_contract_adds_no_authority_and_is_sealed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'external'
            with patch.object(recovery, 'qualify', return_value=self.prefix()), \
                    patch.object(recovery.ex, 'safe_git', return_value='f' * 40):
                value = recovery.create(root, root / 'source', root / 'amendment.json',
                                        destination, authorize=True)
            self.assertEqual(value['authority']['new_sessions'], 0)
            self.assertEqual(value['authority']['new_campaigns'], 0)
            self.assertEqual(value['authority']['new_reservations'], 0)
            self.assertTrue(value['authority']['resume_existing_campaign_only'])
            self.assertEqual(value['hash'], recovery.ex.digest({k: v for k, v in value.items() if k != 'hash'}))

    def test_validation_rejects_changed_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = {'schema': recovery.SCHEMA, 'source_out': str(root / 'source'),
                     'amendment': str(root / 'amendment'), 'commit': 'f' * 40,
                     **self.prefix(), 'authority': {}, 'execution_prohibited': True}
            value['hash'] = recovery.ex.digest(value)
            path = root / 'contract.json'; path.write_text(json.dumps(value))
            changed = self.prefix(); changed['budget_prefix'] = {'events': 9, 'tip': 'e' * 64, 'view': {}}
            with patch.object(recovery, 'qualify', return_value=changed), \
                    patch.object(recovery.ex, 'safe_git', return_value='f' * 40):
                with self.assertRaisesRegex(ValueError, 'PREFIX_CHANGED:budget_prefix'):
                    recovery.validate(root, path)


if __name__ == '__main__':
    unittest.main()
