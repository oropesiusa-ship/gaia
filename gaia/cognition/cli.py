"""Explicit local cognitive tasks and read-only trace inspection; no bootstrap."""
import json
from pathlib import Path
from .. import config
from .schema import task,validate_task
from .store import CognitiveStore
from .evidence import import_evidence
from .orchestrator import CognitiveOrchestrator
from .conversation import ConversationStore
from .context_policy import select_context
from .research_agenda import BenchmarkObservation
from .research_campaign import CampaignBudget,ResearchCampaign
from ..local_intelligence.primary import (PrimaryLocalIntelligenceBackend,
                                          DEFAULT_CHAT_CONTEXT,MAX_TESTED_CONTEXT)


def load(path):
    p=Path(path)
    if p.is_symlink()or p.stat().st_size>2*2**20:raise ValueError('INVALID_COGNITIVE_INPUT')
    return json.loads(p.read_bytes())


def register(sub,root):
    for name in ('cognitive-task','cognitive-run','cognitive-tasks','cognitive-trace','cognitive-result',
                   'cognitive-conversation','cognitive-chat-append','cognitive-chat-history','chat','research-campaign'):
        p=sub.add_parser(name,help='Bounded local cognition with externally validated read-only tools')
        p.add_argument('--state-dir',type=Path,default=Path(root)/'state_cognition');p.add_argument('--json',action='store_true')
        if name=='cognitive-task':
            p.add_argument('--objective',required=True);p.add_argument('--task-type',default='ANSWER_FROM_EVIDENCE')
            p.add_argument('--evidence',type=Path,action='append',default=[]);p.add_argument('--output',type=Path)
        elif name=='cognitive-run':
            p.add_argument('--task',required=True,type=Path);p.add_argument('--intelligence-state',type=Path,default=Path(root)/'state_local_intelligence')
            p.add_argument('--authorize-inference',action='store_true')
        elif name=='cognitive-conversation':p.add_argument('--label',required=True);p.add_argument('--user',default='local')
        elif name=='cognitive-chat-append':
            p.add_argument('id');p.add_argument('--role',required=True,choices=('USER','ASSISTANT'));p.add_argument('--content',required=True)
        elif name=='cognitive-chat-history':p.add_argument('id')
        elif name=='chat':
            p.add_argument('--intelligence-state',type=Path,default=Path(root)/'state_local_intelligence')
            p.add_argument('--conversation');p.add_argument('--label',default='GAIA local chat');p.add_argument('--user',default='local')
            p.add_argument('--context',default='auto',choices=('auto','4096','8192','16384'))
            p.add_argument('--latency-budget',type=float,default=15)
            p.add_argument('--no-memory',action='store_true');p.add_argument('--inspect-context',action='store_true')
            p.add_argument('--list-sessions',action='store_true')
            p.add_argument('--message');p.add_argument('--max-tokens',type=int,default=96)
        elif name=='research-campaign':
            p.add_argument('--evidence',required=True,type=Path);p.add_argument('--intelligence-state',type=Path,default=Path(root)/'state_local_intelligence')
            p.add_argument('--owner',default='local');p.add_argument('--max-iterations',type=int,default=2)
            p.add_argument('--max-llm-calls',type=int,default=6);p.add_argument('--max-tokens',type=int,default=3072)
            p.add_argument('--max-duration',type=int,default=480);p.add_argument('--authorize-inference',action='store_true')
        elif name in ('cognitive-trace','cognitive-result'):p.add_argument('id')
        p.set_defaults(f=lambda args,cmd=name:run(root,cmd,args),cognition_command=True)


