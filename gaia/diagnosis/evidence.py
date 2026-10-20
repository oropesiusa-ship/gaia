"""Validated v0.2 inputs and scalar allowlist evidence. Never collects host data."""
import math
import re

from ..observation.schema import validate as validate_observation
from ..provenance import canonical_json, digest

HASH = re.compile(r"[a-f0-9]{64}")


def pointer(document, path):
    value = document
    try:
        for key in path.strip("/").split("/"):
            value = value[int(key)] if isinstance(value, list) else value[key]
        return value
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def validate_input(document):
    try:
        validate_observation(document)
        facts = document["sections"]["facts"]
        measurements = document["sections"]["measurements"]
        if not isinstance(facts, dict) or not isinstance(measurements, dict):
            raise ValueError("Invalid observation section types")
        for name in ("source_identity", "host_identity", "runtime_identity", "environment_identity"):
            if not all(isinstance(k, str) for k in document[name]):
                raise ValueError("Invalid identity")
        source = document["source_identity"]
        for key in ("source_aggregate_hash", "observation_source_hash", "protected_source_identity"):
            if not HASH.fullmatch(source.get(key, "")):
                raise ValueError("Invalid source identity")
        for name in ("host_identity", "runtime_identity"):
            if not HASH.fullmatch(document[name].get("stable_hash", "")):
                raise ValueError("Invalid stable identity")
        expected_environment = digest({"host": document["host_identity"], "runtime": document["runtime_identity"], "source": source})
        if document["environment_identity"].get("identity_hash") != expected_environment:
            raise ValueError("Environment identity mismatch")
        if "host" in facts and "gpu" in facts:
            if document["host_identity"]["stable_hash"] != digest({"host": facts["host"], "gpu": facts["gpu"]}):
                raise ValueError("Host identity mismatch")
        runtime = facts.get("runtime", {})
        if "identity" in runtime:
            expected = digest(runtime["identity"])
            if runtime.get("identity_hash") != expected or document["runtime_identity"]["stable_hash"] != expected:
                raise ValueError("Runtime identity mismatch")
        if "source_files" in facts:
            files = facts["source_files"]
            protected = {p: h for p, h in files.items() if p.startswith("gaia/protected/")}
            if source["observation_source_hash"] != digest(files) or source["protected_source_identity"] != digest(protected):
                raise ValueError("Source identity mismatch")
        for scope in ("workload", "resources"):
            for key, metric in measurements.get(scope, {}).get("statistics", {}).items():
                # Missing optional metrics are allowed; malformed reported metrics are not.
                if not isinstance(metric, dict):
                    raise ValueError("Invalid measurement")
                for field in ("median", "mean", "min", "max", "standard_deviation", "coefficient_of_variation"):
                    if metric.get(field) is not None and number(metric[field]) is None:
                        raise ValueError("Invalid measurement number")
                if "samples" in metric:
                    from ..observation.stability import summarize
                    values = metric["samples"]
                    if not isinstance(values, list) or any(number(v) is None for v in values):
                        raise ValueError("Invalid samples")
                    expected = summarize(values, metric.get("criteria", {}).get("max_cv", 0.10),
                                         metric.get("criteria", {}).get("minimum_samples", 3))
                    for field in ("count", "mean", "median", "min", "max", "standard_deviation", "coefficient_of_variation", "stability"):
                        if metric.get(field) != expected[field]:
                            raise ValueError("Measurement summary mismatch")
        canonical_json(document)
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError("Invalid observation input") from exc
    return document


def identity_reference(document, role):
    return {"role": role, "observation_id": document["observation_id"], "observation_hash": document["observation_hash"],
            "environment_hash": document["environment_identity"]["identity_hash"],
            "source_hash": document["source_identity"]["observation_source_hash"]}


class Evidence:
    def __init__(self, current, baseline=None):
        self.inputs = {"current": current}
        if baseline is not None:
            self.inputs["baseline"] = baseline
        self.items = []

    def add(self, role, field, relation, group, *, kind="CORRELATIONAL", strength="MODERATE"):
        value = pointer(self.inputs[role], field)
        # No arbitrary strings from observations: only known statuses and scalar metrics.
        allowed = {"ok", "error", "timeout", "invalid", "AVAILABLE", "UNAVAILABLE", "ERROR", "NOT_CONFIGURED",
                   "STABLE", "NOISY", "INSUFFICIENT_DATA", "FROZEN", "UNKNOWN"}
        identity_hash = isinstance(value, str) and HASH.fullmatch(value) and field.split("/")[1] in {
            "source_identity", "host_identity", "runtime_identity", "environment_identity"}
        if value is None or (number(value) is None and type(value) is not bool and not (isinstance(value, str) and value in allowed) and not identity_hash):
            return None
        item = {"evidence_id": f"e{len(self.items) + 1:04d}", "observation_ref": identity_reference(self.inputs[role], role),
                "field": field, "type": kind, "value": value, "expected_relation": relation,
                "strength": strength, "group": group, "supports": [], "contradicts": []}
        self.items.append(item)
        return item["evidence_id"]

    def by_id(self, evidence_id):
        return next(e for e in self.items if e["evidence_id"] == evidence_id)
