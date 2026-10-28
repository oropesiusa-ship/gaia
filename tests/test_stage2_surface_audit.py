"""Surface/order audit fixtures; no candidate or LLM execution."""
from unittest.mock import patch
from test_autonomy_integration import Fixture
from gaia.autonomy.lineage import create_lineage
from gaia.autonomy.freeze import freeze
from gaia.autonomy.session import SessionStore, session_contract
from gaia.autonomy.schema import campaign
from gaia.autonomy.controller import create_campaign
from tools.stage2_executor import LIMITS
from tools.audit_endurance_session import audit_session


class SecondSurfaceAuditTests(Fixture):
    def setup_session(self, reverse=False):
        numpy = self.lineage()
        inference = create_lineage(self.root, self.state, 'IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA')
        ids = [inference['lineage_id'], numpy['lineage_id']]
        contract = session_contract(ids, stage='stage2', limits=LIMITS,
                                    frozen=freeze(self.root, self.state, ids))
        session = SessionStore(self.state, contract['session_id'])
        session.create(contract, self.root)
        ordered = [inference, numpy] if not reverse else [numpy, inference]
        for lineage in ordered:
            c = campaign(lineage['objective'], mode='CONTROLLED_AUTONOMOUS', promotion=False,
                         lineage_id=lineage['lineage_id'], limits={'maximum_iterations': 5,
                         'maximum_experiments': 3, 'maximum_wall_time': 1740,
                         'maximum_compute_budget': 1740, 'maximum_disk_budget': 512*2**20})
            created = create_campaign(self.root, self.state, c)
            session.event('CAMPAIGN_STARTED', {'campaign_id': created['campaign_id'], 'lineage_id': lineage['lineage_id']})
            session.event('CAMPAIGN_FINISHED', {'campaign_id': created['campaign_id'], 'wall_s': 1})
        session.event('STOPPED', {'reason': 'SYNTHETIC_TEST'})
        return session

    def audit(self, session, **kwargs):
        with patch('tools.audit_endurance_session.audit_closed_loop.audit_campaign', return_value={'status': 'PASS'}), \
             patch('tools.audit_endurance_session.inspect_campaign', return_value={
                 'recovery': 'TERMINAL_OK', 'stopping_reason': 'NO_PROGRESS'}):
            return audit_session(self.root, self.state, session.identifier, stage='stage2', **kwargs)

    def test_s1_default_remains_numpy_only_and_s2_requires_explicit_exact_profile(self):
        session = self.setup_session()
        old = self.audit(session)
        self.assertTrue(any(reason.startswith('STAGE_SCOPE:') for reason in old['failures']))
        second = self.audit(session, stage2_surfaces=('local_inference', 'numpy_mlp'))
        self.assertFalse(any(reason.startswith(('STAGE_SCOPE:', 'STAGE2_CAMPAIGN_ROLE_ORDER:'))
                             for reason in second['failures']), second)
        self.assertEqual(second['status'], 'FAIL')  # No real execution/telemetry proof was supplied.

    def test_permuted_campaigns_and_arbitrary_profiles_are_rejected(self):
        session = self.setup_session(reverse=True)
        second = self.audit(session, stage2_surfaces=('local_inference', 'numpy_mlp'))
        self.assertTrue(any(reason.startswith('STAGE2_CAMPAIGN_ROLE_ORDER:') for reason in second['failures']))
        invalid = self.audit(session, stage2_surfaces=('numpy_mlp', 'local_inference'))
        self.assertIn('INVALID_STAGE2_SURFACE_SEQUENCE', invalid['failures'])
