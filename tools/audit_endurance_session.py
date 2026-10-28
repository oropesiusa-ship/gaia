#!/usr/bin/env python3
"""Stage auditor for 1.1 endurance sessions: replays the plan's PASS/FAIL criteria from a session's committed evidence.

Read-only on state. Checks journal and freeze integrity, every campaign's offline audit and recovery class, campaign
limits against the stage budget (never looser than 1.0), authority (no network, no expansion), stopping reasons,
telemetry gaps (≥2x cadence is unexplained), supervisor RSS/FD bands, and that no process of the session survives."""
import argparse
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from gaia.autonomy.session import SessionStore,validate_session
from gaia.autonomy.store import CampaignStore
from gaia.autonomy.inspection import inspect_campaign
from gaia.autonomy.telemetry import Telemetry
from gaia.autonomy.supervisor import controllers
from gaia.autonomy.lineage import LineageStore
from tools.stage2_fds import fd_count,capture_events
import audit_closed_loop

# 1.0 v1 campaign defaults: a stage may only be as strict or stricter.
V1_LIMITS={'maximum_iterations':3,'maximum_experiments':3,'maximum_wall_time':1800,'maximum_compute_budget':1200,'maximum_network_research':0}
STAGES={'stage0':{'maximum_iterations':3,'maximum_experiments':1,'maximum_wall_time':900,'maximum_compute_budget':900,
                  'maximum_disk_budget':512*2**20,'maximum_network_research':0,'promotion':False,'surface':'numpy_mlp'},
        'stage1':{'maximum_iterations':3,'maximum_experiments':2,'maximum_wall_time':900,'maximum_compute_budget':900,
                  'maximum_disk_budget':512*2**20,'maximum_network_research':0,'promotion':False,'surface':'numpy_mlp'},
        'stage2':{'maximum_iterations':5,'maximum_experiments':3,'maximum_wall_time':1800,'maximum_compute_budget':1800,
                  'maximum_disk_budget':512*2**20,'maximum_network_research':0,'promotion':False,'surface':'numpy_mlp'}}
EXPLAINED_STOPS={'DRY_RUN_COMPLETE_NO_EXPERIMENT_EXECUTED','SHADOW_COMPLETE_NO_EXPERIMENT_EXECUTED','NO_PROGRESS','STOPPED_BUDGET',
                 'NO_NOVEL_CANDIDATE','NO_AUTHORIZED_NON_DUPLICATE_EXPERIMENT','REPEATED_INCONCLUSIVE','POST_PROMOTION_REGRESSION_ROLLED_BACK',
                 'NO_SIGNIFICANT_TARGET','NO_AUTHORIZED_EXPERIMENT','OPERATOR_STOP'}
RSS_BAND=(64*2**20,0.20);FD_BAND=5


def gaps(rows,cadence,key=None,*,inclusive=False):
    """Intervals between consecutive samples of one stream (per key) longer than twice its cadence."""
    found=[];last={}
    for r in sorted(rows,key=lambda r:r['clock']['monotonic']if r['clock'].get('boot_id')else r['clock']['wall']):
        k=r.get(key)if key else None;prev=last.get(k)
        if prev and prev['clock'].get('boot_id')==r['clock'].get('boot_id'):
            dt=r['clock']['monotonic']-prev['clock']['monotonic']
            if dt>2*cadence or (inclusive and dt==2*cadence):found.append({'stream':k,'gap_s':dt,'limit_s':2*cadence})
        last[k]=r
    return found


