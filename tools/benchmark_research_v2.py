#!/usr/bin/env python3
"""Run one fresh structural research V2 holdout candidate."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gaia.cognition.research_agenda import BenchmarkObservation,deterministic_agenda
from gaia.cognition.research_dialogue import DirectResearchRunner
from gaia.cognition.research_evaluator_v2 import CRITERIA_HASH,candidate_from_dialogue,evaluate_candidate
from gaia.cognition.spanish_diagnostic import augment_observation
from gaia.local_intelligence.primary import PrimaryLocalIntelligenceBackend


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--diagnostic',type=Path,required=True)
    parser.add_argument('--intelligence-state',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--split-fields',action='store_true');args=parser.parse_args()
    observed=BenchmarkObservation.from_bytes(args.evidence.read_bytes(),args.evidence.name)
    observed=augment_observation(observed,args.diagnostic.read_bytes(),args.diagnostic.name)
    issue=next(value for value in observed['issues']if value['task_id']=='spanish')
    factory=lambda:PrimaryLocalIntelligenceBackend(args.intelligence_state,context=4096)
    dialogue=DirectResearchRunner(factory,split_fields=args.split_fields).run(observed,issue);candidate=candidate_from_dialogue(issue,dialogue)
    baseline_agenda=deterministic_agenda(observed);baseline_intervention=next(value['proposed_change']for value in baseline_agenda['hypotheses']if value['problem'].startswith('spanish '))
    evaluation=evaluate_candidate(issue,candidate,{'intervention':baseline_intervention})
    value={'schema':'gaia_research_v2_holdout_run','authority':'NONE','criteria_hash':CRITERIA_HASH,'source':observed['source'],
           'diagnostic_source':issue['diagnostic_details']['source'],'dialogue':dialogue,'candidate':candidate,'evaluation':evaluation,
           'baseline':{'selector':'DETERMINISTIC_BASELINE_V1','maximum_v2_score':7,'intervention':baseline_intervention},
           'network_requests':0,'executions':0,'promotions':0}
    args.output.write_text(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    print(json.dumps({'dialogue_status':dialogue['status'],'score':evaluation['score'],'status':evaluation['status'],'output':str(args.output)},indent=2))


if __name__=='__main__':main()
