#!/usr/bin/env python3
"""Reproduce learning from exact saved sources and immutable history, entirely offline."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.learning.contradictions import with_history
from gaia.learning.engine import learn
from gaia.learning.ingestion import load_source
from gaia.learning.schema import validate
from gaia.learning.store import LearningStore
from gaia.provenance import canonical_json, digest


def source_policy():
    allowed = {None, "", "datetime", "time", "json", "math", "re", "hashlib", "fcntl", "os", "pathlib", "tempfile", "provenance", "config",
               "schema", "records", "consolidation", "contradictions", "applicability", "engine", "store", "query", "ingestion", "report"}
    forbidden = {"run_trial", "propose", "promote", "rollback", "run_gates", "diagnose", "prioritize", "collect", "connect", "urlopen", "system", "popen", "eval", "exec", "__import__"}
    files = {}
    for path in sorted((ROOT / "gaia/learning").glob("*.py")):
        raw = path.read_bytes()
        files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node, ast.Import) and any(n.name not in allowed for n in node.names):
                raise ValueError("Learning import authority violation")
            if isinstance(node, ast.ImportFrom):
                if node.module not in allowed or node.module == "engine" and node.level != 1:
                    raise ValueError("Learning module authority violation")
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                if name in forbidden or name == "run" and not (path.name == "cli.py" and isinstance(node.func, ast.Name)):
                    raise ValueError("Execution authority call")
    return {"status": "PASS", "source_hash": digest(files), "files": files, "no_execution_authority": True,
            "no_network_or_llm": True, "no_evolution_policy_integration": True}


def audit_run(run, sources, previous_knowledge=()):
    if run["run_hash"] != digest({k: v for k, v in run.items() if k != "run_hash"}):
        raise ValueError("Run hash mismatch")
    for category in ("records", "knowledge"):
        for item in run[category]:
            validate(item)
    supplied = {s["source_hash"]: s for s in sources}
    if set(run["source_hashes"]) - supplied.keys():
        raise ValueError("Missing exact learning source")
    reproduced = with_history(learn([supplied[h] for h in run["source_hashes"]], {"learning": run["settings"]}), previous_knowledge)
    ignored = {"run_hash", "cost"}
    if {k: v for k, v in run.items() if k not in ignored} != {k: v for k, v in reproduced.items() if k not in ignored}:
        raise ValueError("Learning interpretation, privacy or trace mismatch")
    if any(run["cost"][key] != reproduced["cost"][key] for key in ("records_processed", "knowledge_items_generated")):
        raise ValueError("Cost accounting mismatch")
    return {"status": "PASS", "run_hash": run["run_hash"], "records": len(run["records"]), "knowledge_items": len(run["knowledge"]),
            "schemas_hashes": True, "source_refs": True, "duplicates_replication": True, "confidence": True,
            "contradictions_supersession": True, "context_scope": True, "privacy_allowlist": True, "reproduced": True}


def audit_store(state):
    store = LearningStore(state)
    batches = store.batches()
    previous = {}
    result = []
    for batch in batches:
        run = batch["run"]
        sources = [store._read("sources", h) for h in run["source_hashes"]]
        result.append(audit_run(run, sources, previous.values()))
        previous.update({k["learning_id"]: k for k in run["knowledge"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if not args.state_dir and not args.run:
            raise ValueError("Explicit run/store required")
        result = {"schema": "gaia_learning_audit_v1", "status": "PASS", "source_policy": source_policy(), "runs": []}
        if args.state_dir:
            result["runs"] += audit_store(args.state_dir)
        if args.run:
            sources = [load_source(p) for p in args.source]
            previous = {}
            for path in args.run:
                run = json.loads(path.read_bytes())
                result["runs"].append(audit_run(run, sources, previous.values()))
                previous.update({k["learning_id"]: k for k in run["knowledge"]})
        result["audit_hash"] = digest(result)
        if args.output:
            with args.output.open("xb") as stream:
                stream.write(canonical_json(result))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Learning audit: FAIL (source, interpretation or store)")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
