import copy
import unittest

from gaia.cognition.research_evaluator_v2 import evaluate_candidate


def fixture(intervention='Compare symbolic multiplication operator wording.',cause='The language representation changes arithmetic behavior.'):
    ref={'source':{'id':'evidence.json','sha256':'a'*64},'pointer':'/rows/0/score'}
    issue={'task_id':'reasoning','diagnostic_details':{'diagnosis':'LANGUAGE_OR_OPERATOR_REPRESENTATION_SUPPORTED'},
           'evidence_refs':[ref],'research_evidence_refs':[]}
    candidate={'schema':'gaia_research_candidate_v2','task_id':'reasoning','cause':cause,'intervention':intervention,
               'evidence_refs':[ref],'prediction':'Exact objective pass improves.','metric':{'criterion':'gain >= 1 and regressions == 0','evaluator':'FROZEN_EXISTING'},
               'experiment':{'protocol':['Run control.','Run candidate.','Score both.'],'execute':False,'promotion_allowed':False},'authority':'NONE'}
    baseline={'intervention':'Use the deterministic baseline scaffold.'}
    return issue,candidate,baseline


class ResearchEvaluatorV2Tests(unittest.TestCase):
    def test_accepts_causal_intervention_without_lexical_task_name(self):
        issue,candidate,baseline=fixture()
        value=evaluate_candidate(issue,candidate,baseline)
        self.assertEqual(value['score'],8);self.assertTrue(all(value['checks'].values()))

    def test_rejects_lexical_match_with_unrelated_intervention(self):
        issue,candidate,baseline=fixture('Add generic reasoning feedback for users.')
        value=evaluate_candidate(issue,candidate,baseline)
        self.assertFalse(value['checks']['causal_consistency'])

    def test_rejects_wrong_binding_reference_authority_and_baseline_copy(self):
        issue,candidate,baseline=fixture()
        mutations=(('structural_task_binding',{'task_id':'spanish'}),
                   ('real_references',{'evidence_refs':[{'source':{'id':'x','sha256':'b'*64},'pointer':'/x'}]}),
                   ('authority_respected',{'authority':'EXECUTE'}),
                   ('novel_intervention',{'intervention':baseline['intervention']}))
        for check,change in mutations:
            with self.subTest(check=check):
                altered=copy.deepcopy(candidate);altered.update(change)
                self.assertFalse(evaluate_candidate(issue,altered,baseline)['checks'][check])
        executable=copy.deepcopy(candidate);executable['experiment']['execute']=True
        self.assertFalse(evaluate_candidate(issue,executable,baseline)['checks']['authority_respected'])


if __name__=='__main__':unittest.main()
