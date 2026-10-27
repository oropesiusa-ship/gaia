"""Trace terminal reopenings to detect even short-lived process children.

Sampling alone cannot prove zero ephemeral children. strace follows the trusted
terminal CLI from exec through exit. Production calls additionally require the
dedicated Linux subreaper so a timeout cannot leave an unowned process tree.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from tools import stage2_executor as ex


def process_trace(text):
    """Fail closed on incomplete traces and any process creation attempt.

    CLONE_THREAD creates a thread, not a child process, and is reported separately.
    A failed fork attempt still violates the terminal no-action invariant.
    """
    children = []
    threads = []
    execs = []
    exits = []
    incomplete = []
    pending = {}
    for line in text.splitlines():
        # strace interleaves thread exits and clone calls. Reconstruct matched
        # unfinished/resumed pairs instead of treating normal interleaving as
        # missing evidence. A missing or mismatched half still fails closed.
        identity = re.match(r'\s*(\d+)\s+', line)
        pid = identity.group(1) if identity else 'single'
        resumed = re.search(r'<\.\.\. (\w+) resumed>', line)
        if resumed:
            previous = pending.pop(pid, None)
            if previous is None or previous[0] != resumed.group(1):
                incomplete.append(line)
                continue
            line = previous[1].replace('<unfinished ...>', '') + line[resumed.end():]
        if '<unfinished ...>' in line:
            opening = re.search(r'\b(\w+)\(', line)
            if opening is None or pid in pending:
                incomplete.append(line)
            else:
                pending[pid] = (opening.group(1), line)
            continue
        match = re.search(r'\b(clone3?|fork|vfork|execve|execveat|exit_group)\(', line)
        if not match:
            continue
        call = match.group(1)
        if call in ('clone', 'clone3') and 'CLONE_THREAD' in line:
            threads.append(line)
        elif call in ('clone', 'clone3', 'fork', 'vfork'):
            children.append(line)
        elif call in ('execve', 'execveat'):
            execs.append(line)
        else:
            exits.append(line)
    incomplete.extend(row[1] for row in pending.values())
    complete = (len(execs) == 1 and bool(re.search(r'= 0\s*$', execs[0]))
                and len(exits) == 1 and 'exit_group(0)' in exits[0]
                and not incomplete)
    return {'status': 'PASS' if complete and not children else 'FAIL',
            'process_creation_attempts': children, 'thread_creation_calls': len(threads),
            'exec_calls': len(execs), 'complete': complete,
            'incomplete_lines': incomplete}


def traced_terminal_noop(state, campaign_id, paths, trace_path, *, root, boundary):
    """Real CLI replay with immutable owned bytes and process-creation evidence.

    Trace output must be outside all owned evidence roots. The caller archives
    its hash only after the read-only operation; no repair/retry is performed.
    """
    boundary.verify()
    trace_path = Path(trace_path).absolute()
    if any(p.is_symlink() for p in [trace_path, *trace_path.parents]):
        raise ValueError('SYMLINKED_TERMINAL_TRACE')
    for path in [*paths, state]:
        if trace_path.is_relative_to(Path(path).resolve()):
            raise ValueError('TRACE_MUST_BE_OUTSIDE_READ_ONLY_SCOPE')
    if trace_path.exists():
        raise FileExistsError('TERMINAL_TRACE_EXISTS')
    tracer = shutil.which('strace')
    if tracer is None:
        raise ValueError('STRACE_REQUIRED_FOR_EPHEMERAL_CHILD_PROOF')
    # O_EXCL prevents an existing trace from being overwritten.
    fd = os.open(trace_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    boundary.begin()
    captured = []
    unexpected = []
    try:
        def replay(identifier):
            proc = subprocess.Popen(
                [tracer, '-f', '-qq', '-e', 'trace=process', '-o', str(trace_path),
                 sys.executable, '-B', str(Path(root) / 'gaia.py'), 'autonomy-run',
                 identifier, '--state-dir', str(Path(state).resolve()), '--authorize-campaign'],
                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                start_new_session=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
            boundary.attach(proc)
            try:
                stdout, stderr = proc.communicate(timeout=60)
            except BaseException:
                boundary.drain()
                proc.communicate()
                raise
            if proc.returncode:
                raise ValueError('TRACED_TERMINAL_CLI_FAILED:' + stderr[-1000:])
            return json.loads(stdout)

        result = ex.terminal_noop(state, campaign_id, paths, root=root, replay=replay)
    finally:
        captured = boundary.collect()
        controller_pid = getattr(boundary.controller, 'pid', None)
        from gaia.autonomy.supervisor import alive
        unexpected = [row for row in captured if row['pid'] != controller_pid
                      and alive(row['pid'], row['starttime'])]
        boundary.drain()
    trace = process_trace(trace_path.read_text())
    # At normal completion communicate has reaped the tracer. Any other child
    # still present is unexpected, even if draining subsequently succeeds.
    survivors = [row for row in captured if alive(row['pid'], row['starttime'])]
    result.update(execution_path='REAL_CLI_STRACE', trace=trace,
                  trace_sha256=ex.sha(trace_path), survivors=survivors,
                  unexpected_children=unexpected,
                  child_creation_claim='PASS' if trace['status'] == 'PASS' else 'FAIL')
    if trace['status'] != 'PASS' or survivors or unexpected:
        result['status'] = 'FAIL'
        result['result'] = 'TERMINAL_REPLAY_FAILED'
    return result