def audit_session(root,state,session_id,*,stage=None,expected_classes=('TERMINAL_OK',),stage2_surfaces=None):
    root,state=Path(root),Path(state);session=SessionStore(state,session_id);failures=[];notes=[]
    contract=validate_session(session.read());events=session.events();view=session.state_view();limits=contract['limits']
    second_session=False
    if stage2_surfaces is not None:
        if stage!='stage2'or stage2_surfaces!=('local_inference','numpy_mlp')or len(contract['lineages'])!=2:
            failures.append('INVALID_STAGE2_SURFACE_SEQUENCE')
        else:
            lineages=[LineageStore(state,identifier).read()for identifier in contract['lineages']]
            if (tuple(value['surface']for value in lineages)!=stage2_surfaces
                    or any(value['hash']!=contract['freeze']['lineages'][value['lineage_id']]['hash']for value in lineages)):
                failures.append('INVALID_STAGE2_SURFACE_SEQUENCE')
            else:second_session=True
    if stage=='stage1':
        for key,ceiling in {'maximum_campaigns':5,'maximum_wall_s':5400,'maximum_compute_s':5400,
                            'maximum_storage_bytes':2*2**30,'maximum_research':0}.items():
            if limits[key]>ceiling:failures.append(f'SESSION_STAGE_LIMIT:{key}')
        if contract['stage']!='stage1'or contract['allow_promotion']or contract['mode']!='CONTROLLED_AUTONOMOUS':
            failures.append('SESSION_STAGE_SCOPE')
    if stage=='stage2':
        for key,ceiling in {'maximum_campaigns':2,'maximum_wall_s':7200,'maximum_compute_s':7200,
                            'maximum_storage_bytes':4*2**30,'maximum_research':0}.items():
            if limits[key]>ceiling:failures.append(f'SESSION_STAGE_LIMIT:{key}')
        if contract['stage']!='stage2'or contract['allow_promotion']or contract['mode']!='CONTROLLED_AUTONOMOUS':failures.append('SESSION_STAGE_SCOPE')
        if len(view['finished'])!=2:failures.append('S1_TWO_CAMPAIGNS_NOT_EXERCISED')
    if not view['stopped']:failures.append('SESSION_NOT_STOPPED')
    started=[e['payload']for e in events if e['kind']=='CAMPAIGN_STARTED']
    if len({p['campaign_id']for p in started})!=len(started):failures.append('DUPLICATE_CAMPAIGN')
    campaigns=[]
    for ordinal,p in enumerate(started):
        cid=p['campaign_id'];row={'campaign_id':cid}
        try:row['audit']=audit_closed_loop.audit_campaign(root,state,cid)['status']
        except (ValueError,KeyError,TypeError)as exc:row['audit']='FAIL '+(str(exc)if isinstance(exc,ValueError)else type(exc).__name__+':'+str(exc))
        info=inspect_campaign(state,cid);row.update(recovery=info['recovery'],reason=info.get('stopping_reason'))
        c=CampaignStore(state,cid).read('contract')
        if row['audit']!='PASS':failures.append(f'CAMPAIGN_AUDIT:{cid}')
        if info['recovery']not in expected_classes:failures.append(f'CAMPAIGN_CLASS:{cid}:{info["recovery"]}')
        if info.get('stopping_reason')not in EXPLAINED_STOPS:failures.append(f'UNEXPLAINED_STOP:{cid}:{info.get("stopping_reason")}')
        for k,v in V1_LIMITS.items():
            if stage=='stage2'and c['schema']=='gaia_closed_loop_campaign_v2':v=STAGES['stage2'].get(k,v)
            if k in ('maximum_iterations','maximum_experiments','maximum_network_research')and c[k]>v:failures.append(f'LOOSER_THAN_1_0:{cid}:{k}')
        if stage:
            b=STAGES[stage]
            for k in ('maximum_iterations','maximum_experiments','maximum_wall_time','maximum_compute_budget','maximum_disk_budget','maximum_network_research'):
                if c[k]>b[k]:failures.append(f'LOOSER_THAN_STAGE:{cid}:{k}')
            expected_surface=stage2_surfaces[ordinal]if second_session and ordinal<2 else b['surface']
            if second_session and (ordinal>=2 or p['lineage_id']!=contract['lineages'][ordinal]
                    or c.get('lineage_id')!=p['lineage_id']or c['mode']!=contract['mode']):
                failures.append(f'STAGE2_CAMPAIGN_ROLE_ORDER:{cid}')
            if c['promotion_policy']['enabled']!=b['promotion']or c['surface']!=expected_surface:failures.append(f'STAGE_SCOPE:{cid}')
        state_now=CampaignStore(state,cid).inspect()['state']
        if state_now.get('report_ref'):
            report=CampaignStore(state,cid).get(state_now['report_ref'])
            if report.get('permission_expansions')or report['metrics'].get('network_requests'):failures.append(f'AUTHORITY:{cid}')
            row['time']=report['metrics'].get('time');row['progress']=report['metrics'].get('progress')
            if stage=='stage2':
                charges=[e['payload']for e in events if e['kind']=='CAMPAIGN_FINISHED'and e['payload'].get('campaign_id')==cid]
                if len(charges)!=1:failures.append(f'CAMPAIGN_CHARGE_COUNT:{cid}')
                else:
                    charge=charges[0];values=[charge.get('supervised_s'),report['metrics'].get('total_wall_time'),charge.get('wall_s')]
                    if any(type(v)not in (int,float)or not math.isfinite(v)or v<0 for v in values):failures.append(f'CAMPAIGN_CHARGE_INVALID:{cid}')
                    elif charge['wall_s']!=max(values[:2])or charge['wall_s']>1800:failures.append(f'CAMPAIGN_CHARGE_MISMATCH:{cid}')
        campaigns.append(row)
    rows=Telemetry(session.root/'telemetry').samples()
    fd_required=False;fd_captures=[]
    if stage=='stage2':
        baseline_file=session.root/'evidence'/'baseline.json'
        baseline_data=json.loads(baseline_file.read_bytes())if baseline_file.exists()else{}
        fd_required='fd_accounting'in baseline_data.get('supervisor',{})
        if fd_required or any('supervisor_fd_accounting'in r or 'fd_accounting'in r.get('supervisor',{})for r in rows):
            try:fd_captures=capture_events(state,session)
            except (OSError,ValueError,TypeError):failures.append('PIDFD_CAPTURE_JOURNAL_INVALID')
    def measured_fds(metrics,clock,idle=False):
        if stage!='stage2':return metrics.get('fds')
        try:return fd_count(metrics,captures=fd_captures,clock=clock,required=fd_required,idle=idle)
        except (ValueError,KeyError,TypeError)as exc:
            failures.append('FD_ACCOUNTING_INVALID:'+str(exc))
            return metrics.get('fds')
    # Periodic streams are sampled while a campaign runs; the storage checks between campaigns are gates, not a stream.
    process=[r for r in rows if r['kind']=='PROCESS'];vram=[r for r in rows if r['kind']=='VRAM'];storage=[r for r in rows if r['kind']=='STORAGE'and r.get('campaign_id')]
    # VRAM is one host sensor, including scheduled idle. Partitioning by campaign
    # invents holes in the idle stream every time a campaign is running.
    telemetry_gaps=(gaps(process,limits['heartbeat_s'],'campaign_id',inclusive=stage=='stage2')
        +gaps(vram,limits['vram_sample_s'],inclusive=stage=='stage2')
        +gaps(storage,limits['storage_sample_s'],'campaign_id',inclusive=stage=='stage2'))
    if telemetry_gaps:failures.append('TELEMETRY_GAPS')
    if started and not process:failures.append('NO_PROCESS_TELEMETRY')
    bands={}
    if process:
        rss=[r['supervisor_rss_bytes']for r in process if r.get('supervisor_rss_bytes')]
        fds=[measured_fds({'fds':r.get('supervisor_fds'),'pid':r.get('supervisor_pid'),
              'start_time':r.get('supervisor_start_time'),
              **({'fd_accounting':r['supervisor_fd_accounting']}if 'supervisor_fd_accounting'in r else{})},r['clock'])
              for r in process if r.get('supervisor_fds')is not None]
        if fd_required and any(r.get('supervisor_fds')is None for r in process):failures.append('PROCESS_FD_MEASUREMENT_MISSING')
        if rss:
            allowed=max(RSS_BAND[0],RSS_BAND[1]*rss[0]);bands['supervisor_rss']={'first':rss[0],'max':max(rss),'allowed_growth':allowed}
            if max(rss)-rss[0]>allowed:failures.append('SUPERVISOR_RSS_BAND')
        if fds:
            bands['supervisor_fds']={'first':fds[0],'max':max(fds),'allowed_growth':FD_BAND}
            if stage=='stage2'and fd_required:
                raw=[r['supervisor_fds']for r in process if r.get('supervisor_fds')is not None]
                bands['supervisor_fds'].update(accounting='VERIFIED_PIDFD_CUSTODY_SEPARATED',raw_first=raw[0],raw_max=max(raw))
            if max(fds)-fds[0]>FD_BAND:failures.append('SUPERVISOR_FD_BAND')
    survivors=[p for e in events if e['kind']=='CHILD_EXITED'for p in e['payload'].get('survivors')or[]]
    if survivors:failures.append('PROCESSES_SURVIVED_CLEANUP')
    orphans_stopped=[p for e in events if e['kind']=='CHILD_EXITED'for p in e['payload'].get('orphans_stopped')or[]]
    if orphans_stopped:notes.append({'orphans_stopped_by_cleanup':orphans_stopped})
    live=[p for c in campaigns for p in controllers(c['campaign_id'])]
    if live:failures.append('LIVE_CONTROLLERS_AFTER_SESSION')
    if stage=='stage2':
        metrics=[r for r in rows if r['kind']=='STAGE2_METRICS']
        if not metrics:failures.append('NO_STAGE2_METRICS')
        else:
            clocks=[view['started_clock'],*[r['clock']for r in metrics],events[-1]['clock']]
            if len({r.get('boot_id')for r in clocks})!=1:failures.append('STAGE2_BOOT_DISCONTINUITY')
            if any(b['monotonic']-a['monotonic']>=20 for a,b in zip(clocks,clocks[1:])):failures.append('STAGE2_OBSERVATION_GAPS')
            supervisors=[r['supervisor']for r in metrics]
            rss=[r.get('rss_bytes')for r in supervisors]
            fds=[measured_fds(r['supervisor'],r['clock'],idle=r['phase']in('SCHEDULED_IDLE','POST_CLEANUP'))for r in metrics]
            baseline_path=session.root/'evidence'/'baseline.json'
            baseline=json.loads(baseline_path.read_bytes())if baseline_path.exists()else{}
            baseline_supervisor=baseline.get('supervisor',{})
            if not baseline_supervisor:failures.append('NO_STAGE2_BASELINE')
            if any(v is None for v in rss+fds):failures.append('INCOMPLETE_SUPERVISOR_METRICS')
            else:
                initial_rss=baseline_supervisor.get('rss_bytes',rss[0]);initial_fds=baseline_supervisor.get('fds',fds[0])
                if max(rss)-initial_rss>max(64*2**20,.2*initial_rss):failures.append('STAGE2_IDLE_RSS_BAND')
                if max(fds)-initial_fds>5:failures.append('STAGE2_IDLE_FD_BAND')
            idle=[r for r in metrics if r['phase']=='SCHEDULED_IDLE'and r['supervisor'].get('rss_bytes')is not None]
            warm=[r for r in idle if r['clock']['monotonic']>=idle[0]['clock']['monotonic']+300]if idle else[]
            if len(warm)>1:
                x=[r['clock']['monotonic']for r in warm];y=[r['supervisor']['rss_bytes']for r in warm]
                xm=sum(x)/len(x);ym=sum(y)/len(y);den=sum((v-xm)**2 for v in x)
                slope=sum((a-xm)*(b-ym)for a,b in zip(x,y))/den*3600 if den else 0
                bands['stage2_idle_rss_slope_bytes_per_hour']=slope
                if slope>2**20:failures.append('STAGE2_IDLE_RSS_SLOPE')
            else:notes.append({'idle_rss_slope':'NOT_EXERCISED'})
            if any(r.get('pss_bytes')is None for r in supervisors):notes.append({'pss_coverage':'PARTIAL'})
            before={g['index']:g['used_mib']for g in baseline.get('vram',{}).get('gpus',[])}
            after={g['index']:g['used_mib']for g in (vram[-1]if vram else{}).get('gpus',[])}
            if before and before.keys()==after.keys():
                if any(abs(after[k]-v)>256 for k,v in before.items()):failures.append('STAGE2_POST_IDLE_VRAM_BAND')
            else:notes.append({'vram_return_to_baseline':'NOT_EXERCISED'})
            if any(r.get('stage_storage_bytes',4*2**30)>=4*2**30 for r in metrics):failures.append('STAGE2_STORAGE_EXCEEDED')
            if any(r.get('stage_budget',{}).get('overrun')for r in metrics):failures.append('STAGE2_COMPUTE_RESERVATION_EXCEEDED')
            notes.append({'final_pass_coverage':'S1_ONLY_NOT_FINAL_STAGE2_PASS',
                          'unproven':['ZERO_EPHEMERAL_CHILDREN','FULL_DRIFT_ATTRIBUTION','SESSION_2_PERSISTENCE']})
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
