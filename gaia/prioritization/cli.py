"""Explicit saved-diagnosis CLI, no automatic diagnosis or observation."""
import json
from pathlib import Path
from .. import config
from ..diagnosis.store import DiagnosisStore
from .engine import prioritize
from .store import PriorityStore
from .report import render


def register(sub, root):
    for name in ("prioritize", "priorities", "priority"):
        parser = sub.add_parser(name, help="Rank research targets from saved diagnoses")
        parser.add_argument("--state-dir", type=Path)
        parser.add_argument("--json", action="store_true")
        if name == "prioritize":
            parser.add_argument("diagnoses", nargs="+", help="Diagnosis IDs/latest or saved JSON paths")
        elif name == "priority":
            parser.add_argument("id")
        parser.set_defaults(f=lambda args, command=name: run(root, command, args), priority_command=True)


def run(root, command, args):
    try:
        cfg = config.load(root)
        state = args.state_dir or Path(root) / cfg["workload"]["state_dir"]
        store = PriorityStore(state)
        if command == "prioritize":
            inputs = []
            for ref in args.diagnoses:
                path = Path(ref)
                if path.suffix == ".json":
                    if path.is_symlink():
                        raise ValueError("Diagnosis symlink forbidden")
                    inputs.append(json.loads(path.read_bytes()))
                else:
                    inputs.append(DiagnosisStore(state).read(ref))
            value = store.save(prioritize(inputs, cfg))
            output = render(value)
        elif command == "priority":
            value = store.read(args.id)
            output = render(value)
        else:
            value = [{"prioritization_id": d["prioritization_id"], "timestamp": d["timestamp"], "targets": len(d["candidate_targets"]),
                      "prioritization_hash": d["prioritization_hash"]} for d in (store.read(i) for i in store.ids())]
            output = "\n".join(f"{v['prioritization_id']} targets={v['targets']} {v['timestamp']}" for v in value)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) if args.json else output)
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Prioritization command failed: INVALID_INPUT_OR_STORE")
        return 2
