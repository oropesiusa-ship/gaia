import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from gaia.gaia_transformer import genome as G
from gaia.gaia_transformer.campaign_store import CampaignStore
from gaia.gaia_transformer.lab.calibration import SPEC
from gaia.gaia_transformer.lab.guard import check_source


class TestGpuGenome(unittest.TestCase):
    def test_all_single_component_variants_render(self):
        for key, values in G.SPACE.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    check_source(G.render({**G.BASE, key: value}))

    def test_proposals_are_reproducible_and_history_updates_operator_statistics(self):
        g, op, hypothesis = G.propose(G.BASE, [], 1)
        self.assertEqual((g, op, hypothesis), G.propose(G.BASE, [], 1))
        self.assertNotEqual(G.digest(g), G.digest(G.BASE))
        records = [{"type": "end", "id": "e00001", "operator": op, "decision": "accepted", "genome_sha256": G.digest(g)}]
        self.assertEqual(G.operator_stats(records)[op]["reward"], 1)
        self.assertNotEqual(G.digest(G.propose(G.BASE, records, 2)[0]), G.digest(g))

    def test_invalid_genome_and_half_precision_are_not_exposed(self):
        with self.assertRaises(ValueError):
            G.render({**G.BASE, "dim": 63})
        with self.assertRaises(ValueError):
            G.render({**G.BASE, "dtype": "fp16"})


class TestGpuCampaignStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CampaignStore(Path(self.tmp.name), "state_gpu")
        self.store.publish(dict(G.BASE), G.render(G.BASE), {"type": "baseline"}, allow_baseline=True)

    def tearDown(self):
        self.tmp.cleanup()

    def evidence(self, accepted=True):
        def group(cost, source):
            return [{"status": "ok", "valid": True, "reached": True, "cost_s": cost,
                     "peak_rss_mb": 1500, "peak_vram_nvml_mb": 238, "spec": {"seed": seed},
                     "candidate_sha256": hashlib.sha256(source.encode()).hexdigest()}
                    for seed in SPEC["confirm_seeds"]]
        return {"experiment_id": "e00001", "parent": "v0000", "comparison": {"confirmation": {
            "champion": group(4.0, G.render(G.BASE)),
            "candidate": group(3.0 if accepted else 5.0, G.render({**G.BASE, "lr": .006}))}}}

    def test_rejected_or_forged_source_cannot_replace_champion(self):
        g = {**G.BASE, "lr": .006}
        with self.assertRaises(ValueError):
            self.store.publish(g, G.render(g), self.evidence(False))
        with self.assertRaises(ValueError):
            self.store.publish(g, "not matching", self.evidence())
        fabricated = self.evidence()
        fabricated["comparison"]["confirmation"]["candidate"][0]["candidate_sha256"] = "other-source"
        with self.assertRaises(ValueError):
            self.store.publish(g, G.render(g), fabricated)
        self.assertEqual(self.store.current_version(), "v0000")

    def test_complete_publication_and_rollback(self):
        g = {**G.BASE, "lr": .006}
        self.assertEqual(self.store.publish(g, G.render(g), self.evidence()), "v0001")
        self.store.verify_versions()
        self.assertEqual(self.store.rollback(), "v0000")

    def test_interrupted_start_is_aborted_and_id_not_reused(self):
        self.store.append({"type": "start", "id": "e00007", "operator": "lr"})
        recovered, next_id = self.store.recover()
        self.assertEqual((recovered, next_id), (1, 8))
        self.assertEqual(self.store.records()[-1]["decision"], "aborted")
        self.assertEqual(self.store.recover(), (0, 8))

    def test_interruption_after_current_commit_recovers_accepted_not_aborted(self):
        self.store.append({"type": "start", "id": "e00001", "operator": "lr"})
        g = {**G.BASE, "lr": .006}
        self.store.publish(g, G.render(g), self.evidence())
        self.assertEqual(self.store.recover(), (1, 2))
        self.assertEqual(self.store.records()[-1]["decision"], "accepted")

    def test_partial_version_and_partial_ledger_do_not_corrupt_future_records(self):
        pending = self.store.stable / ".pending-interrupted"
        pending.mkdir()
        (pending / "trainer.py").write_text("partial")
        self.store.ledger.write_text('{"type":"start","id":')
        self.store.append({"type": "note", "reason": "recovered"})
        self.store.recover()
        self.assertFalse(pending.exists())
        self.assertEqual(self.store.records()[-1]["type"], "note")

    def test_recovery_removes_only_owned_trial_temporary_directories(self):
        self.store.tmp.mkdir()
        owned = self.store.tmp / "gaia-gpu-interrupted"
        owned.mkdir()
        (owned / "candidate.py").write_text("partial candidate")
        unrelated = self.store.tmp / "user-work"
        unrelated.mkdir()
        self.store.recover()
        self.assertFalse(owned.exists())
        self.assertTrue(unrelated.exists())

    def test_modified_stable_source_fails_integrity(self):
        (self.store.stable / "v0000/trainer.py").write_text("changed")
        with self.assertRaises(RuntimeError):
            self.store.recover()


if __name__ == "__main__":
    unittest.main()