def run(root,cmd,args):
    try:
        if cmd=='chat':return chat(args)
        if cmd=='research-campaign':
            if not args.authorize_inference:raise ValueError('EXPLICIT_LOCAL_INFERENCE_AUTHORIZATION_REQUIRED')
            if args.evidence.is_symlink()or args.evidence.stat().st_size>4*2**20:raise ValueError('INVALID_COGNITIVE_INPUT')
            observed=BenchmarkObservation.from_bytes(args.evidence.read_bytes(),args.evidence.name)
            budget=CampaignBudget(max_iterations=args.max_iterations,max_llm_calls=args.max_llm_calls,max_tokens=args.max_tokens,max_duration_s=args.max_duration)
            factory=lambda:PrimaryLocalIntelligenceBackend(args.intelligence_state,context=DEFAULT_CHAT_CONTEXT)
            value=ResearchCampaign(CognitiveStore(args.state_dir),factory,budget=budget,owner_id=args.owner).run(observed)
            print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False));return 0
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
        elif cmd=='cognitive-conversation':value=ConversationStore(args.state_dir).create(args.label,args.user)
        elif cmd=='cognitive-chat-append':value=ConversationStore(args.state_dir).append(args.id,args.role,args.content)
        elif cmd=='cognitive-chat-history':value=ConversationStore(args.state_dir).history(args.id)
        elif cmd=='cognitive-tasks':value=store.list('TASK')
        else:value=store.get(args.id,'TRACE'if cmd=='cognitive-trace'else'RESULT')
        print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False))
        return 2 if cmd=='cognitive-run'and value['result']['payload']['status']=='FAILED'else 0
    except ValueError as exc:
        code=str(exc) if str(exc).isupper()and len(str(exc))<100 else'INVALID_CONTRACT_EVIDENCE_OR_AUTHORITY'
        print('Cognition failed: '+code);return 2
    except (OSError,TypeError,KeyError):
        print('Cognition failed: LOCAL_RUNTIME_OR_CONTRACT_FAILURE');return 2


def chat(args):
    conversations=ConversationStore(args.state_dir)
    if args.list_sessions:
        values=[{'id':v['id'],'label':v['payload']['label'],'owner_id':v['payload'].get('owner_id','local')}
                for v in conversations.store.list('CONVERSATION') if v['payload'].get('owner_id','local')==args.user]
        print(json.dumps(values,indent=2));return 0
    conversation=(conversations._conversation(args.conversation) if args.conversation
                  else conversations.create(args.label,args.user))
    if conversation['payload'].get('owner_id','local')!=args.user:raise ValueError('CONVERSATION_OWNER_MISMATCH')
    def decide(pending=''):
        return select_context(conversations.history(conversation['id']),mode=args.context,
                              latency_budget_s=args.latency_budget,pending_characters=len(pending))
    def load_backend(value):
        backend=PrimaryLocalIntelligenceBackend(args.intelligence_state,context=value['context'])
        try:backend.load()
        except Exception:
            if value['fallback'] is None:raise
            backend=PrimaryLocalIntelligenceBackend(args.intelligence_state,context=value['fallback']);backend.load()
            value={**value,'context':value['fallback'],'fallback_applied':'LOAD_FAILURE'}
        return backend,value
    decision=decide(args.message or'');backend,decision=load_backend(decision)
    try:
        if args.message is not None:
            value=conversations.respond(conversation['id'],args.message,backend,
                                        maximum=decision['context'],max_tokens=args.max_tokens,memory=not args.no_memory)
            print(json.dumps({'conversation_id':conversation['id'],'context_decision':decision,**value},indent=2,
                             sort_keys=True,allow_nan=False))
            return 0 if value['status']=='OK'else 2
        print('GAIA local chat '+conversation['id']+' (context '+str(decision['context'])+'). /exit to stop; /context to inspect.')
        while True:
            try:text=input('you> ')
            except EOFError:break
            if text.strip() in ('/exit','/quit'):break
            if text.strip()=='/context':
                print(json.dumps({'decision':decision,'turns':len(conversations.history(conversation['id']))},indent=2));continue
            if not text.strip():continue
            desired=decide(text)
            if desired['context']!=decision['context']:
                backend.unload();backend,decision=load_backend(desired)
                print('[context changed to '+str(decision['context'])+']')
            value=conversations.respond(conversation['id'],text,backend,
                                        maximum=decision['context'],max_tokens=args.max_tokens,memory=not args.no_memory)
            if args.inspect_context:print(json.dumps({'projection':value['projection'],'memory':value.get('memory',[])},indent=2))
            print('gaia> '+(value['assistant_turn']['payload']['content'] if value['status']=='OK'
                            else '[generation failed; user turn preserved]'))
        return 0
    finally:backend.unload()
