"""Independent immutable artifact store, content-addressed cache references and run commit indexes."""
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from ..provenance import canonical_json, digest
from .schema import PREFIXES, artifact, reference, validate

DIRECTORIES = {"REQUEST": "requests", "SOURCE": "sources", "EXTRACTION": "extractions", "CLAIM": "claims",
               "ASSESSMENT": "assessments", "CONCLUSION": "conclusions", "CACHE": "cache", "ACQUISITION": "acquisitions"}


class ResearchStore:
    def __init__(self, state):
        self.directory = Path(state) / "research"

    def path(self, kind, identifier):
        prefix = "rr" if kind == "RUN" else PREFIXES.get(kind)
        if prefix is None or not isinstance(identifier, str) or not re.fullmatch(prefix + r"[a-f0-9]{24}", identifier):
            raise ValueError("Invalid research artifact reference")
        path = self.directory / ("runs" if kind == "RUN" else DIRECTORIES[kind]) / (identifier + ".json")
        if self.directory.is_symlink() or path.parent.is_symlink() or path.is_symlink():
            raise ValueError("Research symlink forbidden")
        return path

    def _sync(self, directory):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _put(self, kind, identifier, document):
        path = self.path(kind, identifier)
        path.parent.mkdir(exist_ok=True)
        data = canonical_json(document)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("Attempted research overwrite")
            return
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), 0o444)
                os.fsync(stream.fileno())
            os.link(temporary, path)
            self._sync(path.parent)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def put(self, document):
        validate(document)
        if document["kind"] == "REQUEST":
            from .request import validate_request
            validate_request(document)
        if document["kind"] == "SOURCE":
            from .fetch import validate_source
            validate_source(document)
        if self.directory.is_symlink():
            raise ValueError("Research store symlink forbidden")
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._put(document["kind"], document["artifact_id"], document)
            self._sync(self.directory)
        return document

    def read(self, identifier):
        if identifier == "latest":
            values = self.list("CONCLUSION")
            if not values:
                raise ValueError("No research conclusions")
            return values[-1]
        kind = next((k for k, prefix in PREFIXES.items() if identifier.startswith(prefix)), None)
        if kind is None:
            raise ValueError("Unknown research artifact")
        raw = self.path(kind, identifier).read_bytes()
        value = validate(json.loads(raw))
        if canonical_json(value) != raw or value["artifact_id"] != identifier:
            raise ValueError("Noncanonical/misidentified research artifact")
        if kind == "SOURCE":
            from .fetch import validate_source
            validate_source(value)
        if kind == "REQUEST":
            from .request import validate_request
            validate_request(value)
        return value

    def list(self, kind):
        if kind not in DIRECTORIES or self.directory.is_symlink() or (self.directory / DIRECTORIES[kind]).is_symlink():
            raise ValueError("Invalid research category")
        values = [self.read(p.stem) for p in (self.directory / DIRECTORIES[kind]).glob(PREFIXES[kind] + "*.json")]
        return sorted(values, key=lambda v: (v["created_at"], v["artifact_id"]))

    def cache_source(self, source):
        self.put(source)
        p = source["payload"]
        entry = artifact("CACHE", {"url": p["requested_url"], "final_url": p["url"], "source_ref": reference(source),
                                   "content_identity": p["content_identity"], "retrieved_at": source["created_at"]}, created_at=source["created_at"])
        self.put(entry)
        return source

    def cached(self, url, freshness, configuration, as_of):
        from .policy import settings
        cfg = settings(configuration)
        maximum_age = min(cfg["cache_max_age_seconds"], cfg["high_freshness_cache_seconds"]) if freshness == "HIGH" else cfg["cache_max_age_seconds"]
        for entry in reversed(self.list("CACHE")):
            p = entry["payload"]
            if p["url"] != url:
                continue
            age = (datetime.fromisoformat(as_of) - datetime.fromisoformat(p["retrieved_at"])).total_seconds()
            if 0 <= age <= maximum_age:
                value = self.read(p["source_ref"]["id"])
                if value["hash"] != p["source_ref"]["hash"] or value["payload"]["content_identity"] != p["content_identity"]:
                    raise ValueError("Research cache identity mismatch")
                return value
        return None

    def save_run(self, run, request, sources):
        if run["run_hash"] != digest({k: v for k, v in run.items() if k != "run_hash"}) or run["request_ref"] != reference(request):
            raise ValueError("Research run hash mismatch")
        self.put(request)
        if run.get("acquisition_ref"):
            acquisition = self.read(run["acquisition_ref"]["id"])
            if acquisition["kind"] != "ACQUISITION" or reference(acquisition) != run["acquisition_ref"] or acquisition["payload"]["request_ref"] != reference(request):
                raise ValueError("Research acquisition phase reference mismatch")
        for source in sources:
            self.cache_source(source)
        for category in ("extractions", "claims", "assessments", "source_assessments"):
            for value in run[category]:
                self.put(value)
        self.put(run["conclusion"])
        identifier = "rr" + run["run_hash"][:24]
        with (self.directory / ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._sync(self.directory)
            self._put("RUN", identifier, run)  # Commit index after referenced artifacts.
            self._sync(self.directory)
        return run
