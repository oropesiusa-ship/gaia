#!/usr/bin/env python3
"""Offline cognitive trace audit; no model execution or network access."""
import argparse
import ast
import hashlib
import json
from pathlib import Path,PurePosixPath
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gaia.cognition.schema import validate,validate_task,ref
from gaia.cognition.store import CognitiveStore
from gaia.cognition.tools import ToolRegistry
from gaia.cognition.evidence import project
from gaia.cognition.context import SYSTEM_POLICY
from gaia.cognition.benchmark import evaluate,identity
from gaia.cognition.planner import validate_plan
from gaia.provenance import canonical_json,digest


def source_policy():
    files={}
    forbidden={'subprocess','socket','http','urllib','shutil','engine','publication','rollback','mutate','protected'}
    for path in sorted((ROOT/'gaia/cognition').glob('*.py')):
        raw=path.read_bytes();files[path.relative_to(ROOT).as_posix()]=hashlib.sha256(raw).hexdigest()
        for node in ast.walk(ast.parse(raw)):
            names=[a.name for a in node.names]if isinstance(node,ast.Import)else[node.module or'']if isinstance(node,ast.ImportFrom)else[]
            if any(name.split('.')[0]in forbidden for name in names):raise ValueError('COGNITION_AUTHORITY_IMPORT')
            if isinstance(node,ast.Call):
                name=node.func.attr if isinstance(node.func,ast.Attribute)else node.func.id if isinstance(node.func,ast.Name)else''
                if name in ('eval','exec','__import__','system','popen','Popen','run_trial','promote','mutate','rollback','install_runtime','download'):raise ValueError('COGNITION_AUTHORITY_CALL')
    return {'status':'PASS','files':files,'hash':digest(files),'scope':'STATIC_CALL_AND_IMPORT_REVIEW_NOT_FORMAL_PROOF'}


