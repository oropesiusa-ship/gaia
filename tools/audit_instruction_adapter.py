#!/usr/bin/env python3
"""Offline A/B audit for the experimental prompt adapter; does not load a model."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gaia.cognition.chat_quality import OBJECTIVE_TASKS,objective_score,recall_score
from gaia.cognition.instruction_adapter import adapt
from gaia.provenance import digest

def _scores(value):
    result=[]
    for row in value['rows']:
        if not row.get('objective'):continue
        task=next((v for v in OBJECTIVE_TASKS if v['id']==row['task']),None)
        if task:actual=objective_score(task,row['text'])
        elif row['task']=='within_conversation_recall':actual=recall_score(row['text'],'DELTA_314')
        elif row['task']=='fact_update':actual=recall_score(row['text'],'SUR_20','NORTE_10')
        else:actual=recall_score(row['text'],'NEBULA_77')
        result.append((row,actual))
    return result

def audit(baseline_path,candidate_path):
    baseline=json.loads(Path(baseline_path).read_bytes())['memory'];candidate=json.loads(Path(candidate_path).read_bytes());checks={}
    policy=candidate.get('prompt_policy');checks['schemas']=candidate.get('schema')=='gaia_chat_quality_benchmark_v1'and policy in ('LITERAL_AND_OPERATOR_V1','EXACT_OUTPUT_AND_OPERATOR_V2')
    checks['policy_identity']=candidate.get('prompt_policy_sha256')==digest({'policy':policy,'prompts':[adapt(v['prompt'],policy)for v in OBJECTIVE_TASKS]})
    scored=_scores(candidate);checks['scores_replayed']=all(row['objective']==actual for row,actual in scored)
    checks['same_tasks']=[r['task']for r,a in scored]==[r['task']for r in baseline['rows']if r.get('objective')]
    checks['objective_gain']=candidate['objective']['passed']>baseline['objective']['passed']
    checks['format_gain']=candidate['objective']['format_passed']>baseline['objective']['format_passed']
    checks['reasoning_gain']=next(r for r,a in scored if r['task']=='reasoning')['objective']['pass']
    checks['runtime']=candidate['failures']==0 and candidate['telemetry']['runtime_returncode']==-15
    checks['cost_bound']=(candidate['median_latency_s']<=baseline['median_latency_s']*1.10 and
        candidate['telemetry']['peak_rss_sum_bytes']<=baseline['telemetry']['peak_rss_sum_bytes']*1.10 and
        candidate['telemetry']['peak_device_vram_increment_bytes']<=baseline['telemetry']['peak_device_vram_increment_bytes']*1.10)
    return {'schema':'gaia_instruction_adapter_audit_v1','status':'PASS'if all(checks.values())else'FAIL','checks':checks,
        'decision':'RETAIN_EXPERIMENTAL_NOT_PROMOTED','authority':'NONE'}

if __name__=='__main__':
    value=audit(sys.argv[1],sys.argv[2]);print(json.dumps(value,indent=2,sort_keys=True));raise SystemExit(value['status']!='PASS')
