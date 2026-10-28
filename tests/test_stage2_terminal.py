"""Synthetic syscall traces, not recovery/campaign evidence."""
import unittest
import json
from pathlib import Path
import shutil
import subprocess
import sys
from test_autonomy_integration import Fixture
from tools.stage2_executor import ROOT
from tools.stage2_terminal import process_trace


class TerminalTraceTests(unittest.TestCase):
    clean = '100 execve("python", ["python"], 0x0) = 0\n100 exit_group(0) = ?\n'

    def test_clean_trace(self):
        self.assertEqual(process_trace(self.clean)['status'], 'PASS')

    def test_even_ephemeral_or_failed_fork_attempts_fail(self):
        for call in ('fork() = 101', 'vfork() = 101',
                     'clone(child_stack=NULL, flags=SIGCHLD) = 101',
                     'clone3({flags=0}, 88) = -1 ENOSYS'):
            with self.subTest(call=call):
                self.assertEqual(process_trace(self.clean + '100 ' + call)['status'], 'FAIL')

    def test_threads_are_not_child_processes(self):
        trace = self.clean + '100 clone(flags=CLONE_VM|CLONE_THREAD) = 101\n'
        result = process_trace(trace)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['thread_creation_calls'], 1)

    def test_interleaved_complete_thread_exits_are_valid(self):
        trace = self.clean + ('101 exit(0 <unfinished ...>\n'
                              '102 exit(0 <unfinished ...>\n'
                              '101 <... exit resumed>) = ?\n'
                              '102 <... exit resumed>) = ?\n')
        self.assertEqual(process_trace(trace)['status'], 'PASS')

    def test_interleaved_fork_still_fails(self):
        trace = self.clean + ('100 clone(flags=SIGCHLD <unfinished ...>\n'
                              '100 <... clone resumed>) = 101\n')
        self.assertEqual(process_trace(trace)['status'], 'FAIL')

    def test_missing_failed_or_additional_exec_and_incomplete_trace_fail(self):
        for text in ('', self.clean.splitlines()[0], self.clean.replace('= 0', '= -1'),
                     self.clean + self.clean,
                     self.clean + '100 clone(<unfinished ...>\n'):
            with self.subTest(text=text):
                self.assertEqual(process_trace(text)['status'], 'FAIL')


class TerminalCLITraceTests(Fixture):
    @unittest.skipUnless(shutil.which('strace'), 'strace unavailable; no ephemeral-child claim')
    def test_terminal_fixture_real_cli_has_no_child_processes(self):
        loop = self.loop(self.lineage()['lineage_id'])
        self.go(loop)
        cid = loop.contract['campaign_id']
        # The boundary must run in a fresh dedicated process, never in unittest.
        script = '''import json,sys
from pathlib import Path
from tools.stage2_children import ChildBoundary
from tools.stage2_terminal import traced_terminal_noop
with ChildBoundary() as boundary:
    result=traced_terminal_noop(Path(sys.argv[1]),sys.argv[2],[Path(sys.argv[1])],
        Path(sys.argv[3]),root=Path.cwd(),boundary=boundary)
print(json.dumps(result))
'''
        result = subprocess.run([sys.executable, '-B', '-c', script, str(self.state), cid,
                                 str(self.root / 'terminal.strace')],
                                cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['status'], 'PASS', value)
        self.assertEqual(value['child_creation_claim'], 'PASS', value)
        self.assertEqual(value['execution_path'], 'REAL_CLI_STRACE')
