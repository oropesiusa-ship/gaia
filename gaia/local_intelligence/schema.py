"""Canonical evidence for local intelligence discovery, qualification and inference."""
from datetime import datetime, timezone
import json
from ..provenance import canonical_json, digest

SCHEMA = "gaia_local_intelligence_v1"
KINDS = {"HOST_PROFILE", "BUDGET", "RETENTION", "DISCOVERY", "RUNTIME", "MODEL", "DOWNLOAD", "INSTALL", "STACK", "SMOKE", "BENCHMARK", "SELECTION", "INFERENCE", "FAILURE"}
STATES = ("DISCOVERED", "STATICALLY_EVALUATED", "STATICALLY_INCOMPATIBLE", "ELIGIBLE_FOR_INSTALL", "INSTALLED_OR_BUILT",
          "SMOKE_TESTED", "MODEL_COMPATIBLE", "BENCHMARKED", "QUALIFIED", "SELECTED", "NOT_SELECTED", "QUALIFICATION_FAILED")
AUTHORITY = {"model_tool_authority": "NONE", "evaluator_modification": False, "publication_authority": False,
             "research_network_authority": False, "source_modification": False}


def artifact(kind, payload, *, created_at=None):
    if kind not in KINDS:
        raise ValueError("Invalid intelligence artifact kind")
    value = {"schema": SCHEMA, "kind": kind, "created_at": created_at or datetime.now(timezone.utc).isoformat(),
              "authority": dict(AUTHORITY), "payload": payload,
             "limitations": ["Host-bound tested evidence, not universal best available intelligence or general intelligence.",
                             "Runtime/model outputs are untrusted data and cannot change GAIA policy or protected evaluation."]}
    value["id"] = "li" + digest(value)[:24]
    value["hash"] = digest(value)
    return validate(value)


def validate(value):
    if set(value) != {"schema", "kind", "created_at", "authority", "payload", "limitations", "id", "hash"} or value["schema"] != SCHEMA or value["kind"] not in KINDS or value["authority"] != AUTHORITY:
        raise ValueError("Invalid intelligence envelope/authority")
    if value["id"] != "li" + digest({k: v for k, v in value.items() if k not in ("id", "hash")})[:24] or value["hash"] != digest({k: v for k, v in value.items() if k != "hash"}):
        raise ValueError("Intelligence identity mismatch")
    canonical_json(value)
    return value


def ref(value):
    return {"id": value["id"], "hash": value["hash"]}
