#!/usr/bin/env python3
"""Portable offline audit of Research Dialogue V1 evidence; never loads a model."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from gaia.cognition.research_agenda import BenchmarkObservation,validate_research_artifact
from gaia.cognition.research_comparison import CRITERIA_HASH
from gaia.cognition.schema import ref,validate
from gaia.provenance import digest


def audit(evidence_path,source_path):
    value=json.loads(Path(evidence_path).read_bytes());raw=Path(source_path).read_bytes()
    observed=BenchmarkObservation.from_bytes(raw,Path(source_path).name);checks={}
    checks['schema']=value.get('schema')=='gaia_1_2_research_dialogue_real_evidence_v1'
    checks['self_hash']=value.get('evidence_sha256')==digest({k:v for k,v in value.items()if k!='evidence_sha256'})
    checks['source']=value.get('source')==observed['source']
    try:validate_research_artifact(value['baseline'],observed=observed);checks['baseline']=True
    except (ValueError,KeyError,TypeError):checks['baseline']=False
    records=value.get('dialogues',[]);comparisons=value.get('comparisons',[])
    try:
        for record in records+comparisons:validate(record)
        checks['envelopes']=True
    except (ValueError,KeyError,TypeError):checks['envelopes']=False
    dialogues=[r['payload']['dialogue']for r in records]
    checks['three_roles']=len(dialogues)==1 and [t['role']for t in dialogues[0]['turns']]==['RESEARCHER','CRITIC','REVIEWER']
    checks['structured_only']=all(not t['raw_output_stored']and t['hidden_reasoning_requested']is False for d in dialogues for t in d['turns'])
    checks['authority']=all(d['authority']=='NONE'and all(t['model_authority']=='NONE'for t in d['turns'])for d in dialogues)
    checks['safe_stop']=len(dialogues)==1 and dialogues[0]['status']=='STOPPED'and dialogues[0]['reason']=='MORE_EVIDENCE'and dialogues[0]['review']['experiment']is None
    comp=[r['payload']['comparison']for r in comparisons]
    checks['comparison']=len(comp)==1 and comp[0]['criteria_hash']==CRITERIA_HASH and comp[0]['winner']=='BASELINE'and comp[0]['evaluator_modified']is False
    campaign=value.get('campaign',{});cp=campaign.get('payload',{})
    try:validate(campaign);checks['campaign_refs']=(cp['dialogue_refs']==[ref(v)for v in records]and cp['comparison_refs']==[ref(v)for v in comparisons])
    except (ValueError,KeyError,TypeError):checks['campaign_refs']=False
    checks['boundaries']=cp.get('authority')=='NONE'and all(cp.get(k)==0 for k in ('network_requests','source_changes','evaluator_changes','promotions'))
    checks['honest_claims']=value.get('claims')=={'llm_authority':'NONE','autonomous_stages':3,'experiment_executed':False,'gaia_1_2_certified':False}
    return {'schema':'gaia_research_dialogue_audit_v1','status':'PASS'if all(checks.values())else'FAIL','checks':checks}


if __name__=='__main__':
    result=audit(sys.argv[1],sys.argv[2]);print(json.dumps(result,indent=2,sort_keys=True));raise SystemExit(result['status']!='PASS')