def audit_trace(store,trace):
    validate(trace)
    if trace['kind']!='TRACE':raise ValueError('TRACE_REQUIRED')
    def resolve(r,kind):
        v=store.get(r['id'],kind)
        if ref(v)!=r:raise ValueError('TRACE_REFERENCE_HASH')
        return v
    task=validate_task(resolve(trace['payload']['task_ref'],'TASK')['payload']);registry=ToolRegistry(store)
    result=resolve(trace['payload']['result_ref'],'RESULT')['payload']
    kinds=('CONTEXT','PROPOSAL','VALIDATION','TOOL_RESULT','MODEL_TURN','PLAN');events=[]
    for r in trace['payload']['events']:
        v=None
        for kind in kinds:
            try:v=store.get(r['id'],kind);break
            except FileNotFoundError:pass
        if v is None or ref(v)!=r:raise ValueError('UNRESOLVED_TRACE_EVENT')
        events.append(v)
    seen={};facts={};tool_results=[];context=None;model_turns=0;reserved=0;last_model=None
    for event in events:
        kind=event['kind'];p=event['payload']
        if kind=='CONTEXT':
            context=p
            if p['system_policy_hash']!=digest(SYSTEM_POLICY)or p['context']['SYSTEM_POLICY']!=SYSTEM_POLICY:raise ValueError('SYSTEM_CONTRACT_CHANGED')
            if p['input_tokens']>p['max_input_tokens']or p['input_tokens']+p['reserved_output_tokens']+p['reserved_adapter_safety_tokens']>p['backend_context_tokens']:raise ValueError('CONTEXT_BUDGET_VIOLATION')
            included=[v['fact_id']for v in p['included_items']]
            if any(fid not in facts for fid in included):raise ValueError('FABRICATED_CONTEXT_FACT')
            prompt_rows=p['context']['LOCAL_VERIFIED_EVIDENCE']+p['context']['EXTERNAL_UNTRUSTED_EVIDENCE']
            if len(prompt_rows)!=len(included):raise ValueError('CONTEXT_PROJECTION_MISMATCH')
            for row in prompt_rows:
                index=int(row['id'][1:])-1;fact=facts[included[index]]
                if row!={'id':row['id'],'field':fact['field'],'value':fact['value'],'instruction_authority':'NONE'}:raise ValueError('CONTEXT_FACT_CHANGED')
        elif kind=='MODEL_TURN':
            model_turns+=1;reserved+=p['max_tokens'];last_model=event
            ctx=resolve(p['context_ref'],'CONTEXT')['payload']
            if p['request_hash']!=digest(ctx['prompt'])or p['raw_output_stored']or p['chain_of_thought_requested']:raise ValueError('MODEL_TURN_BOUNDARY')
        elif kind=='PROPOSAL':
            registry.validate(p['proposal'],task)
            if p['model_turn_ref']['id']not in seen or seen[p['model_turn_ref']['id']]['kind']!='MODEL_TURN':raise ValueError('PROPOSAL_WITHOUT_MODEL_TURN')
            if ref(seen[p['model_turn_ref']['id']])!=p['model_turn_ref']:raise ValueError('PROPOSAL_MODEL_HASH_MISMATCH')
        elif kind=='VALIDATION'and p['decision']=='ACCEPT':
            if p['proposal_ref']['id']not in seen:raise ValueError('VALIDATION_BEFORE_PROPOSAL')
            if ref(seen[p['proposal_ref']['id']])!=p['proposal_ref']:raise ValueError('VALIDATION_PROPOSAL_HASH_MISMATCH')
        elif kind=='TOOL_RESULT':
            prop=seen[p['proposal_ref']['id']];approved=seen[p['validation_ref']['id']]
            if ref(prop)!=p['proposal_ref']or ref(approved)!=p['validation_ref']:raise ValueError('TOOL_CHAIN_HASH_MISMATCH')
            if approved['kind']!='VALIDATION'or approved['payload']['decision']!='ACCEPT'or approved['payload']['proposal_ref']!=ref(prop):raise ValueError('TOOL_WITHOUT_EXTERNAL_AUTHORIZATION')
            proposal=prop['payload']['proposal'];record,_=registry.validate(proposal,task)
            if p['tool_id']!=proposal['tool_id']or p['result']!={'evidence_ref':ref(record),'facts':project(record)}or p['side_effects']:raise ValueError('FABRICATED_TOOL_RESULT')
            facts.update({f['fact_id']:f for f in p['result']['facts']});tool_results.append(ref(event))
        seen[event['id']]=event
    if result['task_ref']!=trace['payload']['task_ref']or result['task_id']!=task['task_id']:raise ValueError('TASK_RESULT_MISMATCH')
    if result['preserved_tool_result_refs']!=tool_results or result['tool_calls']!=len(tool_results):raise ValueError('LOST_TOOL_EVIDENCE')
    if model_turns>task['resource_budget']['max_steps']or len(tool_results)>task['resource_budget']['max_tool_calls']or reserved>task['resource_budget']['max_output_tokens']:raise ValueError('LOOP_BUDGET_VIOLATION')
    for claim in result['claims']:
        fact=facts[claim['fact_id']]
        if claim['claim']!={'field':fact['field'],'value':fact['value']}or claim['evidence_refs']!=[fact['evidence_ref']]or claim['source_class']!=fact['source_class']or claim['support_status']!='EXACT_EXTRACTIVE_SUPPORT':raise ValueError('UNSUPPORTED_CLAIM')
        if context is None or fact['fact_id']not in[f['fact_id']for f in context['included_items']]:raise ValueError('CLAIM_OUTSIDE_LAST_CONTEXT')
    if result['status']=='OK'and len({c['evidence_refs'][0]['id']for c in result['claims']})<task['evidence_requirements']['minimum_sources']:raise ValueError('INSUFFICIENT_GROUNDING')
    if result['status']=='OK'and any(not any(c['claim']['field'].startswith(k)for c in result['claims'])for k in task['evidence_requirements']['required_fields']):raise ValueError('REQUIRED_FIELDS_MISSING')
    if result['forbidden_actions_executed']or result['network_requests']or result['source_changes']or result['hidden_chain_of_thought_stored']:raise ValueError('RESULT_AUTHORITY_ESCALATION')
    if result['plan']and(result['plan']['executed']or result['plan']['authority']!='DECLARATIVE_ONLY'):raise ValueError('PLAN_EXECUTION_DENIED')
    if result['plan']:
        aliases={'fact_aliases':{'f'+str(i+1):facts[item['fact_id']]for i,item in enumerate(context['included_items'])}}
        expected,claims=validate_plan({'kind':'PLAN','steps':result['plan']['steps']},aliases,task,registry)
        if expected!=result['plan']or claims!=result['claims']or not any(v['kind']=='PLAN'and v['payload']==expected for v in events):raise ValueError('PLAN_DOES_NOT_REPRODUCE')
    return {'status':'PASS','trace_ref':ref(trace),'result_status':result['status'],'model_turns':model_turns,'validated_tool_calls':len(tool_results),'claims':len(result['claims'])}


