"""Explicit ancestor-only CPU CURRENT transaction and narrowly scoped recovery."""
import json
import os
from pathlib import Path
import re
import threading
import uuid

from . import atomic_publish, ledger, manifest, provenance

INTENT_SCHEMA = "mvp_cpu_rollback_intent_v1"


class RollbackError(RuntimeError):
    def __init__(self, code, reason):
        self.code, self.reason = code, reason
        super().__init__(f"{code}: {reason}")


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"v[0-9]{4,}", value):
        raise ValueError("Destination must be an explicit v[0-9]{4,} identifier")
    return value


def ancestors(store, origin, target, records):
    version(origin)
    version(target)
    if origin == target:
        raise ValueError("Rollback destination equals CURRENT")
    certified = {"v0000"} | {r["payload"]["version"] for r in records if r["event_type"] == "version_promoted"}
    cursor, seen = origin, set()
    while cursor != target:
        if cursor in seen or cursor not in certified or cursor == "v0000":
            raise ValueError("Destination is not a certified ancestor of CURRENT")
        seen.add(cursor)
        doc = manifest._document(store.stable / cursor / "manifest.json")
        cursor = version(doc["parent_version"])
    if target not in certified:
        raise ValueError("Destination has no certified ledger origin")
    return list(seen)


def artifact_identity(store, name):
    version(name)
    directory = store.stable / name
    if store.stable.is_symlink() or not directory.resolve().is_relative_to(store.dir.resolve()):
        raise ValueError("Stable path escapes this state")
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Missing/unsafe stable version: " + name)
    doc = manifest._document(directory / "manifest.json")
    return {"manifest_hash": doc["manifest_hash"], "evidence_hash": manifest.file_hash(directory / "evidence.json"),
            "environment_hash": doc["environment_hash"]}


def validate_event(store, payload, records_before, previous_hash):
    """Pure ledger semantic validation, independent of today's CURRENT."""
    origin, target = version(payload["from_version"]), version(payload["to_version"])
    if (payload["operator_initiated"] is not True or not isinstance(payload["reason"], str) or not payload["reason"].strip()
            or payload["previous_current"] != origin or payload["resulting_current"] != target
            or payload["ledger_head"] != previous_hash or type(payload["recovered_after_crash"]) is not bool):
        raise ValueError("Invalid explicit rollback event/intention")
    if payload["version"] != target or payload["parent"] != origin or payload["manifest_hash"] != payload["to_manifest_hash"]:
        raise ValueError("Rollback envelope version/parent/manifest mismatch")
    if type(payload["ledger_sequence"]) is not int or payload["ledger_sequence"] != len(records_before):
        raise ValueError("Rollback intent sequence mismatch")
    if ledger.current_from_records(records_before) != origin:
        raise ValueError("Rollback intention origin differs from certified CURRENT history")
    from datetime import datetime
    datetime.fromisoformat(payload["timestamp"])
    uuid.UUID(payload["execution_id"])
    uuid.UUID(payload["intent_id"])
    ancestors(store, origin, target, records_before)
    for prefix, name in (("from", origin), ("to", target)):
        identity = artifact_identity(store, name)
        for key in ("manifest_hash", "evidence_hash"):
            if payload[prefix + "_" + key] != identity[key]:
                raise ValueError("Rollback artifact identity mismatch: " + prefix + "_" + key)
        if identity["environment_hash"] != payload["environment_hash"]:
            raise ValueError("Rollback crosses certified environment/line")
    body = {k: v for k, v in payload.items() if k not in ("type", "intent_hash")}
    body["recovered_after_crash"] = False
    expected = {"intent_schema": INTENT_SCHEMA, "payload": body}
    if manifest.digest(expected) != payload["intent_hash"]:
        raise ValueError("Rollback intent hash mismatch")


def _validate_environment(eng, origin, target, checked):
    ancestors(eng.store, origin, target, checked["records"])
    for name in (origin, target):
        result = manifest.validate_manifest(eng, eng.store.stable / name / "manifest.json")
        if not result["ok"]:
            raise ValueError("; ".join(result["errors"]))
    if not provenance.bwrap_capability()["verified"]:
        raise ValueError("Required bwrap capability unavailable")


