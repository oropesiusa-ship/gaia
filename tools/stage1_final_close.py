#!/usr/bin/env python3
"""One final authorized drill, one full suite, then separately scoped Stage 1 claims."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from stage0_preflight import cli
from stage1_coverage import terminal_replay,window_coverage
from audit_endurance_session import audit_session
from gaia.autonomy.session import SessionStore
from gaia.autonomy.freeze import git
from gaia.autonomy.policy import identities


def write(path,value):
    with path.open('x')as f:json.dump(value,f,indent=2)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',required=True)
    a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    if (out/'00-start.json').exists():raise SystemExit('Never restart this final-attempt workflow')
    if git(ROOT,'status','--porcelain'):raise SystemExit('Clean working tree required')
    identity=identities(ROOT);commit=git(ROOT,'rev-parse','HEAD')
    write(out/'00-start.json',{'commit':commit,'identity':identity,'maximum_new_campaigns':1,'maximum_new_experiments':2})
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'};python=sys.executable
    drill=out/'drill';drill.mkdir()
    print('FINAL DRILL STARTED; no further attempts permitted',flush=True)
    with (drill/'run.log').open('w')as log:
        result=subprocess.run([python,'-B','tools/stage1_recovery_drill.py','--out',str(drill),
            '--state','state_endurance_stage1_recovery_attempt1','--continue-lineage','ale07ce6b7ed344fcab4ad39b4'],
            cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    receipt=drill/'05-recovery_result.json'
    recovery=json.loads(receipt.read_text())if receipt.exists()else{'outcome':'FAIL','reason':'NO_DRILL_RESULT'}
    outcome=recovery['outcome']
    print('FINAL DRILL:',outcome,'exit',result.returncode,flush=True)
    started=time.monotonic()
    with (out/'full-suite.log').open('w')as log:
        suite=subprocess.run([python,'-B','-W','error::ResourceWarning','-m','unittest','discover','-s','tests'],
            cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    text=(out/'full-suite.log').read_text()
    suite_receipt={'returncode':suite.returncode,'duration_s':time.monotonic()-started,
        'resource_warnings':'ResourceWarning:'in text,'tail':text.splitlines()[-8:]}
    write(out/'01-full-suite.json',suite_receipt)
    print('FULL SUITE:',json.dumps(suite_receipt),flush=True)
    state=ROOT/'state_endurance_stage1_attempt2';sid='ase9fefbaf2a9440db80473263'
    audit=audit_session(ROOT,state,sid,stage='stage1')
    coverage=window_coverage(SessionStore(state,sid))
    replay=terminal_replay(ROOT,state,sid,cli)
    p0=ROOT/'.gaia/stage0/attempt3-20261025T223404/15-seal.json'
    s0=json.loads(p0.read_text())['sessions']['CONTROLLED']
    audit0=audit_session(ROOT,ROOT/'state_endurance_stage0_attempt3',s0,stage='stage0')
    write(out/'02-reaudit.json',{'stage0':audit0,'stage1':audit,'window':coverage,'terminal_replay':replay})
    # Do not turn real faults into missing coverage, or hide a failed native audit.
    drill_audit_path=drill/'04-offline_audit.json'
    drill_audit=json.loads(drill_audit_path.read_text())['status']if drill_audit_path.exists()else'FAIL'
    seal_path=drill/'07-seal.json'
    sealed=seal_path.exists()and json.loads(seal_path.read_text()).get('outcome')==outcome
    contract_path=drill/'02-contract.json';budget_ok=False;budget_proof={}
    if contract_path.exists():
        drill_sid=json.loads(contract_path.read_text())['session_id']
        ds=SessionStore(ROOT/'state_endurance_stage1_recovery_attempt1',drill_sid)
        events=ds.events();view=ds.state_view();limits=ds.read()['limits']
        elapsed=events[-1]['clock']['monotonic']-view['started_clock']['monotonic']
        same_boot=all(e['clock']['boot_id']==view['started_clock']['boot_id']for e in events)
        budget_ok=bool(view['stopped'])and same_boot and elapsed<=3600 and view['compute_s']<=3600 and len(view['campaigns'])==1
        budget_ok=budget_ok and limits['maximum_campaigns']==1 and limits['campaign_experiments']==2 and limits['campaign_wall_s']==3000
        budget_proof={'status':'PASS'if budget_ok else'FAIL','wall_s':elapsed,'compute_s':view['compute_s'],'campaigns':len(view['campaigns']),'same_boot':same_boot}
    valid_recovery=outcome in ('PASS','NOT_EXERCISED')and drill_audit=='PASS'and sealed and budget_ok
    write(out/'02-drill-budget.json',budget_proof)
    stable=identities(ROOT)==identity
    passed=all([audit0['status']=='PASS',audit['status']=='PASS',coverage['status']=='PASS',replay['status']=='PASS',
                suite.returncode==0,not suite_receipt['resource_warnings'],valid_recovery,stable])
    claim='PASS'if passed else'PENDING_REVIEW'
    digest={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()for p in sorted(out.rglob('*'))if p.is_file()}
    final={'STAGE_1_ENDURANCE':claim,'POST_PROMOTION_RECOVERY_REAL_DRILL':outcome,'commit':commit,
           'source_identity_unchanged':stable,'source_identity':identity['hash'],'full_suite':suite_receipt,
           'window':coverage,'stage1_audit':audit['status'],'terminal_replay':replay['status'],
           'prior_drill_outcomes':['NOT_EXERCISED','NOT_EXERCISED'],'final_drill_returncode':result.returncode,
           'final_drill_budget':budget_proof,
           'evidence_sha256':digest,'stage2_started':False}
    write(out/'03-final-claims.json',final)
    report=ROOT/'docs/endurance_evidence/STAGE1_FINAL_REPORT.md'
    if report.exists():raise SystemExit('Final report already exists; refusing to overwrite')
    body=f'''# GAIA 1.1 — Cierre consolidado de Stage 1

- **STAGE_1_ENDURANCE = {claim}**
- **POST_PROMOTION_RECOVERY_REAL_DRILL = {outcome}**
- **Stage 2: no iniciado.**

## Alcance y evidencia

Commit de validación: `{commit}`. Identidad de fuentes: `{identity['hash']}`.
Identidad conservada respecto al inicio de la validación: {stable}.
Resultados completos y hashes: `{out/'03-final-claims.json'}`.

## Endurance natural

Ventana observada: {coverage['observed_wall_s']:.3f} s, cinco campañas y diez
experimentos. Tiempo acumulado de campañas: {coverage['campaign_compute_s']:.3f} s;
el resto incluye reposo programado y supervisión, no experimentación continua.
Mayor hueco de observación: {coverage['largest_observation_gap_s']:.3f} s.
Auditoría: {audit['status']}; cobertura temporal: {coverage['status']};
replay terminal sin cambios en bytes propios: {replay['status']}.
Reauditoría de Stage 0: {audit0['status']}.

La evidencia original de la ventana conserva su FAIL por la agrupación errónea
de muestras de VRAM. La corrección tool-only audita el sensor global incluyendo
campañas y reposo; no relaja cadencias ni descarta muestras. Se conservan la
auditoría original, la reanálisis identificada y sus hashes de evidencia.

## Recovery separado

Se conservan dos intentos anteriores NOT_EXERCISED y un único intento final
autorizado, con una campaña nueva de hasta dos experimentos, límites fijados,
linaje desechable separado y aprendizaje conservado. Ningún ganador preparado,
criterio relajado, publicación forzada ni repetición automática posterior.
Checkpoint: VERIFYING con matriz nativa viva, al menos 5 s observada y
confirmada por heartbeat; un SIGKILL del controlador identificado por pid/start.
Resultado final: **{outcome}**. Auditoría del drill: {drill_audit}.

NOT_EXERCISED no certifica recuperación real ni la sustituye por tests: indica
que no surgió una promoción/checkpoint legítimo dentro del presupuesto. Según
la separación de claims aprobada por el operador, esa ausencia no invalida el
endurance. Cualquier fallo real mantiene el cierre pendiente de revisión.

## Regresión final

Una suite completa, sin reintentos, código de salida {suite.returncode};
ResourceWarnings detectados: {suite_receipt['resource_warnings']}.

```text
{chr(10).join(suite_receipt['tail'])}
```

## Siguiente fase

No se ha iniciado Stage 2. Su preparación exige runbook, límites y criterios
de ventana explícitos, incluyendo persistencia, reapertura e inferencia local
si se autoriza. Sigue sin afirmarse recuperación post-promoción real cuando
el claim correspondiente sea NOT_EXERCISED. Este cierre no es la release 1.1.
'''
    with report.open('x')as f:f.write(body)
    print('FINAL CLAIMS:',json.dumps(final,default=str),flush=True)
    print('REPORT:',report,flush=True)
    return 0 if passed else 2


if __name__=='__main__':raise SystemExit(main())
