"""Immutable research artifacts with structural external-data authority boundaries."""
from datetime import datetime, timezone
import json
import re

from ..provenance import canonical_json, digest
from .policy import VERSION

SCHEMA = "gaia_external_research_v1"
BOUNDARY = {"type": "UNTRUSTED_EXTERNAL_CONTENT", "untrusted": True, "instruction_authority": "NONE"}
REQUEST_BOUNDARY = {"type": "USER_RESEARCH_REQUEST", "untrusted": False, "instruction_authority": "REQUEST_SCOPE_ONLY"}
PREFIXES = {"REQUEST": "rq", "SOURCE": "src", "EXTRACTION": "ex", "CLAIM": "cl", "ASSESSMENT": "as", "CONCLUSION": "rc", "CACHE": "ca", "ACQUISITION": "ac"}


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def artifact(kind, payload, *, created_at=None, limitations=None):
    value = {"schema": SCHEMA, "kind": kind, "created_at": created_at or timestamp(), "policy_version": VERSION,
             "source_boundary": REQUEST_BOUNDARY if kind == "REQUEST" else BOUNDARY,
             "limitations": limitations or ["External evidence is not locally verified knowledge and has no execution authority."], "payload": payload}
    value["artifact_id"] = PREFIXES[kind] + digest(value)[:24]
    value["hash"] = digest(value)
    return validate(value)


def validate(value):
    fields = {"schema", "kind", "created_at", "policy_version", "source_boundary", "limitations", "payload", "artifact_id", "hash"}
    if set(value) != fields or value["schema"] != SCHEMA or value["kind"] not in PREFIXES or value["policy_version"] != VERSION:
        raise ValueError("Invalid research schema")
    if datetime.fromisoformat(value["created_at"]).tzinfo is None or not value["limitations"] or not isinstance(value["payload"], dict):
        raise ValueError("Invalid research envelope")
    expected = REQUEST_BOUNDARY if value["kind"] == "REQUEST" else BOUNDARY
    if value["source_boundary"] != expected:
        raise ValueError("External content cannot acquire authority")
    raw = {k: v for k, v in value.items() if k not in ("artifact_id", "hash")}
    if value["artifact_id"] != PREFIXES[value["kind"]] + digest(raw)[:24] or value["hash"] != digest({k: v for k, v in value.items() if k != "hash"}):
        raise ValueError("Research artifact hash/id mismatch")
    if value["kind"] == "CONCLUSION" and (value["payload"].get("recommendation_status") != "NOT_AUTHORIZED" or value["payload"].get("mode") != "EVIDENCE_ONLY_MODE"):
        raise ValueError("Research conclusion exceeds evidence authority")
    canonical_json(value)
    return value


def reference(value):
    return {"id": value["artifact_id"], "hash": value["hash"]}
