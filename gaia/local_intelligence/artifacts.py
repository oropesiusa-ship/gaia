"""Explicit official artifact acquisition, separate from research text privileges. No install scripts."""
import hashlib
import http.client
import os
from pathlib import Path
import re
import tarfile
import time
import base64
import json
import threading
from urllib.parse import urljoin, urlsplit, urlunsplit
import zipfile

from ..external_research.network import FetchError, PinnedConnection, normalize_url, resolve_public
from .schema import artifact
from .store import IntelligenceStore

REDIRECT_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com", "huggingface.co",
                  "cdn-lfs.huggingface.co", "cdn-lfs-us-1.hf.co", "cas-bridge.xethub.hf.co", "us.aws.cdn.hf.co", "cdn-lfs.hf.co",
                  "files.pythonhosted.org"}


def validate_spec(spec):
    if set(spec) != {"url", "upstream", "version", "sha256", "size", "license", "kind", "research_refs"}:
        raise ValueError("Exact artifact manifest required")
    url = normalize_url(spec["url"])
    if urlsplit(url).hostname not in ("github.com", "huggingface.co", "files.pythonhosted.org"):
        raise ValueError("Artifact must originate at authorized official host")
    if not re.fullmatch(r"[a-f0-9]{64}", spec["sha256"]) or type(spec["size"]) is not int or spec["size"] <= 0 or not spec["research_refs"] or not spec["license"]:
        raise ValueError("Artifact needs expected hash/size/license/research evidence")
    if spec["kind"] not in ("RUNTIME", "MODEL", "SUPPORT"):
        raise ValueError("Unknown artifact role")
    upstream=normalize_url(spec['upstream'])
    if not re.fullmatch(r'[A-Za-z0-9_.+-]{1,100}',spec['version']) or spec['license'] not in ('MIT','Apache-2.0','AGPL-3.0','AGPL-3.0-only','BSD-3-Clause'):
        raise ValueError('Pinned version and compatible explicit license required')
    if urlsplit(url).hostname=='github.com' and not url.startswith(upstream+'/releases/download/'+spec['version']+'/'):
        raise ValueError('Runtime URL is not a pinned release of its declared upstream')
    if urlsplit(url).hostname=='huggingface.co' and (not re.fullmatch(r'[a-f0-9]{40}',spec['version']) or not url.startswith(upstream+'/resolve/'+spec['version']+'/')):
        raise ValueError('Model URL must be commit-pinned to its declared upstream')
    return spec


def validate_research_manifest(spec,state):
    """A URL/hash alone cannot authorize installation: match actual upstream metadata."""
    from ..external_research.store import ResearchStore
    validate_spec(spec)
    proofs=[]; matched=False
    for identifier in spec['research_refs']:
        s=ResearchStore(state).read(identifier if isinstance(identifier,str) else identifier['id'])
        if s['kind']!='SOURCE' or s['payload']['origin']!='LIVE_PUBLIC_FETCH':raise ValueError('Live upstream research evidence required for installation')
        if isinstance(identifier,dict) and identifier.get('hash')!=s['hash']:raise ValueError('Research reference hash mismatch')
        p=s['payload'];proofs.append({'id':s['artifact_id'],'hash':s['hash'],'content_hash':p['content_hash'],'url':p['url']})
        try:data=json.loads(base64.b64decode(p['body_base64']))
        except ValueError:continue
        if isinstance(data,dict):
            for asset in data.get('assets',[]):
                if (asset.get('browser_download_url')==spec['url'] and asset.get('size')==spec['size']
                        and asset.get('digest')=='sha256:'+spec['sha256'] and data.get('tag_name')==spec['version']
                        and p['url'].startswith('https://api.github.com/repos/'+spec['upstream'].removeprefix('https://github.com/')+'/releases/')):matched=True
            for file in data.get('urls',[]):
                if p['domain']=='pypi.org' and file.get('url')==spec['url'] and file.get('size')==spec['size'] and file.get('digests',{}).get('sha256')==spec['sha256']:matched=True
        if isinstance(data,list) and p['url'].startswith('https://huggingface.co/api/models/'+spec['upstream'].removeprefix('https://huggingface.co/')+'/tree/'+spec['version']):
            for file in data:
                if file.get('lfs',{}).get('oid')==spec['sha256'] and file.get('size')==spec['size'] and spec['url'].endswith('/'+file.get('path','')):matched=True
    if not matched:raise ValueError('Expected artifact hash/size/version not attested by captured upstream metadata')
    return proofs


