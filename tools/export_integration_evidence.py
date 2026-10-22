#!/usr/bin/env python3
"""Export portable 1.0.1 evidence: reports, offline audits, Annex B records and lineage journals. Read-only on state."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from gaia.autonomy.store import CampaignStore
from gaia.autonomy.lineage import LineageStore
from gaia.provenance import canonical_json,digest
import audit_closed_loop


def write(path,value):
    raw=canonical_json(value)
    # Portable evidence never carries private mount paths or user directories.
    if b'/home/'in raw or b'/Users/'in raw or b'/tmp/claude'in raw:raise ValueError('PRIVATE_PATH_IN_EXPORT')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb')as f:f.write(canonical_json(value))
    return digest(value)


def export(state,campaigns,out):
    out=Path(out);files={};lineages=set()
    for label,identifier in campaigns:
        store=CampaignStore(state,identifier);events=store.events();contract=store.read('contract')
        audit=audit_closed_loop.audit_campaign(ROOT,Path(state),identifier)
        report=store.get(events[-1]['state']['report_ref'])
        records=[];seen=[]
        for ev in events:
            r=ev['state'].get('record_ref')
            if r and r not in seen:seen.append(r);records.append(store.get(r))
        value={'label':label,'campaign_id':identifier,'contract':contract,'report':report,'offline_audit':audit,'experiment_records':records,
               'journal':{'events':len(events),'trace_hash':events[-1]['hash']}}
        files[f'campaigns/{label}.json']=write(out/'campaigns'/f'{label}.json',value)
        if contract.get('lineage_id'):lineages.add(contract['lineage_id'])
    for lineage_id in sorted(lineages):
        store=LineageStore(state,lineage_id)
        files[f'lineages/{lineage_id}.json']=write(out/'lineages'/f'{lineage_id}.json',
            {'contract':store.read(),'events':store.events(),'state':store.state(),'scope':'COMMITTED_LINEAGE_JOURNAL'})
    manifest={'schema':'gaia_integration_evidence_v1','files':files,'source_policy':audit_closed_loop.source_policy()}
    manifest['hash']=digest(manifest);write(out/'manifest.json',manifest);return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state-dir',required=True);p.add_argument('--out',required=True)
    p.add_argument('campaign',nargs='+',help='label=campaign_id');a=p.parse_args()
    print(json.dumps(export(a.state_dir,[c.split('=',1)for c in a.campaign],a.out)['files'],indent=1))
