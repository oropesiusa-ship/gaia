"""Restartable bounded coordinator for autonomous research dialogue iterations."""
from dataclasses import dataclass
import re
import time

from ..provenance import canonical_json,digest
from .research_agenda import deterministic_agenda
from .research_comparison import compare_research
from .research_dialogue import DialogueBudget,ResearchDialogueRunner
from .schema import ref,seal


SCHEMA='gaia_research_campaign_v1'


@dataclass(frozen=True)
class CampaignBudget:
    max_iterations:int=2
    max_llm_calls:int=6
    max_tokens:int=3072
    max_duration_s:int=480
    max_storage_bytes:int=2*2**20

    def validate(self):
        if (type(self.max_iterations)is not int or not 1<=self.max_iterations<=8 or type(self.max_llm_calls)is not int or not 3<=self.max_llm_calls<=24
                or type(self.max_tokens)is not int or not 384<=self.max_tokens<=16384 or type(self.max_duration_s)is not int or not 10<=self.max_duration_s<=1800
                or type(self.max_storage_bytes)is not int or not 65536<=self.max_storage_bytes<=8*2**20):raise ValueError('INVALID_CAMPAIGN_BUDGET')
        return self

    def data(self):return {k:getattr(self,k)for k in ('max_iterations','max_llm_calls','max_tokens','max_duration_s','max_storage_bytes')}


def _fingerprint(issue):return digest({'task_id':issue['task_id'],'evidence_refs':issue['evidence_refs'],
                                       'research_evidence_refs':issue.get('research_evidence_refs',[])})


