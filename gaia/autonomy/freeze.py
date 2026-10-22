"""Reproducible protocol freeze (1.1 §10): everything a session's results depend on, fixed at creation and re-checked."""
import subprocess
from pathlib import Path
from .. import config,manifest
from ..provenance import digest
from .policy import identities
from .lineage import LineageStore,engine_state_dir

# Selection pointer moves the closed loop itself makes; any other move is a protocol change.
OWN_POINTER_REASONS=('CLOSED_LOOP_PROMOTION','CLOSED_LOOP_ROLLBACK')


def git(root,*args):
    try:return subprocess.run(['git',*args],cwd=root,capture_output=True,text=True,timeout=30).stdout.strip()or None
    except (OSError,subprocess.SubprocessError):return None


def selection(root,intelligence_state):
    from ..local_intelligence.store import IntelligenceStore
    if not(Path(root)/intelligence_state).is_dir():return {'selection':None,'stack_id':None,'stack_hash':None,'pointer_entries':0}
    store=IntelligenceStore(Path(root)/intelligence_state);current=store.read('current','SELECTION');stack=current['payload']['primary']['stack']
    return {'selection':{'id':current['id'],'hash':current['hash']},'stack_id':stack.get('stack_id'),'stack_hash':digest(stack),
            'pointer_entries':len(store.pointer_entries())}


def freeze(root,state,lineages):
    """The frozen protocol. Raises if the hashed sources have uncommitted changes."""
    root=Path(root)
    if git(root,'status','--porcelain','--','gaia','gaia.py'):raise ValueError('UNCOMMITTED_SOURCE_CHANGES')
    source=identities(root);cfg=config.load(root);value={'commit':git(root,'rev-parse','HEAD'),'source_identity_hash':source['hash'],
        'protected_hash':source['protected_hash'],'engine_config_hash':digest(cfg),'acceptance':cfg['acceptance'],'lineages':{},'selections':{}}
    for lineage_id in lineages:
        lineage=LineageStore(state,lineage_id).read()
        if lineage['source_identity_hash']!=source['hash']:raise ValueError('LINEAGE_SOURCE_DIFFERS_FROM_FROZEN_SOURCES')
        bench=root/engine_state_dir(lineage_id)/'benchmark.json'
        value['lineages'][lineage_id]={'hash':lineage['hash'],'objective':lineage['objective'],'surface':lineage['surface'],
            'benchmark_hash':manifest.file_hash(bench)if bench.exists()else None}
        if lineage['intelligence_state']not in value['selections']:value['selections'][lineage['intelligence_state']]=selection(root,lineage['intelligence_state'])
    value['hash']=digest(value);return value


def changes(root,state,frozen):
    """Fields that no longer match the frozen protocol; legitimate moves made by the session's own closed loop are not changes."""
    from ..local_intelligence.store import IntelligenceStore
    root=Path(root);found=[]
    if git(root,'status','--porcelain','--','gaia','gaia.py'):found.append('UNCOMMITTED_SOURCE_CHANGES')
    source=identities(root);cfg=config.load(root)
    for key,now in (('source_identity_hash',source['hash']),('protected_hash',source['protected_hash']),('engine_config_hash',digest(cfg)),
                    ('acceptance',cfg['acceptance'])):
        if frozen[key]!=now:found.append(key.upper()+'_CHANGED')
    if git(root,'rev-parse','HEAD')!=frozen['commit']:found.append('COMMIT_CHANGED')
    for lineage_id,v in frozen['lineages'].items():
        lineage=LineageStore(state,lineage_id).read()
        if lineage['hash']!=v['hash']:found.append('LINEAGE_CONTRACT_CHANGED')
        bench=root/engine_state_dir(lineage_id)/'benchmark.json'
        # The first campaign of a fresh numpy lineage creates its protected benchmark; afterwards it never changes.
        if v['benchmark_hash']is not None and(not bench.exists()or manifest.file_hash(bench)!=v['benchmark_hash']):found.append('BENCHMARK_CHANGED')
    for state_name,v in frozen['selections'].items():
        if v['selection']is None:
            if(root/state_name).is_dir():found.append('SELECTION_CHANGED_OUTSIDE_SESSION')
            continue
        store=IntelligenceStore(root/state_name);entries=store.pointer_entries()
        if any(e['reason']not in OWN_POINTER_REASONS or(e['reason']=='CLOSED_LOOP_PROMOTION'and e['receipt'].get('lineage_id')not in frozen['lineages'])
               for e in entries[v['pointer_entries']:]):found.append('SELECTION_CHANGED_OUTSIDE_SESSION')
        elif len(entries)==v['pointer_entries']and selection(root,state_name)['selection']!=v['selection']:found.append('SELECTION_CHANGED_OUTSIDE_SESSION')
    return sorted(set(found))
