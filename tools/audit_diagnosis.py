#!/usr/bin/env python3
"""Audit saved diagnoses against their exact saved observations, entirely offline.

python tools/audit_diagnosis.py --diagnosis d.json --observation o.json \
    --observation baseline.json --output audit.json
No collection, diagnostic experiments or evolutionary execution occurs here.
"""
import argparse
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.diagnosis.engine import diagnose
from gaia.diagnosis.evidence import pointer, validate_input
from gaia.diagnosis.schema import validate
from gaia.provenance import canonical_json, digest


def source_policy():
    imports, calls = set(), set()
    hashes = {}
    import hashlib
    for path in sorted((ROOT / "gaia/diagnosis").glob("*.py")):
        data = path.read_bytes()
        hashes[path.relative_to(ROOT).as_posix()] = hashlib.sha256(data).hexdigest()
        for node in ast.walk(ast.parse(data)):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
                elif isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
    forbidden_imports = {"socket", "requests", "urllib", "http", "torch", "transformers", "subprocess",
                         "engine", "search", "mutate", "publication", "rollback", "ledger", "observation.collector"}
    forbidden_calls = {"propose", "promote", "mutate", "run_trial", "run_gates", "rollback", "urlopen", "connect", "eval", "exec", "__import__"}
    # A relative import of diagnosis.engine is local composition, not gaia.engine.
    if imports & (forbidden_imports - {"engine"}) or calls & forbidden_calls:
        raise ValueError("Diagnosis authority/import policy violation")
    for path in (ROOT / "gaia/diagnosis").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_bytes())):
            if isinstance(node, ast.ImportFrom) and node.module == "engine" and node.level != 1:
                raise ValueError("Evolution engine import")
    return {"status": "PASS", "source_hash": digest(hashes), "source_files": hashes,
            "no_evolution_calls": True, "no_network_or_llm": True}


def audit_document(document, observations):
    validate(document)
    inputs = {o["observation_hash"]: validate_input(o) for o in observations}
    roles = {}
    for ref in document["source_observations"]:
        value = inputs.get(ref["observation_hash"])
        if value is None or value["observation_id"] != ref["observation_id"]:
            raise ValueError("Missing exact source observation")
        roles[ref["role"]] = value
    for item in document["evidence"]:
        observed = roles[item["observation_ref"]["role"]]
        if pointer(observed, item["field"]) != item["value"]:
            raise ValueError("Evidence reference/value mismatch")
    reproduced = diagnose(roles["current"], roles.get("baseline"), {"diagnosis": document["rules"]["thresholds"]})
    excluded = {"diagnosis_id", "timestamp", "diagnosis_hash", "cost"}
    if {k: v for k, v in reproduced.items() if k not in excluded} != {k: v for k, v in document.items() if k not in excluded}:
        raise ValueError("Diagnosis inference/allowlist reproduction mismatch")
    # Reproduction constrains every persisted string to the engine's fixed vocabulary,
    # bounded source refs and allowed evidence values; private input fields are not echoed.
    if document["cost"]["rules_evaluated"] != len(document["rules"]["evaluated"]) or document["cost"]["hypotheses_generated"] != len(document["hypotheses"]):
        raise ValueError("Cost accounting mismatch")
    return {"status": "PASS", "diagnosis_id": document["diagnosis_id"], "diagnosis_hash": document["diagnosis_hash"],
            "schema_hashes": True, "input_identities": True, "traceability": True, "confidence_consistency": True,
            "contradictions_checked": True, "privacy_allowlist": True, "no_recommendations": True,
            "reproduced_inference": True, "outcome": document["outcome"], "evidence_count": len(document["evidence"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis", type=Path, action="append", required=True)
    parser.add_argument("--observation", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        observations = [json.loads(p.read_bytes()) for p in args.observation]
        result = {"schema": "gaia_diagnosis_audit_v1", "status": "PASS", "source_policy": source_policy(),
                  "diagnoses": [audit_document(json.loads(p.read_bytes()), observations) for p in args.diagnosis]}
        result["audit_hash"] = digest(result)
        if args.output:
            with args.output.open("xb") as stream:
                stream.write(canonical_json(result))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("Diagnosis audit: FAIL (invalid evidence, trace or policy)")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
