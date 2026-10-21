"""Explicit saved-input shadow planning. No implicit observation, diagnosis or execution."""
import json
from pathlib import Path

from .. import config
from ..learning.store import LearningStore
from ..prioritization.store import PriorityStore
from .engine import plan_experiments
from .query import query
from .report import render
from .store import StrategyStore


def load(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Input symlink forbidden")
    return json.loads(path.read_bytes())


def register(sub, root):
    for name in ("plan-experiments", "experiment-strategies", "experiment-strategy", "strategy-metrics"):
        parser = sub.add_parser(name, help="Shadow experimental strategy planning (never executes)")
        parser.add_argument("--state-dir", type=Path)
        parser.add_argument("--json", action="store_true")
        if name == "plan-experiments":
            parser.add_argument("priority", help="Priority ID/latest or saved priority JSON")
            parser.add_argument("--learning-run", type=Path, action="append", default=[])
            parser.add_argument("--learning-state", type=Path)
            parser.add_argument("--context", type=Path)
            parser.add_argument("--diagnosis", type=Path, action="append", default=[])
            parser.add_argument("--analysis-mode", choices=("CURRENT_TARGET", "HISTORICAL_ANALYSIS"), default="CURRENT_TARGET")
        elif name in ("experiment-strategy", "strategy-metrics"):
            parser.add_argument("id", nargs="?" if name == "strategy-metrics" else None, default="latest")
        else:
            parser.add_argument("--target")
            parser.add_argument("--priority-hash")
            parser.add_argument("--class", dest="strategy_class")
            parser.add_argument("--knowledge")
            parser.add_argument("--duplicates", action="store_true")
            parser.add_argument("--highest", action="store_true")
        parser.set_defaults(f=lambda args, command=name: run(root, command, args), meta_strategy_command=True)


def run(root, command, args):
    try:
        cfg = config.load(root)
        state = args.state_dir or Path(root) / cfg["workload"]["state_dir"]
        store = StrategyStore(state)
        if command == "plan-experiments":
            priority = load(args.priority) if Path(args.priority).suffix == ".json" else PriorityStore(state).read(args.priority)
            runs = [load(p) for p in args.learning_run]
            if args.learning_state:
                runs += [b["run"] for b in LearningStore(args.learning_state).batches()]
            value = store.save(plan_experiments(priority, runs, context=load(args.context) if args.context else None,
                                                 diagnoses=[load(p) for p in args.diagnosis], analysis_mode=args.analysis_mode, configuration=cfg))
            output = render(value)
        elif command == "experiment-strategy":
            value = store.read(args.id)
            output = render(value)
        elif command == "strategy-metrics":
            doc = store.read(args.id)
            value = {"strategy_id": doc["strategy_id"], "decision_hash": doc["output_hash"], "learning_refs": doc["learning_refs"], "metrics": doc["meta_metrics"]}
            output = json.dumps(value, indent=2)
        elif any((args.target, args.priority_hash, args.strategy_class, args.knowledge, args.duplicates, args.highest)):
            value = query(store, target=args.target, priority_hash=args.priority_hash, strategy_class=args.strategy_class,
                          knowledge=args.knowledge, duplicates=args.duplicates, highest=args.highest)
            output = "\n".join(f"{v['strategy_id']} {v['rank']} {v['plan']['class']} {v['plan']['mode']}" for v in value)
        else:
            value = [{"strategy_id": d["strategy_id"], "timestamp": d["timestamp"], "plans": len(d["candidate_plans"]),
                      "mode": d["mode"], "hash": d["output_hash"]} for d in (store.read(i) for i in store.ids())]
            output = "\n".join(f"{d['strategy_id']} SHADOW plans={d['plans']}" for d in value)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) if args.json else output)
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Experiment strategy command failed: INVALID_INPUT_OR_STORE")
        return 2
