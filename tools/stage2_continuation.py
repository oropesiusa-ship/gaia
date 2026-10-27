"""Prospective administrative amendment: retain real S1, never reset its budget.

Only the boundary/orchestration/composite audit and dependency declaration may
change. Every S1 execution dependency and all gaia sources must remain byte
identical. Original contracts, failed boundary, session and receipts stay intact.
This does not authorize experiments: the dedicated S2 CLI still needs its flag.
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from tools import stage2_executor as ex
from tools.stage2_protocol import FILES,tool_hashes
from tools.stage2_boundary import verify_manifest,retained_scratch
from tools.stage2_runtime import audit_aggregate
from tools.audit_endurance_session import audit_session
from tools.stage1_coverage import window_coverage
from tools.stage2_observer import audit_observer
from gaia.autonomy.session import SessionStore
from gaia.autonomy.lineage import engine_state_dir
from gaia.autonomy.store import durable

SELF='tools/stage2_continuation.py'
ADMIN_CHANGES={'tools/stage2_boundary.py','tools/stage2_orchestrator.py',
               'tools/stage2_audit.py','tools/stage2_protocol.py',SELF}
TEST_CHANGES={'tests/test_stage2_boundary.py','tests/test_stage2_orchestrator.py',
              'tests/test_stage2_audit.py','tests/test_stage2_continuation.py',
              'tests/test_stage2_retained_scratch.py'}


def sealed(value):
    if not isinstance(value,dict)or value.get('hash')!=ex.digest({k:v for k,v in value.items()if k!='hash'}):
        raise ValueError('CONTINUATION_HASH_MISMATCH')
    return value


def archive_manifest(directory):
    directory=Path(directory);path=directory/'manifest.json'
    actual=ex.inventory([directory],include_cache=True)
    expected=json.loads(path.read_bytes())
    if not expected or {p:h for p,h in actual.items()if p!=str(path)}!=expected:
        raise ValueError('ADMINISTRATIVE_ARCHIVE_CHANGED')
    return actual


def roots_for(root,parent):
    out=Path(parent['state_path']).parent
    return [out,*[Path(root)/engine_state_dir(lin)for lin in parent['lineages']],ex.operational_scratch(parent)]


def parent_binding(root,contract_path):
    path=ex.safe_out(root,Path(contract_path)).resolve()
    parent=ex.validate_contract(json.loads(path.read_bytes()))
    protocol=sealed(json.loads((path.parent/'orchestration.json').read_bytes()))
    if (protocol.get('schema')!='gaia_master_stage2_orchestration_v1'
            or protocol.get('base_contract_hash')!=parent['hash']
            or protocol.get('real_recovery_required')is not True
            or protocol.get('execution_prohibited')is not True):
        raise ValueError('INVALID_PARENT_ORCHESTRATION')
    if Path(parent['state_path'])!=path.parent/'state':raise ValueError('CANONICAL_STAGE2_STATE_REQUIRED')
    return parent,protocol


def change_scope(root,parent,protocol):
    if not re.fullmatch('[0-9a-f]{40}',parent['commit']):raise ValueError('INVALID_PARENT_COMMIT')
    if set(protocol['files'])!=set(FILES)-{SELF}:raise ValueError('PARENT_DEPENDENCY_SET_CHANGED')
    current=ex.safe_git(root,'rev-parse','HEAD')
    if not current or ex.safe_git(root,'status','--porcelain')!='':raise ValueError('CLEAN_COMMITTED_CONTINUATION_REQUIRED')
    changed=subprocess.check_output(['git','diff','--name-only','--no-renames',parent['commit'],current],cwd=root,text=True).splitlines()
    if not set(changed)<=ADMIN_CHANGES|TEST_CHANGES:raise ValueError('S1_OR_UNAPPROVED_SOURCE_CHANGED')
    for path,want in protocol['files'].items():
        original=subprocess.check_output(['git','show',parent['commit']+':'+path],cwd=root)
        if hashlib.sha256(original).hexdigest()!=want:raise ValueError('PARENT_GIT_SOURCE_NOT_ATTESTED')
        if path not in ADMIN_CHANGES and ex.sha(Path(root)/path)!=want:
            raise ValueError('S1_EXECUTION_DEPENDENCY_CHANGED:'+path)
        if path=='tools/stage2_protocol.py':
            def without_files(text):
                tree=ast.parse(text)
                tree.body=[node for node in tree.body if not(isinstance(node,ast.Assign)and
                    any(isinstance(target,ast.Name)and target.id=='FILES'for target in node.targets))]
                return ast.dump(tree,include_attributes=False)
            if without_files(original.decode())!=without_files((Path(root)/path).read_text()):
                raise ValueError('RECOVERY_OR_PROTOCOL_LOGIC_CHANGED')
        if path=='tools/stage2_orchestrator.py':
            def first_functions(text):
                return {node.name:ast.dump(node,include_attributes=False)for node in ast.parse(text).body
                        if isinstance(node,ast.FunctionDef)and node.name in('prepare','binding','run_first')}
            if first_functions(original.decode())!=first_functions((Path(root)/path).read_text()):
                raise ValueError('S1_ORCHESTRATION_FUNCTION_CHANGED')
    if parent['identity']!=ex.identities(root)or parent['inventory']!=ex.inventory([Path(root)/'gaia',Path(root)/'gaia.py']):
        raise ValueError('EXPERIMENTAL_SOURCE_CHANGED')
    if parent['plan']['administrative_hashes']!={p:ex.sha(ex.ROOT/p)for p in ex.ADMIN_FILES}:
        raise ValueError('FROZEN_S1_ADMINISTRATIVE_DEPENDENCY_CHANGED')
    if parent['runtime']!={'python':sys.version,'executable':sys.executable}or parent['boot_id']!=ex.boot_id():
        raise ValueError('CONTINUATION_RUNTIME_OR_BOOT_CHANGED')
    plan=Path(root)/'docs/GAIA — Plan Maestro de Estabilización y Cierre de la Versión 1.1'
    if ex.sha(plan)!=protocol['master_plan_sha256']:raise ValueError('MASTER_PLAN_CHANGED')
    return current,changed


def original_s1(root,parent,extra):
    out=Path(parent['state_path']).parent
    original=json.loads((out/'manifest-s1.json').read_bytes())
    verify_manifest(original,ex.inventory(roots_for(root,parent),include_cache=True),out/'manifest-s1.json',additional=extra)
    result=json.loads((out/'result-s1.json').read_bytes())
    if result.get('status')!='S1_OBSERVED'or result.get('subreaper',{}).get('status')!='PASS':
        raise ValueError('REAL_S1_NOT_OBSERVED')
    store=SessionStore(Path(parent['state_path']),result['session_id'])
    aggregate=ex.StageBudget(out/'budget',parent['hash'],roots_for(root,parent))
    checks={'audit':audit_session(root,store.state,store.identifier,stage='stage2'),
            'aggregate':audit_aggregate(store,aggregate),'window':window_coverage(store),
            'reconciliation':ex.reconcile(store,roots_for(root,parent),root=root),
            'scratch':retained_scratch(parent,store.state,[store.identifier]),
            'observer':audit_observer(out.parent/(out.name+'-observer'),parent['hash'],
                started=store.state_view()['started_clock'],stopped=store.events()[-1]['clock'])}
    if any(check['status']!='PASS'for check in checks.values()):raise ValueError('S1_CONTINUATION_REAUDIT_FAILED')
    return store,aggregate,checks


def effective_contract(root,parent):
    value=copy.deepcopy(parent)
    value['commit']=ex.safe_git(root,'rev-parse','HEAD')
    value['freeze']=ex.frozen(root,Path(parent['state_path']),parent['lineages'])
    # The first benchmark creation is expected; everything else is invariant.
    old=copy.deepcopy(parent['freeze']);new=copy.deepcopy(value['freeze'])
    for key in ('hash','commit'):old.pop(key,None);new.pop(key,None)
    for lin,binding in old['lineages'].items():
        if binding['benchmark_hash']is None:new['lineages'][lin]['benchmark_hash']=None
    if old!=new:raise ValueError('EXPERIMENTAL_FREEZE_CHANGED')
    if ex.changes(root,Path(parent['state_path']),parent['freeze']):raise ValueError('PARENT_PROTOCOL_INVARIANT_CHANGED')
    value['hash']=ex.digest({k:v for k,v in value.items()if k!='hash'})
    return ex.validate_contract(value)


def create(root,contract_path,out,regression,*,authorize=False):
    if not authorize:raise ValueError('EXPLICIT_ADMINISTRATIVE_AMENDMENT_AUTHORIZATION_REQUIRED')
    root=Path(root).resolve();out=ex.safe_out(root,Path(out)/'amendment.json').parent.resolve()
    parent,protocol=parent_binding(root,contract_path)
    parent_out=Path(parent['state_path']).parent
    if out.is_relative_to(parent_out)or out.exists():raise ValueError('NEW_EXTERNAL_CONTINUATION_DIRECTORY_REQUIRED')
    current,changed=change_scope(root,parent,protocol)
    regression=Path(regression)
    receipt=json.loads((regression/'result.json').read_bytes());start=json.loads((regression/'start.json').read_bytes())
    if (receipt.get('status')!='PASS'or receipt.get('returncode')!=0 or start['commit']!=current
            or receipt['log_sha256']!=ex.sha(regression/'full-suite.log')
            or start['source_manifest']!=ex.inventory([root/p for p in ('gaia','tools','tests','gaia.py')])):
        raise ValueError('CURRENT_CONTINUATION_REGRESSION_REQUIRED')
    extra=archive_manifest(parent_out/'boundary')
    failed=json.loads((parent_out/'boundary/result.json').read_bytes())
    if (failed.get('status')!='BLOCKED_PREEXECUTION'or failed.get('terminal_replays')
            or failed.get('budget_unchanged')is not True or failed.get('ownership',{}).get('status')!='PASS'
            or failed['inspection']['failures']!=['admission']
            or failed['inspection']['checks']['admission']['reasons']!=['OPERATIONAL_BACKEND_SCRATCH_BUSY']):
        raise ValueError('PARENT_FAILURE_NOT_THE_REVIEWED_ADMINISTRATIVE_BLOCK')
    if failed['inspection']['owned_manifest'].get(str(parent_out/'manifest-s1.json'))!=ex.sha(parent_out/'manifest-s1.json'):
        raise ValueError('S1_MANIFEST_ANCHOR_CHANGED')
    store,aggregate,checks=original_s1(root,parent,extra)
    budget=aggregate.view()
    if budget['sessions']!=[store.identifier]or len(budget['charges'])!=2 or budget['remaining_compute_s']!=3600:
        raise ValueError('EXACT_S2_REMAINING_BUDGET_REQUIRED')
    if (parent_out/'session2-start.json').exists():raise ValueError('SESSION2_ALREADY_STARTED')
    effective=effective_contract(root,parent)
    current_protocol=copy.deepcopy(protocol)
    current_protocol.update(base_contract_hash=effective['hash'],files=tool_hashes(root))
    current_protocol['hash']=ex.digest({k:v for k,v in current_protocol.items()if k!='hash'})
    events=aggregate.events()
    value={'schema':'gaia_stage2_administrative_continuation_v1','parent_contract_path':str(Path(contract_path).resolve()),
        'parent_contract_hash':parent['hash'],'parent_orchestration_hash':protocol['hash'],
        's1_commit':parent['commit'],'s2_commit':current,'s1_session_id':store.identifier,
        's1_manifest_sha256':ex.sha(parent_out/'manifest-s1.json'),
        's1_result_sha256':ex.sha(parent_out/'result-s1.json'),'prior_boundary_archive':extra,
        'changed_files':changed,'contract':effective,'protocol':current_protocol,
        'budget_prefix':{'events':len(events),'tip':events[-1]['hash'],'view':budget},
        'checks':{name:check['status']for name,check in checks.items()},
        'regression':{'path':str(regression.resolve()),'result_sha256':ex.sha(regression/'result.json')},
        'execution_prohibited':True,'s1_execution_repeated':False,'reservation_reset':False,
        's2_boundary_path':str(out/'boundary'),'authorization':'USER_APPROVED_ADMINISTRATIVE_CONTINUATION_ONLY'}
    value['hash']=ex.digest(value)
    out.mkdir(parents=True)
    durable(out/'amendment.json',value,True)
    return {'status':'AMENDMENT_PREPARED_ONLY','amendment_path':str(out/'amendment.json'),
            's1_preserved':True,'remaining_compute_s':3600,'execution_prohibited':True}


def validate(root,contract_path,path,*,after=False):
    root=Path(root).resolve();path=ex.safe_out(root,Path(path)).resolve()
    value=sealed(json.loads(path.read_bytes()))
    parent,protocol=parent_binding(root,contract_path)
    current,changed=change_scope(root,parent,protocol)
    if (value.get('schema')!='gaia_stage2_administrative_continuation_v1'
            or value['parent_contract_path']!=str(Path(contract_path).resolve())
            or value['parent_contract_hash']!=parent['hash']or value['parent_orchestration_hash']!=protocol['hash']
            or value['s2_commit']!=current or value['changed_files']!=changed
            or value.get('execution_prohibited')is not True or value.get('reservation_reset')is not False
            or value.get('s1_execution_repeated')is not False
            or value['s2_boundary_path']!=str(path.parent/'boundary')
            or value['protocol']['files']!=tool_hashes(root)):
        raise ValueError('CONTINUATION_BINDING_CHANGED')
    effective=ex.validate_contract(value['contract']);sealed(value['protocol'])
    if effective!=effective_contract(root,parent):raise ValueError('CONTINUATION_EXPERIMENTAL_CONTRACT_CHANGED')
    expected_protocol=copy.deepcopy(protocol)
    expected_protocol.update(base_contract_hash=effective['hash'],files=tool_hashes(root))
    expected_protocol['hash']=ex.digest({k:v for k,v in expected_protocol.items()if k!='hash'})
    if value['protocol']!=expected_protocol:raise ValueError('CONTINUATION_PROTOCOL_CHANGED')
    out=Path(parent['state_path']).parent
    if ex.sha(out/'manifest-s1.json')!=value['s1_manifest_sha256']or ex.sha(out/'result-s1.json')!=value['s1_result_sha256']:
        raise ValueError('PRESERVED_S1_ATTESTATION_CHANGED')
    if archive_manifest(out/'boundary')!=value['prior_boundary_archive']:raise ValueError('FAILED_BOUNDARY_ARCHIVE_CHANGED')
    aggregate=ex.StageBudget(out/'budget',parent['hash'],roots_for(root,parent))
    events=aggregate.events();prefix=value['budget_prefix'];n=prefix['events']
    if type(n)is not int or n<=0 or len(events)<n or events[n-1]['hash']!=prefix['tip']:
        raise ValueError('ORIGINAL_BUDGET_PREFIX_CHANGED')
    if not after:
        if len(events)!=n or aggregate.view()!=prefix['view']:raise ValueError('BUDGET_CHANGED_BEFORE_SESSION2')
        original_s1(root,parent,value['prior_boundary_archive'])
    else:
        # Immutable S1 session/campaign/scratch artifacts must remain byte-identical;
        # C4 may append to the shared lineage and native experiment ledger.
        expected=json.loads((out/'manifest-s1.json').read_bytes())
        sid=value['s1_session_id'];store=SessionStore(Path(parent['state_path']),sid)
        scratch=ex.operational_scratch(parent)
        prefixes=[store.root,out/'contract.json',out/'orchestration.json',out/'subreaper.jsonl']
        prefixes.extend(Path(parent['state_path'])/'autonomy/campaigns'/cid for cid in store.state_view()['campaigns'])
        prefixes.extend({scratch/Path(filename).relative_to(scratch).parts[0]for filename in expected
                         if Path(filename).is_relative_to(scratch)})
        preserved={filename:want for filename,want in expected.items()
                   if any(Path(filename).is_relative_to(base)for base in prefixes)}
        if ex.inventory(prefixes,include_cache=True)!=preserved:raise ValueError('PRESERVED_S1_BYTES_CHANGED')
    return {'parent':parent,'contract':effective,'protocol':value['protocol'],
            'ledger_hash':parent['hash'],'boundary_path':Path(value['s2_boundary_path']),
            'additional':value['prior_boundary_archive'],'amendment':value,'directory':path.parent}
