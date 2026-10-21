#!/usr/bin/env python3
"""Offline external-evidence audit. It never resolves DNS, fetches or executes a source."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.external_research.engine import replay, validate_acquisition
from gaia.external_research.fetch import validate_source
from gaia.external_research.schema import BOUNDARY, reference, validate
from gaia.provenance import canonical_json, digest


def source_policy():
    allowed = {None, "", "abc", "base64", "datetime", "email.utils", "html.parser", "hashlib", "http.client", "ipaddress",
               "json", "math", "os", "fcntl", "pathlib", "queue", "re", "socket", "ssl", "tempfile", "threading", "time",
               "urllib.parse", "urllib.robotparser", "zlib", "provenance", "config", "assessment", "claims", "cli", "engine",
               "extraction", "fetch", "network", "policy", "report", "request", "schema", "search", "store", "diagnosis.evidence",
               "diagnosis.schema", "experiment_strategy.schema"}
    denied_calls = {"run_trial", "promote", "propose", "mutate", "rollback", "run_gates", "exec", "eval", "__import__", "Popen", "system", "popen", "install"}
    files = {}
    for path in sorted((ROOT / "gaia/external_research").glob("*.py")):
        raw = path.read_bytes()
        files[path.relative_to(ROOT).as_posix()] = hashlib.sha256(raw).hexdigest()
        for node in ast.walk(ast.parse(raw)):
            if isinstance(node, ast.Import) and any(a.name not in allowed for a in node.names):
                raise ValueError("External research import authority violation")
            if isinstance(node, ast.ImportFrom) and (node.module not in allowed or node.module == "engine" and node.level != 1):
                raise ValueError("External research module authority violation")
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                if name in denied_calls or name == "run" and not (path.name == "cli.py" and isinstance(node.func, ast.Name)):
                    raise ValueError("Execution or mutation authority call")
                if name in ("connect", "wrap_socket", "getaddrinfo") and path.name != "network.py":
                    raise ValueError("Network connection outside pinned transport")
    return {"status": "PASS", "source_hash": digest(files), "files": files, "no_external_code_execution": True,
            "no_experiment_or_mutation_authority": True, "network_entry_point": "AUTHORIZED_PINNED_PUBLIC_TRANSPORT_ONLY"}


def audit_run(request, sources, run, acquisition=None):
    replay(request, sources, run)
    if run.get("acquisition_ref"):
        if acquisition is None or reference(validate_acquisition(request, acquisition)) != run["acquisition_ref"]:
            raise ValueError("Missing exact fetch phase evidence")
        captured = {tuple(sorted(e["source_ref"].items())) for e in acquisition["payload"]["result"]["events"] if e["status"] in ("FETCHED", "CACHE")}
        if captured != {tuple(sorted(reference(s).items())) for s in sources}:
            raise ValueError("Acquisition sources differ from interpretation sources")
    source_map = {s["artifact_id"]: validate_source(s) for s in sources}
    extractions = {e["artifact_id"]: e for e in run["extractions"]}
    for value in run["extractions"] + run["claims"] + run["assessments"] + run["source_assessments"] + [run["conclusion"]]:
        validate(value)
        if value["source_boundary"] != BOUNDARY:
            raise ValueError("External instruction boundary violation")
    for claim in run["claims"]:
        p = claim["payload"]
        source = source_map[p["source_ref"]["id"]]
        extraction = extractions[p["extraction_ref"]["id"]]
        fragment = next((f for f in extraction["payload"]["fragments"] if f["fragment_id"] == p["support"]["fragment_id"]), None)
        if (p["source_ref"] != reference(source) or fragment is None or fragment["text"] != p["support"]["quote"]
                or p["support"]["content_hash"] != source["payload"]["content_hash"]):
            raise ValueError("Uncited claim or wrong quote")
    live = [s for s in sources if s["payload"]["origin"] == "LIVE_PUBLIC_FETCH"]
    for source in live:
        if not source["payload"]["policy"]["settings"]["network_enabled"]:
            raise ValueError("Live capture without global authorization")
        if source["payload"]["request_ref"] == reference(request) and not request["payload"]["network_authorized"]:
            raise ValueError("Live capture lacks request authorization")
    return {"status": "PASS", "request_ref": reference(request), "run_hash": run["run_hash"], "sources": len(sources), "live_sources": len(live),
            "claims": len(run["claims"]), "source_hashes_and_identities": True, "public_url_policy": True,
            "retrieval_attestations_checked_offline": True, "untrusted_boundaries": True, "claim_citations": True,
            "quality_contradiction_applicability_reproduced": True, "replay_deterministic": True,
            "privacy_output_allowlist": True, "recommendation_status": "NOT_AUTHORIZED"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--source", type=Path, action="append", default=[])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--acquisition", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_bytes())
        sources = [json.loads(p.read_bytes()) for p in args.source]
        result = {"schema": "gaia_external_research_audit_v1", "status": "PASS", "source_policy": source_policy(),
                  "run": audit_run(request, sources, json.loads(args.run.read_bytes()), json.loads(args.acquisition.read_bytes()) if args.acquisition else None)}
        result["audit_hash"] = digest(result)
        if args.output:
            with args.output.open("xb") as stream:
                stream.write(canonical_json(result))
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("External research audit: FAIL")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
