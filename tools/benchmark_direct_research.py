#!/usr/bin/env python3
"""Run the pre-registered one-role research proposal against the frozen comparator."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gaia.cognition.research_agenda import BenchmarkObservation,deterministic_agenda
from gaia.cognition.research_comparison import compare_research
from gaia.cognition.research_dialogue import DirectResearchRunner
from gaia.local_intelligence.primary import PrimaryLocalIntelligenceBackend


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--intelligence-state',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();observed=BenchmarkObservation.from_bytes(args.evidence.read_bytes(),args.evidence.name)
    issue=sorted(observed['issues'],key=lambda value:(-value['failure_count'],-value['format_failure_count'],value['task_id']))[0]
    factory=lambda:PrimaryLocalIntelligenceBackend(args.intelligence_state,context=4096)
    dialogue=DirectResearchRunner(factory).run(observed,issue);baseline=deterministic_agenda(observed)
    comparison=compare_research(observed,baseline,dialogue,selector='RESEARCH_DIRECT_V1_ONE_ROLE')
    value={'schema':'gaia_direct_research_benchmark_v1','authority':'NONE','dialogue':dialogue,'comparison':comparison,
           'evaluator_modified':False,'network_requests':0,'executions':0,'promotions':0}
    args.output.write_text(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    print(json.dumps({'status':dialogue['status'],'reason':dialogue['reason'],'baseline':comparison['baseline']['score'],
                      'direct':comparison['dialogue']['score'],'winner':comparison['winner'],'output':str(args.output)},indent=2))


if __name__=='__main__':main()
