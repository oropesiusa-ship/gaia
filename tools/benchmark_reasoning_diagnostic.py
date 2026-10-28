#!/usr/bin/env python3
"""Run the frozen 17*23 diagnostic through the existing isolated chat backend."""
import argparse
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gaia.cognition.conversation import ConversationStore
from gaia.cognition.reasoning_diagnostic import VARIANTS,SYMBOLIC_VARIANTS,compare,score
from gaia.local_intelligence.primary import PrimaryLocalIntelligenceBackend
from gaia.provenance import canonical_json,digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--state-dir',type=Path,required=True);p.add_argument('--intelligence-state',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--context',type=int,default=4096)
    p.add_argument('--suite',choices=('v1','symbolic-v2'),default='v1');args=p.parse_args();variants=VARIANTS if args.suite=='v1'else SYMBOLIC_VARIANTS
    store=ConversationStore(args.state_dir);backend=PrimaryLocalIntelligenceBackend(args.intelligence_state,context=args.context);rows=[]
    backend.load()
    try:
        for variant in variants:
            conversation=store.create('reasoning diagnostic '+variant['id'],'reasoning-diagnostic');started=time.perf_counter()
            value=store.respond(conversation['id'],variant['prompt'],backend,maximum=args.context,max_tokens=96,memory=False)
            text=value.get('assistant_turn',{}).get('payload',{}).get('content')
            rows.append({'variant_id':variant['id'],'prompt_sha256':digest(variant['prompt']),'expected':variant['expected'],'format':variant['format'],
                'text':text,'score':score(variant,text),'status':value['status'],'latency_s':time.perf_counter()-started,
                'input_tokens':value['projection']['input_tokens']})
    finally:metrics=backend.unload()
    result={'schema':'gaia_1_2_reasoning_diagnostic_v1'if args.suite=='v1'else'gaia_1_2_reasoning_symbolic_diagnostic_v2','variants_sha256':digest(variants),'rows':rows,'comparison':compare(rows),
        'selection_ref':{'id':backend.selection['id'],'hash':backend.selection['hash']},'context':args.context,'authority':'NONE',
        'tool_calls':0,'network_requests':0,'source_changes':0,'evaluator_changes':0,
        'telemetry':{k:metrics.get(k)for k in ('load_s','peak_rss_sum_bytes','peak_device_vram_increment_bytes','runtime_returncode')}}
    result['evidence_sha256']=digest(result);args.output.write_bytes(canonical_json(result)+b'\n')
    print(result['comparison']['diagnosis'],result['evidence_sha256'])


if __name__=='__main__':main()
