from pathlib import Path
import tempfile
import unittest

from gaia.cognition.research_agenda import BenchmarkObservation
from gaia.cognition.research_campaign import CampaignBudget,ResearchCampaign
from gaia.cognition.store import CognitiveStore
from test_research_dialogue import Backend,outputs


ROOT=Path(__file__).resolve().parents[1]
RAW=(ROOT/'docs/local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json').read_bytes()


class Factory:
    def __init__(self):self.created=0
    def __call__(self):self.created+=1;return Backend(outputs())


class MoreEvidenceThenAcceptFactory:
    def __init__(self):self.created=0
    def __call__(self):
        values=list(outputs())
        if self.created==0:
            values[2]={'decision':'MORE_EVIDENCE'}
        self.created+=1;return Backend(values)


class CampaignTests(unittest.TestCase):
    def setUp(self):self.observed=BenchmarkObservation.from_bytes(RAW,'GAIA_1_2_MEMORY_QUALITY_V1.json')

    def test_two_iterations_persist_and_restart_without_duplicate_inference(self):
        with tempfile.TemporaryDirectory()as state:
            factory=Factory();campaign=ResearchCampaign(CognitiveStore(state),factory)
            first=campaign.run(self.observed);second=campaign.run(self.observed)
            self.assertEqual(first,second);self.assertEqual(factory.created,2)
            self.assertEqual(first['payload']['iterations'],2);self.assertEqual(first['payload']['llm_calls'],6)
            self.assertEqual(first['payload']['reason'],'ITERATION_BUDGET');self.assertTrue(first['payload']['restart_safe'])
            self.assertEqual(len(CognitiveStore(state).list('RESEARCH_DIALOGUE')),2)

    def test_issue_local_rejections_continue_and_are_preserved(self):
        with tempfile.TemporaryDirectory()as state:
            factory=lambda:Backend(['bad json'])
            result=ResearchCampaign(CognitiveStore(state),factory).run(self.observed)
            self.assertEqual(result['payload']['iterations'],2);self.assertEqual(result['payload']['reason'],'ITERATION_BUDGET')
            self.assertEqual(len(CognitiveStore(state).list('RESEARCH_DIALOGUE')),2)

    def test_more_evidence_continues_with_next_untried_issue(self):
        with tempfile.TemporaryDirectory()as state:
            factory=MoreEvidenceThenAcceptFactory();result=ResearchCampaign(CognitiveStore(state),factory).run(self.observed)
            self.assertEqual(result['payload']['iterations'],2)
            self.assertEqual(factory.created,2)
            self.assertEqual(result['payload']['reason'],'ITERATION_BUDGET')
            records=CognitiveStore(state).list('RESEARCH_DIALOGUE')
            self.assertEqual(records[0]['payload']['dialogue']['reason'],'MORE_EVIDENCE')
            self.assertNotEqual(records[0]['payload']['issue_fingerprint'],records[1]['payload']['issue_fingerprint'])

    def test_no_evidence_stops_without_backend(self):
        with tempfile.TemporaryDirectory()as state:
            factory=Factory();observed={**self.observed,'issues':[]}
            result=ResearchCampaign(CognitiveStore(state),factory).run(observed)
            self.assertEqual(result['payload']['reason'],'NO_NEW_EVIDENCE_OR_UNTRIED_ISSUE');self.assertEqual(factory.created,0)

    def test_owner_isolation_changes_campaign_identity(self):
        with tempfile.TemporaryDirectory()as state:
            store=CognitiveStore(state)
            left=ResearchCampaign(store,Factory(),budget=CampaignBudget(max_iterations=1,max_llm_calls=3,max_tokens=512),owner_id='a').run(self.observed)
            right=ResearchCampaign(store,Factory(),budget=CampaignBudget(max_iterations=1,max_llm_calls=3,max_tokens=512),owner_id='b').run(self.observed)
            self.assertNotEqual(left['payload']['campaign_id'],right['payload']['campaign_id'])

    def test_restart_after_final_record_interruption_reuses_dialogue_and_comparison(self):
        with tempfile.TemporaryDirectory()as state:
            store=CognitiveStore(state);factory=Factory();budget=CampaignBudget(max_iterations=1,max_llm_calls=3,max_tokens=1536)
            first=ResearchCampaign(store,factory,budget=budget).run(self.observed)
            store.path('RESEARCH_CAMPAIGN',first['id']).unlink()
            recovered=ResearchCampaign(store,factory,budget=budget).run(self.observed)
            self.assertEqual(factory.created,1);self.assertEqual(recovered['payload']['iterations'],1)
            self.assertEqual(len(recovered['payload']['comparison_refs']),1)


if __name__=='__main__':unittest.main()
