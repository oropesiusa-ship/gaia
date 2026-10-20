"""Independent append-only priority store; no overwrite or evolutionary ledger."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile
from .schema import canonical_json, seal, validate


class PriorityStore:
    def __init__(self, state):
        self.directory = Path(state) / "priorities"

    def path(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"p[0-9]{6,}", identifier):
            raise ValueError("Invalid priority id")
        path = self.directory / (identifier + ".json")
        if self.directory.is_symlink() or path.is_symlink():
            raise ValueError("Priority symlink forbidden")
        return path

    def ids(self):
        if self.directory.is_symlink():
            raise ValueError("Priority store symlink forbidden")
        return sorted((p.stem for p in self.directory.glob("p*.json") if re.fullmatch(r"p[0-9]{6,}", p.stem)), key=lambda s: int(s[1:]))

    def latest(self):
        return self.read("latest") if self.ids() else None

    def read(self, identifier):
        if identifier == "latest":
            ids = self.ids()
            if not ids:
                raise ValueError("No priorities")
            identifier = ids[-1]
        raw = self.path(identifier).read_bytes()
        value = validate(json.loads(raw))
        if value["prioritization_id"] != identifier or canonical_json(value) != raw:
            raise ValueError("Noncanonical or misidentified priority")
        return value

    def save(self, document, *, prioritization_id=None):
        validate(document)
        if self.directory.is_symlink():
            raise ValueError("Priority store symlink forbidden")
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ids = self.ids()
            identifier = prioritization_id or f"p{int(ids[-1][1:]) + 1 if ids else 1:06d}"
            path = self.path(identifier)
            value = seal({**document, "prioritization_id": identifier})
            fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=self.directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical_json(value))
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o444)
                    os.fsync(stream.fileno())
                os.link(temporary, path)
                fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return value
