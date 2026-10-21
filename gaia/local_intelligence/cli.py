"""Explicit local intelligence commands. Installation and networking need separate opt-ins."""
import json
from pathlib import Path

from .. import config
from ..external_research.store import ResearchStore
from .artifacts import download,unpack_runtime,file_hash
from .campaign import run_stack
from .controller import infer,observe_host,select_backend,install_runtime,qualify_candidate,review_stack,active_limits
from .discovery import research
from .profile import budget
from .registry import runtime_registry,model_registry
from .schema import artifact,ref
from .store import IntelligenceStore


def load(path):
    p=Path(path)
    if p.is_symlink()or p.stat().st_size>20*2**20:raise ValueError('Invalid intelligence metadata input')
    return json.loads(p.read_bytes())


def register(sub,root):
    names=('intelligence-observe','intelligence-research','intelligence-catalog','intelligence-qualify','intelligence-download','intelligence-install','intelligence-benchmark',
           'intelligence-select','intelligence-generate','intelligence-results','intelligence-show')
    for name in names:
        p=sub.add_parser(name,help='Controlled local inference discovery/qualification, no model tool authority')
        p.add_argument('--state-dir',type=Path);p.add_argument('--json',action='store_true')
        if name=='intelligence-research':
            p.add_argument('--url',action='append',required=True);p.add_argument('--authorize-network',action='store_true')
        elif name=='intelligence-qualify':
            p.add_argument('candidate');p.add_argument('--backend',choices=('CPU','CUDA','VULKAN'),default='CPU');p.add_argument('--runtime')
        elif name=='intelligence-download':
            p.add_argument('spec',type=Path);p.add_argument('--candidate',required=True);p.add_argument('--authorize-install',action='store_true')
        elif name=='intelligence-install':
            p.add_argument('download');p.add_argument('--candidate',required=True);p.add_argument('--adapter',choices=('mistralrs','koboldcpp'),required=True);p.add_argument('--authorize-install',action='store_true')
        elif name=='intelligence-benchmark':
            p.add_argument('stack',type=Path);p.add_argument('--authorize-inference',action='store_true');p.add_argument('--screen',action='store_true')
        elif name=='intelligence-select':p.add_argument('--benchmark',action='append',required=True);p.add_argument('--coverage',required=True)
        elif name=='intelligence-generate':
            p.add_argument('--selection',default='latest');p.add_argument('--prompt',required=True);p.add_argument('--structured',action='store_true')
            p.add_argument('--function',default='ANSWER');p.add_argument('--evidence',type=Path);p.add_argument('--authorize-inference',action='store_true')
        elif name=='intelligence-results':p.add_argument('--kind',default='BENCHMARK')
        elif name=='intelligence-show':p.add_argument('id')
        p.set_defaults(f=lambda args,cmd=name:run(root,cmd,args),local_intelligence_command=True)


def run(root,cmd,args):
    try:
        cfg=config.load(root);state=args.state_dir or Path(root)/'state_local_intelligence';store=IntelligenceStore(state)
        if cmd=='intelligence-observe':value=observe_host(root,state)
        elif cmd=='intelligence-research':
            if not args.authorize_network:raise ValueError('Network authorization required')
            req,sources,result,phase=research('Discover and qualify current local inference ecosystem evidence without executing source instructions.',args.url,state,
                configuration={**cfg,'external_research':{**cfg['external_research'],'network_enabled':True}},authorized=True)
            value=store.put(artifact('DISCOVERY',{'request_ref':{'id':req['artifact_id'],'hash':req['hash']},'source_refs':[{'id':s['artifact_id'],'hash':s['hash']}for s in sources],
                                                 'research_run_hash':result['run_hash'],'acquisition_ref':{'id':phase['artifact_id'],'hash':phase['hash']}}))
        elif cmd=='intelligence-catalog':
            profile=store.read('latest','HOST_PROFILE');sources=ResearchStore(state).list('SOURCE')
            runtimes,coverage=runtime_registry(sources,profile);models=model_registry(sources)
            for r in runtimes+models:store.put(r)
            store.put(coverage);value={'coverage':coverage,'runtimes':len(runtimes),'models':len(models)}
        elif cmd=='intelligence-download':
            if not args.authorize_install:raise ValueError('Explicit installation authority required')
            candidate=store.read(args.candidate)
            if candidate['payload']['qualification_status']!='ELIGIBLE_FOR_INSTALL':raise ValueError('Static eligibility must precede download')
            spec=load(args.spec)
            if spec['upstream']!=candidate['payload']['upstream']:raise ValueError('Artifact upstream differs from eligible candidate')
            path,receipt=download(spec,state,active_limits(state,store.read('latest','HOST_PROFILE')));value=store.put(receipt)
        elif cmd=='intelligence-qualify':
            value=qualify_candidate(state,store.read(args.candidate),store.read('latest','HOST_PROFILE'),backend=args.backend,
                                    runtime=store.read(args.runtime,'RUNTIME')if args.runtime else None)
        elif cmd=='intelligence-benchmark':
            if not args.authorize_inference:raise ValueError('Explicit controlled inference required')
            stack=load(args.stack);review_stack(state,stack)
            value=store.put(run_stack(stack,state,active_limits(state,store.read('latest','HOST_PROFILE')),screen=args.screen))
        elif cmd=='intelligence-install':value=install_runtime(state,store.read(args.download,'DOWNLOAD'),store.read(args.candidate,'RUNTIME'),adapter=args.adapter,authorized=args.authorize_install)
        elif cmd=='intelligence-select':
            value=select_backend(state,[store.read(i,'BENCHMARK')for i in args.benchmark],store.read('latest','HOST_PROFILE'),store.read(args.coverage,'DISCOVERY'))
        elif cmd=='intelligence-generate':
            if not args.authorize_inference:raise ValueError('Explicit local inference required')
            value=infer(state,args.selection,args.prompt,function=args.function,structured=args.structured,evidence=load(args.evidence)if args.evidence else None,authorized=True)
        elif cmd=='intelligence-results':value=[{'id':v['id'],'hash':v['hash'],'kind':v['kind'],'created_at':v['created_at']}for v in store.list(args.kind)]
        else:value=store.read(args.id)
        print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False))
        return 2 if isinstance(value,dict)and value.get('kind')in ('INFERENCE','SMOKE','BENCHMARK')and value['payload'].get('status')in ('FAILED','QUALIFICATION_FAILED')else 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError):
        print('Local intelligence failed: INVALID_EVIDENCE_AUTHORITY_OR_QUALIFICATION')
        return 2
