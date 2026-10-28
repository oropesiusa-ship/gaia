#!/usr/bin/env python3
"""Offline replay of GAIA 1.2 memory/context claims; never loads a model."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gaia.cognition.chat_quality import OBJECTIVE_TASKS,objective_score,recall_score


def audit(path):
    value=json.loads(Path(path).read_bytes());checks={}
    checks['schema']=value.get('schema')=='gaia_1_2_memory_quality_evidence_v1'
    expected={task['id'] for task in OBJECTIVE_TASKS}|{'within_conversation_recall','fact_update','cross_conversation_recall'}
    for name in ('baseline','memory'):
        section=value[name];rows={r['task']:r for r in section['rows'] if r.get('objective')}
        checks[name+'_tasks']=set(rows)==expected
        recomputed={}
        for identifier,row in rows.items():
            task=next((v for v in OBJECTIVE_TASKS if v['id']==identifier),None)
            if task:score=objective_score(task,row['text'])
            elif identifier=='within_conversation_recall':score=recall_score(row['text'],'DELTA_314')
            elif identifier=='fact_update':score=recall_score(row['text'],'SUR_20','NORTE_10')
            else:score=recall_score(row['text'],'NEBULA_77')
            recomputed[identifier]=score['pass']
        checks[name+'_scores']=sum(recomputed.values())==section['objective']['passed']
        checks[name+'_runtime']=section['failures']==0 and section['telemetry']['runtime_returncode']==-15
    b,m=value['baseline'],value['memory']
    checks['improvement']=m['objective']['passed']>b['objective']['passed']
    br=next(r for r in b['rows']if r.get('task')=='cross_conversation_recall')
    mr=next(r for r in m['rows']if r.get('task')=='cross_conversation_recall')
    checks['memory_attribution']=br['memories']==0 and not br['objective']['pass'] and mr['memories']==1 and mr['objective']['pass']
    adaptive=value['adaptive'];checks['adaptive_8k']=(adaptive['decision']['context']==8192 and adaptive['answer']=='AURORA_808'
        and 4096<adaptive['input_tokens']<8192 and adaptive['decision']['fallback']==4096)
    checks['authority']=value['claims']['tool_authority']=='NONE'and value['claims']['rag_embeddings']=='NOT_JUSTIFIED'
    return {'schema':'gaia_chat_quality_audit_v1','status':'PASS'if all(checks.values())else'FAIL','checks':checks}


if __name__=='__main__':
    result=audit(sys.argv[1]);print(json.dumps(result,indent=2,sort_keys=True));raise SystemExit(result['status']!='PASS')
