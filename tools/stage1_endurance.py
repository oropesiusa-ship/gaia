#!/usr/bin/env python3
"""Stage 1: fresh lineage, bounded sequential session, read-only audit and resource evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from stage0_preflight import cli,lineage,Run
from audit_endurance_session import audit_session
from gaia.autonomy.telemetry import memory,vram,filesystem
from gaia.autonomy.freeze import git
from gaia.autonomy.policy import identities


def resources():
    return {'memory':memory(),'vram':vram(),'filesystem':filesystem(ROOT)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',required=True);ap.add_argument('--state',required=True)
    ap.add_argument('--paced',action='store_true',help='Observe a real 90 minute window with labelled idle slots')
    a=ap.parse_args();state=ROOT/a.state;run=Run(a.out)
    if state.exists():raise SystemExit('Fresh state required')
    if git(ROOT,'status','--porcelain'):raise SystemExit('Clean working tree required')
    before=resources()
    if before['memory']['below_reserve']or before['filesystem']['below_reserve']:
        raise SystemExit('Host resource reserve unavailable')
    run.record(1,'baseline','PASS',resources=before,commit=git(ROOT,'rev-parse','HEAD'),identity=identities(ROOT))
    lin=lineage(state)
    limits={'campaign_wall_s':900,'campaign_iterations':3,'campaign_experiments':2,
            'campaign_disk_bytes':512*2**20,'maximum_campaigns':5,'maximum_wall_s':5400,
            'maximum_compute_s':5400,'maximum_storage_bytes':2*2**30,'minimum_campaign_s':300}
    args=['endurance-session-create','--state-dir',str(state),'--lineage',lin,'--stage','stage1',
          '--mode','CONTROLLED_AUTONOMOUS']
    for k,v in limits.items():args+=['--limit',f'{k}={v}']
    sid=cli(*args)['session_id']
    run.record(2,'contract','PASS',session_id=sid,lineage_id=lin,limits=limits)
    if a.paced:
        from stage1_coverage import PacedSupervisor
        result=PacedSupervisor(ROOT,state,sid).run()
    else:result=cli('endurance-session-run',sid,'--state-dir',str(state),timeout=6000,check=False)
    run.record(3,'session_finished','PASS'if 'reason'in result else'FAIL',result=result)
    audit=audit_session(ROOT,state,sid,stage='stage1')
    run.record(4,'audit',audit['status'],audit=audit,resources_after=resources())
    from stage1_coverage import terminal_replay,window_coverage
    from gaia.autonomy.session import SessionStore
    replay=terminal_replay(ROOT,state,sid,cli)
    run.record(5,'terminal_replay',replay['status'],replay=replay)
    if a.paced:
        coverage=window_coverage(SessionStore(state,sid))
        run.record(6,'window_coverage',coverage['status'],coverage=coverage)
    verdict='PASS'if all(r['status']=='PASS'for r in run.results)else'FAIL'
    run.record(7,'seal',verdict,session_id=sid,identity=identities(ROOT),scope='SESSION_COVERAGE_NOT_FINAL_STAGE_CLOSURE',
               evidence={p.name:__import__('hashlib').sha256(p.read_bytes()).hexdigest()
                         for p in sorted(Path(a.out).glob('*.json'))})
    print('STAGE1_SESSION',verdict,flush=True)
    return 0 if verdict=='PASS'else 2


if __name__=='__main__':raise SystemExit(main())
