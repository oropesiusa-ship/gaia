#!/usr/bin/env python3
"""Authorized disposable native promotion/verification SIGKILL drill. Never forces a promotion."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from stage0_preflight import Run,cli,lineage,no_duplicate_execution,PY
from stage1_coverage import terminal_replay
from audit_endurance_session import audit_session
from gaia.autonomy.clock import stamp
from gaia.autonomy.freeze import git
from gaia.autonomy.inspection import inspect_campaign
from gaia.autonomy.lineage import LineageStore,engine_state_dir
from gaia.autonomy.policy import identities
from gaia.autonomy.session import SessionStore
from gaia.autonomy.store import CampaignStore
from gaia.autonomy.supervisor import alive,controllers,tree
from gaia.autonomy.telemetry import memory,filesystem


def continuation_lineage(root,state,identifier):
    """Only continue a clean, terminal disposable drill lineage; never unblock or reset it."""
    if not Path(state).name.startswith('state_endurance_stage1_recovery_'):
        raise ValueError('DISPOSABLE_RECOVERY_NAMESPACE_REQUIRED')
    store=LineageStore(state,identifier)
    with store.lock():
        contract=store.read();view=store.state()
        if contract['objective']!='IMPROVE_NUMPY_MLP_EXISTING_CRITERIA'or contract['surface']!='numpy_mlp':
            raise ValueError('RECOVERY_LINEAGE_SCOPE_MISMATCH')
        if contract['source_identity_hash']!=identities(root)['hash']:raise ValueError('RECOVERY_SOURCE_CHANGED')
        if view['blocked']or view['open_campaigns']:raise ValueError('RECOVERY_LINEAGE_NOT_CLEANLY_CLOSED')
        if not view['campaigns']:raise ValueError('NO_PREVIOUS_DRILL_CAMPAIGN')
        for cid in view['campaigns']:
            if inspect_campaign(state,cid)['recovery']!='TERMINAL_OK'or controllers(cid):
                raise ValueError('PREVIOUS_CAMPAIGN_NOT_TERMINAL_OK')
        return {'lineage_id':identifier,'previous_campaigns':view['campaigns'],
                'previous_experiments':view['experiments'],'previous_journal_tip':store.events()[-1]['hash']}


def recovery_outcome(injected,audit,duplicates,lineage_state,state_now,reference):
    """Strict reading: safe or unexercised is not the requested rollback/reference PASS."""
    if not injected:return 'NOT_EXERCISED'
    if audit['status']!='PASS'or not duplicates['unique']or lineage_state['blocked']:return 'FAIL'
    if duplicates['intents_reserved']!=duplicates['evaluations']:return 'FAIL'
    if not state_now.get('rollback_count'):return 'NOT_EXERCISED_ROLLBACK'
    if not reference or reference.get('reason')!='AFTER_ROLLBACK'or reference.get('status')!='MEASURED':return 'FAIL'
    return 'PASS'


def inject_during_matrix(state,sid,proc,stop,result):
    """Only kill the exact campaign controller, after the supervisor has observed its live matrix child."""
    candidate=None;first_seen=None
    try:
        while not stop.wait(.5)and proc.poll()is None:
            view=SessionStore(state,sid).state_view();cid=view['running']
            if not cid:continue
            info=inspect_campaign(state,cid);pids=controllers(cid)
            if info.get('phase')!='VERIFYING'or len(pids)!=1:
                candidate=first_seen=None;continue
            pid=pids[0];snapshot=tree(pid)
            matrix=[p for p in snapshot if p['role']=='MATRIX']
            if not matrix:
                candidate=first_seen=None;continue
            leader=next((p for p in snapshot if p['pid']==pid),None)
            if not leader:continue
            identity=(cid,pid,leader['starttime'])
            if candidate!=identity:candidate=identity;first_seen=time.monotonic();continue
            # Heartbeat is 2 s: allow two observations before killing the leader.
            if time.monotonic()-first_seen<5:continue
            heartbeat_path=SessionStore(state,sid).root/'heartbeat.json'
            heartbeat=json.loads(heartbeat_path.read_bytes())
            if heartbeat.get('phase')!='VERIFYING'or heartbeat.get('child_pid')!=pid or not heartbeat.get('processes',{}).get('MATRIX'):continue
            if not alive(pid,leader['starttime']):continue
            # Persist intent and exact process identities before the one planned fault.
            proof={'campaign_id':cid,'controller_pid':pid,'controller_starttime':leader['starttime'],
                   'clock':stamp(),'processes':snapshot,'supervisor_heartbeat':heartbeat,'signal':'SIGKILL'}
            proof_path=SessionStore(state,sid).root/'verification-kill-intent.json'
            proof_path.write_text(json.dumps(proof,indent=2))
            os.kill(pid,signal.SIGKILL)
            result.update(injected=True,proof=proof)
            print('[fault] SIGKILL during real post-promotion regression matrix',flush=True)
            return
    except Exception as exc:
        result.update(error=f'{type(exc).__name__}: {exc}')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',required=True);ap.add_argument('--state',required=True)
    ap.add_argument('--continue-lineage',help='Explicitly continue a terminal disposable drill lineage, preserving all evidence')
    a=ap.parse_args();state=ROOT/a.state;out=Path(a.out);run=Run(out)
    if git(ROOT,'status','--porcelain'):raise SystemExit('Clean working tree required')
    continuation=continuation_lineage(ROOT,state,a.continue_lineage)if a.continue_lineage else None
    if not continuation and state.exists():raise SystemExit('Fresh disposable state required unless --continue-lineage is explicit')
    if memory()['below_reserve']or filesystem(ROOT)['below_reserve']:raise SystemExit('Host reserve unavailable')
    run.record(1,'baseline','PASS',commit=git(ROOT,'rev-parse','HEAD'),identity=identities(ROOT),memory=memory(),filesystem=filesystem(ROOT),continuation=continuation)
    lin=a.continue_lineage or lineage(state)
    # 50 minutes plus the existing bounded 10-minute bookkeeping grace fits the authorized hour.
    limits={'campaign_wall_s':3000,'campaign_iterations':3,'campaign_experiments':2,
            'campaign_disk_bytes':512*2**20,'maximum_campaigns':1,'maximum_wall_s':3600,
            'maximum_compute_s':3600,'maximum_storage_bytes':2*2**30,'minimum_campaign_s':300,
            'maximum_restarts':1,'maximum_recoveries':1,'relaunches_per_campaign':1,'heartbeat_s':2}
    args=['endurance-session-create','--state-dir',str(state),'--lineage',lin,
          '--stage','stage1-recovery-drill','--mode','CONTROLLED_AUTONOMOUS','--allow-promotion']
    for k,v in limits.items():args+=['--limit',f'{k}={v}']
    sid=cli(*args)['session_id']
    run.record(2,'contract','PASS',session_id=sid,lineage_id=lin,limits=limits,
               scope='SEPARATELY_AUTHORIZED_DISPOSABLE_DRILL_NOT_ENDURANCE_AUTHORITY')
    injected={};stop=threading.Event()
    with (out/'supervisor.out').open('w')as stdout,(out/'supervisor.err').open('w')as stderr:
        proc=subprocess.Popen([PY,'-B',str(ROOT/'gaia.py'),'endurance-session-run',sid,'--state-dir',str(state)],
            cwd=ROOT,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True,
            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        thread=threading.Thread(target=inject_during_matrix,args=(state,sid,proc,stop,injected),daemon=True)
        thread.start()
        # Native campaign deadlines and bounded bookkeeping stop measured work;
        # do not orphan the supervisor by imposing an unrelated communicate timeout.
        try:proc.wait()
        finally:stop.set();thread.join(10)
    run.record(3,'planned_fault','PASS'if injected.get('injected')else'FAIL',injection=injected,supervisor_returncode=proc.returncode)
    audit=audit_session(ROOT,state,sid)
    run.record(4,'offline_audit',audit['status'],audit=audit)
    view=SessionStore(state,sid).state_view()
    if not view['campaigns']:
        run.record(5,'recovery_result','FAIL',outcome='NOT_EXERCISED',reason='NO_CAMPAIGN_ADMITTED')
        run.record(7,'seal','FAIL',outcome='NOT_EXERCISED',session_id=sid)
        return 2
    cid=view['campaigns'][0]
    campaign=CampaignStore(state,cid);current=campaign.inspect()['state']
    ls=LineageStore(state,lin).state();reference=ls.get('reference')
    duplicates=no_duplicate_execution(state,cid)
    native_dir=ROOT/engine_state_dir(lin)
    from gaia.store import Store
    from gaia.ledger import verify_ledger
    native=Store(ROOT,engine_state_dir(lin))
    try:ledger=verify_ledger(native);native_version=native.current_version()
    except (OSError,ValueError,KeyError)as exc:
        ledger={'ok':False,'error':f'{type(exc).__name__}: {exc}'};native_version=None
    verdict=recovery_outcome(injected.get('injected'),audit,duplicates,ls,current,reference)
    survivors=[p for p in injected.get('proof',{}).get('processes',[])if alive(p['pid'],p['starttime'])]
    if survivors or not ledger['ok']or(reference and reference.get('version')!=native_version):verdict='FAIL'
    if verdict=='PASS':
        evaluation=campaign.get(current['evaluation_ref'])
        if native_version!=evaluation['before_version']:verdict='FAIL'
    run.record(5,'recovery_result','PASS'if verdict=='PASS'else'FAIL',outcome=verdict,duplicates=duplicates,
               rollback_count=current.get('rollback_count',0),reference=reference,lineage_blocked=ls['blocked'],
               native_version=native_version,native_ledger=ledger,survivors=survivors,
               native_state=str(native_dir))
    if verdict=='PASS':
        replay=terminal_replay(ROOT,state,sid,cli)
        run.record(6,'terminal_replay',replay['status'],replay=replay)
        if replay['status']!='PASS':verdict='FAIL'
    run.record(7,'seal','PASS'if verdict=='PASS'else'FAIL',outcome=verdict,session_id=sid,
               identity=identities(ROOT),commit=git(ROOT,'rev-parse','HEAD'))
    print('STAGE1_RECOVERY_DRILL',verdict,flush=True)
    return 0 if verdict=='PASS'else 2


if __name__=='__main__':raise SystemExit(main())