def _remove_intent(path):
    path.unlink()
    atomic_publish.fsync_directory(path.parent)


def _pending_paths(eng):
    return sorted(eng.store.dir.glob(".rollback-intent-*"))


def recover(eng):
    """Caller holds flock. Never guesses CURRENT or rewrites existing events."""
    paths = _pending_paths(eng)
    report = {"status": "READY", "action": "none", "event_id": None}
    if not paths:
        return report
    if len(paths) != 1:
        raise RollbackError("ROLLBACK_RECOVERY_BLOCKED", "Multiple/partial rollback intents")
    path = paths[0]
    if path.is_symlink() or not re.fullmatch(r"\.rollback-intent-[0-9a-f-]{36}\.json", path.name):
        raise RollbackError("ROLLBACK_RECOVERY_BLOCKED", "Invalid intent path")
    try:
        intent = json.loads(path.read_bytes())
        if intent["intent_schema"] != INTENT_SCHEMA or intent["intent_hash"] != manifest.digest({k: v for k, v in intent.items() if k != "intent_hash"}):
            raise ValueError("Invalid rollback intent digest/schema")
        payload = intent["payload"]
        if path.name != f".rollback-intent-{payload['intent_id']}.json":
            raise ValueError("Rollback intent path/identity mismatch")
        payload = {**payload, "intent_hash": intent["intent_hash"]}
        checked = ledger.verify_ledger(eng.store)
        if not checked["ok"]:
            raise ValueError(str(checked["code"]) + ": " + str(checked["errors"]))
        records = checked["records"]
        sequence = payload["ledger_sequence"]
        if type(sequence) is not int or sequence < 1 or len(records) not in (sequence, sequence + 1):
            raise ValueError("Ledger advanced unexpectedly while rollback intent pending")
        if records[sequence - 1]["record_hash"] != payload["ledger_head"]:
            raise ValueError("Rollback ledger head mismatch")
        validate_event(eng.store, payload, records[:sequence], payload["ledger_head"])
        _validate_environment(eng, payload["from_version"], payload["to_version"], {"records": records[:sequence]})
        current = atomic_publish.read_current(eng.store.stable)
        if len(records) == sequence + 1:
            event = records[-1]
            if (event["event_type"] != "rollback" or event["payload"]["intent_hash"] != intent["intent_hash"]
                    or current != payload["to_version"]):
                raise ValueError("Rollback intent conflicts with ledger/CURRENT")
            report.update(action="already_logged", event_id=event["event_id"])
        elif current == payload["from_version"]:
            report["action"] = "not_committed_intent_removed"
        elif current == payload["to_version"]:
            # A crash may follow replace but precede directory fsync. Make the
            # observed pointer durable before recording the completed operation.
            with (eng.store.stable / "CURRENT").open("rb") as stream:
                os.fsync(stream.fileno())
            atomic_publish.fsync_directory(eng.store.stable)
            event = eng.store.append_ledger_event("rollback", {**payload, "recovered_after_crash": True})
            report.update(action="recovered_rollback_event", event_id=event["event_id"])
        else:
            raise ValueError("CURRENT is neither rollback origin nor destination")
        _remove_intent(path)
        return report
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise RollbackError("ROLLBACK_RECOVERY_BLOCKED", str(exc)) from exc


