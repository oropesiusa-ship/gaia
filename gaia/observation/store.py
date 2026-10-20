"""Independent append-only store: canonical JSON, fsync, atomic no-clobber link."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from .schema import canonical_json, seal, validate


class ObservationStore:
    def __init__(self, state):
        self.directory = Path(state) / "observations"

    def _path(self, observation_id):
        if not re.fullmatch(r"o[0-9]{6,}", observation_id):
            raise ValueError("Invalid observation id")
        path = self.directory / (observation_id + ".json")
        if self.directory.is_symlink() or path.is_symlink():
            raise ValueError("Observation symlink forbidden")
        return path

    def ids(self):
        return sorted((p.stem for p in self.directory.glob("o*.json")
                       if re.fullmatch(r"o[0-9]{6,}", p.stem)), key=lambda x: int(x[1:]))

    def read(self, observation_id):
        if observation_id == "latest":
            ids = self.ids()
            if not ids:
                raise ValueError("No observations")
            observation_id = ids[-1]
        path = self._path(observation_id)
        raw = path.read_bytes()
        value = validate(json.loads(raw))
        if value["observation_id"] != observation_id or canonical_json(value) != raw:
            raise ValueError("Noncanonical or misidentified observation")
        return value

    def latest(self):
        return self.read("latest") if self.ids() else None

    def save(self, document):
        if self.directory.is_symlink():
            raise ValueError("Observation store symlink forbidden")
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ids = self.ids()
            observation_id = document.get("observation_id") or f"o{int(ids[-1][1:]) + 1 if ids else 1:06d}"
            path = self._path(observation_id)
            value = seal({**document, "observation_id": observation_id})
            fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=self.directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical_json(value))
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o444)
                    os.fsync(stream.fileno())
                os.link(temporary, path)  # Atomic visibility and EEXIST instead of overwrite.
                self._sync()
            finally:
                Path(temporary).unlink(missing_ok=True)
            return value

    def _sync(self):
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def set_baseline(self, observation_id):
        value = self.read(observation_id)
        path = self.directory / "baseline.json"
        reference = canonical_json({"observation_id": value["observation_id"], "observation_hash": value["observation_hash"]})
        fd, temporary = tempfile.mkstemp(prefix=".baseline-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(reference)
                stream.flush()
                os.fchmod(stream.fileno(), 0o444)
                os.fsync(stream.fileno())
            os.link(temporary, path)
            self._sync()
        finally:
            Path(temporary).unlink(missing_ok=True)

    def baseline(self):
        path = self.directory / "baseline.json"
        if not path.exists():
            return None
        if path.is_symlink():
            raise ValueError("Baseline symlink forbidden")
        reference = json.loads(path.read_bytes())
        value = self.read(reference["observation_id"])
        if value["observation_hash"] != reference["observation_hash"]:
            raise ValueError("Observation baseline hash mismatch")
        return reference
