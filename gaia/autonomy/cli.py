"""Explicit campaign control; no command disables safety or bypasses a gate."""
import json
from pathlib import Path
from .schema import campaign
from .store import CampaignStore


def register(sub,root):
    for name in ('autonomy-create','autonomy-run','autonomy-status','autonomy-trace','autonomy-pause','autonomy-resume','autonomy-stop'):
        p=sub.add_parser(name,help='Bounded closed-loop numpy_mlp campaign')
        p.add_argument('--state-dir',type=Path,default=Path(root)/'state_autonomy');p.add_argument('--json',action='store_true')
        if name=='autonomy-create':
            p.add_argument('--mode',choices=('DRY_RUN','SHADOW','CONTROLLED_AUTONOMOUS'),default='DRY_RUN')
            p.add_argument('--iterations',type=int,default=3);p.add_argument('--experiments',type=int,default=3)
            p.add_argument('--wall-seconds',type=int,default=1800);p.add_argument('--compute-seconds',type=int,default=1200)
            p.add_argument('--allow-promotion',action='store_true');p.add_argument('--intelligence-state',default='state_local_intelligence')
        else:p.add_argument('campaign_id')
        if name=='autonomy-run':p.add_argument('--authorize-campaign',action='store_true')
        p.set_defaults(f=lambda args,cmd=name:run(root,cmd,args),autonomy_command=True)


def run(root,cmd,args):
    try:
        if cmd=='autonomy-create':
            from .controller import create_campaign
            value=create_campaign(root,args.state_dir,campaign(mode=args.mode,promotion=args.allow_promotion,
                limits={'maximum_iterations':args.iterations,'maximum_experiments':args.experiments,'maximum_wall_time':args.wall_seconds,'maximum_compute_budget':args.compute_seconds}),intelligence_state=args.intelligence_state)
        else:
            store=CampaignStore(args.state_dir,args.campaign_id)
            if cmd=='autonomy-run':
                from .controller import ClosedLoop
                value=ClosedLoop(root,args.state_dir,args.campaign_id).run(authorized=args.authorize_campaign)
            elif cmd=='autonomy-status':
                with store.lock():
                    value=store.current();value={**value,'recovery':'COMPLETED'if value['phase']in ('COMPLETED','STOPPED','FAILED')else'NEEDS_RECOVERY'if value.get('execution_intent')or value.get('rollback_intent')or value.get('research_intent')or value.get('initialization_intent')else'SAFE_TO_RESUME'}
            elif cmd=='autonomy-trace':value={'contract':store.read('contract'),'events':store.events()}
            else:
                request={'autonomy-pause':'PAUSE','autonomy-resume':'RUN','autonomy-stop':'STOP'}[cmd];store.control(request);value={'request':request,'campaign_id':args.campaign_id,'scope':'APPLIED_AT_SAFE_BOUNDARY'}
        print(json.dumps(value,indent=2,sort_keys=True,allow_nan=False));return 2 if value.get('status')=='FAIL'else 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError):print('Autonomy blocked: INVALID_CONTRACT_AUTHORITY_OR_STATE');return 2
