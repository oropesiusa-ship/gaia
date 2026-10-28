"""Session catalog of verified references (1.1 §7): an index over lineages, never a merge of their stores.

A verified reference is an independently replicated acceptance or a version promotion recorded in a lineage's
Annex B records. Reuse is EXACT only when every binding field is equal; any differing hash is reported as
INCOMPATIBLE with the fields that differ. Distinct hashes are never treated as equivalent."""
import json
from pathlib import Path
from ..provenance import digest
from .lineage import LineageStore,engine_state_dir
from .store import CampaignStore

BINDING=('source_identity_hash','environment_hash','surface','objective','reference_version','reference_baseline_hash')


def records(store):
    result=[]
    for ev in store.events():
        if ev['kind']=='EXPERIMENT_RECORDED':
            value=json.loads((store.root/'records'/(ev['payload']['record_ref']['hash']+'.json')).read_bytes())
            if digest({k:v for k,v in value.items()if k!='record_hash'})!=value['record_hash']:raise ValueError('EXPERIMENT_RECORD_CORRUPTED')
            result.append(value)
    return result


def external_reversions(root,store):
    """Versions reverted outside campaign journals: v0.1 Engine ledger rollbacks (numpy) and closed-loop pointer rollbacks (inference)."""
    contract=store.read();reverted=set()
    if root is None:return reverted
    if contract['surface']=='numpy_mlp':
        ledger=Path(root)/engine_state_dir(contract['lineage_id'])/'ledger.jsonl'
        if ledger.exists():
            for line in ledger.read_text().splitlines():
                try:row=json.loads(line)
                except ValueError:continue
                if row.get('event_type')=='rollback':reverted.add((row.get('payload')or{}).get('from_version'))
    else:
        from ..local_intelligence.store import IntelligenceStore
        path=Path(root)/contract['intelligence_state']
        if path.is_dir():
            for e in IntelligenceStore(path).pointer_entries():
                if e['reason']=='CLOSED_LOOP_ROLLBACK':reverted.add((e['receipt'].get('from')or{}).get('id'))
    return reverted-{None}


def follow_up(state,store,root=None):
    """Per promoted version: its post-promotion verification status, and whether anything reverted it."""
    verified={};reverted=external_reversions(root,store)
    for campaign in [e['payload']['campaign_id']for e in store.events()if e['kind']=='CAMPAIGN_ADMITTED']:
        c=CampaignStore(state,campaign);seen=set()
        for ev in c.events():
            s=ev['state']
            for key in ('verification_ref','rollback_ref'):
                r=s.get(key)
                if not r or r['id']in seen:continue
                seen.add(r['id']);value=c.get(r)
                if key=='rollback_ref'and value.get('previous_current'):reverted.add(value['previous_current'])
                if key=='verification_ref'and s.get('after_version'):verified[s['after_version']]=value['status']
    return verified,reverted


def references(state,lineage_id,root=None):
    """Verified references of one lineage, with their full binding. A promotion counts only once its verification
    passed and no later rollback reverted it; a replicated acceptance counts as replicated evidence."""
    store=LineageStore(state,lineage_id);contract=store.read();rows=[];verified,reverted=follow_up(state,store,root)
    for r in records(store):
        version=r['system_version']['version_after'];promoted=r['system_version']['version_before']!=version
        replicated=r['proposed_change']['class']=='REPLICATION'and r['result']['classification']=='ACCEPTED'
        if promoted and(verified.get(version)!='PASS'or version in reverted):continue
        if not(promoted or replicated):continue
        rows.append({'lineage_id':lineage_id,'experiment_id':r['experiment_id'],'record_hash':r['record_hash'],'campaign_id':r['campaign_id'],
            'kind':'PROMOTED_VERSION'if promoted else'REPLICATED_ACCEPTANCE','candidate_hash':r['proposed_change']['candidate_hash'],
            'changes':r['proposed_change']['changes'],'version_after':r['system_version']['version_after'],
            'binding':{'source_identity_hash':r['system_version']['source_identity_hash'],'environment_hash':r['environment'].get('environment_hash'),
                'surface':contract['surface'],'objective':contract['objective'],'reference_version':r['reference_state']['version'],
                'reference_baseline_hash':r['reference_state']['baseline_hash']}})
    return rows


def catalog(state,lineages=None,root=None):
    lineage_root=Path(state)/'autonomy'/'lineages'
    ids=lineages or(sorted(p.name for p in lineage_root.iterdir()if p.is_dir())if lineage_root.exists()else[])
    entries=[];index=[]
    for lineage_id in ids:
        store=LineageStore(state,lineage_id);contract=store.read();view=store.state()
        rows=references(state,lineage_id,root);entries+=rows
        index.append({'lineage_id':lineage_id,'objective':contract['objective'],'surface':contract['surface'],'source_identity_hash':contract['source_identity_hash'],
            'experiments':view['experiments'],'verified_references':len(rows),'blocked':view['blocked']})
    value={'schema':'gaia_session_catalog_v1','lineages':index,'references':entries,'scope':'INDEX_ONLY_NO_STORE_MERGE_EXACT_BINDING_REUSE'}
    value['hash']=digest(value);return value


def applicability(reference,binding):
    """EXACT when every binding field matches; otherwise INCOMPATIBLE with the differing fields (never 'equivalent')."""
    missing=[k for k in BINDING if binding.get(k)is None or reference['binding'].get(k)is None]
    differing=[k for k in BINDING if k not in missing and reference['binding'][k]!=binding[k]]
    if missing:return {'status':'UNASSESSED','missing':missing,'differing':differing}
    return {'status':'EXACT'if not differing else'INCOMPATIBLE','differing':differing}
