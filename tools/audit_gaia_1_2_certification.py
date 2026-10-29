#!/usr/bin/env python3
"""Offline aggregate certification audit for GAIA 1.2 approved gates."""
import json
from pathlib import Path
import sys


def _load(root,name):return json.loads((root/name).read_bytes())


def audit(root):
    quality=_load(root,'GAIA_1_2_FINAL_QUALITY_AUDIT_V1.json')
    research=_load(root,'GAIA_1_2_RESEARCH_V2_HOLDOUT_V7_AUDIT.json')
    continuity=_load(root,'GAIA_1_2_RESEARCH_CONTINUITY_V3_REAL.json')
    regression=_load(root,'GAIA_1_2_FINAL_REGRESSION_DA118A3.json')
    adapter_v2=_load(root,'GAIA_1_2_ADAPTER_GENERALIZATION_EVALUATION_V1.json')
    adapter_v3=_load(root,'GAIA_1_2_ADAPTER_V3_GENERALIZATION_EVALUATION_V1.json')
    campaign=continuity['campaign']['payload'];claims=continuity['claims']
    checks={
        'quality_gate':quality['status']=='PASS'and quality['claims']['cognitive_improvement']=='NOT_CLAIMED',
        'research_v2_gate':research['status']=='PASS'and research['scores']==[8,8],
        'continuity_gate':claims['real_multi_issue_campaign']is True and campaign['iterations']==2 and continuity['reopen']['same_id']and continuity['reopen']['same_hash'],
        'regression_gate':regression['status']=='PASS'and regression['coverage']['disjoint']and regression['coverage']['exhaustive']and regression['aggregate']['failures']==0 and regression['aggregate']['errors']==0,
        'adapter_nonpromotion':adapter_v2['result']['decision']=='REJECT_V2'and adapter_v3['result']['decision']=='REJECT_CANDIDATE',
        'authority':all(value.get('authority')=='NONE'for value in (quality,research,regression))and campaign['authority']=='NONE',
        'no_research_effects':campaign['network_requests']==0 and campaign['source_changes']==0 and campaign['evaluator_changes']==0 and campaign['promotions']==0,
    }
    return {'schema':'gaia_1_2_certification_audit_v1','status':'CERTIFIED'if all(checks.values())else'NOT_CERTIFIED',
            'checks':checks,'evaluated_commit':regression['evaluated_commit'],'authority':'NONE','merge_tag_release_authorized':False}


if __name__=='__main__':
    value=audit(Path(sys.argv[1]));print(json.dumps(value,indent=2,sort_keys=True));raise SystemExit(value['status']!='CERTIFIED')
