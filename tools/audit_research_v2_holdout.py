#!/usr/bin/env python3
"""Offline audit of the pre-registered structural Research V2 holdout replicas."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gaia.cognition.research_agenda import BenchmarkObservation,deterministic_agenda
from gaia.cognition.research_evaluator_v2 import CRITERIA_HASH,evaluate_candidate
from gaia.cognition.spanish_diagnostic import augment_observation


def audit(preregistration,runs):
    prereg=json.loads(Path(preregistration).read_bytes());root=Path(preregistration).parent
    observed=BenchmarkObservation.from_bytes((root/'GAIA_1_2_MEMORY_QUALITY_V1.json').read_bytes(),'GAIA_1_2_MEMORY_QUALITY_V1.json')
    diagnostic=root/'GAIA_1_2_SPANISH_DIAGNOSTIC_V2.json';observed=augment_observation(observed,diagnostic.read_bytes(),diagnostic.name)
    issue=next(value for value in observed['issues']if value['task_id']==prereg['task'])
    baseline=next(value['proposed_change']for value in deterministic_agenda(observed)['hypotheses']if value['problem'].startswith(prereg['task']+' '))
    values=[json.loads(Path(path).read_bytes())for path in runs];recomputed=[evaluate_candidate(issue,value.get('candidate'),{'intervention':baseline})for value in values]
    checks={
        'protocol':prereg.get('status')=='FROZEN_BEFORE_CANDIDATE_IMPLEMENTATION_OR_INFERENCE'and prereg.get('runs')==2,
        'run_count':len(values)==2,
        'criteria_identity':all(value.get('criteria_hash')==CRITERIA_HASH for value in values),
        'scores_recomputed':all(value.get('evaluation')==json.loads(json.dumps(actual)) and actual['score']==8 and actual['status']=='PASS'for value,actual in zip(values,recomputed)),
        'semantic_replica':len({(value['candidate']['cause'],value['candidate']['intervention'])for value in values})==1,
        'authority':all(value.get('authority')=='NONE'and value['candidate']['authority']=='NONE'for value in values),
        'no_effects':all(value.get('network_requests')==0 and value.get('executions')==0 and value.get('promotions')==0 for value in values),
        'budgets':all(value['dialogue']['performance']['calls']==2 and value['dialogue']['performance']['reserved_tokens']==192 for value in values),
    }
    return {'schema':'gaia_research_v2_holdout_audit','status':'PASS'if all(checks.values())else'FAIL','checks':checks,
            'scores':[value['score']for value in recomputed],'criteria_hash':CRITERIA_HASH,'authority':'NONE'}


if __name__=='__main__':
    value=audit(Path(sys.argv[1]),[Path(path)for path in sys.argv[2:]]);print(json.dumps(value,indent=2,sort_keys=True));raise SystemExit(value['status']!='PASS')
