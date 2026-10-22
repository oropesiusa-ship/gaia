"""Explicit campaign control; no command disables safety or bypasses a gate."""
import json
from pathlib import Path
from .schema import campaign
from .store import CampaignStore


def register(sub,root):
    for name in ('autonomy-lineage-create','autonomy-lineage-status','autonomy-lineage-unblock'):
        p=sub.add_parser(name,help='Persistent lineage shared by sequential bounded campaigns')
        p.add_argument('--state-dir',type=Path,default=Path(root)/'state_autonomy');p.add_argument('--json',action='store_true')
        if name=='autonomy-lineage-create':
            p.add_argument('--objective',choices=('IMPROVE_NUMPY_MLP_EXISTING_CRITERIA','IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA','VERIFY_NUMPY_MLP_EXISTING_CRITERIA'),required=True)
            p.add_argument('--intelligence-state',default='state_local_intelligence')
        else:p.add_argument('lineage_id')
        if name=='autonomy-lineage-unblock':p.add_argument('--reason',required=True)
        p.set_defaults(f=lambda args,cmd=name:run_lineage(root,cmd,args),autonomy_command=True)
    for name in ('autonomy-create','autonomy-run','autonomy-status','autonomy-trace','autonomy-pause','autonomy-resume','autonomy-stop','autonomy-repair-cursor'):
        p=sub.add_parser(name,help='Bounded closed-loop numpy_mlp campaign')
        p.add_argument('--state-dir',type=Path,default=Path(root)/'state_autonomy');p.add_argument('--json',action='store_true')
        if name=='autonomy-create':
            p.add_argument('--mode',choices=('DRY_RUN','SHADOW','CONTROLLED_AUTONOMOUS'),default='DRY_RUN')
            # Unspecified limits keep the contract defaults of the selected objective (v1: 3/3/1800/1200, v2: 5/5/3600/3600).
            p.add_argument('--iterations',type=int);p.add_argument('--experiments',type=int)
            p.add_argument('--wall-seconds',type=int);p.add_argument('--compute-seconds',type=int)
            p.add_argument('--allow-promotion',action='store_true');p.add_argument('--intelligence-state',default='state_local_intelligence')
            p.add_argument('--objective',choices=('VERIFY_NUMPY_MLP_EXISTING_CRITERIA','IMPROVE_NUMPY_MLP_EXISTING_CRITERIA','IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA'),
                           default='VERIFY_NUMPY_MLP_EXISTING_CRITERIA')
            p.add_argument('--lineage');p.add_argument('--no-progress-limit',type=int,default=3);p.add_argument('--replication-cap',type=int,default=2)
        else:p.add_argument('campaign_id')
        if name=='autonomy-run':p.add_argument('--authorize-campaign',action='store_true')
        p.set_defaults(f=lambda args,cmd=name:run(root,cmd,args),autonomy_command=True)


def run(root,cmd,args):
    try:
        if cmd=='autonomy-create':
            from .controller import create_campaign
            value=create_campaign(root,args.state_dir,campaign(args.objective,mode=args.mode,promotion=args.allow_promotion,lineage_id=args.lineage,
                no_progress_limit=args.no_progress_limit,replication_cap=args.replication_cap,
                limits={k:v for k,v in {'maximum_iterations':args.iterations,'maximum_experiments':args.experiments,'maximum_wall_time':args.wall_seconds,
                        'maximum_compute_budget':args.compute_seconds}.items()if v is not None}),intelligence_state=args.intelligence_state)
        else:
            store=CampaignStore(args.state_dir,args.campaign_id)
            if cmd=='autonomy-run':
                from .controller import ClosedLoop
                value=ClosedLoop(root,args.state_dir,args.campaign_id).run(authorized=args.authorize_campaign)
            elif cmd=='autonomy-status':
                # Pure inspection: safe while the campaign runs; never locks, writes or repairs.
                from .inspection import inspect_campaign
                value=inspect_campaign(args.state_dir,args.campaign_id)
            elif cmd=='autonomy-repair-cursor':value={**store.repair_cursor(),'campaign_id':args.campaign_id,'scope':'DERIVED_CURSOR_ONLY_UNDER_CAMPAIGN_LOCK'}
            elif cmd=='autonomy-trace':value={'contract':store.read('contract'),'events':store.events()}
            else:
                request={'autonomy-pause':'PAUSE','autonomy-resume':'RUN','autonomy-stop':'STOP'}[cmd];store.control(request);value={'request':request,'campaign_id':args.campaign_id,'scope':'APPLIED_AT_SAFE_BOUNDARY'}
        print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False));return 2 if value.get('status')=='FAIL'else 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):print('Autonomy blocked: INVALID_CONTRACT_AUTHORITY_OR_STATE');return 2


def run_lineage(root,cmd,args):
    from .lineage import LineageStore,create_lineage
    try:
        if cmd=='autonomy-lineage-create':value=create_lineage(root,args.state_dir,args.objective,intelligence_state=args.intelligence_state)
        else:
            store=LineageStore(args.state_dir,args.lineage_id)
            if cmd=='autonomy-lineage-status':value={'contract':store.read(),'state':store.state(),'inspection':'READ_ONLY_NO_LOCK_NO_REPAIR'}
            else:
                if not store.state()['blocked']:raise ValueError('LINEAGE_NOT_BLOCKED')
                with store.lock():value=store.event('UNBLOCKED',{'reason':args.reason,'authority':'EXPLICIT_OPERATOR_REVIEW'})
        print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):print('Autonomy blocked: INVALID_LINEAGE_AUTHORITY_OR_STATE');return 2
