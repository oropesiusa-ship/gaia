"""Administrative orchestration entrypoint tests, without campaign execution."""
import subprocess
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import stage2_orchestrator as orchestrator
from tools.stage2_executor import ROOT
from test_autonomy_integration import Fixture
from gaia.autonomy.freeze import freeze
from gaia.autonomy.session import SessionStore, session_contract


class OrchestratorEntrypointTests(unittest.TestCase):
    def archive(self, directory):
        root = Path(directory)
        out = root / '.gaia/stage2/unit'
        out.mkdir(parents=True)
        contract = out / 'contract.json'
        contract.write_text('{}')
        baseline = orchestrator.ex.inventory([out], include_cache=True)
        archive = out / 'boundary'
        archive.mkdir()
        replays = []
        for role in ('S1-C1', 'S1-C2'):
            trace = archive / f'{role}.strace'
            trace.write_text('100 execve("python", [], 0x0) = 0\n100 exit_group(0) = ?\n')
            replays.append({'status': 'PASS', 'child_creation_claim': 'PASS',
                            'trace_sha256': orchestrator.ex.sha(trace)})
        (archive / 'children.jsonl').write_text('\n'.join(json.dumps(row) for row in [
            {'kind': 'CLEANUP_DRAINED', 'kernel_echild': True},
            {'kind': 'CLEANUP_DRAINED', 'kernel_echild': True},
            {'kind': 'SUBREAPER_RESTORED', 'verified': True}]))
        proof = {'status': 'PASS', 'contract_hash': 'fixture', 'containment': 'PASS',
                 'ownership': {'status': 'PASS'},
                 'budget_unchanged': True, 'terminal_replays': replays,
                 'inspection': {'owned_manifest': baseline}}
        (archive / 'result.json').write_text(json.dumps(proof))
        (archive / 'manifest.json').write_text(json.dumps(orchestrator.ex.inventory([archive])))
        return root, out, contract

    def test_verified_boundary_requires_unchanged_original_owned_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root, out, contract = self.archive(directory)
            proof = orchestrator.verified_boundary(root, contract, {'hash': 'fixture'}, [out])
            self.assertEqual(proof['status'], 'PASS')
            contract.write_text('modified')
            with self.assertRaisesRegex(ValueError, 'STATE_CHANGED_AFTER_BOUNDARY'):
                orchestrator.verified_boundary(root, contract, {'hash': 'fixture'}, [out])

    def test_tampered_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, out, contract = self.archive(directory)
            (out / 'boundary/S1-C1.strace').write_text('truncated')
            with self.assertRaisesRegex(ValueError, 'BOUNDARY_ARCHIVE_CHANGED'):
                orchestrator.verified_boundary(root, contract, {'hash': 'fixture'}, [out])

    def test_external_continuation_boundary_preserves_parent_archive(self):
        with tempfile.TemporaryDirectory()as directory:
            root,out,contract=self.archive(directory)
            original=out/'boundary'
            external=root/'.gaia/stage2/continuation/boundary'
            external.parent.mkdir(parents=True)
            original.rename(external)
            # The historical failed archive is part of the immutable owned state.
            original.mkdir();(original/'result.json').write_text('{"status":"BLOCKED_PREEXECUTION"}')
            proof_path=external/'result.json'
            proof=json.loads(proof_path.read_bytes())
            proof['inspection']['owned_manifest']=orchestrator.ex.inventory([out],include_cache=True)
            proof_path.write_text(json.dumps(proof))
            manifest=external/'manifest.json'
            manifest.write_text(json.dumps({p:h for p,h in orchestrator.ex.inventory([external]).items()if p!=str(manifest)}))
            self.assertEqual(orchestrator.verified_boundary(root,contract,{'hash':'fixture'},[out],archive=external)['status'],'PASS')
            (original/'result.json').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'STATE_CHANGED_AFTER_BOUNDARY'):
                orchestrator.verified_boundary(root,contract,{'hash':'fixture'},[out],archive=external)

    def test_explicit_authorization_precedes_reading_any_contract(self):
        with patch.object(orchestrator, 'binding') as read:
            with self.assertRaisesRegex(ValueError, 'EXPLICIT_STAGE2'):
                orchestrator.run_first(ROOT, 'missing', 'missing', 'missing')
        read.assert_not_called()

    def test_unexercised_recovery_blocks_before_frozen_executor(self):
        with patch.object(orchestrator, 'binding', return_value=({}, {})), \
                patch.object(orchestrator, 'verify_recovery', return_value={'status': 'BLOCKED_PREEXECUTION'}), \
                patch.object(orchestrator.ex, 'run_first_session') as run:
            value = orchestrator.run_first(ROOT, 'fixture', 'fixture', 'fixture', authorize=True)
        run.assert_not_called()
        self.assertEqual(value['status'], 'BLOCKED_PREEXECUTION')
        self.assertEqual(value['campaigns_started'], 0)

    def test_imported_orchestrator_refuses_process_ownership_before_io(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'DEDICATED_ORCHESTRATOR_CLI_REQUIRED'):
                orchestrator.boundary(root, root / 'missing.json')
            self.assertEqual(list(root.iterdir()), [])

    def test_second_authorization_and_dedicated_process_precede_io(self):
        with self.assertRaisesRegex(ValueError, 'EXPLICIT_STAGE2_S2'):
            orchestrator.run_second(ROOT, 'missing', 'missing', 'missing')
        with self.assertRaisesRegex(RuntimeError, 'DEDICATED_ORCHESTRATOR'):
            orchestrator.run_second(ROOT, 'missing', 'missing', 'missing', authorize=True)

    def test_cli_exposes_each_separate_operation(self):
        result = subprocess.run([sys.executable, '-B', '-m', 'tools.stage2_orchestrator', '--help'],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('inspect-boundary', result.stdout)
        self.assertIn('run-second-session', result.stdout)

    def test_direct_script_cli_works_from_repository_root(self):
        result = subprocess.run(
            [sys.executable, '-B', 'tools/stage2_orchestrator.py', '--help'],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('inspect-boundary', result.stdout)
        self.assertIn('run-second-session', result.stdout)


class SecondAdmissionTests(Fixture):
    """Real stores, synthetic prior session; never launch a controller."""
    def setup_prior(self):
        out = self.root / '.gaia/stage2/unit'
        out.mkdir(parents=True)
        self.state = out / 'state'
        lin = self.lineage()['lineage_id']
        frozen = freeze(self.root, self.state, [lin])
        first = session_contract([lin], stage='stage2', limits=orchestrator.ex.LIMITS, frozen=frozen)
        store = SessionStore(self.state, first['session_id'])
        store.create(first, self.root)
        (out / 'boundary').mkdir()
        (out / 'boundary/manifest.json').write_text('{}')
        (out.parent / (out.name + '-observer')).mkdir()
        contract = {'hash': 'fixture', 'lineages': [lin], 'state_path': str(self.state),
                    'plan': orchestrator.ex.scratch_plan(out)}
        budget = orchestrator.ex.StageBudget(out / 'budget', 'fixture', [out])
        with budget.exclusive():
            budget.start_session(store.identifier)
            for role, cid in (('S1-C1', 'ac' + '1'*24), ('S1-C2', 'ac' + '2'*24)):
                budget.reserve(store.identifier, role)
                budget.bind(role, cid)
                budget.finish(role, cid, 100)
        return out, store, contract, budget

    def test_boundary_failure_cannot_create_a_second_session_or_lineage(self):
        out, first, contract, budget = self.setup_prior()
        before = orchestrator.ex.inventory([self.state], include_cache=True)
        with patch.object(orchestrator, '__name__', '__main__'), \
                patch.object(orchestrator, 'binding', return_value=(contract, {'hash': 'fixture', 'files': {}})), \
                patch.object(orchestrator, 'verify_recovery', return_value={'status': 'PASS'}), \
                patch.object(orchestrator, 'verified_boundary', side_effect=ValueError('BOUNDARY_CHANGED')):
            with self.assertRaisesRegex(ValueError, 'BOUNDARY_CHANGED'):
                orchestrator.run_second(self.root, out / 'contract.json', 'fixture', 'fixture', authorize=True)
        self.assertEqual(before, orchestrator.ex.inventory([self.state], include_cache=True))
        self.assertEqual(len(budget.view()['sessions']), 1)
        self.assertFalse((out / 'session2-start.json').exists())

    def test_missing_observer_coverage_blocks_before_any_second_session_effect(self):
        out, first, contract, budget = self.setup_prior()
        before = orchestrator.ex.inventory([self.state], include_cache=True)
        with patch.object(orchestrator, '__name__', '__main__'), \
                patch.object(orchestrator, 'binding', return_value=(contract, {'hash': 'fixture', 'files': {}})), \
                patch.object(orchestrator, 'verify_recovery', return_value={'status': 'PASS'}), \
                patch.object(orchestrator, 'verified_boundary', return_value={'inspection': {'session_id': first.identifier}}), \
                patch('tools.stage2_observer.audit_observer', return_value={'status': 'INCONCLUSIVE_ENVIRONMENT'}):
            result = orchestrator.run_second(self.root, out / 'contract.json', 'fixture', 'fixture', authorize=True)
        self.assertEqual(result['status'], 'BLOCKED_PREEXECUTION')
        self.assertEqual(before, orchestrator.ex.inventory([self.state], include_cache=True))
        self.assertEqual(len(budget.view()['sessions']), 1)
        self.assertFalse((out / 'session2-start.json').exists())
