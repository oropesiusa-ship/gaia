#!/usr/bin/env python3
"""Offline reproduction of shadow strategies from exact saved priorities/learning inputs."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.experiment_strategy.engine import plan_experiments
from gaia.experiment_strategy.schema import validate
from gaia.provenance import canonical_json, digest


def source_policy():
    allowed = {None, "", "datetime", "time", "json", "re", "statistics", "fcntl", "os", "pathlib", "tempfile",
               "provenance", "config", "diagnosis.schema", "learning.schema", "learning.applicability", "learning.store", "learning.engine",
               "prioritization.schema", "prioritization.targets", "prioritization.store", "engine", "model", "policy",
               "history", "inputs", "plans", "schema", "store", "report", "query"}
    forbidden_calls = {"run_trial", "propose", "promote", "mutate", "rollback", "run_gates", "collect", "diagnose",
                       "prioritize", "learn", "ingest", "connect", "urlopen", "system", "popen", "eval", "exec", "__import__"}
    files = {}
    for path in sorted((ROOT / "gaia/experiment_strategy").glob("*.py")):
        raw = path.read_bytes()
        files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node, ast.Import) and any(n.name not in allowed for n in node.names):
                raise ValueError("Strategy import authority violation")
            if isinstance(node, ast.ImportFrom) and (node.module not in allowed or node.module == "engine" and node.level != 1):
                raise ValueError("Evolution or external module authority violation")
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                # inputs.ingest only validates metadata; it is not LearningStore.ingest.
                local_ingest = name == "ingest" and path.name == "engine.py" and isinstance(node.func, ast.Name)
                if name in forbidden_calls and not local_ingest or name == "run" and not (path.name == "cli.py" and isinstance(node.func, ast.Name)):
                    raise ValueError("Execution/mutation authority call")
    return {"status": "PASS", "source_hash": digest(files), "files": files, "no_plan_execution": True,
            "no_mutation_authority": True, "no_evaluator_modification": True, "no_network_or_llm": True}


def audit_document(document, priorities, learning_runs=(), diagnoses=()):
    validate(document)
    priority = next((p for p in priorities if p["prioritization_hash"] == document["priority_ref"]["hash"]), None)
    if priority is None:
        raise ValueError("Missing exact priority source")
    by_hash = {r["run_hash"]: r for r in learning_runs}
    selected = []
    for ref in document["learning_refs"]:
        if ref["run_hash"] not in by_hash:
            raise ValueError("Missing exact learning source")
        selected.append(by_hash[ref["run_hash"]])
    diagnostic = diagnoses if document["diagnosis_binding"] == "EXACT_SOURCES_CHECKED" else ()
    if document["diagnosis_binding"] == "EXACT_SOURCES_CHECKED" and not diagnostic:
        raise ValueError("Missing bound diagnoses")
    reproduced = plan_experiments(priority, selected, context=document["context"], diagnoses=diagnostic,
                                  analysis_mode=document["analysis_mode"], configuration={"meta_strategy": document["policy"]["settings"]})
    dynamic = {"strategy_id", "timestamp", "cost", "output_hash"}
    if {k: v for k, v in document.items() if k not in dynamic} != {k: v for k, v in reproduced.items() if k not in dynamic}:
        raise ValueError("Strategy, knowledge, ranking or privacy reproduction mismatch")
    if any(document["cost"][key] != reproduced["cost"][key] for key in ("targets_processed", "plans_generated", "plans_considered", "learning_runs_processed")):
        raise ValueError("Strategy cost accounting mismatch")
    return {"status": "PASS", "strategy_id": document["strategy_id"], "output_hash": document["output_hash"],
            "plans": len(document["candidate_plans"]), "source_refs": True, "ranking_reproduced": True,
            "knowledge_scope_and_duplicates": True, "shadow_only": True, "no_execution_or_code": True,
            "privacy_allowlist": True, "historical_metrics_reproduced": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", type=Path, action="append", required=True)
    parser.add_argument("--priority", type=Path, action="append", required=True)
    parser.add_argument("--learning-run", type=Path, action="append", default=[])
    parser.add_argument("--diagnosis", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        priorities = [json.loads(p.read_bytes()) for p in args.priority]
        runs = [json.loads(p.read_bytes()) for p in args.learning_run]
        diagnoses = [json.loads(p.read_bytes()) for p in args.diagnosis]
        value = {"schema": "gaia_meta_strategy_audit_v1", "status": "PASS", "source_policy": source_policy(),
                 "decisions": [audit_document(json.loads(p.read_bytes()), priorities, runs, diagnoses) for p in args.decision]}
        value["audit_hash"] = digest(value)
        if args.output:
            with args.output.open("xb") as stream:
                stream.write(canonical_json(value))
        print(json.dumps(value, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Meta strategy audit: FAIL (source, policy or shadow constraints)")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
