"""Hostile and successful controlled inference for Research Dialogue V1."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from gaia.cognition.research_agenda import BenchmarkObservation
from gaia.cognition.research_dialogue import DialogueBudget,ResearchDialogueRunner


ROOT=Path(__file__).resolve().parents[1]
RAW=(ROOT/'docs/local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json').read_bytes()


def outputs():
    researcher={'kind':'RESEARCHER','authority':'NONE','hypotheses':[{'id':'hp1','problem':'Arithmetic output failed exact scoring.',
        'evidence_refs':['e1'],'causal_hypothesis':'The reasoning model may lose multiplication constraints during generation.',
        'intervention':'Compare one fixed arithmetic scaffold against the unchanged prompt.','prediction':'Exact result becomes 391.',
        'metric':{'name':'exact_objective_passes','criterion':'gain >= 1 and regressions == 0','evaluator':'FROZEN_EXISTING'},
        'estimated_cost':{'model_runs':4,'tokens':4096,'duration_s':120},'uncertainty':['Two failures do not establish cause.']}]}
    critic={'kind':'CRITIC','authority':'NONE','hypothesis_id':'hp1','objections':[{'type':'CAUSAL_IDENTIFICATION',
        'detail':'One scaffold cannot distinguish arithmetic ability from instruction adherence.','evidence_refs':['e1']}],
        'recommendation':'REVISE'}
    reviewer={'kind':'REVIEWER','authority':'NONE','decision':'ACCEPT','selected_hypothesis_id':'hp1','evidence_refs':['e1'],
        'experiment':{'protocol':['Run unchanged frozen workload.','Run one pre-registered scaffold variant.','Score with frozen evaluator.'],
        'metric':researcher['hypotheses'][0]['metric'],'budget':{'model_runs':4,'tokens':4096,'duration_s':120},
        'authority_required':'LOCAL_COMPUTE','execute':False,'network_requests':0,'source_changes':0,'evaluator_changes':0,'promotion_allowed':False},
        'next_question':'Does the scaffold improve arithmetic without format regressions?'}
    return researcher,critic,reviewer


class Backend:
    def __init__(self,values):self.values=iter(values);self.loaded=False;self.prompts=[]
    def load(self):self.loaded=True
    def unload(self):self.loaded=False
    def generate(self,prompt,*,max_tokens,timeout=None):
        self.prompts.append(prompt);value=next(self.values)
        if isinstance(value,BaseException):raise value
        return {'status':'OK','text':value if isinstance(value,str)else json.dumps(value),'latency_s':.01,'usage':{'completion_tokens':20}}


class DialogueTests(unittest.TestCase):
    def setUp(self):
        self.observed=BenchmarkObservation.from_bytes(RAW,'GAIA_1_2_MEMORY_QUALITY_V1.json')
        self.issue=next(v for v in self.observed['issues']if v['task_id']=='reasoning')

    def execute(self,values=None,budget=None):
        backend=Backend(values or outputs());result=ResearchDialogueRunner(lambda:backend,budget=budget).run(self.observed,self.issue)
        return result,backend

    def test_three_independent_roles_produce_bounded_review(self):
        result,backend=self.execute()
        self.assertEqual(result['status'],'ACCEPTED');self.assertEqual(result['authority'],'NONE')
        self.assertEqual([v['role']for v in result['turns']],['RESEARCHER','CRITIC','REVIEWER'])
        self.assertEqual(len(backend.prompts),3);self.assertNotEqual(backend.prompts[0],backend.prompts[1])
        self.assertFalse(result['review']['experiment']['execute']);self.assertEqual(result['review']['experiment']['network_requests'],0)
        self.assertTrue(all(v['hidden_reasoning_requested']is False for v in result['turns']))

    def test_malformed_json_invented_reference_empty_critique_and_escalation_are_rejected(self):
        cases=[]
        cases.append((['not json'],'INVALID_MODEL_JSON'))
        invented=list(outputs());invented[0]=copy.deepcopy(invented[0]);invented[0]['hypotheses'][0]['evidence_refs']=['e999'];cases.append((invented,'INVENTED_EVIDENCE_REFERENCE'))
        empty=list(outputs());empty[1]=copy.deepcopy(empty[1]);empty[1]['objections']=[];cases.append((empty,'EMPTY_CRITIQUE'))
        escalated=list(outputs());escalated[2]=copy.deepcopy(escalated[2]);escalated[2]['authority']='SIDE_EFFECT';cases.append((escalated,'RESEARCH_AUTHORITY_ESCALATION'))
        for values,reason in cases:
            with self.subTest(reason=reason):
                result,_=self.execute(values);self.assertEqual(result['status'],'REJECTED');self.assertEqual(result['reason'],reason)

    def test_backend_timeout_and_call_budget_stop_safely(self):
        result,_=self.execute([TimeoutError('slow')]);self.assertEqual((result['status'],result['reason']),('REJECTED','MODEL_TIMEOUT'))
        result,_=self.execute(budget=DialogueBudget(max_calls=2,max_tokens=1024,max_duration_s=10))
        self.assertEqual((result['status'],result['reason']),('REJECTED','LLM_CALL_BUDGET'))

    def test_insufficient_evidence_abstains_without_loading_backend(self):
        backend=Backend(outputs());empty={**self.observed,'issues':[]}
        result=ResearchDialogueRunner(lambda:backend).run(empty,None)
        self.assertEqual((result['status'],result['reason']),('STOPPED','INSUFFICIENT_FAILURE_EVIDENCE'));self.assertFalse(backend.loaded)


if __name__=='__main__':unittest.main()
