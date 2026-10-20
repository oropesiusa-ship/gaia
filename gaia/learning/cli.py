"""Explicit learning on saved structured evidence, never automatic in a campaign."""
import json
from pathlib import Path

from .. import config
from .ingestion import load_source
from .query import query
from .report import render
from .store import LearningStore


def register(sub, root):
    for name in ("learn-experiments", "learning-records", "learning-record", "knowledge", "knowledge-item", "query-knowledge"):
        parser = sub.add_parser(name, help="Contextual memory from saved experimental evidence")
        parser.add_argument("--state-dir", type=Path)
        parser.add_argument("--json", action="store_true")
        if name == "learn-experiments":
            parser.add_argument("sources", nargs="+", type=Path, help="Explicit curated experimental source JSON")
        elif name in ("learning-record", "knowledge-item"):
            parser.add_argument("id")
        elif name == "query-knowledge":
            parser.add_argument("--component")
            parser.add_argument("--workload")
            parser.add_argument("--environment")
            parser.add_argument("--claim-type")
            parser.add_argument("--minimum-confidence", default="VERY_LOW")
            parser.add_argument("--context", type=Path, help="Explicit context JSON, never current-host recollection")
            parser.add_argument("--transferability")
            parser.add_argument("--include-stale", action="store_true")
            parser.add_argument("--include-superseded", action="store_true")
            parser.add_argument("--replicated-only", action="store_true")
        parser.set_defaults(f=lambda args, command=name: run(root, command, args), learning_command=True)


def run(root, command, args):
    try:
        cfg = config.load(root)
        store = LearningStore(args.state_dir or Path(root) / cfg["workload"]["state_dir"])
        if command == "learn-experiments":
            value = store.ingest([load_source(p) for p in args.sources], cfg)
            output = "\n\n".join(render(k) for k in value["run"]["knowledge"]) + "\nCOST " + str(value["run"]["cost"])
        elif command in ("learning-record", "knowledge-item"):
            value = store.read(args.id)
            if (command == "learning-record") != (value["kind"] == "record"):
                raise ValueError("Wrong learning category")
            output = render(value)
        elif command == "query-knowledge":
            if args.context and args.context.is_symlink():
                raise ValueError("Context symlink forbidden")
            context = json.loads(args.context.read_bytes()) if args.context else None
            value = query(store, component=args.component, workload=args.workload, environment=args.environment,
                          claim_type=args.claim_type, minimum_confidence=args.minimum_confidence, context=context,
                          transferability=args.transferability, include_stale=args.include_stale,
                          include_superseded=args.include_superseded, replicated_only=args.replicated_only)
            output = "\n\n".join(render(v["item"]) + "\nAPPLICABILITY VIEW " + str(v["applicability_assessment"]) + "\nEFFECTIVE STATUS " + v["effective_status"] for v in value)
        else:
            category = "records" if command == "learning-records" else "knowledge"
            value = store.items(category, latest_only=category == "knowledge")
            output = "\n".join(f"{v['learning_id']} {v['claim_type']} {v['confidence']} {v['status']}" for v in value)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) if args.json else output)
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("Learning command failed: INVALID_SOURCE_OR_STORE")
        return 2
