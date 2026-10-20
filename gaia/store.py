"""Persistencia: libro de registro, estado, versiones estables, bloqueo, STOP."""
import hashlib
import json
import os
import time
import fcntl
import re
import threading
from contextlib import contextmanager
from pathlib import Path


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Store:
    def __init__(self, root, state_dir="state"):
        self.root = Path(root)
        state_path = Path(state_dir)
        if state_path.is_absolute() or len(state_path.parts) != 1 or state_path.name in ("", ".", ".."):
            raise ValueError("state_dir debe ser un único directorio relativo al proyecto")
        self.dir = self.root / state_path
        created = not self.dir.exists()
        self.dir.mkdir(exist_ok=True)
        if created:
            from .atomic_publish import fsync_directory
            fsync_directory(self.root)
        self.ledger = self.dir / "ledger.jsonl"
        self.stable = self.dir / "stable"
        self.tmp = self.dir / "tmp"
        self.stop_file = self.root / "STOP"
        self._lock_stream = None
        self._lock_owner = None

    # --- libro de registro (append-only) ---
    def append(self, rec):
        from . import ledger
        if ledger.enabled(self):
            return ledger.from_legacy_payload(self, rec)
        rec = {"ts": round(time.time(), 2), **rec}
        with self.ledger.open("ab+") as f:
            if f.tell():
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    f.seek(0, os.SEEK_END)
                    f.write(b"\n")
            f.write((json.dumps(rec, ensure_ascii=False) + "\n").encode())
            f.flush()
            os.fsync(f.fileno())

    def records(self):
        from . import ledger
        if ledger.enabled(self):
            checked = ledger.verify_ledger(self)
            if not checked["ok"]:
                raise RuntimeError(str(checked["code"]) + ": " + "; ".join(checked["errors"]))
            # Preserve the established search/report API without copying raw
            # evidence into the on-disk chain or counting action events twice.
            promoted = {r["payload"]["experiment_id"]: r["payload"]["version"] for r in checked["records"]
                        if r["event_type"] == "version_promoted"}
            return [{**r["payload"], "ts": r["timestamp"],
                     **({"promoted_to": promoted[r["payload"]["id"]]} if r["event_type"] == "experiment_completed"
                        and r["payload"].get("id") in promoted else {})} for r in checked["records"]
                    if r["event_type"] not in ("candidate_accepted", "candidate_rejected")]
        if not self.ledger.exists():
            return []
        out = []
        for ln in self.ledger.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                pass        # última línea truncada por una interrupción
        return out

    def append_ledger_event(self, event_type, payload, *, _test_fault=None):
        from .ledger import append_event, enabled
        if not enabled(self):
            raise ValueError("Only a new CPU ledger-schema state can append certified events")
        return append_event(self, event_type, payload, _test_fault=_test_fault)

    def close_orphans(self, context=None):
        """Recover a verified committed publication; otherwise abort orphan trials."""
        from .ledger import enabled
        if enabled(self):
            # Only recover_publications may reconstruct version_promoted.
            # No caller can turn orphan CPU events into a repaired history.
            return 0
        if context is not None:
            from . import manifest
        recs = self.records()
        ended = {r["id"] for r in recs if r["type"] == "end"}
        n = 0
        for r in recs:
            if r["type"] == "start" and r["id"] not in ended:
                committed = next((event for event in reversed(recs) if event.get("type") == "promotion"
                                  and event.get("experiment_id") == r["id"] and event.get("result") == "committed"), None)
                if context is not None and self.current_version() is not None:
                    current = self.current_version()
                    checked = manifest.validate_manifest(context, self.stable / current / "manifest.json")
                    if not checked["ok"]:
                        raise RuntimeError("Cannot recover experiment from an invalid publication")
                    published = json.loads((self.stable / current / "evidence.json").read_bytes())
                    if published.get("promoted_from") == r["id"]:
                        committed = {"version": current}
                if committed:
                    recovered = {"type": "end", "id": r["id"], "decision": "accepted", "recovered": True,
                                 "promoted_to": committed["version"], "reason": "durable publication committed"}
                    if context is not None:
                        version = committed["version"]
                        checked = manifest.validate_manifest(context, self.stable / version / "manifest.json")
                        if not checked["ok"]:
                            raise RuntimeError("Cannot recover invalid committed version")
                        published = json.loads((self.stable / version / "evidence.json").read_bytes())
                        saved = json.loads(manifest._state_path(self.dir, published["experiment_evidence_path"]).read_bytes())
                        recovered = {**saved, "recovered": True, "promoted_to": version}
                    self.append(recovered)
                    n += 1
                    continue
                self.append({"type": "end", "id": r["id"], "decision": "aborted",
                             "reason": "ejecución interrumpida; resultado NO válido"})
                n += 1
        return n

    # --- estado ---
    def load_state(self):
        p = self.dir / "state.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def save_state(self, st):
        atomic_write(self.dir / "state.json", json.dumps(st, indent=1))

    # --- versiones estables con reversión ---
    def current_version(self):
        p = self.stable / "CURRENT"
        return p.read_text().strip() if p.exists() else None

    def versions(self):
        return sorted(d.name for d in self.stable.glob("v*") if d.is_dir())

    def promote(self, genome, source, evidence, *, context=None, baseline_manifest=None, _test_fault=None):
        """The only CPU publication route; evidence is revalidated under flock."""
        from . import atomic_publish, manifest, provenance, publication
        from . import genome as G
        if not isinstance(evidence, dict):
            raise ValueError("CPU publication evidence must be an object")
        if context is None or context.store is not self or context.cfg["workload"]["id"] != "numpy_mlp":
            raise ValueError("CPU publication requires its certified Engine context")
        if provenance.state_schema(self.dir) != "MVP_CPU_V1":
            raise ValueError("Non-MVP/legacy state cannot publish")
        with self.exclusive():
            name = None
            parent = self.current_version()
            try:
                if baseline_manifest is not None:
                    if parent is not None or any(self.stable.glob("v*")):
                        raise ValueError("Baseline may only be published into a new stable tree")
                    if baseline_manifest["kind"] != "baseline" or source != G.render(genome):
                        raise ValueError("Invalid baseline artifacts")
                    name = "v0000"
                    artifacts = {"trainer.py": source.encode(), "genome.json": publication.genome_bytes(genome),
                                 "manifest.json": manifest.canonical_json(baseline_manifest),
                                 "evidence.json": manifest.canonical_json(evidence)}

                    def validate(directory):
                        if {p.name for p in directory.iterdir()} != publication.ARTIFACTS:
                            raise ValueError("Incomplete baseline staging")
                        result = manifest.validate_manifest(context, _baseline_dir=directory, _current_version="v0000")
                        if not result["ok"]:
                            raise ValueError("; ".join(result["errors"]))

                    publication.durable_references(context)
                else:
                    report = self.recover_publications(context)
                    if report["status"] != "READY":
                        raise ValueError("PUBLICATION_BLOCKED: " + "; ".join(report["errors"]))
                    if report["staging"] or report["pointer_temporaries"]:
                        raise ValueError("PRE_PROMOTION_FAILED: pending staging/pointer transaction requires inspection")
                    # Compute under the same lock, counting even non-current finals.
                    numbers = [int(p.name[1:]) for p in self.stable.iterdir() if re.fullmatch(r"v\d{4,}", p.name)]
                    name = f"v{max(numbers, default=-1) + 1:04d}"
                    artifacts = publication.artifacts(context, name, genome, source, evidence)
                    document = json.loads(artifacts["manifest.json"])
                    parent = document["parent_version"]

                    def validate(directory):
                        # Re-read immutable experiment evidence and the current
                        # environment at both staging and final-directory checks.
                        baseline, _, _, _ = publication.validate_candidate(context, genome, source, evidence)
                        manifest.validate_stable_artifacts(context, directory, baseline, expected_version=name)

                    publication.durable_references(context, evidence)
                atomic_publish.publish(self.stable, name, artifacts, validate, parent, _test_fault=_test_fault)
                if self.current_version() != name:
                    raise RuntimeError("CRITICAL_PUBLICATION_ERROR: CURRENT does not match committed version")
                checked = manifest.validate_manifest(context, self.stable / name / "manifest.json",
                                                     expected_hash=(baseline_manifest or document)["manifest_hash"])
                if not checked["ok"]:
                    raise RuntimeError("CRITICAL_PUBLICATION_ERROR: " + "; ".join(checked["errors"]))
                if baseline_manifest is None:
                    atomic_publish._checkpoint(_test_fault, "after_publication_before_ledger", self.stable / name)
                    self._promotion_event(name)
                return name
            except Exception as exc:
                try:
                    committed = name is not None and self.current_version() == name
                except (OSError, ValueError):
                    committed = True  # Pointer unreadable: do not claim a safe pre-commit failure.
                try:
                    from .ledger import verify_ledger, enabled
                    valid_chain = not enabled(self) or verify_ledger(self)["ok"]
                    if not valid_chain:
                        raise exc
                    self.append({"type": "publication_failure", "version": name, "parent": parent,
                                 "experiment_id": evidence.get("experiment"), "critical": committed,
                                 "result": "critical" if committed else "not_committed", "reason": str(exc),
                                 "phase": getattr(exc, "phase", None)})
                except OSError as diagnostic:
                    raise RuntimeError(("CRITICAL_PUBLICATION_ERROR" if committed else "PUBLICATION_FAILED") +
                                       f": {exc}; diagnostic could not be persisted: {diagnostic}") from exc
                if committed:
                    raise RuntimeError("CRITICAL_PUBLICATION_ERROR: " + str(exc)) from exc
                raise

    def _promotion_event(self, version, recovered=False):
        from . import manifest
        directory = self.stable / version
        doc = manifest._document(directory / "manifest.json")
        evidence = json.loads((directory / "evidence.json").read_bytes())
        self.append({"type": "promotion", "version": version, "parent": doc["parent_version"],
                     "experiment_id": doc["experiment_id"], "manifest_hash": doc["manifest_hash"],
                     "environment_hash": doc["environment_hash"], "trainer_hash": evidence["trainer_hash"],
                     "genome_hash": evidence["genome_hash"], "stable_evidence_hash": evidence["evidence_hash"],
                     "experiment_evidence_hash": doc["experiment_evidence_hash"],
                     "recovered_after_crash": recovered, "result": "committed", "timestamp": doc["created_at"]})

    def recover_publications(self, context):
        """Inspect under lock. Preserve all staging and non-current evidence."""
        from . import manifest
        report = {"status": "BLOCKED", "current": None, "staging": [], "non_current_versions": [],
                  "pointer_temporaries": [], "errors": []}
        try:
            with self.exclusive():
                from . import rollback
                report["rollback_recovery"] = rollback.recover(context)
                entries = sorted(self.stable.iterdir()) if self.stable.exists() else []
                for path in entries:
                    if path.name.startswith(".staging-"):
                        owned = bool(re.fullmatch(r"\.staging-v\d{4,}-[0-9a-f]{32}", path.name))
                        report["staging"].append({"path": path.name, "never_published": owned and path.is_dir() and not path.is_symlink(),
                                                   "action": "preserved_for_inspection"})
                    elif path.name.startswith(".CURRENT-"):
                        report["pointer_temporaries"].append(path.name)
                if (self.stable / "CURRENT").is_symlink():
                    raise ValueError("CURRENT must be a regular pointer file")
                current = self.current_version()
                report["current"] = current
                if not isinstance(current, str) or not re.fullmatch(r"v\d{4,}", current) or not (self.stable / current).is_dir():
                    raise ValueError("CURRENT missing or points to a nonexistent version; manual intervention required")
                from . import ledger
                chain = ledger.verify_ledger(self) if ledger.enabled(self) else None
                if chain is not None and not chain["ok"]:
                    raise ValueError(str(chain["code"]) + ": " + "; ".join(chain["errors"]))
                events = self.records()
                if any(not isinstance(event, dict) for event in events):
                    raise ValueError("Malformed publication ledger record")
                if any(r.get("type") == "publication_failure" and r.get("critical") for r in events):
                    raise ValueError("Unresolved critical publication failure; inspect ledger before continuing")
                for path in entries:
                    if path.name.startswith("v"):
                        if not re.fullmatch(r"v\d{4,}", path.name) or not path.is_dir() or path.is_symlink():
                            raise ValueError("Invalid/corrupt stable version path: " + path.name)
                        checked = manifest.validate_manifest(context, path / "manifest.json", compare_current=False)
                        if not checked["ok"]:
                            raise ValueError("Corrupt stable version " + path.name + ": " + "; ".join(checked["errors"]))
                        anchor = checked.get("stable", checked.get("baseline"))["manifest_hash"]
                        if any(event.get("manifest_hash") != anchor for event in events
                               if event.get("type") == "promotion" and event.get("version") == path.name and event.get("result") == "committed"):
                            raise ValueError("Published manifest differs from its promotion event: " + path.name)
                        if path.name != current:
                            report["non_current_versions"].append(path.name)
                        if chain is not None and path.name == current and current != "v0000" and not any(
                                event.get("type") == "promotion" and event.get("version") == current for event in events):
                            # CURRENT is the commit witness, not a mere renamed
                            # non-current directory. Chain must already contain
                            # completion + acceptance; append enforces that.
                            self._promotion_event(current, recovered=True)
                            report.setdefault("recovered_events", []).append(current)
                critical = [r for r in events if r.get("type") == "publication_failure" and r.get("critical")]
                if critical:
                    raise ValueError("Unresolved critical publication failure; inspect ledger before continuing")
                if chain is not None:
                    refreshed = ledger.verify_ledger(self)
                    if not refreshed["ok"] or ledger.current_from_records(refreshed["records"]) != current:
                        raise ValueError("CURRENT differs from certified publication/rollback history")
                    starts = {r["payload"]["id"] for r in chain["records"] if r["event_type"] == "experiment_started"}
                    ends = {r["payload"]["id"] for r in chain["records"] if r["event_type"] in ("experiment_completed", "experiment_aborted")}
                    active = getattr(context, "_active_record", None)
                    active_id = active[0]["id"] if active else None
                    if starts - ends - ({active_id} if active_id else set()):
                        raise ValueError("Unfinished experiment requires explicit future intervention; no automatic ledger repair")
                    completed_ids = {r["payload"]["id"] for r in chain["records"] if r["event_type"] == "experiment_completed"}
                    action_ids = {r["payload"]["id"] for r in chain["records"] if r["event_type"] in ("candidate_accepted", "candidate_rejected")}
                    if completed_ids - action_ids:
                        raise ValueError("Completed result lacks candidate action; no automatic ledger repair")
                report["status"] = "READY"
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            report["errors"].append(str(exc))
        return report

    def load_version(self, name=None):
        name = name or self.current_version()
        d = self.stable / name
        return json.loads((d / "genome.json").read_text()), (d / "trainer.py").read_text()

    def rollback(self):
        raise RuntimeError("CPU rollback requires Engine.rollback(to_version, reason); direct Store rollback is disabled")

    # --- bloqueo y parada ---
    def lock(self):
        p = self.dir / "gaia.lock"
        if self._lock_stream is not None:
            raise RuntimeError("Store campaign lock is already held")
        stream = p.open("a+")
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stream.seek(0)
            stream.truncate()
            stream.write(str(os.getpid()))
            stream.flush()
        except (OSError, BlockingIOError) as exc:
            stream.close()
            raise RuntimeError("Another GAIA holds the Store campaign lock") from exc
        self._lock_stream = stream
        self._lock_owner = (os.getpid(), threading.get_ident())

    def unlock(self):
        if self._lock_stream is None:
            return
        if self._lock_owner != (os.getpid(), threading.get_ident()):
            raise RuntimeError("Only the campaign lock owner may release it")
        stream, self._lock_stream = self._lock_stream, None
        self._lock_owner = None
        try:
            fcntl.flock(stream, fcntl.LOCK_UN)
        finally:
            stream.close()
        # Never unlink flock files: doing so allows a second lock inode/race.

    @contextmanager
    def exclusive(self):
        if self._lock_owner == (os.getpid(), threading.get_ident()):
            yield
            return
        self.lock()
        try:
            yield
        finally:
            self.unlock()

    def stop_requested(self):
        return self.stop_file.exists()

    def disk_mb(self):
        return sum(f.stat().st_size for f in self.dir.rglob("*") if f.is_file()) / 2**20
