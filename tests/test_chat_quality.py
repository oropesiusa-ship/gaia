import unittest
from gaia.cognition.chat_quality import objective_score,recall_score


class ChatQualityTests(unittest.TestCase):
    def test_objective_scoring_is_strict_and_subjective_free(self):
        self.assertTrue(objective_score({'expected':{'x':1}},'{"x":1}')['pass'])
        self.assertFalse(objective_score({'expected':{'x':1}},'Result: {"x":1}')['pass'])
        self.assertTrue(objective_score({'exact':'NO_SE'},'NO_SE')['pass'])
        self.assertFalse(objective_score({'exact':'NO_SE'},'No sé')['pass'])
        self.assertTrue(recall_score('La clave es NEBULA_77.','NEBULA_77')['pass'])
        self.assertFalse(recall_score('SUR_20 reemplaza NORTE_10','SUR_20','NORTE_10')['pass'])
