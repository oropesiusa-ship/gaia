"""Administrative amendment rejection tests; no real execution authorized."""
import tempfile
import unittest
import json
from unittest.mock import Mock,patch
from pathlib import Path
from tools import stage2_continuation as continuation
from tools.stage2_boundary import verify_manifest


class ContinuationTests(unittest.TestCase):
    def test_authorization_is_required_before_any_io(self):
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION_REQUIRED'):
            continuation.create('/missing','/missing','/missing','/missing')

    def test_only_authenticated_archive_additions_are_excluded(self):
        verify_manifest({'s1':'old'},{'s1':'old','archive':'receipt','manifest':'own'},
                        Path('manifest'),additional={'archive':'receipt'})
        for actual in ({'s1':'changed','archive':'receipt'},
                       {'s1':'old','archive':'changed'},
                       {'s1':'old','archive':'receipt','unknown':'extra'}):
            with self.subTest(actual=actual),self.assertRaises(ValueError):
                verify_manifest({'s1':'old'},actual,Path('manifest'),additional={'archive':'receipt'})

    def test_archive_exclusion_cannot_overlap_original_s1(self):
        with self.assertRaisesRegex(ValueError,'OVERLAPS_S1'):
            verify_manifest({'s1':'old'},{'s1':'old'},Path('manifest'),additional={'s1':'old'})

    def test_sealed_amendment_detects_budget_reset_tampering(self):
        value={'reservation_reset':False,'budget_prefix':{'events':5,'tip':'original'}}
        value['hash']=continuation.ex.digest(value)
        continuation.sealed(value)
        value['budget_prefix']['tip']='reset'
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):continuation.sealed(value)

    def test_archive_manifest_rejects_unknown_and_modified_files(self):
        with tempfile.TemporaryDirectory()as directory:
            out=Path(directory);receipt=out/'result.json';receipt.write_text('{}')
            continuation.durable(out/'manifest.json',{str(receipt):continuation.ex.sha(receipt)},True)
            continuation.archive_manifest(out)
            receipt.write_text('tampered')
            with self.assertRaisesRegex(ValueError,'ARCHIVE_CHANGED'):continuation.archive_manifest(out)

    def test_validation_keeps_original_ledger_and_rejects_prefix_or_reservation_changes(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);out=root/'parent';out.mkdir()
            contract_path=out/'contract.json';contract_path.write_text('{}')
            (out/'manifest-s1.json').write_text('{}');(out/'result-s1.json').write_text('{}')
            amendment=root/'continuation/amendment.json';amendment.parent.mkdir()
            parent={'hash':'original-ledger','state_path':str(out/'state')}
            effective={'hash':'effective-s2'}
            protocol={'files':{},'base_contract_hash':'original-ledger'}
            protocol['hash']=continuation.ex.digest(protocol)
            current_protocol={'files':{},'base_contract_hash':'effective-s2'}
            current_protocol['hash']=continuation.ex.digest(current_protocol)
            value={'schema':'gaia_stage2_administrative_continuation_v1',
                'parent_contract_path':str(contract_path),'parent_contract_hash':'original-ledger',
                'parent_orchestration_hash':protocol['hash'],'s2_commit':'current','changed_files':[],
                'execution_prohibited':True,'reservation_reset':False,'s1_execution_repeated':False,
                's2_boundary_path':str(amendment.parent/'boundary'),'contract':effective,'protocol':current_protocol,
                's1_manifest_sha256':continuation.ex.sha(out/'manifest-s1.json'),
                's1_result_sha256':continuation.ex.sha(out/'result-s1.json'),
                'prior_boundary_archive':{},'budget_prefix':{'events':1,'tip':'old-tip','view':{'remaining_compute_s':3600}}}
            value['hash']=continuation.ex.digest(value);amendment.write_text(json.dumps(value))
            budget=Mock();budget.events.return_value=[{'hash':'old-tip'}]
            budget.view.return_value={'remaining_compute_s':3600}
            with patch.object(continuation.ex,'safe_out',side_effect=lambda root,path:path),\
                 patch.object(continuation,'parent_binding',return_value=(parent,protocol)),\
                 patch.object(continuation,'change_scope',return_value=('current',[])),\
                 patch.object(continuation,'tool_hashes',return_value={}),\
                 patch.object(continuation.ex,'validate_contract',side_effect=lambda value:value),\
                 patch.object(continuation,'effective_contract',return_value=effective),\
                 patch.object(continuation,'archive_manifest',return_value={}),\
                 patch.object(continuation,'roots_for',return_value=[out]),\
                 patch.object(continuation.ex,'StageBudget',return_value=budget)as construct,\
                 patch.object(continuation,'original_s1')as reaudit:
                result=continuation.validate(root,contract_path,amendment)
                self.assertEqual(result['ledger_hash'],'original-ledger')
                self.assertEqual(construct.call_args.args[1],'original-ledger')
                reaudit.assert_called_once()
                budget.events.return_value=[{'hash':'replaced-tip'}]
                with self.assertRaisesRegex(ValueError,'PREFIX_CHANGED'):
                    continuation.validate(root,contract_path,amendment)
                budget.events.return_value=[{'hash':'old-tip'},{'hash':'unexpected-append'}]
                with self.assertRaisesRegex(ValueError,'BUDGET_CHANGED_BEFORE'):
                    continuation.validate(root,contract_path,amendment)
                budget.events.return_value=[{'hash':'old-tip'}]
                budget.view.return_value={'remaining_compute_s':7200}
                with self.assertRaisesRegex(ValueError,'BUDGET_CHANGED_BEFORE'):
                    continuation.validate(root,contract_path,amendment)
