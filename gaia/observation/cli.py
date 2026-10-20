"""Offline CLI: only this subsystem can be reached from observation commands."""
import json
from pathlib import Path

from .. import config
from .collector import collect, settings
from .compare import compare
from .report import render, render_comparison
from .store import ObservationStore


def register(sub, root):
    for name in ("observe", "observations", "observation", "compare-observations"):
        parser = sub.add_parser(name, help="Local system observation (offline)")
        parser.add_argument("--state-dir", type=Path, help="Independent parent of observations/; default configured state")
        parser.add_argument("--json", action="store_true", help="Canonical-structure JSON output")
        if name == "observe":
            parser.add_argument("--quick", action="store_true")
            parser.add_argument("--baseline", action="store_true", help="Establish immutable observation baseline")
        elif name == "observation":
            parser.add_argument("id", help="oNNNNNN, latest or baseline")
        elif name == "compare-observations":
            parser.add_argument("a")
            parser.add_argument("b")
        parser.set_defaults(f=lambda args, command=name: run(root, command, args), observation_command=True)


def run(root, command, args):
    try:
        cfg = config.load(root)
        store = ObservationStore(args.state_dir or Path(root) / cfg["workload"]["state_dir"])
        def read(observation_id):
            if observation_id == "baseline":
                reference = store.baseline()
                if not reference:
                    raise ValueError("No observation baseline")
                observation_id = reference["observation_id"]
            return store.read(observation_id)
        if command == "observe":
            previous = store.latest()
            value = store.save(collect(root, store.directory.parent, cfg, args.quick))
            if args.baseline:
                store.set_baseline(value["observation_id"])
            comparison = compare(previous, value, settings(cfg)["significant_relative_change"]) if previous else None
            output = render(value, comparison)
        elif command == "observations":
            value = [{"observation_id": doc["observation_id"], "timestamp": doc["timestamp"],
                      "mode": doc["sections"]["context"]["mode"], "observation_hash": doc["observation_hash"]}
                     for doc in (store.read(i) for i in store.ids())]
            output = "\n".join(f"{v['observation_id']} {v['timestamp']} {v['mode']} {v['observation_hash']}" for v in value)
        elif command == "observation":
            value = read(args.id)
            output = render(value)
        else:
            value = compare(read(args.a), read(args.b), settings(cfg)["significant_relative_change"])
            output = render_comparison(value)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) if args.json else output)
        return 0
    except (OSError, ValueError, KeyError) as exc:
        # Do not expose arbitrary local paths in failure output.
        print("Observation command failed: " + type(exc).__name__)
        return 2
