"""Read-only ownership attribution outside the frozen S1 supervisor.

10 s process/lock/storage cadence, GPU process accounting every 30 s. Sampling
is polling, not a physical quota. Only the wrapper's own Popen is terminated
on a safety stop; observing a foreign owner never grants signal authority.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from tools import stage2_executor as ex
from tools.stage2_runtime import process_metrics
from tools.stage2_session2 import experiment_process
from gaia.autonomy.clock import stamp
from gaia.autonomy.supervisor import processes, tree, proc_info, role
from gaia.autonomy.store import durable
from tools.stage2_fds import fd_count


def lock_holders(paths, text, table, owned, current_info=None):
    locks = {}
    for path in paths:
        path = Path(path)
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError('SYMLINKED_OBSERVED_LOCK')
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        key = (os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino)
        locks[key] = {'path': str(path), 'identity': list(key), 'holders': []}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) > 1 and fields[1] == '->':
            continue  # Waiting request, not a held lock.
        if len(fields) < 6:
            raise ValueError('MALFORMED_PROC_LOCKS')
        device = fields[5].split(':')
        if len(device) != 3:
            raise ValueError('MALFORMED_PROC_LOCK_DEVICE')
        key = (int(device[0], 16), int(device[1], 16), int(device[2]))
        if key not in locks:
            continue
        pid = int(fields[4])
        info = table.get(pid)
        if current_info is not None:
            current = current_info(pid)
            if info is None or current is None or info[7] != current[7]:
                info = None
        ours = info is not None and owned.get(pid) == info[7]
        locks[key]['holders'].append({'pid': pid, 'start_time': info[7] if info else None,
            'ownership': 'OWNED' if ours else 'FOREIGN' if info else 'UNKNOWN'})
    return list(locks.values())


def gpu_processes():
    """nvidia-smi XML includes graphics as well as compute processes."""
    try:
        run = subprocess.run(['nvidia-smi', '-q', '-x'], capture_output=True, text=True, timeout=5)
        if run.returncode:
            raise ValueError('GPU_ACCOUNTING_UNAVAILABLE')
        xml = ET.fromstring(run.stdout)
        rows = []
        for gpu in xml.findall('gpu'):
            processes_node = gpu.find('processes')
            if processes_node is None:
                raise ValueError('GPU_PROCESS_ACCOUNTING_MISSING')
            if (processes_node.text or '').strip() == 'N/A':
                raise ValueError('GPU_PROCESS_ACCOUNTING_UNAVAILABLE')
            for process in processes_node.findall('process_info'):
                pid = int(process.findtext('pid'))
                memory = process.findtext('used_memory')
                if memory is None or not memory.endswith(' MiB'):
                    raise ValueError('GPU_PROCESS_MEMORY_UNAVAILABLE')
                info = proc_info(pid)
                rows.append({'gpu': gpu.attrib['id'], 'pid': pid,
                             'used_mib': int(memory[:-4]),
                             'start_time': info[7] if info else None})
        if not xml.findall('gpu'):
            raise ValueError('GPU_INVENTORY_MISSING')
        return {'status': 'PASS', 'processes': rows}
    except (OSError, ValueError, TypeError, ET.ParseError, subprocess.SubprocessError) as exc:
        return {'status': 'INCONCLUSIVE_ENVIRONMENT', 'error': str(exc), 'processes': []}


def snapshot_descendants(table, controller_pid):
    """Resolve descendants from one coherent process snapshot.

    Calling ``processes()`` and then ``tree()`` takes two censuses. Short-lived
    bwrap/worker children can be present in the first but absent from the
    second, producing a false foreign-process result. Build the closure from
    the same table used for foreign detection and verify every identity again.
    """
    selected = {controller_pid}
    changed = True
    while changed:
        changed = False
        for pid, info in table.items():
            if pid not in selected and info[0] in selected:
                selected.add(pid); changed = True
    rows = []
    for pid in selected:
        info = table.get(pid)
        current = proc_info(pid)
        if info is None or current is None or current[7] != info[7]:
            continue
        rows.append({'pid': pid, 'ppid': info[0], 'pgid': info[1], 'sid': info[2],
                     'rss_bytes': info[3], 'fds': info[4], 'role': role(info[5]),
                     'cmd': info[5][:200], 'state': info[6], 'starttime': info[7]})
    return rows


def sample(root, state, controller_pid, *, gpu=False, terminal=False, supervisor_metrics=None):
    table = processes()
    ancestry = snapshot_descendants(table, controller_pid)
    owned = {row['pid']: row['starttime'] for row in ancestry}
    paths = [Path(root) / '.gaia/locks/experiment.lock', Path(state).parent / 'budget/.lock',
             *Path(state).rglob('.lock')]
    holders = lock_holders(paths, Path('/proc/locks').read_text(), table, owned, current_info=proc_info)
    foreign = {pid: {'start_time': info[7], 'role': role(info[5])}
               for pid, info in table.items() if owned.get(pid) != info[7] and info[6] != 'Z'
               and (experiment_process(info[5]) or role(info[5]) == 'BACKEND')}
    failures = []
    if any(holder['ownership'] != 'OWNED' for row in holders for holder in row['holders']):
        failures.append('LOCK_HOLDER_NOT_OWNED_OR_UNATTRIBUTABLE')
    if foreign:
        failures.append('EXTERNAL_EXPERIMENT_OR_BACKEND')
    if not terminal and controller_pid not in table:
        failures.append('OBSERVED_CONTROLLER_MISSING')
    value = {'clock': stamp(), 'kind': 'ATTRIBUTION', 'controller_pid': controller_pid,
             'terminal': terminal, 'processes': [{**row, **process_metrics(row['pid'])} for row in ancestry],
             'observer': supervisor_metrics if supervisor_metrics is not None else process_metrics(os.getpid()),
             'locks': holders, 'foreign_experiments': foreign, 'failures': failures}
    if gpu:
        value['gpu'] = gpu_processes()
        for row in value['gpu']['processes']:
            row['ownership'] = 'OWNED' if row['start_time'] is not None and owned.get(row['pid']) == row['start_time'] else 'FOREIGN'
            if row['start_time'] is None:
                value['gpu']['status'] = 'INCONCLUSIVE_ENVIRONMENT'
        if value['gpu']['status'] != 'PASS':
            failures.append('GPU_OWNERSHIP_ACCOUNTING_UNAVAILABLE')
    value['status'] = 'PASS' if not failures else 'INCONCLUSIVE_ENVIRONMENT'
    return value


def coverage(rows,captures=None):
    failures = []
    if len(rows) < 2:
        failures.append('ATTRIBUTION_NOT_EXERCISED')
    if any(row.get('status') != 'PASS' for row in rows):
        failures.append('ATTRIBUTION_INCOMPLETE_OR_FOREIGN_ACTIVITY')
    clocks = [row['clock'] for row in rows]
    if len({clock['boot_id'] for clock in clocks}) != 1:
        failures.append('ATTRIBUTION_BOOT_DISCONTINUITY')
    if any(not 0 <= b['monotonic'] - a['monotonic'] < 20 for a, b in zip(clocks, clocks[1:])):
        failures.append('ATTRIBUTION_OBSERVATION_GAP')
    gpu = [row for row in rows if 'gpu' in row]
    if len(gpu) < 2 or any(row['gpu']['status'] != 'PASS' for row in gpu):
        failures.append('GPU_ATTRIBUTION_INCOMPLETE')
    if any(b['clock']['monotonic'] - a['clock']['monotonic'] >= 60 for a, b in zip(gpu, gpu[1:])):
        failures.append('GPU_ATTRIBUTION_GAP')
    identities = {}
    for row in rows:
        for lock in row['locks']:
            previous = identities.setdefault(lock['path'], lock['identity'])
            if previous != lock['identity']:
                failures.append('LOCK_IDENTITY_CHANGED')
    observers = [row for row in rows if 'observer' in row]
    if len(observers) != len(rows):
        failures.append('OBSERVER_METRICS_MISSING')
    if observers:
        initial = observers[0]['observer']
        if len({(row['observer'].get('pid'), row['observer'].get('start_time')) for row in observers}) != 1:
            failures.append('OBSERVER_IDENTITY_CHANGED')
        if any(row['observer'].get('rss_bytes') is None or row['observer'].get('pss_bytes') is None
               or row['observer'].get('fds') is None for row in observers):
            failures.append('OBSERVER_METRICS_INCOMPLETE')
        else:
            counts=[]
            for row in observers:
                try:counts.append(fd_count(row['observer'],captures=captures,clock=row['clock']))
                except (ValueError,KeyError,TypeError)as exc:
                    failures.append('OBSERVER_FD_ACCOUNTING_INVALID:'+str(exc))
                    counts.append(row['observer']['fds'])
            if max(row['observer']['rss_bytes'] for row in observers) - initial['rss_bytes'] > max(64*2**20, .2*initial['rss_bytes']):
                failures.append('OBSERVER_RSS_BAND')
            if max(counts) - counts[0] > 5:
                failures.append('OBSERVER_FD_BAND')
            warm = [row for row in observers if row['clock']['monotonic'] >= observers[0]['clock']['monotonic'] + 300]
            if len(warm) > 1:
                x = [row['clock']['monotonic'] for row in warm]
                y = [row['observer']['rss_bytes'] for row in warm]
                xm, ym = sum(x)/len(x), sum(y)/len(y)
                denominator = sum((value-xm)**2 for value in x)
                slope = sum((a-xm)*(b-ym) for a, b in zip(x, y))/denominator*3600 if denominator else 0
                if slope > 2**20:
                    failures.append('OBSERVER_RSS_SLOPE')
    violation = any(reason in failures for reason in ('OBSERVER_RSS_BAND', 'OBSERVER_FD_BAND',
                    'OBSERVER_RSS_SLOPE', 'LOCK_IDENTITY_CHANGED'))
    return {'status': 'FAIL' if violation else 'INCONCLUSIVE_ENVIRONMENT' if failures else 'PASS',
            'failures': sorted(set(failures)), 'samples': len(rows), 'gpu_samples': len(gpu)}


def audit_observer(directory, contract_hash, *, started, stopped):
    """Replay external observation rather than trust its saved PASS label."""
    directory = Path(directory).resolve()
    manifest_path = directory / 'manifest.json'
    expected = json.loads(manifest_path.read_bytes())
    actual = ex.inventory([directory], include_cache=True)
    def canonical(items):
        result = {}
        for name, value in items.items():
            path = Path(name)
            path = path.resolve() if path.is_absolute() else (ex.ROOT / path).resolve()
            if not path.is_relative_to(directory):
                raise ValueError('OBSERVER_MANIFEST_PATH_OUTSIDE_ARCHIVE')
            relative = str(path.relative_to(directory))
            if relative in result:
                raise ValueError('OBSERVER_MANIFEST_DUPLICATE_PATH')
            result[relative] = value
        return result
    actual = {p: h for p, h in actual.items() if Path(p).resolve() != manifest_path}
    if canonical(actual) != canonical(expected):
        raise ValueError('OBSERVER_MANIFEST_CHANGED')
    report = json.loads((directory / 'result.json').read_bytes())
    if report.get('contract_hash') != contract_hash or report.get('returncode') != 0 or report.get('error'):
        raise ValueError('OBSERVER_RUN_NOT_VALID')
    rows = [json.loads(line) for line in (directory / 'samples.jsonl').read_text().splitlines()]
    result = coverage(rows)
    if (not rows or rows[0]['clock']['boot_id'] != started['boot_id']
            or rows[-1]['clock']['boot_id'] != stopped['boot_id']
            or rows[0]['clock']['monotonic'] > started['monotonic']
            or rows[-1]['clock']['monotonic'] < stopped['monotonic']):
        if result['status'] != 'FAIL':
            result.update(status='INCONCLUSIVE_ENVIRONMENT')
        result['failures'].append('OBSERVER_DOES_NOT_COVER_FULL_SESSION')
    return result


def observed_first(root, contract_path, contract):
    """External observer: no changes to the frozen S1 runtime or its snapshot."""
    root, contract_path = Path(root), Path(contract_path)
    out = contract_path.parent
    observer = out.parent / (out.name + '-observer')
    observer.mkdir(mode=0o700)  # No retry/adoption of an existing observation.
    state = Path(contract['state_path'])
    from gaia.autonomy.lineage import engine_state_dir
    roots = [out, observer, *[root / engine_state_dir(lin) for lin in contract['lineages']]]
    budget = ex.StageBudget(out / 'budget', contract['hash'], roots)
    command = [sys.executable, '-B', '-m', 'tools.stage2_runtime', '--contract', str(contract_path),
               '--authorize-stage2-s1']
    with (observer / 'stdout.json').open('x') as stdout, (observer / 'stderr.log').open('x') as stderr:
        proc = subprocess.Popen(command, cwd=root, stdout=stdout, stderr=stderr,
            start_new_session=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        error = None
        try:
            index = 0
            while proc.poll() is None:
                row = sample(root, state, proc.pid, gpu=index % 3 == 0)
                with (observer / 'samples.jsonl').open('a') as stream:
                    stream.write(json.dumps(row, sort_keys=True) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                if budget.storage() >= 4 * 2**30:
                    raise RuntimeError('STAGE_STORAGE_EXCEEDED')
                if row['status'] != 'PASS':
                    raise RuntimeError('ATTRIBUTION_SAFETY_STOP')
                index += 1
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
        except BaseException as exc:
            error = f'{type(exc).__name__}: {exc}'
            if proc.poll() is None:
                proc.terminate()  # This exact Popen only; never a foreign owner.
        finally:
            proc.wait()  # Dedicated runtime drains its own descendants.
    terminal = sample(root, state, proc.pid, gpu=True, terminal=True)
    with (observer / 'samples.jsonl').open('a') as stream:
        stream.write(json.dumps(terminal, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    rows = [json.loads(line) for line in (observer / 'samples.jsonl').read_text().splitlines()]
    audit = coverage(rows)
    durable(observer / 'result.json', {'status': audit['status'], 'coverage': audit,
        'returncode': proc.returncode, 'error': error, 'contract_hash': contract['hash']}, True)
    durable(observer / 'manifest.json', ex.inventory([observer], include_cache=True), True)
    if proc.returncode or error or audit['status'] != 'PASS':
        failed = (audit['status'] == 'FAIL' or bool(error and 'STAGE_STORAGE_EXCEEDED' in error)
                  or (proc.returncode != 0 and error is None))
        return {'status': 'FAIL' if failed else 'INCONCLUSIVE_ENVIRONMENT', 'observer': audit, 'error': error,
                'final_stage2_status': 'NOT_EXERCISED'}
    return json.loads((observer / 'stdout.json').read_bytes())
