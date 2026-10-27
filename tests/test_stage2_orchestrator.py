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

    def test_explicit_authorization_precedes_reading_any_contract(self):
        with patch.object(orchestrator, 'binding') as read:
            with self.assertRaisesRegex(ValueError, 'EXPLICIT_STAGE2'):
                orchestrator.run_first(ROOT, 'missing', 'missing', 'missing')
        read.assert_not_called()

    def test_unexercised_recovery_blocks_before_frozen_executor(self):
        with patch.object(orchestrator, 'binding'), \
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
