"""Separate immutable diagnosis history, canonical and atomic create-only."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from .schema import canonical_json, seal, validate


class DiagnosisStore:
    def __init__(self, state):
        self.directory = Path(state) / "diagnoses"

    def path(self, diagnosis_id):
        if not isinstance(diagnosis_id, str) or not re.fullmatch(r"d[0-9]{6,}", diagnosis_id):
            raise ValueError("Invalid diagnosis id")
        path = self.directory / (diagnosis_id + ".json")
        if self.directory.is_symlink() or path.is_symlink():
            raise ValueError("Diagnosis symlink forbidden")
        return path

    def ids(self):
        if self.directory.is_symlink():
            raise ValueError("Diagnosis store symlink forbidden")
        return sorted((p.stem for p in self.directory.glob("d*.json") if re.fullmatch(r"d[0-9]{6,}", p.stem)), key=lambda x: int(x[1:]))

    def read(self, diagnosis_id):
        if diagnosis_id == "latest":
            ids = self.ids()
            if not ids:
                raise ValueError("No diagnoses")
            diagnosis_id = ids[-1]
        data = self.path(diagnosis_id).read_bytes()
        value = validate(json.loads(data))
        if value["diagnosis_id"] != diagnosis_id or canonical_json(value) != data:
            raise ValueError("Noncanonical or misidentified diagnosis")
        return value

    def latest(self):
        return self.read("latest") if self.ids() else None

    def save(self, document, *, diagnosis_id=None):
        if self.directory.is_symlink():
            raise ValueError("Diagnosis store symlink forbidden")
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ids = self.ids()
            diagnosis_id = diagnosis_id or f"d{int(ids[-1][1:]) + 1 if ids else 1:06d}"
            path = self.path(diagnosis_id)
            validate(document)
            value = seal({**document, "diagnosis_id": diagnosis_id})
            fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=self.directory)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(canonical_json(value))
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o444)
                    os.fsync(stream.fileno())
                os.link(temporary, path)
                directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return value