def perform(eng, target, reason, *, _test_fault=None):
    """Called only by Engine.rollback under a freshly acquired campaign lock."""
    store = eng.store
    if (store._lock_owner != (os.getpid(), threading.get_ident()) or
            not getattr(eng, "_rollback_in_progress", False)):
        raise RollbackError("ROLLBACK_BLOCKED", "Rollback requires the explicit Engine transaction lock")
    target = version(target)
    if not isinstance(reason, str) or not reason.strip():
        raise RollbackError("INVALID_REASON", "Rollback requires a non-empty operator reason")
    if provenance.state_schema(store.dir) != "MVP_CPU_V1":
        raise RollbackError("ROLLBACK_BLOCKED", "Legacy/non-certifiable state")
    report = store.recover_publications(eng)
    if report["status"] != "READY":
        raise RollbackError("ROLLBACK_BLOCKED", str(report["errors"]))
    if report["staging"] or report["pointer_temporaries"]:
        raise RollbackError("ROLLBACK_BLOCKED", "Pending staging/publication temporaries require inspection")
    checked = ledger.verify_ledger(store)
    if not checked["ok"]:
        raise RollbackError("ROLLBACK_BLOCKED", str(checked["errors"]))
    origin = version(atomic_publish.read_current(store.stable))
    _validate_environment(eng, origin, target, checked)
    certified = {"v0000"} | {r["payload"]["version"] for r in checked["records"] if r["event_type"] == "version_promoted"}
    if set(store.versions()) - certified:
        raise RollbackError("ROLLBACK_BLOCKED", "Uncertified/non-current publication pending")
    before, after = artifact_identity(store, origin), artifact_identity(store, target)
    payload = {"from_version": origin, "to_version": target, "reason": reason.strip(), "operator_initiated": True,
               **provenance.purpose_metadata(eng.cfg),
               "version": target, "parent": origin, "manifest_hash": after["manifest_hash"],
               "from_manifest_hash": before["manifest_hash"], "to_manifest_hash": after["manifest_hash"],
               "from_evidence_hash": before["evidence_hash"], "to_evidence_hash": after["evidence_hash"],
               "previous_current": origin, "resulting_current": target, "environment_hash": before["environment_hash"],
               "timestamp": manifest.timestamp(), "execution_id": eng.execution_id,
               "intent_id": str(uuid.uuid4()), "ledger_head": checked["last_hash"],
               "ledger_sequence": len(checked["records"]), "recovered_after_crash": False}
    intent = {"intent_schema": INTENT_SCHEMA, "payload": payload}
    intent["intent_hash"] = manifest.digest(intent)
    path = store.dir / f".rollback-intent-{payload['intent_id']}.json"
    temporary = path.with_suffix(".tmp")
    with temporary.open("xb") as stream:
        stream.write(manifest.canonical_json(intent))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    atomic_publish.fsync_directory(store.dir)
    atomic_publish._checkpoint(_test_fault, "after_intent_created", path)

    def revalidate(directory):
        chain = ledger.verify_ledger(store)
        if not chain["ok"] or chain["last_hash"] != payload["ledger_head"]:
            raise RollbackError("ROLLBACK_BLOCKED", "Ledger changed during rollback")
        _validate_environment(eng, origin, target, chain)
        validate_event(store, {**payload, "intent_hash": intent["intent_hash"]}, chain["records"], chain["last_hash"])

    atomic_publish._checkpoint(_test_fault, "before_current_change", path)
    atomic_publish.switch_current(store.stable, target, origin, revalidate, _test_fault=_test_fault)
    if atomic_publish.read_current(store.stable) != target:
        raise RollbackError("ROLLBACK_BLOCKED", "CURRENT failed post-switch verification")
    revalidate(store.stable / target)
    store.load_version(target)
    atomic_publish._checkpoint(_test_fault, "after_current_verified", path)
    atomic_publish._checkpoint(_test_fault, "before_rollback_append", path)
    event = store.append_ledger_event("rollback", {**payload, "intent_hash": intent["intent_hash"]})
    atomic_publish._checkpoint(_test_fault, "after_rollback_append", path)
    if not ledger.verify_ledger(store)["ok"]:
        raise RollbackError("ROLLBACK_BLOCKED", "Ledger failed post-rollback verification")
    atomic_publish._checkpoint(_test_fault, "before_intent_remove", path)
    _remove_intent(path)
    return {"status": "COMPLETED", "code": None, "previous_current": origin, "to_version": target,
            "resulting_current": store.current_version(), "validations": "PASS", "event_id": event["event_id"]}
