"""CPU-only canonical hash chain. No repair, truncation, signatures or VCS."""
import json
import os
from pathlib import Path
import uuid

from . import provenance
from .atomic_publish import fsync_directory, _checkpoint

SCHEMA = "mvp_cpu_ledger_v1"
TYPES = {"baseline_initialized", "experiment_started", "experiment_completed", "experiment_aborted",
         "candidate_rejected", "candidate_accepted", "version_promoted", "publication_failed",
         "identity", "human_intervention", "meta", "research_diagnosis", "research_hypothesis",
         "research_result", "research_unlock", "rollback"}
ALIASES = {"init": "baseline_initialized", "start": "experiment_started", "promotion": "version_promoted",
           "publication_failure": "publication_failed"}


def enabled(store):
    try:
        state = json.loads((store.dir / "state.json").read_bytes())
        return state.get("ledger_schema") == SCHEMA and state.get("state_schema") == provenance.STATE_SCHEMA
    except (OSError, ValueError, AttributeError):
        return False


def _path(store, relative):
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Unsafe ledger reference")
    path = store.dir / p
    if path.is_symlink() or not path.resolve().is_relative_to(store.dir.resolve()) or not path.is_file():
        raise ValueError("Missing/unsafe ledger reference: " + str(relative))
    return path


