#!/usr/bin/env python3
"""Explicit, lossless scratch relocation. No deletion and no GAIA/session execution."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import shutil
from contextlib import contextmanager

from tools.inventory_backend_scratch import snapshot, processes, sha


def write_new(path, value):
    data = json.dumps(value, indent=2, sort_keys=True).encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(Path(path).parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_mkdir(path):
    path = Path(path)
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise ValueError('INVALID_DIRECTORY')
        return
    durable_mkdir(path.parent)
    path.mkdir()
    sync_directory(path.parent)
    sync_directory(path)


def evidence_manifest(root):
    result = {}
    for base in [root / 'docs', root / '.gaia/stage0', root / '.gaia/stage1']:
        if base.exists():
            for row in snapshot(base):
                if row['kind'] == 'file':
                    result[str(base / row['path'])] = row['sha256']
    smoke = root / 'state_local_intelligence/discovery/smoke-mistralrs-CPU.json'
    if smoke.exists():
        result[str(smoke)] = sha(smoke.read_bytes())
    return result


def preserved_entries(rows):
    # Root ctime changes when renamed. Child inode/device/hash/size/timestamps and
    # all directory names must remain intact; atime is not restored by writing.
    keys = ('path', 'kind', 'inode', 'device', 'uid', 'gid', 'mode', 'size_bytes',
            'sha256', 'mtime_ns', 'ctime_ns')
    return [{k: v for k, v in r.items() if k in keys and not (r['path'] == '.' and k == 'ctime_ns')}
            for r in rows]


def inspect_archive(destination):
    """Read-only recovery inspection; never guesses or automatically rolls back."""
    destination = Path(destination)
    before = json.loads((destination / 'manifest-before.json').read_bytes())
    work = destination / 'work'
    after = snapshot(work) if work.exists() else []
    if before.get('method') == 'VERIFIED_COPY_ORIGINALS_UNTOUCHED':
        intact = work.exists() and content_manifest(before['inventory']) == content_manifest(after)
    else:
        intact = work.exists() and preserved_entries(before['inventory']) == preserved_entries(after)
    return {'status': 'ARCHIVE_INTACT' if intact else 'NEEDS_OPERATOR_RECOVERY',
            'receipt_present': (destination / 'receipt.json').exists(),
            'automatic_recovery': False, 'archive': str(work)}


@contextmanager
def exclusive_host(root):
    from gaia.autonomy.lineage import host_experiment_lock
    with host_experiment_lock(root):
        yield


def content_manifest(rows):
    return {r['path']: (r['size_bytes'], r['sha256']) for r in rows if r['kind'] == 'file'}


def archive(root, destination, *, apply=False):
    root = Path(root).absolute()
    with exclusive_host(root):
        return _archive(root, destination, apply=apply)


def copy_archive(root, destination, *, apply=False):
    """Retain unknown historical data without requiring authority to move it.

    Originals remain in place even on interrupted/inconsistent copies. This mode
    never asserts stale ownership or opens the historical root for Stage2 work.
    """
    root, destination = Path(root).absolute(), Path(destination).absolute()
    if '..' in root.parts or '..' in destination.parts:
        raise ValueError('ARCHIVE_PATH_TRAVERSAL')
    if not destination.is_relative_to(root / '.gaia/archives') or destination == root / '.gaia/archives':
        raise ValueError('ARCHIVE_MUST_BE_UNDER_GAIA_ARCHIVES')
    source = root / 'state_local_intelligence/work'
    if any(p.is_symlink() for path in (source, destination) for p in [path, *path.parents]):
        raise ValueError('SYMLINK_ARCHIVE_PATH')
    if destination.exists():
        raise FileExistsError('ARCHIVE_ALREADY_EXISTS')
    before = snapshot(source)
    if any(r['kind'] not in ('file', 'directory') for r in before):
        raise ValueError('SPECIAL_OR_SYMLINK_SCRATCH_REFUSED')
    if not apply:
        return {'status': 'DRY_RUN', 'method': 'VERIFIED_COPY_ORIGINALS_UNTOUCHED'}
    durable_mkdir(destination)
    evidence = evidence_manifest(root)
    refs = subprocess.run(['git', 'show-ref', '--head'], cwd=root, capture_output=True, text=True).stdout
    record = {'method': 'VERIFIED_COPY_ORIGINALS_UNTOUCHED', 'source': str(source),
              'destination': str(destination / 'work'), 'inventory': before,
              'process_snapshot': processes(source), 'preserved_certification_evidence': evidence,
              'git_refs_before': refs, 'timestamp': datetime.now(timezone.utc).isoformat(),
              'policy': 'OPERATOR_AUTHORIZED_RETAIN_ALL_UNKNOWN_NO_DELETE_OR_MOVE'}
    write_new(destination / 'manifest-before.json', record)
    shutil.copytree(source, destination / 'work', copy_function=shutil.copy2)
    for path in (destination / 'work').rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    directories = [p for p in (destination / 'work').rglob('*') if p.is_dir()]
    for path in [*sorted(directories, key=lambda p: len(p.parts), reverse=True), destination / 'work', destination]:
        sync_directory(path)
    after = snapshot(destination / 'work')
    originals_after = snapshot(source)
    evidence_after = evidence_manifest(root)
    refs_after = subprocess.run(['git', 'show-ref', '--head'], cwd=root, capture_output=True, text=True).stdout
    originals_intact = preserved_entries(before) == preserved_entries(originals_after)
    copied = content_manifest(before) == content_manifest(after)
    directories_intact = {r['path'] for r in before if r['kind'] == 'directory'} == {r['path'] for r in after if r['kind'] == 'directory'}
    good = originals_intact and copied and directories_intact and evidence == evidence_after and refs == refs_after
    write_new(destination / 'manifest-after.json', {'inventory': after,
              'originals_after': originals_after, 'certification_evidence': evidence_after})
    write_new(destination / 'original-path-locator.json', {
        'original_root_retained': str(source), 'archive_copy_root': str(destination / 'work'),
        'mapping_rule': 'same relative path; originals remain authoritative, verified copy is retention fallback',
        'manifest_before_sha256': sha((destination / 'manifest-before.json').read_bytes()),
        'manifest_after_sha256': sha((destination / 'manifest-after.json').read_bytes())})
    result = {'status': 'ARCHIVED_COPY_VERIFIED' if good else 'FAIL', 'deleted_files': 0,
              'moved_files': 0, 'files': len(content_manifest(before)), 'archive': str(destination / 'work'),
              'originals_retained': str(source), 'originals_inode_metadata_content_unchanged': originals_intact,
              'copied_content_and_directory_names_verified': copied and directories_intact,
              'certification_evidence_unchanged': evidence == evidence_after, 'git_refs_unchanged': refs == refs_after,
              'stage2_executed': False}
    write_new(destination / 'receipt.json', result)
    if not good:
        raise ValueError('ARCHIVE_COPY_INCONSISTENT_PRESERVE_ORIGINALS_AND_COPY')
    return result


def _archive(root, destination, *, apply=False):
    root, destination = Path(root).absolute(), Path(destination).absolute()
    if '..' in destination.parts or '..' in root.parts:
        raise ValueError('ARCHIVE_PATH_TRAVERSAL')
    source = root / 'state_local_intelligence/work'
    allowed = root / '.gaia/archives'
    if not destination.is_relative_to(allowed) or destination == allowed:
        raise ValueError('ARCHIVE_MUST_BE_UNDER_GAIA_ARCHIVES')
    for path in (source, destination):
        if any(p.is_symlink() for p in [path, *path.parents]):
            raise ValueError('SYMLINK_ARCHIVE_PATH')
    if destination.exists():
        raise FileExistsError('ARCHIVE_ALREADY_EXISTS')
    before = snapshot(source)
    proc = processes(source)
    if proc['scratch_references'] or proc['backend_candidates']:
        raise ValueError('ACTIVE_SCRATCH_OR_BACKEND_REFUSED')
    unreadable_same_uid = []
    for row in proc.get('unreadable_processes', []):
        try:
            if Path('/proc', str(row['pid'])).stat().st_uid == os.geteuid():
                unreadable_same_uid.append(row)
        except FileNotFoundError:
            pass
    if unreadable_same_uid:
        raise ValueError('UNREADABLE_SAME_UID_PROCESS_REFUSED')
    # Do not follow or relocate ambiguous special files. All ordinary files are
    # retained, regardless of unknown ownership or unique-evidence status.
    if any(r['kind'] not in ('directory', 'file') for r in before):
        raise ValueError('SPECIAL_OR_SYMLINK_SCRATCH_REFUSED')
    if not apply:
        return {'status': 'DRY_RUN', 'source': str(source), 'destination': str(destination)}
    durable_mkdir(destination)
    if destination.stat().st_dev != source.stat().st_dev:
        raise ValueError('SAME_FILESYSTEM_RENAME_REQUIRED')
    evidence_before = evidence_manifest(root)
    git_refs = subprocess.run(['git', 'show-ref', '--head'], cwd=root, capture_output=True, text=True)
    record = {'source': str(source), 'destination': str(destination / 'work'),
              'timestamp': datetime.now(timezone.utc).isoformat(), 'inventory': before,
              'process_snapshot': proc,
              'preserved_certification_evidence': evidence_before,
              'git_refs_before': git_refs.stdout if git_refs.returncode == 0 else 'NO_GIT_REFS_AVAILABLE',
              'quiescence': 'HOST_EXPERIMENT_LOCK_AND_VISIBLE_BACKEND_SCAN_AND_SAME_UID_PROC_VISIBILITY',
              'other_uid_visibility': 'LIMITED; unknown material retained losslessly, never classified stale',
              'policy': 'OPERATOR_AUTHORIZED_LOSSLESS_ARCHIVE_ALL_NO_DELETE',
              'classification': 'RETAINED_ARCHIVE_UNKNOWN_OWNERS_NOT_DISCARDED',
              'unreadable_processes_do_not_prove_inactivity': True}
    write_new(destination / 'manifest-before.json', record)
    check = snapshot(source)
    if preserved_entries(before) != preserved_entries(check):
        raise ValueError('SCRATCH_CHANGED_DURING_ARCHIVE')
    final_proc = processes(source)
    if final_proc['scratch_references'] or final_proc['backend_candidates']:
        raise ValueError('ACTIVE_SCRATCH_BEFORE_RENAME')
    for row in final_proc.get('unreadable_processes', []):
        try:
            if Path('/proc', str(row['pid'])).stat().st_uid == os.geteuid():
                raise ValueError('UNREADABLE_SAME_UID_PROCESS_REFUSED')
        except FileNotFoundError:
            pass
    # A single rename retains bytes, inode identity, and child mtimes; crash before
    # empty work recreation cannot destroy the archived evidence.
    mode = source.stat().st_mode & 0o777
    os.rename(source, destination / 'work')
    sync_directory(destination)
    sync_directory(source.parent)
    source.mkdir(mode=mode)
    sync_directory(source.parent)
    after = snapshot(destination / 'work')
    intact = preserved_entries(before) == preserved_entries(after)
    evidence_after = evidence_manifest(root)
    refs_after = subprocess.run(['git', 'show-ref', '--head'], cwd=root, capture_output=True, text=True)
    intact = intact and evidence_before == evidence_after and git_refs.stdout == refs_after.stdout
    write_new(destination / 'manifest-after.json', {'inventory': after, 'certification_evidence': evidence_after})
    locator = {'original_root': str(source), 'archive_root': str(destination / 'work'),
               'historical_reference': str(root / 'state_local_intelligence/discovery/smoke-mistralrs-CPU.json'),
               'historical_reference_sha256': sha((root / 'state_local_intelligence/discovery/smoke-mistralrs-CPU.json').read_bytes())
                   if (root / 'state_local_intelligence/discovery/smoke-mistralrs-CPU.json').exists() else None,
               'mapping_rule': 'append unchanged original relative path to archive_root; do not modify historical records',
               'manifest_before_sha256': sha((destination / 'manifest-before.json').read_bytes()),
               'manifest_after_sha256': sha((destination / 'manifest-after.json').read_bytes())}
    write_new(destination / 'original-path-locator.json', locator)
    result = {'status': 'ARCHIVED_VERIFIED' if intact else 'FAIL', 'deleted_files': 0,
              'archive': str(destination / 'work'), 'original_path': str(source),
              'files': len(content_manifest(before)), 'content_unchanged': intact,
              'inode_device_and_directory_identity_preserved': intact,
              'certification_evidence_unchanged': evidence_before == evidence_after,
              'manifest_before_sha256': sha((destination / 'manifest-before.json').read_bytes()),
              'restoration': 'with runtime stopped: remove empty operational work only, rename archived work back; never merge',
              'empty_operational_work': not any(source.iterdir()), 'stage2_executed': False}
    write_new(destination / 'receipt.json', result)
    if not intact:
        raise ValueError('ARCHIVE_VERIFICATION_FAILED_PRESERVE_BOTH_PATHS')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--copy-retain-originals', action='store_true')
    args = parser.parse_args()
    action = copy_archive if args.copy_retain_originals else archive
    print(json.dumps(action(args.root, args.destination, apply=args.apply), indent=2))


if __name__ == '__main__':
    main()
