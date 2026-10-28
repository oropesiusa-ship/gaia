import json
from pathlib import Path
import unittest

from gaia.cognition.research_agenda import BenchmarkObservation,deterministic_agenda
from gaia.cognition.research_comparison import CRITERIA_HASH,compare_research
from gaia.cognition.research_dialogue import ResearchDialogueRunner
from test_research_dialogue import Backend,outputs


ROOT=Path(__file__).resolve().parents[1]
RAW=(ROOT/'docs/local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json').read_bytes()


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.observed=BenchmarkObservation.from_bytes(RAW,'GAIA_1_2_MEMORY_QUALITY_V1.json')
        self.issue=next(v for v in self.observed['issues']if v['task_id']=='reasoning')
        self.baseline=deterministic_agenda(self.observed)

    def test_same_evidence_pre_registered_scoring(self):
        dialogue=ResearchDialogueRunner(lambda:Backend(outputs())).run(self.observed,self.issue)
        value=compare_research(self.observed,self.baseline,dialogue)
        self.assertEqual(value['criteria_hash'],CRITERIA_HASH);self.assertEqual(value['source'],self.baseline['source'])
        self.assertFalse(value['evaluator_modified']);self.assertEqual(value['winner'],'DIALOGUE')
        self.assertGreater(value['dialogue']['score'],value['baseline']['score'])

    def test_rejected_output_never_beats_baseline(self):
        dialogue=ResearchDialogueRunner(lambda:Backend(['bad json'])).run(self.observed,self.issue)
        value=compare_research(self.observed,self.baseline,dialogue)
        self.assertEqual(value['winner'],'BASELINE');self.assertEqual(value['dialogue']['score'],2)


if __name__=='__main__':unittest.main()
