#!/usr/bin/env python3
"""Read-only scratch ownership investigation. Never deletes, moves or runs a backend."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat


def sha(data):
    return hashlib.sha256(data).hexdigest()


def utc(ns):
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).isoformat()


def snapshot(base):
    """lstat only; never follow symlinks or open special files."""
    base = Path(base)
    result = []
    for path in [base, *sorted(base.rglob('*'))]:
        s = path.lstat()
        row = {'path': str(path.relative_to(base)) or '.', 'mode': oct(s.st_mode),
               'uid': s.st_uid, 'gid': s.st_gid, 'inode': s.st_ino, 'device': s.st_dev,
               'size_bytes': s.st_size, 'mtime_ns': s.st_mtime_ns, 'ctime_ns': s.st_ctime_ns,
               'atime_ns_before_read': s.st_atime_ns, 'mtime_utc': utc(s.st_mtime_ns),
               'ctime_utc': utc(s.st_ctime_ns)}
        if stat.S_ISREG(s.st_mode):
            data = path.read_bytes()
            row.update(kind='file', sha256=sha(data))
            if path.name.endswith('.json'):
                try:
                    row['metadata'] = json.loads(data)
                except (ValueError, UnicodeError):
                    row['metadata_error'] = 'INVALID_JSON'
        elif stat.S_ISDIR(s.st_mode):
            row['kind'] = 'directory'
        elif stat.S_ISLNK(s.st_mode):
            row.update(kind='symlink', target=os.readlink(path))
        else:
            row['kind'] = 'special'
        result.append(row)
    return result


def processes(base):
    """Inspect all /proc entries: command, cwd, root, open fds, maps and identity."""
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    matches, errors, backends = [], [], []
    prefix = str(Path(base).resolve())
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            cmd = (path / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            row = {'pid': int(path.name), 'ppid': int(fields[1]), 'pgid': int(fields[2]),
                   'sid': int(fields[3]), 'state': fields[0], 'start_ticks': int(fields[19]),
                   'boot_id': boot, 'cmdline': cmd, 'references': []}
            if re.search(r'koboldcpp|llama-server|runtime_worker|/worker.py', cmd):
                backends.append(row)
            if prefix in cmd:
                row['references'].append({'source': 'cmdline', 'value': cmd})
            for link in ['cwd', 'root', *['fd/' + p.name for p in (path / 'fd').iterdir()]]:
                try:
                    value = os.readlink(path / link)
                    if prefix in value:
                        row['references'].append({'source': link, 'value': value})
                except FileNotFoundError:
                    pass
            for line in (path / 'maps').read_text().splitlines():
                if prefix in line:
                    row['references'].append({'source': 'maps', 'value': line})
            if row['references']:
                matches.append(row)
        except (PermissionError, ProcessLookupError) as exc:
            errors.append({'pid': path.name, 'error': type(exc).__name__})
        except FileNotFoundError:
            pass  # A process can finish while /proc is being inspected.
    return {'boot_id': boot, 'scratch_references': matches, 'backend_candidates': backends,
            'unreadable_processes': errors, 'locks': Path('/proc/locks').read_text()}


def reference_scan(root, base, names):
    """Literal path/name scan; skipped/denied files are explicit uncertainty, never proof."""
    refs = {name: [] for name in names}
    skipped, errors = [], []
    count = 0
    pattern = re.compile('|'.join(re.escape(n) for n in names))
    for directory, dirs, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        dirs[:] = [d for d in dirs if d != '.git' and not d.startswith('scratch-incident-')
                   and not (parent / d).is_symlink()
                   and (parent / d).resolve() != base.resolve()]
        for name in files:
            path = parent / name
            if path.is_symlink():
                skipped.append({'path': str(path), 'reason': 'SYMLINK'})
                continue
            try:
                size = path.stat().st_size
                if size > 32 * 2**20:
                    skipped.append({'path': str(path), 'reason': 'OVER_32_MIB', 'size': size})
                    continue
                data = path.read_bytes()
                if b'\0' in data[:8192]:
                    continue
                text = data.decode('utf-8', errors='replace')
                count += 1
                for number, line in enumerate(text.splitlines(), 1):
                    for match in set(pattern.findall(line)):
                        refs[match].append({'path': str(path), 'line': number,
                                            'preview': line[:1500], 'file_sha256': sha(data)})
            except (OSError, ValueError) as exc:
                errors.append({'path': str(path), 'error': str(exc)})
    return {'references': refs, 'text_files_scanned': count, 'skipped': skipped, 'errors': errors,
            'scope': 'repository including ignored state/evidence; excludes .git, scratch, generated scratch-incident-* evidence, symlinks, binary and >32MiB files'}


def classify(name, proc, refs):
    live = [p for p in proc['scratch_references'] if any(name in r['value'] for r in p['references'])]
    # A path reference is not a durable ownership binding to this Stage. Never infer
    # stale/reproducible/disposable from absence of a live reference or from age.
    if live:
        return 'ACTIVE_FOREIGN', 'LIVE_PATH_REFERENCE_NOT_OWNED_BY_STAGE2'
    if refs:
        return 'UNKNOWN_OWNER', 'REFERENCES_REQUIRE_SEMANTIC_RECONCILIATION'
    return 'UNKNOWN_OWNER', 'NO_DURABLE_OWNER_OR_DISPOSABILITY_PROOF'


def scratch_gate(base):
    """Unknown/nonempty scratch is always blocked; no cleanup or Stage 2 retry."""
    entries = list(Path(base).iterdir()) if Path(base).exists() else []
    return {'status': 'BLOCKED_PREEXECUTION' if entries else 'PASS',
            'reason': 'SHARED_BACKEND_SCRATCH_BUSY' if entries else 'SCRATCH_EMPTY',
            'entries': len(entries), 'cleanup_performed': False, 'session_started': False}


def investigate(root, base):
    before = snapshot(base)
    proc = processes(base)
    names = [p.name for p in sorted(Path(base).iterdir())]
    refs = reference_scan(Path(root), Path(base), names)
    hashes = sorted({r['sha256'] for r in before if r['kind'] == 'file'})
    hash_refs = reference_scan(Path(root), Path(base), hashes)
    rows = []
    for name in names:
        files = [r for r in before if r['path'] == name or r['path'].startswith(name + '/')]
        classification, reason = classify(name, proc, refs['references'][name])
        rows.append({'directory': name, 'classification': classification, 'reason': reason,
                     'automatic_cleanup_permitted': False,
                     'files': sum(r['kind'] == 'file' for r in files),
                     'file_bytes': sum(r['size_bytes'] for r in files if r['kind'] == 'file'),
                     'owner_metadata_candidates': [r for r in files if re.search(r'lock|manifest|receipt|owner|metadata', r['path'], re.I)],
                     'reference_count': len(refs['references'][name])})
    after = snapshot(base)
    stable = lambda rows: [{k:v for k,v in row.items() if k != 'atime_ns_before_read'} for row in rows]
    return {'status': 'BLOCKED_PREEXECUTION', 'reason': 'UNRECONCILED_SHARED_BACKEND_SCRATCH',
            'inventory': before, 'inventory_sha256': sha(json.dumps(before, sort_keys=True).encode()),
            'classification': rows, 'processes': proc, 'reference_scan': refs,
            'content_hash_reference_scan': hash_refs, 'gate': scratch_gate(base),
            'content_and_metadata_unchanged_except_possible_atime': stable(before) == stable(after),
            'destructive_actions': [], 'stage2_retried': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    base = a.root / 'state_local_intelligence/work'
    if a.out.resolve().is_relative_to(base.resolve()):
        raise ValueError('EVIDENCE_MUST_NOT_BE_WRITTEN_IN_SCRATCH')
    result = investigate(a.root.resolve(), base.resolve())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('x') as f:
        json.dump(result, f, indent=2)


if __name__ == '__main__':
    main()
