"""Explicit evidence-only CLI; live networking needs global opt-in and a request authorization."""
import json
from pathlib import Path

from .. import config
from .engine import acquire, analyze, replay
from .report import render
from .request import create, observation_context
from .schema import reference
from .store import ResearchStore


def load(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Research input symlink forbidden")
    if path.stat().st_size > 12 * 2**20:
        raise ValueError("Offline research input too large")
    return json.loads(path.read_bytes())


def register(sub, root):
    for name in ("research-create", "research-fetch", "research-run", "research-replay", "research-requests", "research-request",
                 "research-sources", "research-source", "research-claims", "research-conclusion"):
        parser = sub.add_parser(name, help="Explicit external evidence acquisition; never executes external content")
        parser.add_argument("--state-dir", type=Path)
        parser.add_argument("--json", action="store_true")
        if name == "research-create":
            parser.add_argument("--question", required=True)
            parser.add_argument("--url", action="append", required=True)
            parser.add_argument("--topic", action="append", required=True)
            parser.add_argument("--domain", action="append", default=[])
            parser.add_argument("--source-class", action="append")
            parser.add_argument("--authorize-network", action="store_true")
            parser.add_argument("--freshness", default="MEDIUM")
            parser.add_argument("--observation", type=Path)
            parser.add_argument("--strategy", type=Path)
            parser.add_argument("--diagnosis", type=Path)
        elif name in ("research-fetch", "research-run"):
            parser.add_argument("request")
            parser.add_argument("--enable-network", action="store_true", help="Ephemeral global opt-in, still requires authorized request")
            parser.add_argument("--offline", action="store_true")
        elif name == "research-replay":
            parser.add_argument("request")
            parser.add_argument("--source", type=Path, action="append", required=True)
            parser.add_argument("--run", type=Path, help="Captured run to verify deterministically; no network")
        elif name in ("research-request", "research-source", "research-conclusion"):
            parser.add_argument("id")
        parser.set_defaults(f=lambda args, command=name: run(root, command, args), external_research_command=True)


def run(root, command, args):
    try:
        cfg = config.load(root)
        store = ResearchStore(args.state_dir or Path(root) / cfg["workload"]["state_dir"])
        def request(ref):
            return load(ref) if Path(ref).suffix == ".json" else store.read(ref)
        if command == "research-create":
            context, refs = {}, []
            if args.observation:
                context, ref = observation_context(load(args.observation))
                refs.append(ref)
            if args.strategy:
                from ..experiment_strategy.schema import validate
                strategy = validate(load(args.strategy))
                refs.append({"kind": "STRATEGY", "id": strategy["strategy_id"], "hash": strategy["output_hash"]})
            if args.diagnosis:
                from ..diagnosis.schema import validate
                diagnosis = validate(load(args.diagnosis))
                refs.append({"kind": "DIAGNOSIS", "id": diagnosis["diagnosis_id"], "hash": diagnosis["diagnosis_hash"]})
            value = store.put(create(args.question, args.url, topics=args.topic, context=context, refs=refs,
                                     allowed_domains=args.domain, allowed_classes=args.source_class,
                                     network_authorized=args.authorize_network, freshness=args.freshness, configuration=cfg))
            output = "Research request " + value["artifact_id"] + " network_authorized=" + str(value["payload"]["network_authorized"])
        elif command in ("research-fetch", "research-run"):
            req = request(args.request)
            if args.enable_network:
                cfg = {**cfg, "external_research": {**cfg.get("external_research", {}), "network_enabled": True}}
            store.put(req)
            sources, acquisition = acquire(req, store, cfg, offline=args.offline)
            if command == "research-fetch":
                value = {"request_ref": reference(req), "sources": [reference(s) for s in sources], "acquisition": acquisition}
                output = json.dumps(value, indent=2)
            else:
                value = analyze(req, sources)
                store.save_run(value, req, sources)
                output = render(value) + "\nACQUISITION: " + str(acquisition)
        elif command == "research-replay":
            req = request(args.request)
            sources = [load(p) for p in args.source]
            value = replay(req, sources, load(args.run)) if args.run else analyze(req, sources)
            store.save_run(value, req, sources)
            output = render(value)
        elif command in ("research-request", "research-source", "research-conclusion"):
            value = store.read(args.id)
            expected = {"research-request": "REQUEST", "research-source": "SOURCE", "research-conclusion": "CONCLUSION"}[command]
            if value["kind"] != expected:
                raise ValueError("Wrong research artifact category")
            output = json.dumps(value, indent=2)
        else:
            kind = {"research-requests": "REQUEST", "research-sources": "SOURCE", "research-claims": "CLAIM"}[command]
            value = [{"id": v["artifact_id"], "hash": v["hash"], "created_at": v["created_at"], "kind": v["kind"]} for v in store.list(kind)]
            output = "\n".join(f"{v['id']} {v['kind']} {v['created_at']}" for v in value)
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) if args.json else output)
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print("External research failed: INVALID_REQUEST_SOURCE_OR_STORE")
        return 2
