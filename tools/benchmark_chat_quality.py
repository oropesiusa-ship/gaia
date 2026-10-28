#!/usr/bin/env python3
"""Real local chat benchmark. It never executes model output or grants tools."""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from gaia.cognition.chat_quality import OBJECTIVE_TASKS,SUBJECTIVE_TASKS,objective_score,recall_score
from gaia.cognition.instruction_adapter import adapt,POLICIES
from gaia.cognition.conversation import ConversationStore
from gaia.local_intelligence.primary import PrimaryLocalIntelligenceBackend
from gaia.provenance import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--state-dir',type=Path,required=True)
    p.add_argument('--intelligence-state',type=Path,required=True);p.add_argument('--context',type=int,default=4096)
    p.add_argument('--memory',choices=('enabled','disabled'),required=True);p.add_argument('--prompt-policy',choices=POLICIES,default='ORIGINAL');args=p.parse_args()
    memory=args.memory=='enabled';store=ConversationStore(args.state_dir)
    backend=PrimaryLocalIntelligenceBackend(args.intelligence_state,context=args.context);backend.load();rows=[]
    def ask(owner,prompt,identifier=None):
        conversation=store._conversation(identifier) if identifier else store.create('benchmark '+owner,owner)
        started=time.perf_counter();value=store.respond(conversation['id'],prompt,backend,maximum=args.context,max_tokens=96,memory=memory)
        rows.append({'id':owner,'status':value['status'],'text':value.get('assistant_turn',{}).get('payload',{}).get('content'),
                     'latency_s':time.perf_counter()-started,'input_tokens':value['projection']['input_tokens'],
                     'memories':len(value.get('memory',[]))})
        return conversation,value
    try:
        for task in OBJECTIVE_TASKS:
            adapted=adapt(task['prompt'],args.prompt_policy)
            _,value=ask('objective-'+task['id'],adapted['prompt']);rows[-1].update(task=task['id'],category=task['category'],
                objective=objective_score(task,rows[-1]['text']),prompt_changes=adapted['changes'])
        conversation,_=ask('within-memory','Recuerda que el código de sesión es DELTA_314.')
        _,value=ask('within-memory','¿Cuál es el código de sesión? Responde sólo con el código.',conversation['id'])
        rows[-1].update(task='within_conversation_recall',category='MEMORY',objective=recall_score(rows[-1]['text'],'DELTA_314'))
        conversation,_=ask('fact-update','Mi zona preferida es NORTE_10.')
        ask('fact-update','Actualización: mi zona preferida ahora es SUR_20.',conversation['id'])
        _,value=ask('fact-update','¿Cuál es mi zona preferida vigente? Responde sólo con la zona.',conversation['id'])
        rows[-1].update(task='fact_update',category='MEMORY',objective=recall_score(rows[-1]['text'],'SUR_20','NORTE_10'))
        source=store.create('memory source','cross-memory');store.append(source['id'],'USER','El proyecto ORION tiene la clave recuperable NEBULA_77.')
        _,value=ask('cross-memory','¿Cuál es la clave recuperable del proyecto ORION? Responde sólo con la clave.')
        rows[-1].update(task='cross_conversation_recall',category='MEMORY',objective=recall_score(rows[-1]['text'],'NEBULA_77'))
        for task in SUBJECTIVE_TASKS:
            ask('subjective-'+task['id'],task['prompt']);rows[-1].update(task=task['id'],category=task['category'],subjective='NOT_SCORED')
    finally:telemetry=backend.unload()
    objective=[r for r in rows if 'objective'in r]
    result={'schema':'gaia_chat_quality_benchmark_v1','context':args.context,'memory':args.memory,
            'prompt_policy':args.prompt_policy,
            'prompt_policy_sha256':digest({'policy':args.prompt_policy,'prompts':[adapt(v['prompt'],args.prompt_policy)for v in OBJECTIVE_TASKS]}),
            'objective':{'passed':sum(r['objective']['pass']for r in objective),'total':len(objective),
                         'format_passed':sum(r['objective'].get('format_pass',r['objective']['pass'])for r in objective)},
            'median_latency_s':statistics.median(r['latency_s']for r in rows),'failures':sum(r['status']!='OK'for r in rows),
            'rows':rows,'telemetry':{k:telemetry.get(k)for k in ('peak_rss_sum_bytes','peak_device_vram_increment_bytes','runtime_returncode')},
            'subjective_policy':'OUTPUTS_RECORDED_NOT_SCORED'}
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=='__main__':main()
