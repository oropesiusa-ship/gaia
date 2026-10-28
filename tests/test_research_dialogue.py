"""Hostile and successful controlled inference for Research Dialogue V1."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from gaia.cognition.research_agenda import BenchmarkObservation
from gaia.cognition.research_dialogue import DialogueBudget,DirectResearchRunner,ResearchDialogueRunner
from gaia.cognition.research_agenda import deterministic_agenda
from gaia.cognition.research_comparison import compare_research


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

    def test_schema_rejection_preserves_shape_without_model_values(self):
        result,_=self.execute([{'unexpected':'secret text','items':[{'x':391}]}])
        self.assertEqual(result['reason'],'INVALID_RESEARCHER_SCHEMA')
        shape=result['turns'][0]['rejected_response_shape']
        self.assertEqual(shape['type'],'object');self.assertEqual(shape['keys'],['items','unexpected'])
        self.assertNotIn('secret',str(shape));self.assertNotIn('391',str(shape))

    def test_backend_timeout_and_call_budget_stop_safely(self):
        result,_=self.execute([TimeoutError('slow')]);self.assertEqual((result['status'],result['reason']),('REJECTED','MODEL_TIMEOUT'))
        result,_=self.execute(budget=DialogueBudget(max_calls=2,max_tokens=1024,max_duration_s=10))
        self.assertEqual((result['status'],result['reason']),('REJECTED','LLM_CALL_BUDGET'))

    def test_insufficient_evidence_abstains_without_loading_backend(self):
        backend=Backend(outputs());empty={**self.observed,'issues':[]}
        result=ResearchDialogueRunner(lambda:backend).run(empty,None)
        self.assertEqual((result['status'],result['reason']),('STOPPED','INSUFFICIENT_FAILURE_EVIDENCE'));self.assertFalse(backend.loaded)

    def test_enriched_mode_exposes_frozen_expected_and_observed_values_only_when_selected(self):
        enriched,backend=self.execute()
        self.assertIn('391',backend.prompts[0]);self.assertIn('0.7391',backend.prompts[0]);self.assertEqual(enriched['evidence_mode'],'ENRICHED_OBJECTIVE_V1')
        self.assertIn('concrete testable intervention',backend.prompts[0])
        plain_backend=Backend(outputs())
        plain=ResearchDialogueRunner(lambda:plain_backend,evidence_mode='COUNTS_V1').run(self.observed,self.issue)
        self.assertNotIn('391',plain_backend.prompts[0]);self.assertNotIn('0.7391',plain_backend.prompts[0]);self.assertEqual(plain['evidence_mode'],'COUNTS_V1')

    def test_minimal_researcher_wire_derives_policy_fields_from_verified_evidence(self):
        values=list(outputs());values[0]={'cause':'Arithmetic reasoning is unreliable for this multiplication.','change':'Test a short multiplication scaffold.'}
        result,_=self.execute(values)
        hypothesis=result['research']['hypotheses'][0]
        self.assertEqual(hypothesis['prediction'],'Expected exact output: {"resultado":391}')
        self.assertEqual(hypothesis['evidence_refs'],[self.issue['evidence_refs'][0]])
        self.assertIn('unverified',hypothesis['uncertainty'][0])

    def test_single_proposal_wire_preserves_model_text_as_unverified_cause_and_intervention(self):
        values=list(outputs());values[0]={'proposal':'Arithmetic reasoning may be wrong; test a multiplication scaffold.'}
        result,_=self.execute(values);hypothesis=result['research']['hypotheses'][0]
        self.assertEqual(hypothesis['causal_hypothesis'],values[0]['proposal']);self.assertEqual(hypothesis['intervention'],values[0]['proposal'])

    def test_compact_proposal_may_carry_only_valid_evidence_aliases(self):
        values=list(outputs());values[0]={'proposal':'Test a symbolic multiplication restatement.','refs':['e1']}
        result,_=self.execute(values);self.assertEqual(result['status'],'ACCEPTED')
        values[0]={'proposal':'Test a symbolic multiplication restatement.','refs':['invented']}
        result,_=self.execute(values);self.assertEqual(result['reason'],'INVENTED_EVIDENCE_REFERENCE')

    def test_explicit_hypothesis_test_intervention_variant_is_normalized_without_losing_text(self):
        values=list(outputs());values[0]={'hypothesis':'Arithmetic calculation may be wrong.','test':'Repeat the frozen multiplication.',
            'intervention':'Use a multiplication scaffold.'}
        result,_=self.execute(values);hypothesis=result['research']['hypotheses'][0]
        self.assertEqual(hypothesis['causal_hypothesis'],values[0]['hypothesis']);self.assertIn(values[0]['test'],hypothesis['intervention'])

    def test_critic_missing_recommendation_defaults_to_conservative_revision(self):
        values=list(outputs());values[1]={'kind':'C','objection':'The test does not distinguish calculation from formatting.'}
        result,_=self.execute(values);self.assertEqual(result['critique']['recommendation'],'REVISE')

    def test_v2_transfers_critic_detail_without_anchoring_reviewer_decision(self):
        backend=Backend(outputs())
        result=ResearchDialogueRunner(lambda:backend,evidence_mode='ENRICHED_TRANSFER_V2').run(self.observed,self.issue)
        self.assertEqual(result['status'],'ACCEPTED')
        reviewer=backend.prompts[2]
        self.assertIn('"proposal"',backend.prompts[0])
        self.assertIn('One scaffold cannot distinguish arithmetic ability',reviewer)
        self.assertIn('ACCEPT, MODIFY, DISCARD, MORE_EVIDENCE, or STOP',reviewer)
        self.assertNotIn('"decision":"MORE_EVIDENCE"',reviewer)

    def test_direct_one_role_proposal_uses_same_frozen_comparator(self):
        backend=Backend([{'proposal':'The reasoning failure may come from the Spanish multiplication operator; test a symbolic operator restatement.'}])
        result=DirectResearchRunner(lambda:backend).run(self.observed,self.issue)
        comparison=compare_research(self.observed,deterministic_agenda(self.observed),result,selector='RESEARCH_DIRECT_V1_ONE_ROLE')
        self.assertEqual(result['status'],'ACCEPTED')
        self.assertEqual(result['performance']['calls'],1)
        self.assertGreater(comparison['dialogue']['score'],comparison['baseline']['score'])
        self.assertEqual(comparison['dialogue']['selector'],'RESEARCH_DIRECT_V1_ONE_ROLE')


if __name__=='__main__':unittest.main()
