"""Canonical observation envelope and independently verifiable section evidence."""
from datetime import datetime
import json
import re

from ..provenance import canonical_json, digest

OBSERVATION_SCHEMA = "gaia_system_observation_v1"
STATUSES = {"AVAILABLE", "UNAVAILABLE", "FROZEN", "NOT_CONFIGURED", "UNKNOWN"}
SECTIONS = {"facts", "measurements", "capabilities", "context"}


def seal(document):
    value = json.loads(canonical_json(document))
    value["evidence_hashes"] = {k: digest(v) for k, v in value["sections"].items()}
    value["observation_hash"] = digest({k: v for k, v in value.items() if k != "observation_hash"})
    validate(value)
    return value


def validate(value):
    required = {"observation_id", "schema", "timestamp", "source_identity", "host_identity",
                "runtime_identity", "environment_identity", "collector_version", "sections",
                "evidence_hashes", "observation_hash"}
    if not required <= value.keys() or value["schema"] != OBSERVATION_SCHEMA:
        raise ValueError("Invalid observation schema/envelope")
    if not re.fullmatch(r"o[0-9]{6,}", value["observation_id"]):
        raise ValueError("Invalid observation id")
    if datetime.fromisoformat(value["timestamp"]).tzinfo is None:
        raise ValueError("Observation timestamp must include timezone")
    if set(value["sections"]) != SECTIONS:
        raise ValueError("Invalid observation sections")
    for name in ("source_identity", "host_identity", "runtime_identity", "environment_identity"):
        if not isinstance(value[name], dict) or not value[name]:
            raise ValueError("Missing identity: " + name)
    for capability in value["sections"]["capabilities"]:
        if (capability.get("status") not in STATUSES or
                not {"name", "evidence", "conditions"} <= capability.keys()):
            raise ValueError("Invalid capability")
    if value["evidence_hashes"] != {k: digest(v) for k, v in value["sections"].items()}:
        raise ValueError("Observation evidence hash mismatch")
    if value["observation_hash"] != digest({k: v for k, v in value.items() if k != "observation_hash"}):
        raise ValueError("Observation hash mismatch")
    canonical_json(value)  # Reject NaN and non-JSON values.
    return value
