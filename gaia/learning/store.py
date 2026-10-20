"""Content-addressed immutable records/knowledge and an atomic batch visibility index."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from ..provenance import canonical_json, digest
from .contradictions import with_history
from .engine import learn, settings
from .schema import validate, validate_source


class LearningStore:
    def __init__(self, state):
        self.directory = Path(state) / "learning"

    def _path(self, category, identifier):
        patterns = {"records": r"l[a-f0-9]{24}", "knowledge": r"k[a-f0-9]{24}", "sources": r"[a-f0-9]{64}", "batches": r"b[0-9]{6,}"}
        if category not in patterns or not isinstance(identifier, str) or not re.fullmatch(patterns[category], identifier):
            raise ValueError("Invalid learning reference")
        path = self.directory / category / (identifier + ".json")
        if self.directory.is_symlink() or path.parent.is_symlink() or path.is_symlink():
            raise ValueError("Learning symlink forbidden")
        return path

    def batches(self):
        if self.directory.is_symlink() or (self.directory / "batches").is_symlink():
            raise ValueError("Learning store symlink forbidden")
        paths = sorted((self.directory / "batches").glob("b*.json"))
        result, previous = [], None
        for index, path in enumerate(paths, 1):
            if path.stem != f"b{index:06d}":
                raise ValueError("Noncontiguous learning batches")
            value = self._read("batches", path.stem)
            if (value["schema"] != "gaia_learning_batch_v1" or value["batch_id"] != path.stem
                    or value["previous_batch_hash"] != previous or value["batch_hash"] != digest({k: v for k, v in value.items() if k != "batch_hash"})):
                raise ValueError("Learning batch chain mismatch")
            run = value["run"]
            if run["schema"] != "gaia_learning_run_v1" or run["run_hash"] != digest({k: v for k, v in run.items() if k != "run_hash"}):
                raise ValueError("Learning run hash mismatch")
            for category in ("records", "knowledge"):
                for item in run[category]:
                    validate(item)
                    if self._read(category, item["learning_id"]) != item:
                        raise ValueError("Learning index artifact mismatch")
            for sh in run["source_hashes"]:
                if validate_source(self._read("sources", sh))["source_hash"] != sh:
                    raise ValueError("Learning source filename identity mismatch")
            previous = value["batch_hash"]
            result.append(value)
        return result

    def _read(self, category, identifier):
        raw = self._path(category, identifier).read_bytes()
        value = json.loads(raw)
        if canonical_json(value) != raw:
            raise ValueError("Noncanonical learning artifact")
        return value

    def items(self, category="knowledge", *, latest_only=False):
        if category not in ("records", "knowledge"):
            raise ValueError("Unknown learning category")
        batches = self.batches()
        selected = batches[-1:] if latest_only else batches
        values = {v["learning_id"]: v for b in selected for v in b["run"][category]}
        return [values[k] for k in sorted(values)]

    def read(self, identifier):
        category = "records" if identifier.startswith("l") else "knowledge"
        values = self.items(category)
        if identifier == "latest":
            values = self.items("knowledge", latest_only=True)
            if not values:
                raise ValueError("No knowledge")
            return max(values, key=lambda v: (v["created_at"], v["learning_id"]))
        self._path(category, identifier)
        for value in values:
            if value["learning_id"] == identifier:
                return value
        raise ValueError("No committed learning artifact")

    def _sync(self, directory):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write(self, category, identifier, document):
        path = self._path(category, identifier)
        path.parent.mkdir(exist_ok=True)
        raw = canonical_json(document)
        if path.exists():
            if path.read_bytes() != raw:
                raise ValueError("Attempted learning overwrite")
            return
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fchmod(stream.fileno(), 0o444)
                os.fsync(stream.fileno())
            os.link(temporary, path)
            self._sync(path.parent)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def ingest(self, sources, configuration=None):
        cfg = settings(configuration)
        incoming = {validate_source(s)["source_hash"]: s for s in sources}
        if not incoming:
            raise ValueError("Explicit sources required")
        if self.directory.is_symlink():
            raise ValueError("Learning store symlink forbidden")
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            batches = self.batches()
            old_sources = {sh: self._read("sources", sh) for b in batches for sh in b["run"]["source_hashes"]}
            if batches and cfg != batches[-1]["run"]["settings"]:
                raise ValueError("Use a separate learning store for another interpretation policy")
            combined = {**old_sources, **incoming}
            if batches and set(combined) == set(old_sources):
                return batches[-1]
            previous_knowledge = {k["learning_id"]: k for b in batches for k in b["run"]["knowledge"]}
            run = with_history(learn(list(combined.values()), {"learning": cfg}), previous_knowledge.values())
            identifier = f"b{len(batches) + 1:06d}"
            for sh, source in combined.items():
                self._write("sources", sh, source)
            for category in ("records", "knowledge"):
                for item in run[category]:
                    self._write(category, item["learning_id"], item)
            batch = {"schema": "gaia_learning_batch_v1", "batch_id": identifier,
                     "previous_batch_hash": batches[-1]["batch_hash"] if batches else None, "run": run}
            batch["batch_hash"] = digest(batch)
            self._sync(self.directory)  # Artifact subdirectories durable before visibility.
            self._write("batches", identifier, batch)  # Sole visibility/commit point.
            self._sync(self.directory)
            return batch