class ResearchCampaign:
    def __init__(self,store,backend_factory,*,budget=None,owner_id='local',evidence_mode='ENRICHED_OBJECTIVE_V1'):
        self.store=store;self.backend_factory=backend_factory;self.budget=(budget or CampaignBudget()).validate()
        if not isinstance(owner_id,str)or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',owner_id):raise ValueError('INVALID_CAMPAIGN_OWNER')
        if evidence_mode not in ('ENRICHED_OBJECTIVE_V1','ENRICHED_TRANSFER_V2'):raise ValueError('INVALID_RESEARCH_EVIDENCE_MODE')
        self.owner_id=owner_id
        self.evidence_mode=evidence_mode

    def _id(self,observed):return 'rc'+digest({'schema':SCHEMA,'source':observed['source'],'owner_id':self.owner_id,'budget':self.budget.data(),'evidence_mode':self.evidence_mode})[:24]

    def run(self,observed):
        campaign_id=self._id(observed);finals=[v for v in self.store.list('RESEARCH_CAMPAIGN')if v['payload'].get('campaign_id')==campaign_id]
        if finals:return finals[-1]
        baseline=deterministic_agenda(observed);start=time.monotonic()
        records=[v for v in self.store.list('RESEARCH_DIALOGUE')if v['payload'].get('campaign_id')==campaign_id]
        comparisons=[v for v in self.store.list('RESEARCH_COMPARISON')if v['payload'].get('campaign_id')==campaign_id]
        stored_bytes=sum(len(canonical_json(v))for v in records+comparisons);storage_limit=self.budget.max_storage_bytes-16384
        processed={v['payload']['issue_fingerprint']for v in records};calls=sum(v['payload']['dialogue']['performance']['calls']for v in records)
        tokens=sum(v['payload']['dialogue']['performance']['reserved_tokens']for v in records);dialogue_refs=[ref(v)for v in records];comparison_refs=[ref(v)for v in comparisons]
        compared={v['payload']['dialogue_ref']['id']for v in comparisons}
        for record in records:
            if record['id']not in compared:
                comparison=compare_research(observed,baseline,record['payload']['dialogue'])
                candidate=seal('RESEARCH_COMPARISON',{'schema':SCHEMA,'campaign_id':campaign_id,'owner_id':self.owner_id,
                    'iteration':record['payload']['iteration'],'dialogue_ref':ref(record),'comparison':comparison,'authority':'NONE'})
                if stored_bytes+len(canonical_json(candidate))>storage_limit:raise ValueError('STORAGE_BUDGET')
                comp=self.store.put(candidate);stored_bytes+=len(canonical_json(candidate))
                comparison_refs.append(ref(comp))
        reason=None
        issues=sorted(observed.get('issues',[]),key=lambda v:(-v['failure_count'],-v['format_failure_count'],v['task_id']))
        for iteration in range(len(records)+1,self.budget.max_iterations+1):
            if time.monotonic()-start>=self.budget.max_duration_s:reason='DURATION_BUDGET';break
            candidates=[v for v in issues if _fingerprint(v)not in processed]
            if not candidates:reason='NO_NEW_EVIDENCE_OR_UNTRIED_ISSUE';break
            if calls+3>self.budget.max_llm_calls:reason='LLM_CALL_BUDGET';break
            remaining_tokens=self.budget.max_tokens-tokens
            if remaining_tokens<288:reason='TOKEN_BUDGET';break
            issue=candidates[0];fingerprint=_fingerprint(issue)
            dialogue_budget=DialogueBudget(max_calls=3,max_tokens=min(1536,remaining_tokens),max_duration_s=min(180,self.budget.max_duration_s))
            dialogue=ResearchDialogueRunner(self.backend_factory,budget=dialogue_budget,evidence_mode=self.evidence_mode).run(observed,issue)
            payload={'schema':SCHEMA,'campaign_id':campaign_id,'owner_id':self.owner_id,'iteration':iteration,'issue_fingerprint':fingerprint,
                     'dialogue':dialogue,'authority':'NONE','hidden_reasoning_stored':False}
            candidate=seal('RESEARCH_DIALOGUE',payload);size=len(canonical_json(candidate))
            if stored_bytes+size>storage_limit:reason='STORAGE_BUDGET';break
            record=self.store.put(candidate);stored_bytes+=size;dialogue_refs.append(ref(record));processed.add(fingerprint)
            calls+=dialogue['performance']['calls'];tokens+=dialogue['performance']['reserved_tokens']
            comparison=compare_research(observed,baseline,dialogue)
            candidate=seal('RESEARCH_COMPARISON',{'schema':SCHEMA,'campaign_id':campaign_id,'owner_id':self.owner_id,
                'iteration':iteration,'dialogue_ref':ref(record),'comparison':comparison,'authority':'NONE'})
            if stored_bytes+len(canonical_json(candidate))>storage_limit:reason='STORAGE_BUDGET';break
            comp=self.store.put(candidate);stored_bytes+=len(canonical_json(candidate));comparison_refs.append(ref(comp))
            if dialogue['status']=='REJECTED':
                if dialogue['reason']in ('INVALID_MODEL_JSON','INVALID_RESEARCHER_SCHEMA','INVALID_CRITIC_SCHEMA','INVALID_REVIEWER_SCHEMA'):continue
                reason='DIALOGUE_REJECTED_'+dialogue['reason'];break
            if dialogue['status']=='STOPPED':
                if dialogue['reason']=='MORE_EVIDENCE':continue
                reason='DIALOGUE_STOPPED_'+dialogue['reason'];break
        if reason is None:
            reason='ITERATION_BUDGET'if len(dialogue_refs)>=self.budget.max_iterations else'NO_NEW_EVIDENCE_OR_UNTRIED_ISSUE'
        payload={'schema':SCHEMA,'campaign_id':campaign_id,'owner_id':self.owner_id,'source':observed['source'],'status':'STOPPED','reason':reason,
            'iterations':len(dialogue_refs),'llm_calls':calls,'reserved_tokens':tokens,'dialogue_refs':dialogue_refs,'comparison_refs':comparison_refs,
            'budget':self.budget.data(),'authority':'NONE','network_requests':0,'source_changes':0,'evaluator_changes':0,'promotions':0,
            'duration_s':time.monotonic()-start,'restart_safe':True}
        return self.store.put(seal('RESEARCH_CAMPAIGN',payload))
