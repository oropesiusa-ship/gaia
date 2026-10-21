"""Explicit local cognitive tasks and read-only trace inspection; no bootstrap."""
import json
from pathlib import Path
from .. import config
from .schema import task,validate_task
from .store import CognitiveStore
from .evidence import import_evidence
from .orchestrator import CognitiveOrchestrator


def load(path):
    p=Path(path)
    if p.is_symlink()or p.stat().st_size>2*2**20:raise ValueError('INVALID_COGNITIVE_INPUT')
    return json.loads(p.read_bytes())


def register(sub,root):
    for name in ('cognitive-task','cognitive-run','cognitive-tasks','cognitive-trace','cognitive-result'):
        p=sub.add_parser(name,help='Bounded local cognition with externally validated read-only tools')
        p.add_argument('--state-dir',type=Path,default=Path(root)/'state_cognition');p.add_argument('--json',action='store_true')
        if name=='cognitive-task':
            p.add_argument('--objective',required=True);p.add_argument('--task-type',default='ANSWER_FROM_EVIDENCE')
            p.add_argument('--evidence',type=Path,action='append',default=[]);p.add_argument('--output',type=Path)
        elif name=='cognitive-run':
            p.add_argument('--task',required=True,type=Path);p.add_argument('--intelligence-state',type=Path,default=Path(root)/'state_local_intelligence')
            p.add_argument('--authorize-inference',action='store_true')
        elif name in ('cognitive-trace','cognitive-result'):p.add_argument('id')
        p.set_defaults(f=lambda args,cmd=name:run(root,cmd,args),cognition_command=True)


def run(root,cmd,args):
    try:
        store=CognitiveStore(args.state_dir)
        if cmd=='cognitive-task':
            refs=[import_evidence(store,load(path),path.stem)for path in args.evidence]
            value=task(args.objective,args.task_type,refs);store.save_task(value)
            if args.output:
                from ..provenance import canonical_json
                with args.output.open('xb')as stream:stream.write(canonical_json(value))
        elif cmd=='cognitive-run':
            if not args.authorize_inference:raise ValueError('EXPLICIT_LOCAL_INFERENCE_AUTHORIZATION_REQUIRED')
            value=CognitiveOrchestrator(args.state_dir,configuration=config.load(root),intelligence_state=args.intelligence_state).run(validate_task(load(args.task)))
        elif cmd=='cognitive-tasks':value=store.list('TASK')
        else:value=store.get(args.id,'TRACE'if cmd=='cognitive-trace'else'RESULT')
        print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False))
        return 2 if cmd=='cognitive-run'and value['result']['payload']['status']=='FAILED'else 0
    except (OSError,ValueError,TypeError,KeyError):
        print('Cognition failed: INVALID_CONTRACT_EVIDENCE_OR_AUTHORITY');return 2
