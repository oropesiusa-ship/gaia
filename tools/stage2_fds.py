"""Verified custody descriptors, separate from the unchanged +5 FD leak band.

Raw counts are always retained. Only a non-inheritable kernel pidfd, pinned by
the dedicated ChildBoundary to a captured identity, can be accounted separately.
Offline readers additionally require the matching immutable capture event.
"""
import os
from pathlib import Path

from gaia.autonomy.supervisor import proc_info

SCHEMA = 'gaia_owned_pidfd_accounting_v1'
LINK = 'anon_inode:[pidfd]'


def kernel_pid(fd):
    fields = dict(line.split(':', 1) for line in Path(f'/proc/self/fdinfo/{fd}').read_text().splitlines() if ':' in line)
    if 'Pid' not in fields:
        raise ValueError('PIDFD_KERNEL_IDENTITY_MISSING')
    return int(fields['Pid'].strip())


def with_owned_pidfds(metrics, boundary):
    """Live measurement; no descriptor is closed, adopted or signalled here."""
    metrics = dict(metrics)
    if metrics.get('pid') != os.getpid() or type(metrics.get('fds')) is not int:
        raise RuntimeError('FD_MEASUREMENT_UNAVAILABLE')
    pinned = []
    active = False
    if boundary is not None:
        boundary.verify()
        if boundary.pid != os.getpid():
            raise RuntimeError('FD_CUSTODIAN_IDENTITY_MISMATCH')
        active = boundary.active
        if not active and boundary.fds:
            raise RuntimeError('PIDFDS_OUTSIDE_OWNERSHIP_EPOCH')
        for pid, fd in boundary.fds.items():
            row = boundary.owned[pid]
            stat = os.fstat(fd)
            identity = [stat.st_dev, stat.st_ino]
            if (row.get('pidfd') != fd or row.get('pidfd_identity') != identity
                    or row.get('role') != 'OWNED_CHILD'
                    or row.get('custodian_pid') != metrics['pid']
                    or row.get('custodian_starttime') != metrics['start_time']
                    or os.readlink(f'/proc/self/fd/{fd}') != LINK or os.get_inheritable(fd)):
                raise RuntimeError('UNVERIFIED_CUSTODY_DESCRIPTOR')
            target = kernel_pid(fd)
            if target == pid:
                current = proc_info(pid)
                if current is None:
                    # A worker can be reaped by its controller between reads.
                    target = kernel_pid(fd)
                    if target != -1:
                        raise RuntimeError('PIDFD_PROCESS_IDENTITY_UNAVAILABLE')
                elif current[7] != row['starttime']:
                    raise RuntimeError('PIDFD_PROCESS_IDENTITY_CHANGED')
            if target not in (pid, -1):
                raise RuntimeError('PIDFD_TARGET_MISMATCH')
            pinned.append({'fd': fd, 'pid': pid, 'start_time': row['starttime'],
                           'identity': identity, 'kernel_pid': target, 'link': LINK, 'cloexec': True})
    if len(pinned) > metrics['fds']:
        raise RuntimeError('FD_COUNT_INCONSISTENT')
    metrics['fd_accounting'] = {'schema': SCHEMA, 'owner_pid': metrics['pid'],
        'owner_start_time': metrics['start_time'], 'active_epoch': active,
        'raw_fds': metrics['fds'], 'pidfds': pinned,
        'unaccounted_fds': metrics['fds'] - len(pinned)}
    return metrics


def fd_count(metrics, *, captures=None, clock=None, required=False, idle=False):
    """Offline validation; missing custody evidence never earns a subtraction."""
    if not isinstance(metrics,dict):
        raise ValueError('INVALID_FD_MEASUREMENT')
    raw = metrics.get('fds')
    if type(raw) is not int or raw < 0:
        raise ValueError('INVALID_RAW_FD_COUNT')
    data = metrics.get('fd_accounting')
    if data is None:
        if required:
            raise ValueError('FD_ACCOUNTING_MISSING')
        return raw  # Historical evidence keeps the original strict raw band.
    if not isinstance(data,dict) or (captures is not None and not isinstance(captures,list)):
        raise ValueError('INVALID_FD_ACCOUNTING_OR_CAPTURE_JOURNAL')
    if (data.get('schema') != SCHEMA or data.get('raw_fds') != raw
            or type(data.get('raw_fds')) is not int or type(data.get('unaccounted_fds')) is not int
            or type(data.get('owner_pid')) is not int or data['owner_pid'] <= 0
            or type(data.get('owner_start_time')) is not int or data['owner_start_time'] < 0
            or data.get('owner_pid') != metrics.get('pid')
            or data.get('owner_start_time') != metrics.get('start_time')
            or type(data.get('active_epoch')) is not bool
            or not isinstance(data.get('pidfds'), list)):
        raise ValueError('INVALID_FD_ACCOUNTING')
    rows = data['pidfds']
    if (idle or not data['active_epoch']) and rows:
        raise ValueError('CUSTODY_DESCRIPTORS_REMAIN_AT_IDLE')
    if idle and data['active_epoch']:
        raise ValueError('OWNERSHIP_EPOCH_REMAINS_AT_IDLE')
    if len(rows) > raw or data.get('unaccounted_fds') != raw - len(rows):
        raise ValueError('FD_ACCOUNTING_ARITHMETIC_MISMATCH')
    seen_fds, seen_pids = set(), set()
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError('INVALID_PIDFD_PROOF')
        if (any(type(row.get(k)) is not int for k in ('fd', 'pid', 'start_time', 'kernel_pid'))
                or row['fd'] < 0 or row['pid'] <= 0 or row['start_time'] < 0
                or row.get('link') != LINK or row.get('cloexec') is not True
                or row['kernel_pid'] not in (row['pid'], -1)
                or not isinstance(row.get('identity'), list) or len(row['identity']) != 2
                or any(type(value) is not int or value < 0 for value in row['identity'])
                or row['fd'] in seen_fds or row['pid'] in seen_pids):
            raise ValueError('INVALID_PIDFD_PROOF')
        seen_fds.add(row['fd']); seen_pids.add(row['pid'])
        matches = [event for event in captures or [] if isinstance(event,dict) and event.get('kind') == 'CHILD_CAPTURED'
            and event.get('role') == 'OWNED_CHILD'
            and event.get('pid') == row['pid'] and event.get('starttime') == row['start_time']
            and event.get('pidfd') == row['fd'] and event.get('pidfd_identity') == row['identity']
            and event.get('custodian_pid') == data['owner_pid']
            and event.get('custodian_starttime') == data['owner_start_time']]
        if clock is not None:
            matches = [event for event in matches if isinstance(event.get('clock'),dict) and event['clock'].get('boot_id') == clock['boot_id']
                       and event['clock']['monotonic'] <= clock['monotonic']]
        if not matches:
            raise ValueError('PIDFD_CAPTURE_EVIDENCE_MISSING')
    return data['unaccounted_fds']


def capture_events(state, session):
    """S1 has the live subreaper journal; S2 archives its pre-audit captures."""
    import json
    archived = session.root / 'evidence/pidfd-captures.json'
    if any(path.is_symlink() for path in [archived,*archived.parents]):
        raise ValueError('SYMLINKED_PIDFD_CAPTURE_JOURNAL')
    if archived.exists():
        return json.loads(archived.read_bytes())
    path = Path(state).parent / 'subreaper.jsonl'
    if any(parent.is_symlink() for parent in [path,*path.parents]):
        raise ValueError('SYMLINKED_PIDFD_CAPTURE_JOURNAL')
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
