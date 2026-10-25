#!/usr/bin/env python3
"""Stage auditor for 1.1 endurance sessions: replays the plan's PASS/FAIL criteria from a session's committed evidence.

Read-only on state. Checks journal and freeze integrity, every campaign's offline audit and recovery class, campaign
limits against the stage budget (never looser than 1.0), authority (no network, no expansion), stopping reasons,
telemetry gaps (≥2x cadence is unexplained), supervisor RSS/FD bands, and that no process of the session survives."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from gaia.autonomy.session import SessionStore,validate_session
from gaia.autonomy.store import CampaignStore
from gaia.autonomy.inspection import inspect_campaign
from gaia.autonomy.telemetry import Telemetry
from gaia.autonomy.supervisor import controllers
import audit_closed_loop

# 1.0 v1 campaign defaults: a stage may only be as strict or stricter.
V1_LIMITS={'maximum_iterations':3,'maximum_experiments':3,'maximum_wall_time':1800,'maximum_compute_budget':1200,'maximum_network_research':0}
STAGES={'stage0':{'maximum_iterations':3,'maximum_experiments':1,'maximum_wall_time':900,'maximum_compute_budget':900,
                  'maximum_disk_budget':512*2**20,'maximum_network_research':0,'promotion':False,'surface':'numpy_mlp'},
        'stage1':{'maximum_iterations':3,'maximum_experiments':2,'maximum_wall_time':900,'maximum_compute_budget':900,
                  'maximum_disk_budget':512*2**20,'maximum_network_research':0,'promotion':False,'surface':'numpy_mlp'}}
EXPLAINED_STOPS={'DRY_RUN_COMPLETE_NO_EXPERIMENT_EXECUTED','SHADOW_COMPLETE_NO_EXPERIMENT_EXECUTED','NO_PROGRESS','STOPPED_BUDGET',
                 'NO_NOVEL_CANDIDATE','NO_AUTHORIZED_NON_DUPLICATE_EXPERIMENT','REPEATED_INCONCLUSIVE','POST_PROMOTION_REGRESSION_ROLLED_BACK',
                 'NO_SIGNIFICANT_TARGET','NO_AUTHORIZED_EXPERIMENT','OPERATOR_STOP'}
RSS_BAND=(64*2**20,0.20);FD_BAND=5


def gaps(rows,cadence,key=None):
    """Intervals between consecutive samples of one stream (per key) longer than twice its cadence."""
    found=[];last={}
    for r in sorted(rows,key=lambda r:r['clock']['monotonic']if r['clock'].get('boot_id')else r['clock']['wall']):
        k=r.get(key)if key else None;prev=last.get(k)
        if prev and prev['clock'].get('boot_id')==r['clock'].get('boot_id'):
            dt=r['clock']['monotonic']-prev['clock']['monotonic']
            if dt>2*cadence:found.append({'stream':k,'gap_s':dt,'limit_s':2*cadence})
        last[k]=r
    return found


def audit_session(root,state,session_id,*,stage=None,expected_classes=('TERMINAL_OK',)):
    root,state=Path(root),Path(state);session=SessionStore(state,session_id);failures=[];notes=[]
    contract=validate_session(session.read());events=session.events();view=session.state_view();limits=contract['limits']
    if stage=='stage1':
        for key,ceiling in {'maximum_campaigns':5,'maximum_wall_s':5400,'maximum_compute_s':5400,
                            'maximum_storage_bytes':2*2**30,'maximum_research':0}.items():
            if limits[key]>ceiling:failures.append(f'SESSION_STAGE_LIMIT:{key}')
        if contract['stage']!='stage1'or contract['allow_promotion']or contract['mode']!='CONTROLLED_AUTONOMOUS':
            failures.append('SESSION_STAGE_SCOPE')
    if not view['stopped']:failures.append('SESSION_NOT_STOPPED')
    started=[e['payload']for e in events if e['kind']=='CAMPAIGN_STARTED']
    if len({p['campaign_id']for p in started})!=len(started):failures.append('DUPLICATE_CAMPAIGN')
    campaigns=[]
    for p in started:
        cid=p['campaign_id'];row={'campaign_id':cid}
        try:row['audit']=audit_closed_loop.audit_campaign(root,state,cid)['status']
        except (ValueError,KeyError,TypeError)as exc:row['audit']='FAIL '+(str(exc)if isinstance(exc,ValueError)else type(exc).__name__+':'+str(exc))
        info=inspect_campaign(state,cid);row.update(recovery=info['recovery'],reason=info.get('stopping_reason'))
        c=CampaignStore(state,cid).read('contract')
        if row['audit']!='PASS':failures.append(f'CAMPAIGN_AUDIT:{cid}')
        if info['recovery']not in expected_classes:failures.append(f'CAMPAIGN_CLASS:{cid}:{info["recovery"]}')
        if info.get('stopping_reason')not in EXPLAINED_STOPS:failures.append(f'UNEXPLAINED_STOP:{cid}:{info.get("stopping_reason")}')
        for k,v in V1_LIMITS.items():
            if k in ('maximum_iterations','maximum_experiments','maximum_network_research')and c[k]>v:failures.append(f'LOOSER_THAN_1_0:{cid}:{k}')
        if stage:
            b=STAGES[stage]
            for k in ('maximum_iterations','maximum_experiments','maximum_wall_time','maximum_compute_budget','maximum_disk_budget','maximum_network_research'):
                if c[k]>b[k]:failures.append(f'LOOSER_THAN_STAGE:{cid}:{k}')
            if c['promotion_policy']['enabled']!=b['promotion']or c['surface']!=b['surface']:failures.append(f'STAGE_SCOPE:{cid}')
        state_now=CampaignStore(state,cid).inspect()['state']
        if state_now.get('report_ref'):
            report=CampaignStore(state,cid).get(state_now['report_ref'])
            if report.get('permission_expansions')or report['metrics'].get('network_requests'):failures.append(f'AUTHORITY:{cid}')
            row['time']=report['metrics'].get('time');row['progress']=report['metrics'].get('progress')
        campaigns.append(row)
    rows=Telemetry(session.root/'telemetry').samples()
    # Periodic streams are sampled while a campaign runs; the storage checks between campaigns are gates, not a stream.
    process=[r for r in rows if r['kind']=='PROCESS'];vram=[r for r in rows if r['kind']=='VRAM'];storage=[r for r in rows if r['kind']=='STORAGE'and r.get('campaign_id')]
    telemetry_gaps=gaps(process,limits['heartbeat_s'],'campaign_id')+gaps(vram,limits['vram_sample_s'],'campaign_id')+gaps(storage,limits['storage_sample_s'],'campaign_id')
    if telemetry_gaps:failures.append('TELEMETRY_GAPS')
    if started and not process:failures.append('NO_PROCESS_TELEMETRY')
    bands={}
    if process:
        rss=[r['supervisor_rss_bytes']for r in process if r.get('supervisor_rss_bytes')];fds=[r['supervisor_fds']for r in process if r.get('supervisor_fds')is not None]
        if rss:
            allowed=max(RSS_BAND[0],RSS_BAND[1]*rss[0]);bands['supervisor_rss']={'first':rss[0],'max':max(rss),'allowed_growth':allowed}
            if max(rss)-rss[0]>allowed:failures.append('SUPERVISOR_RSS_BAND')
        if fds:
            bands['supervisor_fds']={'first':fds[0],'max':max(fds),'allowed_growth':FD_BAND}
            if max(fds)-fds[0]>FD_BAND:failures.append('SUPERVISOR_FD_BAND')
    survivors=[p for e in events if e['kind']=='CHILD_EXITED'for p in e['payload'].get('survivors')or[]]
    if survivors:failures.append('PROCESSES_SURVIVED_CLEANUP')
    orphans_stopped=[p for e in events if e['kind']=='CHILD_EXITED'for p in e['payload'].get('orphans_stopped')or[]]
    if orphans_stopped:notes.append({'orphans_stopped_by_cleanup':orphans_stopped})
    live=[p for c in campaigns for p in controllers(c['campaign_id'])]
    if live:failures.append('LIVE_CONTROLLERS_AFTER_SESSION')
    from gaia.autonomy.session import restarts_used
    if restarts_used(view)>limits['maximum_restarts']or view['recoveries']>limits['maximum_recoveries']:failures.append('RECOVERY_LIMITS')
    return {'schema':'gaia_endurance_session_audit_v1','session_id':session_id,'stage':contract['stage'],'status':'FAIL'if failures else'PASS',
            'failures':failures,'notes':notes,'stopped':view['stopped'],'campaigns':campaigns,'telemetry':{'process':len(process),'vram':len(vram),
            'storage':len(storage),'gaps':telemetry_gaps},'bands':bands,'restarts':view['restarts'],'supervisor_starts':view['supervisor_starts'],
            'recoveries':view['recoveries'],'compute_s':view['compute_s']}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--state-dir',required=True);ap.add_argument('--stage');ap.add_argument('session_id')
    a=ap.parse_args();result=audit_session(ROOT,ROOT/a.state_dir if not Path(a.state_dir).is_absolute()else Path(a.state_dir),a.session_id,stage=a.stage)
    print(json.dumps(result,indent=1,default=str));return 0 if result['status']=='PASS'else 2


if __name__=='__main__':raise SystemExit(main())
