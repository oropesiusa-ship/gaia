"""Second-session coordination fixtures; never execute candidates or inference."""
from unittest.mock import patch
from test_autonomy_integration import Fixture
from gaia.autonomy.lineage import create_lineage
from gaia.autonomy.freeze import freeze
from gaia.autonomy.session import SessionStore, session_contract
from gaia.autonomy.supervisor import Supervisor
from tools import stage2_executor as ex, stage2_runtime as rt
from tools.stage2_session2 import SecondSessionSupervisor, session2_lineages, experiment_process
from gaia.autonomy.catalog import BINDING


class SecondSessionTests(Fixture):
    def test_desktop_workers_are_not_gaia_experiments(self):
        for command in ('gdm-session-worker [pam/gdm-password]',
                        '/usr/libexec/gnome-session-init-worker ubuntu', 'node worker.js'):
            self.assertFalse(experiment_process(command))
        for command in ('python -I /lab/worker.py /work',
                        'python -m gaia.autonomy.regression', 'python gaia.py autonomy-run campaign'):
            self.assertTrue(experiment_process(command))

    def setup_second(self, promotion=False):
        numpy = self.lineage()['lineage_id']
        inference = create_lineage(self.root, self.state,
                                  'IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA')['lineage_id']
        ids = [inference, numpy]
        frozen = freeze(self.root, self.state, ids)
        contract = session_contract(ids, stage='stage2', promotion=promotion,
                                    limits=ex.LIMITS, frozen=frozen)
        store = SessionStore(self.state, contract['session_id'])
        store.create(contract, self.root)
        aggregate = ex.StageBudget(self.root / 'evidence/budget', 'fixture',
                                   [self.root / 'evidence', self.state])
        with aggregate.exclusive():
            aggregate.start_session('first')
            for role, cid in (('S1-C1', 'first-one'), ('S1-C2', 'first-two')):
                aggregate.reserve('first', role)
                aggregate.bind(role, cid)
                aggregate.finish(role, cid, 100)
            aggregate.start_session(store.identifier)
        return ids, store, aggregate

    def supervisor(self, ids, store, aggregate):
        with patch.object(rt, 'vram', return_value={'source': 'UNIT', 'gpus': []}):
            return SecondSessionSupervisor(self.root, self.state, store.identifier,
                                           {}, aggregate, original_numpy=ids[1])

    def test_factual_lineage_order_is_required(self):
        ids, store, aggregate = self.setup_second()
        self.assertEqual(len(session2_lineages(self.state, ids, ids[1])), 2)
        with self.assertRaises(ValueError):
            session2_lineages(self.state, list(reversed(ids)), ids[1])
        with self.assertRaises(ValueError):
            session2_lineages(self.state, ids, ids[0])

    def test_promotion_refused_before_baseline_write(self):
        ids, store, aggregate = self.setup_second(promotion=True)
        with self.assertRaisesRegex(ValueError, 'PROMOTION_FORBIDDEN'):
            self.supervisor(ids, store, aggregate)
        self.assertFalse((store.root / 'evidence/baseline.json').exists())

    def test_c3_then_c4_preserve_aggregate_reservations(self):
        ids, store, aggregate = self.setup_second()
        supervisor = self.supervisor(ids, store, aggregate)
        with aggregate.exclusive(), patch.object(supervisor, 'guard'), \
                patch.object(supervisor, 'locks_free', return_value=True), \
                patch('tools.stage2_session2.ex.qualify_backend'), \
                patch('tools.stage2_session2.numpy_binding', return_value=dict.fromkeys(BINDING, 'fixture') | {'surface': 'numpy_mlp'}), \
                patch.object(Supervisor, 'create_campaign', side_effect=['third', 'fourth']):
            self.assertEqual(supervisor.create_campaign(ids[0], 1800), 'third')
            store.event('CAMPAIGN_STARTED', {'campaign_id': 'third', 'lineage_id': ids[0]})
            store.event('CAMPAIGN_FINISHED', {'campaign_id': 'third', 'wall_s': 100})
            aggregate.finish('S2-C3', 'third', 100)
            self.assertEqual(supervisor.create_campaign(ids[1], 1800), 'fourth')
            view = aggregate.view()
        self.assertEqual(view['reserved_compute_s'], 7200)
        self.assertEqual(view['remaining_compute_s'], 0)
        self.assertEqual(view['bindings']['S2-C3'], 'third')
        self.assertEqual(view['bindings']['S2-C4'], 'fourth')

    def test_wrong_order_and_backend_failure_do_not_reserve(self):
        ids, store, aggregate = self.setup_second()
        supervisor = self.supervisor(ids, store, aggregate)
        before = aggregate.view()
        with aggregate.exclusive(), patch.object(supervisor, 'guard'), \
                patch.object(supervisor, 'locks_free', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'LINEAGE_ORDER'):
                supervisor.create_campaign(ids[1], 1800)
            with patch('tools.stage2_session2.ex.qualify_backend', side_effect=ValueError('BACKEND')):
                with self.assertRaisesRegex(ValueError, 'BACKEND'):
                    supervisor.create_campaign(ids[0], 1800)
        self.assertEqual(aggregate.view(), before)