def download(spec, state, budget, *, timeout=900):
    validate_spec(spec)
    state = Path(state).resolve()
    proofs=validate_research_manifest(spec,state)
    root = state / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise ValueError("Artifact root symlink")
    maximum = budget["max_download_bytes"]
    store=IntelligenceStore(state)
    history={v['payload']['sha256']:v['payload']for v in store.list('DOWNLOAD')}
    if spec['sha256']not in history:
        if sum(d['size']for d in history.values())+spec['size']>maximum:raise ValueError('Cumulative download budget exhausted')
        key={'RUNTIME':'max_runtime_artifacts','MODEL':'max_model_artifacts'}.get(spec['kind'])
        if key and sum(d['kind']==spec['kind']for d in history.values())>=budget[key]:raise ValueError('Artifact count budget exhausted')
    existing = sum(p.stat().st_size for p in root.iterdir() if p.is_file())
    path = root / spec["sha256"]
    if path.is_symlink():
        raise ValueError("Artifact symlink")
    if path.exists():
        if path.stat().st_size != spec["size"] or file_hash(path) != spec["sha256"]:
            raise ValueError("Existing artifact corrupt")
        return path, store.put(artifact("DOWNLOAD", {**spec, "research_proofs":proofs,"observed_sha256": spec["sha256"], "observed_size": spec["size"], "cached": True}))
    if spec['kind']=='MODEL'and sum(d['kind']=='MODEL'and(root/sha).is_file()for sha,d in history.items())>=budget['max_models_simultaneous']:
        raise ValueError('Simultaneous model retention budget exhausted')
    if existing + spec["size"] > maximum:
        raise ValueError("Explicit total download budget exhausted")
    temporary = root / (spec["sha256"] + ".part")
    if temporary.exists():
        raise ValueError("Partial artifact retained; explicit cleanup needed before retry")
    start, url, redirects = time.monotonic(), spec["url"], []
    try:
        for _ in range(6):
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443) or parts.hostname not in REDIRECT_HOSTS:
                raise ValueError("Artifact redirect outside approved CDN scope")
            ips = resolve_public(parts.hostname, 443, min(10, timeout))
            conn = PinnedConnection(parts.hostname, ips[0], 443, tls=True, timeout=15)
            response = None
            watchdog=threading.Timer(max(.001,timeout-(time.monotonic()-start)),conn.abort);watchdog.daemon=True;watchdog.start()
            try:
                conn.request("GET", parts.path + ("?" + parts.query if parts.query else ""), headers={"User-Agent": "GAIA/0.8 controlled qualification", "Accept-Encoding": "identity", "Connection": "close"})
                response = conn.getresponse()
                if not conn.verified:
                    raise ValueError("Artifact peer not pinned")
                if response.status in (301, 302, 303, 307, 308):
                    nxt = urljoin(url, response.getheader("Location") or "")
                    redirects.append({"host": parts.hostname, "status": response.status, "location_hash": hashlib.sha256(nxt.encode()).hexdigest()})
                    url = nxt
                    continue
                if response.status != 200 or response.getheader("Content-Encoding", "identity") not in ("identity", ""):
                    raise ValueError("Artifact unavailable or encoded")
                declared = response.getheader("Content-Length")
                if declared and int(declared) != spec["size"]:
                    raise ValueError("Artifact declared size differs from qualification manifest")
                total, h = 0, hashlib.sha256()
                with temporary.open("xb") as stream:
                    while True:
                        if time.monotonic() - start > timeout:
                            raise TimeoutError("Artifact deadline")
                        block = response.read1(min(2**20, spec["size"] - total + 1))
                        if not block:
                            break
                        total += len(block)
                        if total > spec["size"]:
                            raise ValueError("Artifact exceeded declared size")
                        h.update(block)
                        stream.write(block)
                    stream.flush()
                    os.fsync(stream.fileno())
                if total != spec["size"] or h.hexdigest() != spec["sha256"]:
                    raise ValueError("Artifact digest mismatch")
                os.link(temporary, path)
                temporary.unlink()
                path.chmod(0o444)
                receipt = artifact("DOWNLOAD", {**spec, "research_proofs":proofs,"observed_sha256": h.hexdigest(), "observed_size": total,
                    "cached": False, "final_host": parts.hostname, "redirects": redirects, "duration_s": time.monotonic() - start,
                    "signed_redirect_queries_persisted": False})
                return path, store.put(receipt)
            finally:
                try:
                    if response: response.close()
                finally:
                    try:conn.close(force=True)
                    finally:watchdog.cancel();watchdog.join(timeout=.1)
        raise ValueError("Artifact redirect limit")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def unpack_runtime(archive, destination, *, max_bytes=2 * 2**30):
    """Passive extraction only, no symlinks/devices/scripts or archive hooks executed."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    entries, total = [], 0
    def target(name, size):
        nonlocal total
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts or "\\" in name or size < 0:
            raise ValueError("Unsafe archive member")
        total += size
        if total > max_bytes:
            raise ValueError("Runtime extraction budget")
        return destination / rel
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                if member.is_dir():
                    continue
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Archive symlink")
                out = target(member.filename, member.file_size)
                out.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as src, out.open("xb") as dst:
                    copy_bounded(src, dst, member.file_size)
                entries.append(out)
    else:
        with tarfile.open(archive) as package:
            for member in package:
                if member.isdir():
                    continue
                if not member.isfile():
                    raise ValueError("Nonregular archive member")
                out = target(member.name, member.size)
                out.parent.mkdir(parents=True, exist_ok=True)
                with package.extractfile(member) as src, out.open("xb") as dst:
                    copy_bounded(src, dst, member.size)
                entries.append(out)
    return [{"path": p.relative_to(destination).as_posix(), "sha256": file_hash(p), "size": p.stat().st_size} for p in entries]


def copy_bounded(src, dst, expected):
    total = 0
    while True:
        block = src.read(min(2**20, expected - total + 1))
        if not block:
            break
        total += len(block)
        if total > expected:
            raise ValueError("Archive member size exceeded")
        dst.write(block)
    if total != expected:
        raise ValueError("Truncated archive member")
