"""Interpret saved observations only. Never invokes collectors or workloads."""
import json
from pathlib import Path

from .. import config
from ..observation.store import ObservationStore
from .engine import diagnose
from .report import render
from .store import DiagnosisStore


def register(sub, root):
    for name in ("diagnose", "diagnoses", "diagnosis"):
        parser = sub.add_parser(name, help="Interpret saved system observations locally")
        parser.add_argument("--state-dir", type=Path)
        parser.add_argument("--json", action="store_true")
        if name == "diagnose":
            parser.add_argument("observation", help="Observation id/latest or a saved JSON path")
            parser.add_argument("--baseline", help="Baseline observation id or saved JSON path")
        elif name == "diagnosis":
            parser.add_argument("id", help="dNNNNNN or latest")
        parser.set_defaults(f=lambda args, command=name: run(root, command, args), diagnosis_command=True)


def run(root, command, args):
    try:
        cfg = config.load(root)
        state = args.state_dir or Path(root) / cfg["workload"]["state_dir"]
        store = DiagnosisStore(state)
        def observation(value):
            path = Path(value)
            if path.suffix == ".json":
                if path.is_symlink():
                    raise ValueError("Observation symlink forbidden")
                return json.loads(path.read_bytes())
            return ObservationStore(state).read(value)
        if command == "diagnose":
            value = store.save(diagnose(observation(args.observation), observation(args.baseline) if args.baseline else None, cfg))
            output = render(value)
        elif command == "diagnosis":
            value = store.read(args.id)
            output = render(value)
        else:
            value = [{"diagnosis_id": d["diagnosis_id"], "timestamp": d["timestamp"], "outcome": d["outcome"], "diagnosis_hash": d["diagnosis_hash"]}
                     for d in (store.read(i) for i in store.ids())]
            output = "\n".join(f"{d['diagnosis_id']} {d['timestamp']} {d['outcome']}" for d in value)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) if args.json else output)
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Diagnosis command failed: INVALID_INPUT_OR_STORE")
        return 2