def audit_bundle(directory):
    root=Path(directory);manifest=json.loads((root/'manifest.json').read_bytes())
    if manifest.get('schema')!='gaia_cognition_evidence_bundle_v1'or manifest['hash']!=digest({k:v for k,v in manifest.items()if k!='hash'}):raise ValueError('INVALID_BUNDLE_MANIFEST')
    documents={};records={};total=0
    for name,sha in manifest['files'].items():
        rel=PurePosixPath(name);path=root/name
        if rel.is_absolute()or'..'in rel.parts or path.is_symlink()or not path.resolve().is_relative_to(root.resolve()):raise ValueError('BUNDLE_PATH_ESCAPE')
        total+=path.stat().st_size
        if total>32*2**20:raise ValueError('BUNDLE_SIZE_BOUND')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('BUNDLE_FILE_TAMPERED')
        value=json.loads(raw)
        if canonical_json(value)!=raw:raise ValueError('BUNDLE_NONCANONICAL_JSON')
        documents[name]=value
        if name.startswith('records/'):
            validate(value)
            if name!='records/'+value['id']+'.json':raise ValueError('BUNDLE_RECORD_ID_MISMATCH')
            records[value['id']]=value
    class BundleStore:
        def get(self,identifier,kind):
            value=records.get(identifier)
            if value is None or value['kind']!=kind:raise FileNotFoundError('NOT_IN_BUNDLE')
            return value
    store=BundleStore();audits=[]
    if manifest.get('status')!='PASS'or 'benchmark-final.json'not in documents or 'cli.json'not in documents:raise ValueError('INCOMPLETE_CERTIFICATION_BUNDLE')
    expected_runs=[row['run']for name in ('benchmark-final.json','benchmark-additional.json')if name in documents for row in documents[name]['cases']]+[documents['cli.json']['run']]
    if not expected_runs or manifest['result_refs']!=[ref(v['result'])for v in expected_runs]or manifest['trace_refs']!=[ref(v['trace'])for v in expected_runs]:raise ValueError('BUNDLE_RUN_INDEX_MISMATCH')
    if len(documents['benchmark-final.json']['cases'])!=manifest['final_series_cases']or manifest['final_series_cases']<1:raise ValueError('BUNDLE_CASE_COUNT_MISMATCH')
    for r in manifest['trace_refs']:
        trace=store.get(r['id'],'TRACE')
        if ref(trace)!=r:raise ValueError('BUNDLE_TRACE_HASH_MISMATCH')
        audits.append(audit_trace(store,trace))
    for name in [n for n in ('benchmark-final.json','benchmark-additional.json')if n in documents]:
        campaign=documents[name]
        if campaign['hash']!=digest({k:v for k,v in campaign.items()if k!='hash'})or campaign['benchmark_hash']!=identity()or campaign['status']!='PASS':raise ValueError('BENCHMARK_IDENTITY_MISMATCH')
        for file,sha in campaign['implementation_hashes'].items():
            if hashlib.sha256((ROOT/file).read_bytes()).hexdigest()!=sha:raise ValueError('IMPLEMENTATION_CHANGED_SINCE_REAL_TASKS')
        for row in campaign['cases']:
            result=store.get(row['run']['result']['id'],'RESULT');trace=store.get(row['run']['trace']['id'],'TRACE')
            if result!=row['run']['result']or trace!=row['run']['trace']:raise ValueError('BENCHMARK_EVIDENCE_MISMATCH')
            tools=[store.get(r['id'],'TOOL_RESULT')['payload']['tool_id']for r in result['payload']['preserved_tool_result_refs']]
            if evaluate(row['case'],row['run'],tools)!=row['evaluation']or row['evaluation']['status']!='PASS':raise ValueError('BENCHMARK_DOES_NOT_REPRODUCE')
    if documents['audit.json']['source_policy']!=source_policy():raise ValueError('AUDITED_SOURCE_CHANGED')
    return {'status':'PASS','documents':len(documents),'records':len(records),'bytes':total,'traces':audits,'benchmark_scoring_reproduced':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--state-dir',type=Path);group.add_argument('--bundle',type=Path);p.add_argument('--trace');p.add_argument('--output',type=Path);a=p.parse_args()
    try:
        if a.bundle:evidence={'bundle':audit_bundle(a.bundle)}
        else:
            if not a.trace:raise ValueError('TRACE_REQUIRED')
            store=CognitiveStore(a.state_dir);evidence={'trace':audit_trace(store,store.get(a.trace,'TRACE'))}
        value={'schema':'gaia_cognition_audit_v1','status':'PASS','source_policy':source_policy(),**evidence}
        value['hash']=digest(value)
        if a.output:
            with a.output.open('xb')as f:f.write(canonical_json(value))
        print(json.dumps(value,indent=2));return 0
    except (OSError,ValueError,KeyError,TypeError,AttributeError):print('Cognition audit: FAIL');return 2


if __name__=='__main__':raise SystemExit(main())
