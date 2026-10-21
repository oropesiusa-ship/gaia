"""Closed read-only tool contracts. No network, shell, editing or execution dispatch."""
from dataclasses import dataclass
import time
from .schema import TYPES,AUTHORITIES,seal,ref,safe_text
from .evidence import TOOLS,project


@dataclass(frozen=True)
class ToolContract:
    tool_id:str
    description:str
    input_schema:dict
    output_schema:dict
    authority_level:str='READ_ONLY'
    side_effects:tuple=()
    network_usage:bool=False
    cost_class:str='BOUNDED_LOCAL_READ'
    timeout:int=2
    allowed_task_types:tuple=TYPES


class ToolRegistry:
    def __init__(self,store):
        self.store=store
        self.contracts={tool:ToolContract(tool,domain+' evidence snapshot lookup',
            {'type':'object','required':['id'],'properties':{'id':{'type':'string','pattern':'^cg[a-f0-9]{24}$'}},'additionalProperties':False},
            {'type':'object','required':['evidence_ref','facts'],
             'properties':{'evidence_ref':{'type':'object','required':['id','hash'],
                 'properties':{'id':{'type':'string'},'hash':{'type':'string'}},'additionalProperties':False},
                 'facts':{'type':'array','items':{'type':'object'}}},'additionalProperties':False})for domain,tool in TOOLS.items()}

    def validate(self,proposal,task):
        keys={'tool_id','arguments','reason','expected_information','authority_required'}
        if not isinstance(proposal,dict)or set(proposal)!=keys:raise ValueError('INVALID_TOOL_PROPOSAL')
        contract=self.contracts.get(proposal['tool_id'])
        if contract is None:raise ValueError('UNKNOWN_TOOL')
        if contract.authority_level!='READ_ONLY'or contract.side_effects or contract.network_usage:raise ValueError('TOOL_AUTHORITY_DENIED')
        if proposal['tool_id']not in task['allowed_tools']or task['task_type']not in contract.allowed_task_types or proposal['authority_required']!='READ_ONLY':raise ValueError('TOOL_PERMISSION_DENIED')
        args=proposal['arguments']
        if not isinstance(args,dict)or set(args)!={'id'}:raise ValueError('INVALID_TOOL_ARGUMENTS')
        permitted=next((r for r in task['context_refs']if r['tool_id']==proposal['tool_id']and r['id']==args['id']),None)
        if permitted is None:raise ValueError('TOOL_REFERENCE_NOT_AUTHORIZED')
        safe_text(proposal['reason'],160);safe_text(proposal['expected_information'],160)
        record=self.store.get(args['id'],'EVIDENCE')
        if ref(record)!={'id':permitted['id'],'hash':permitted['hash']}or TOOLS[record['payload']['domain']]!=proposal['tool_id']:raise ValueError('TOOL_SOURCE_MISMATCH')
        return record,contract

    def execute(self,proposal,task):
        start=time.monotonic();record,contract=self.validate(proposal,task)
        facts=project(record)
        if time.monotonic()-start>contract.timeout:raise TimeoutError('TOOL_TIMEOUT')
        return {'evidence_ref':ref(record),'facts':facts},time.monotonic()-start