def _file_hash(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def references(store, payload, event_type):
    refs = []

    def add(relative, role):
        path = _path(store, relative)
        refs.append({"path": relative, "role": role, "sha256": _file_hash(path)})

    if event_type == "baseline_initialized":
        for name in ("manifest.json", "evidence.json", "trainer.py", "genome.json"):
            add("stable/v0000/" + name, name)
        add("benchmark.json", "benchmark")
        add("provenance/snapshots/" + payload["source_snapshot"]["snapshot_id"] + "/manifest.json", "snapshot_manifest")
    elif event_type in ("experiment_started", "experiment_completed", "candidate_accepted", "candidate_rejected"):
        eid = payload["id"]
        for name in ("manifest.json", "trainer.py", "genome.json"):
            add(f"experiments/{eid}/{name}", name)
        if event_type != "experiment_started":
            add(f"experiments/{eid}/evidence.json", "evidence.json")
        doc = json.loads(_path(store, f"experiments/{eid}/manifest.json").read_bytes())
        add(doc["gate_report_path"], "gate_report")
        add(str(Path(doc["gate_report_path"]).with_name("evidence.json")), "gate_evidence")
        if doc.get("proposal_trace_path"):
            add(doc["proposal_trace_path"], "proposal_trace")
    elif event_type == "experiment_aborted":
        eid = payload["id"]
        if (store.dir / "experiments" / eid / "manifest.json").exists():
            for name in ("manifest.json", "trainer.py", "genome.json"):
                add(f"experiments/{eid}/{name}", name)
        if (store.dir / "experiments" / eid / "evidence.json").exists():
            add(f"experiments/{eid}/evidence.json", "evidence.json")
    elif event_type == "version_promoted":
        version = payload["version"]
        for name in ("manifest.json", "evidence.json", "trainer.py", "genome.json"):
            add(f"stable/{version}/{name}", name)
        doc = json.loads(_path(store, f"stable/{version}/manifest.json").read_bytes())
        add(doc["pre_promotion_path"], "pre_promotion")
    elif event_type == "rollback":
        from .rollback import version
        for prefix in ("from", "to"):
            name = version(payload[prefix + "_version"])
            for filename in ("manifest.json", "evidence.json", "trainer.py", "genome.json"):
                add(f"stable/{name}/{filename}", prefix + "_" + filename)
    return refs


def _verify_records(store, records):
    purpose = provenance.purpose_metadata(json.loads(_path(store, "stable/v0000/manifest.json").read_bytes()))
    if provenance.purpose_metadata(store.load_state()) != purpose:
        raise ValueError("Ledger certification/autonomous state purpose mismatch")
    previous = None
    ids = set()
    started, completed, accepted, promoted, actions = {}, {}, set(), set(), set()
    logical_current = None
    for index, record in enumerate(records, 1):
        if record["ledger_schema"] != SCHEMA or type(record["sequence"]) is not int or record["sequence"] != index:
            raise ValueError("Ledger schema/sequence mismatch")
        uid = str(uuid.UUID(record["event_id"]))
        if uid != record["event_id"] or uid in ids:
            raise ValueError("Duplicate/invalid event_id")
        ids.add(uid)
        if record["previous_hash"] != previous:
            raise ValueError("Ledger previous_hash mismatch")
        if record["record_hash"] != provenance.digest({k: v for k, v in record.items() if k != "record_hash"}):
            raise ValueError("Ledger record_hash mismatch")
        from datetime import datetime
        datetime.fromisoformat(record["timestamp"])
        typ, payload = record["event_type"], record["payload"]
        if any(record.get(k) != v or payload.get(k) != v for k, v in purpose.items()):
            raise ValueError("Ledger certification origin mismatch")
        if typ not in TYPES or not isinstance(payload, dict):
            raise ValueError("Invalid event_type/payload")
        if record["experiment_id"] != payload.get("id", payload.get("experiment_id")) or record["version"] != payload.get("version"):
            raise ValueError("Ledger event envelope references differ from payload")
        if record["parent"] != payload.get("parent", payload.get("parent_version", payload.get("stable_version"))):
            raise ValueError("Ledger parent envelope mismatch")
        if index == 1 and typ != "baseline_initialized":
            raise ValueError("Ledger genesis must be baseline_initialized")
        if typ == "baseline_initialized":
            if index != 1 or payload["version"] != "v0000":
                raise ValueError("Invalid baseline genesis")
            baseline = json.loads(_path(store, "stable/v0000/manifest.json").read_bytes())
            ev = json.loads(_path(store, "stable/v0000/evidence.json").read_bytes())
            for key in ("manifest_hash", "environment_hash", "source_hash", "config_hash", "sandbox_policy_hash"):
                if payload[key] != baseline[key] or ev[key] != baseline[key]:
                    raise ValueError("Genesis baseline identity mismatch: " + key)
            for key in ("trainer_hash", "genome_hash"):
                if payload[key] != ev[key]:
                    raise ValueError("Genesis artifact mismatch")
            logical_current = "v0000"
        eid = payload.get("id", payload.get("experiment_id"))
        if typ == "experiment_started":
            if eid in started:
                raise ValueError("Experiment started twice")
            doc = json.loads(_path(store, f"experiments/{eid}/manifest.json").read_bytes())
            if (doc["experiment_id"] != eid or payload["experiment_manifest_hash"] != doc["manifest_hash"] or
                    payload["stable_version"] != doc["parent_version"] or payload["environment_hash"] != doc["environment_hash"] or
                    payload["source_sha"] != doc["candidate_trainer_hash"] or provenance.digest(payload["genome"]) != doc["candidate_genome_hash"] or
                    doc["baseline_manifest_hash"] != json.loads(_path(store, "stable/v0000/manifest.json").read_bytes())["manifest_hash"]):
                raise ValueError("Experiment start manifest mismatch")
            from . import readiness
            from types import SimpleNamespace
            gate_report = readiness.validate_report(SimpleNamespace(store=store), doc,
                genome_hash=doc["candidate_genome_hash"], trainer_hash=doc["candidate_trainer_hash"],
                parent=doc["parent_version"], compare_current=False)
            if not gate_report["ok"] or any(payload.get(key) != doc[key] for key in (
                    "campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")):
                raise ValueError("Experiment cannot start without valid G0-G5 report")
            _path(store, "stable/" + doc["parent_version"] + "/manifest.json")
            started[eid] = record
        if typ in ("experiment_completed", "experiment_aborted"):
            if eid not in started or eid in completed:
                raise ValueError("Completion/abort without unique start")
            completed[eid] = payload
            if typ == "experiment_completed":
                if payload["decision"] not in ("accepted", "rejected", "deferred", "pareto_alternative"):
                    raise ValueError("Invalid completed statistical decision")
                ev = json.loads(_path(store, f"experiments/{eid}/evidence.json").read_bytes())
                for key in ("evidence_hash", "experiment_manifest_hash", "decision", "promotable", "environment_hash"):
                    if payload[key] != ev[key]:
                        raise ValueError("Experiment completion evidence mismatch: " + key)
            elif not payload.get("reason") or not payload.get("reason_code"):
                raise ValueError("Aborted experiment requires structured reason")
        if typ in ("candidate_accepted", "candidate_rejected"):
            if eid in actions:
                raise ValueError("Duplicate candidate action")
            actions.add(eid)
            if eid not in completed or completed[eid].get("decision") in ("aborted", "invalid"):
                raise ValueError("Candidate action without completed result")
            if typ == "candidate_accepted":
                if completed[eid]["decision"] != "accepted" or completed[eid]["promotable"] is not True or eid in accepted:
                    raise ValueError("Acceptance without promotable statistical result")
                accepted.add(eid)
            elif completed[eid]["decision"] == "accepted":
                raise ValueError("Rejection contradicts accepted result")
            if payload["evidence_hash"] != completed[eid]["evidence_hash"]:
                raise ValueError("Candidate action evidence mismatch")
            if typ == "candidate_accepted":
                from . import manifest, publication
                baseline = manifest._document(store.stable / "v0000/manifest.json")
                experiment = manifest._document(store.dir / f"experiments/{eid}/manifest.json")
                execution = manifest._execution_evidence(store.dir / f"experiments/{eid}/evidence.json", experiment, baseline)
                publication.confirmation(baseline, experiment, execution)
        if typ == "version_promoted":
            if eid not in accepted or payload["version"] in promoted:
                raise ValueError("Promotion without acceptance or duplicate version")
            if payload["parent"] != logical_current:
                raise ValueError("Promotion parent differs from ledger CURRENT history")
            doc = json.loads(_path(store, f"stable/{payload['version']}/manifest.json").read_bytes())
            ev = json.loads(_path(store, f"stable/{payload['version']}/evidence.json").read_bytes())
            if (doc["experiment_id"] != eid or doc["parent_version"] != payload["parent"] or
                    doc["manifest_hash"] != payload["manifest_hash"] or ev["promoted_from"] != eid or
                    payload["trainer_hash"] != ev["trainer_hash"] or payload["genome_hash"] != ev["genome_hash"] or
                    payload["stable_evidence_hash"] != ev["evidence_hash"] or
                    payload["result"] != "committed"):
                raise ValueError("Promotion version/evidence mismatch")
            promoted.add(payload["version"])
            logical_current = payload["version"]
        if typ == "rollback":
            from .rollback import validate_event
            if payload["from_version"] != logical_current:
                raise ValueError("Rollback origin differs from ledger CURRENT history")
            validate_event(store, payload, records[:index - 1], previous)
            logical_current = payload["to_version"]
        if typ == "publication_failed" and (not payload.get("reason") or payload.get("result") not in ("critical", "not_committed")):
            raise ValueError("Publication failure requires reason and result")
        for reference in record["references"]:
            if _file_hash(_path(store, reference["path"])) != reference["sha256"]:
                raise ValueError("Ledger evidence/artifact hash mismatch: " + reference["path"])
        evidence_reference = next((r for r in record["references"] if r["role"] in ("evidence.json", "to_evidence.json")), None)
        if (record["evidence_ref"] != (evidence_reference["path"] if evidence_reference else None) or
                record["evidence_hash"] != (evidence_reference["sha256"] if evidence_reference else None) or
                record["manifest_hash"] != payload.get("experiment_manifest_hash", payload.get("manifest_hash"))):
            raise ValueError("Ledger evidence/manifest envelope mismatch")
        expected_roles = {r["path"] for r in references(store, payload, typ)}
        if expected_roles != {r["path"] for r in record["references"]}:
            raise ValueError("Ledger omits required evidence references")
        if len(expected_roles) != len(record["references"]):
            raise ValueError("Duplicate ledger artifact reference")
        previous = record["record_hash"]
    return previous


def current_from_records(records):
    current = None
    for record in records:
        if record["event_type"] == "baseline_initialized":
            current = "v0000"
        elif record["event_type"] == "version_promoted":
            current = record["payload"]["version"]
        elif record["event_type"] == "rollback":
            current = record["payload"]["to_version"]
    return current


def verify_ledger(store, *, allow_empty=False):
    result = {"ok": False, "code": "LEDGER_INVALID", "schema": False, "chain": False,
              "evidence_refs": False, "version_refs": False, "records": [], "errors": []}
    try:
        if not store.ledger.exists():
            if allow_empty:
                result.update(ok=True, schema=True, chain=True, evidence_refs=True, version_refs=True)
                return result
            raise ValueError("MVP ledger missing (genesis required)")
        raw = store.ledger.read_bytes()
        if not raw or not raw.endswith(b"\n"):
            result["code"] = "LEDGER_TRUNCATED_OR_PARTIAL"
            raise ValueError("LEDGER_TRUNCATED_OR_PARTIAL")
        records = [json.loads(line) for line in raw.splitlines()]
        if not records:
            raise ValueError("Missing ledger genesis")
        result["records"] = records
        result["last_hash"] = _verify_records(store, records)
        result.update(ok=True, code=None, schema=True, chain=True, evidence_refs=True, version_refs=True)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result["errors"].append(str(exc))
    return result


def append_event(store, event_type, payload, *, _test_fault=None):
    from .manifest import timestamp
    if event_type not in TYPES:
        raise ValueError("Unsupported CPU ledger event: " + event_type)
    # Do not retain mutable caller-owned dictionaries. The compatibility type
    # is only a read API field; the authoritative type is in the envelope.
    payload = json.loads(provenance.canonical_json(payload))
    purpose = provenance.purpose_metadata(store.load_state())
    if any(k in payload and payload[k] != v for k, v in purpose.items()):
        raise ValueError("CPU event cannot override certification purpose")
    payload.update(purpose)
    payload.setdefault("type", {"baseline_initialized": "init", "experiment_started": "start",
                               "experiment_completed": "end", "experiment_aborted": "end",
                               "version_promoted": "promotion", "publication_failed": "publication_failure"}.get(event_type, event_type))
    with store.exclusive():
        if event_type == "rollback":
            from .atomic_publish import read_current
            if read_current(store.stable) != payload["resulting_current"]:
                raise ValueError("Cannot log rollback before CURRENT has changed")
        current = verify_ledger(store, allow_empty=event_type == "baseline_initialized")
        if not current["ok"]:
            raise RuntimeError(str(current["code"]) + ": " + "; ".join(current["errors"]))
        refs = references(store, payload, event_type)
        record = {"ledger_schema": SCHEMA, "sequence": len(current["records"]) + 1,
                  **purpose,
                  "event_id": str(uuid.uuid4()), "event_type": event_type, "timestamp": timestamp(),
                  "previous_hash": current.get("last_hash"), "payload": payload, "references": refs,
                  "manifest_hash": payload.get("experiment_manifest_hash", payload.get("manifest_hash")),
                  "version": payload.get("version"), "parent": payload.get("parent", payload.get("parent_version", payload.get("stable_version"))),
                  "experiment_id": payload.get("id", payload.get("experiment_id"))}
        evidence = next((r for r in refs if r["role"] in ("evidence.json", "to_evidence.json")), None)
        record["evidence_ref"] = evidence["path"] if evidence else None
        record["evidence_hash"] = evidence["sha256"] if evidence else None
        record["record_hash"] = provenance.digest(record)
        _verify_records(store, [*current["records"], record])
        data = provenance.canonical_json(record) + b"\n"
        _checkpoint(_test_fault, "before_append", store.ledger)
        fd = os.open(store.ledger, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            if _test_fault == "during_write":
                os.write(fd, data[:len(data) // 2])
                raise RuntimeError("Injected ledger partial write")
            if os.write(fd, data) != len(data):
                raise RuntimeError("LEDGER_TRUNCATED_OR_PARTIAL: short append")
            _checkpoint(_test_fault, "after_write_before_fsync", store.ledger)
            os.fsync(fd)
            fsync_directory(store.dir)
            _checkpoint(_test_fault, "after_fsync", store.ledger)
        finally:
            os.close(fd)
        verified = verify_ledger(store)
        if not verified["ok"] or verified["last_hash"] != record["record_hash"]:
            raise RuntimeError("Ledger post-append verification failed")
        return record


def from_legacy_payload(store, payload):
    typ = payload["type"]
    event = ALIASES.get(typ, typ)
    if typ == "end":
        event = "experiment_aborted" if payload.get("decision") in ("invalid", "aborted") else "experiment_completed"
    payload = {k: v for k, v in payload.items() if k != "trial_metrics"}
    if event == "experiment_aborted":
        reason = str(payload.get("reason"))
        payload["reason_code"] = next((code for marker, code in (
            ("MISMATCH", "ENVIRONMENT_MISMATCH"), ("SANDBOX", "SANDBOX_FAILURE"),
            ("STOP", "STOP_REQUESTED"), ("INTERRUPTED", "INTERRUPTED")) if marker in reason), "EXPERIMENT_ABORTED")
    with store.exclusive():
        record = append_event(store, event, payload)
        if event == "experiment_completed":
            action = "candidate_accepted" if payload["decision"] == "accepted" else "candidate_rejected"
            append_event(store, action, payload)
    return record
