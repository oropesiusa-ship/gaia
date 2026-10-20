"""Immutable shadow decisions, plans, history and metric snapshots. Commit index is last."""
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from ..provenance import canonical_json
from .schema import seal, validate


class StrategyStore:
    def __init__(self, state):
        self.directory = Path(state) / "experiment-strategies"

    def path(self, category, identifier):
        pattern = r"xp[a-f0-9]{24}" if category == "plans" else r"s[0-9]{6,}"
        if category not in ("decisions", "plans", "history", "metrics") or not isinstance(identifier, str) or not re.fullmatch(pattern, identifier):
            raise ValueError("Invalid strategy artifact reference")
        path = self.directory / category / (identifier + ".json")
        if self.directory.is_symlink() or path.parent.is_symlink() or path.is_symlink():
            raise ValueError("Strategy symlink forbidden")
        return path

    def ids(self):
        if self.directory.is_symlink() or (self.directory / "decisions").is_symlink():
            raise ValueError("Strategy store symlink forbidden")
        return sorted((p.stem for p in (self.directory / "decisions").glob("s*.json") if re.fullmatch(r"s[0-9]{6,}", p.stem)), key=lambda s: int(s[1:]))

    def _read(self, category, identifier):
        raw = self.path(category, identifier).read_bytes()
        value = json.loads(raw)
        if canonical_json(value) != raw:
            raise ValueError("Noncanonical strategy artifact")
        return value

    def read(self, identifier):
        if identifier == "latest":
            ids = self.ids()
            if not ids:
                raise ValueError("No experiment strategies")
            identifier = ids[-1]
        value = validate(self._read("decisions", identifier))
        if value["strategy_id"] != identifier:
            raise ValueError("Misidentified strategy decision")
        if self._read("history", identifier) != value["history"] or self._read("metrics", identifier) != value["meta_metrics"]:
            raise ValueError("Strategy history/metrics mismatch")
        for plan in value["candidate_plans"]:
            if self._read("plans", plan["plan_id"]) != plan:
                raise ValueError("Strategy plan artifact mismatch")
        return value

    def latest(self):
        return self.read("latest") if self.ids() else None

    def _sync(self, directory):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _put(self, category, identifier, document, *, reuse=False):
        path = self.path(category, identifier)
        path.parent.mkdir(exist_ok=True)
        raw = canonical_json(document)
        if path.exists():
            if reuse and path.read_bytes() == raw:
                return
            raise FileExistsError("Strategy artifact already exists")
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

    def save(self, document, *, strategy_id=None):
        validate(document)
        if self.directory.is_symlink():
            raise ValueError("Strategy store symlink forbidden")
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            high_water = []
            for category in ("decisions", "history", "metrics"):
                if (self.directory / category).is_symlink():
                    raise ValueError("Strategy category symlink forbidden")
                high_water += [int(p.stem[1:]) for p in (self.directory / category).glob("s*.json") if re.fullmatch(r"s[0-9]{6,}", p.stem)]
            identifier = strategy_id or f"s{max(high_water, default=0) + 1:06d}"
            if self.path("decisions", identifier).exists():
                raise FileExistsError("Strategy decision already committed")
            value = seal({**document, "strategy_id": identifier})
            for plan in value["candidate_plans"]:
                self._put("plans", plan["plan_id"], plan, reuse=True)
            self._put("history", identifier, value["history"])
            self._put("metrics", identifier, value["meta_metrics"])
            self._sync(self.directory)
            self._put("decisions", identifier, value)  # Sole visibility/commit point.
            self._sync(self.directory)
            return value
