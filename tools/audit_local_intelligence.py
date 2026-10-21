#!/usr/bin/env python3
"""Offline portable evidence audit. Never loads a model, executes a runtime or opens a socket."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gaia.external_research.fetch import validate_source
from gaia.external_research.request import validate_request
from gaia.external_research.extraction import extract
from gaia.external_research.schema import reference as external_ref,validate as external_validate
from gaia.local_intelligence.benchmark import evaluate
from gaia.local_intelligence.discovery import source_json,DISCOVERY_BUDGET
from gaia.local_intelligence.profile import derive
from gaia.local_intelligence.schema import validate,ref
from gaia.local_intelligence.selection import select,dimensions
from gaia.diagnosis.schema import validate as validate_diagnosis
from gaia.provenance import canonical_json,digest


def source_policy():
    hashes={}
    for path in sorted((ROOT/'gaia/local_intelligence').glob('*.py')):
        raw=path.read_bytes();hashes[path.relative_to(ROOT).as_posix()]=hashlib.sha256(raw).hexdigest()
        for node in ast.walk(ast.parse(raw)):
            names=[a.name for a in node.names]if isinstance(node,ast.Import)else[node.module or'']if isinstance(node,ast.ImportFrom)else[]
            if any(name.split('.')[0]in('protected','engine','publication','mutation','rollback','meta')for name in names):raise ValueError('Protected authority import')
            if 'subprocess'in names and path.name not in ('backend.py','isolation.py','runtime_worker.py'):raise ValueError('Unexpected native execution module')
            if isinstance(node,ast.Call):
                name=node.func.attr if isinstance(node.func,ast.Attribute)else node.func.id if isinstance(node.func,ast.Name)else''
                if name in ('eval','exec','__import__','system','popen','promote','mutate','run_trial','run_gates','rollback'):raise ValueError('Forbidden execution/experiment authority')
    return {'status':'PASS','files':hashes,'source_hash':digest(hashes),'scope':'STATIC_IMPORT_AND_CALL_BOUNDARY_NOT_FORMAL_PROGRAM_PROOF'}


def audit_bundle(directory):
    directory=Path(directory);manifest=json.loads((directory/'manifest.json').read_bytes())
    if manifest['schema']!='gaia_local_intelligence_bundle_v1':raise ValueError('Unknown bundle')
    documents={};total=0
    for name,sha in manifest['files'].items():
        rel=PurePosixPath(name);path=directory/name
        if rel.is_absolute()or'..'in rel.parts or rel.suffix!='.json'or path.is_symlink()or not path.resolve().is_relative_to(directory.resolve()):raise ValueError('Unsafe evidence path')
        total+=path.stat().st_size
        if total>64*2**20:raise ValueError('Evidence size bound')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Bundle file hash mismatch')
        documents[name]=json.loads(raw)
    local={v['id']:validate(v)for v in documents.values()if v.get('schema')=='gaia_local_intelligence_v1'}
    sources={v['artifact_id']:validate_source(v)for v in documents.values()if v.get('schema')=='gaia_external_research_v1'and v['kind']=='SOURCE'}
    external={v['artifact_id']:external_validate(v)for v in documents.values()if v.get('schema')=='gaia_external_research_v1'}
    observations={v['observation_id']:v for v in documents.values()if v.get('schema')=='gaia_system_observation_v1'}
    for v in external.values():
        if v['kind']=='REQUEST':validate_request(v)
    extractions={}
    for v in external.values():
        if v['kind']=='CLAIM':
            p=v['payload'];s=sources[p['source_ref']['id']]
            if s['artifact_id']not in extractions:extractions[s['artifact_id']]=extract(s)
            e=extractions[s['artifact_id']]
            fragment=next((f for f in e['payload']['fragments']if f['fragment_id']==p['support']['fragment_id']),None)
            if external_ref(s)!=p['source_ref']or external_ref(e)!=p['extraction_ref']or fragment is None or fragment['text']!=p['support']['quote']or p['support']['content_hash']!=s['payload']['content_hash']:raise ValueError('Research claim citation does not reproduce')
    diagnoses={v['diagnosis_id']:validate_diagnosis(v)for v in documents.values()if v.get('schema')=='gaia_system_diagnosis_v1'}
    def lookup(reference):
        value=local[reference['id']]
        if ref(value)!=reference:raise ValueError('Local evidence reference mismatch')
        return value
    for value in local.values():
        p=value['payload']
        for key in ('previous_ref','parent_catalog_ref','candidate_ref','download_ref','previous_receipt_ref'):
            if key in p:lookup(p[key])
        if value['kind']=='HOST_PROFILE':
            observation=observations[p['observation_id']]
            if derive(observation)['payload']!=p:raise ValueError('Host not derived from observation')
        if value['kind']in ('MODEL','RUNTIME'):
            for r in p.get('evidence_refs',[]):
                if external_ref(sources[r['id']])!=r:raise ValueError('Uncited catalog fact')
            if p.get('version_evidence'):
                r=p['version_evidence'];source=sources[r['id']];data=source_json(source)
                if external_ref(source)!=r or p['discovered_version']!=data.get('tag_name','commit-'+data.get('object',{}).get('sha','')):raise ValueError('Runtime version not supported by cited metadata')
        if value['kind']=='BENCHMARK'and p['status']=='QUALIFIED':
            dimensions(value)
            if evaluate(p['responses'])!=p['evaluation']:raise ValueError('Evaluation does not reproduce')
        if value['kind']=='DOWNLOAD'and p.get('research_proofs'):
            matched=False
            for proof in p['research_proofs']:
                source=sources[proof['id']];sp=source['payload']
                if proof['hash']!=source['hash']or proof['content_hash']!=sp['content_hash']or proof['url']!=sp['url']:raise ValueError('Acquisition proof mismatch')
                try:data=source_json(source)
                except (ValueError,UnicodeError):continue
                if isinstance(data,dict):
                    matched|=any(a.get('browser_download_url')==p['url']and a.get('digest')=='sha256:'+p['sha256']and a.get('size')==p['size']and data.get('tag_name')==p['version']for a in data.get('assets',[]))
                elif isinstance(data,list)and sp['url'].startswith('https://huggingface.co/api/models/'+p['upstream'].removeprefix('https://huggingface.co/')+'/tree/'+p['version']):
                    matched|=any(f.get('lfs',{}).get('oid')==p['sha256']and f.get('size')==p['size']and p['url'].endswith('/'+f.get('path',''))for f in data)
            if not matched:raise ValueError('Download not attested by upstream metadata')
    selection=lookup(manifest['selection_ref']);p=selection['payload']
    limits=lookup(manifest['budget_ref'])['payload']['current']
    results=[lookup(r)for r in manifest['final_benchmark_refs']]
    reproduced=select(results,lookup(p['host_ref']),coverage=p['coverage'])
    if reproduced['payload']!=p:raise ValueError('Selection/Pareto does not reproduce')
    if p['best_available_claim']:raise ValueError('Unsupported universal winner claim')
    for result in results:
        telemetry=result['payload']['telemetry']
        if result['payload']['status']=='QUALIFIED'and not all(telemetry.get('isolation',{}).get(k)for k in ('network_namespace_isolated','pid_namespace_isolated','root_read_only','runtime_read_only','model_read_only')):raise ValueError('Missing final isolation evidence')
        if telemetry.get('peak_rss_sum_bytes',0)>limits['worker_ram_bytes']or result['payload']['duration_s']>limits['benchmark_timeout_seconds']:raise ValueError('Final qualification resource budget exceeded')
    downloads={v['payload']['sha256']:v['payload']for v in local.values()if v['kind']=='DOWNLOAD'}
    if sum(d['size']for d in downloads.values())>limits['max_download_bytes']:raise ValueError('Artifact acquisition budget exceeded')
    for kind,key in [('MODEL','max_model_artifacts'),('RUNTIME','max_runtime_artifacts')]:
        if sum(d['kind']==kind for d in downloads.values())>limits[key]:raise ValueError('Artifact count budget exceeded')
    configurations={}
    for v in local.values():
        if v['kind']in ('BENCHMARK','SMOKE'):
            s=v['payload']['stack'];configurations.setdefault(s['model_hash'],set()).add(s['stack_id'])
    if sum(map(len,configurations.values()))>limits['max_stacks']or any(len(v)>limits['max_configurations_per_model']for v in configurations.values()):raise ValueError('Configuration budget exceeded')
    requests=sum(v['payload']['result']['requests']for v in external.values()if v['kind']=='ACQUISITION')
    decoded=sum(v['payload']['result']['decoded_bytes']for v in external.values()if v['kind']=='ACQUISITION')
    if requests>DISCOVERY_BUDGET['max_public_requests']or decoded>DISCOVERY_BUDGET['max_decoded_bytes']or len(sources)>DISCOVERY_BUDGET['max_sources']:raise ValueError('Research phase budget exceeded')
    inferences=[v for v in local.values()if v['kind']=='INFERENCE']
    if not inferences or any(v['payload']['tool_calls_executed']or v['payload']['policy_changes']or v['payload']['output_boundary']!='UNTRUSTED_MODEL_DATA'for v in inferences):raise ValueError('Inference authority boundary violated')
    for value in inferences:
        p=value['payload'];lookup(p['selection_ref'])
        if p['status']=='OK'and not p['backend_verification']['verified']:raise ValueError('Unverified live inference backend')
        for r in p['evidence_refs']:
            if r['kind']=='EXTERNAL_UNTRUSTED'and external[r['id']]['hash']!=r['hash']:raise ValueError('External inference evidence mismatch')
            if r['kind']=='DIAGNOSIS_DATA'and diagnoses[r['id']]['diagnosis_hash']!=r['hash']:raise ValueError('Diagnosis inference evidence mismatch')
    return {'status':'PASS','scope':'OFFLINE_EVIDENCE_INTEGRITY_AND_RECOMPUTATION_NOT_INDEPENDENT_HARDWARE_ATTESTATION',
        'files':len(documents),'sources':len(sources),'research_requests':requests,'research_decoded_bytes':decoded,'local_artifacts':len(local),
        'final_benchmarks':len(results),'selection_ref':ref(selection),'claim':selection['payload']['claim'],'inferences':len(inferences),'bytes':total}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('bundle',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    try:
        result={'schema':'gaia_local_intelligence_audit_v1','status':'PASS','source_policy':source_policy(),'evidence':audit_bundle(args.bundle)}
        result['hash']=digest(result)
        if args.output:
            with args.output.open('xb')as stream:stream.write(canonical_json(result))
        print(json.dumps(result,indent=2));return 0
    except (OSError,ValueError,KeyError,TypeError,AttributeError)as exc:
        print('Local intelligence audit: FAIL ('+type(exc).__name__+')');return 2


if __name__=='__main__':raise SystemExit(main())
