import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from gaia.gaia_transformer import genome as G, research as R
from gaia.gaia_transformer.campaign_store import CampaignStore
from gaia.gaia_transformer.lab.calibration import SPEC
from gaia.gaia_transformer.lab.guard import check_source
from gaia import bootstrap


def pair(a, b, ratio=.8):
    def group(source, cost):
        return [{"status": "ok", "valid": True, "reached": True, "cost_s": cost, "peak_rss_mb": 1500,
                 "peak_vram_nvml_mb": 238, "spec": {"seed": seed}, "candidate_sha256": R.champion_key(source)}
                for seed in SPEC["confirm_seeds"]]
    from gaia.gaia_transformer.lab.calibration import decide
    champion, candidate = group(a, 4.), group(b, 4 * ratio)
    return {"champion": champion, "candidate": candidate, "decision": decide(champion, candidate, SPEC["confirm_seeds"])}


class TestGpuResearch(unittest.TestCase):
    def test_extensions_preserve_baseline_and_are_valid_candidates(self):
        source = G.render(G.BASE)
        self.assertEqual(G.render({**G.BASE, "optimizer_impl": "scalar"}), source)
        self.assertEqual(G.digest({**G.BASE, "optimizer_impl": "scalar"}), G.digest(G.BASE))
        for key in G.RESEARCH_SPACE:
            check_source(G.render({**G.BASE, key: "foreach"}))

    def test_unproven_options_never_enter_search(self):
        for index in range(1, 25):
            candidate, _, _ = G.propose(G.BASE, [], index)
            self.assertNotIn("optimizer_impl", candidate)
            self.assertNotIn("clip_impl", candidate)
        candidate, operator, _ = G.propose(G.BASE, [], 1, unlocked=["optimizer_impl"])
        self.assertEqual(operator, "optimizer_impl")
        self.assertEqual(candidate[operator], "foreach")

    def test_only_supported_matching_evidence_unlocks(self):
        source = G.render(G.BASE)
        candidate = {**G.BASE, "optimizer_impl": "foreach"}
        record = {"type": "research_end", "family": "optimizer_foreach", "champion_sha256": R.champion_key(source),
                  "verdict": "supported", "candidate_genome": candidate, "comparison": pair(source, G.render(candidate))}
        self.assertEqual(R.unlocked_options([record], source), ["optimizer_impl"])
        for key, value in (("verdict", "inconclusive"), ("champion_sha256", "other"), ("comparison", {})):
            self.assertEqual(R.unlocked_options([{**record, key: value}], source), [])
        forged = copy.deepcopy(record)
        forged["comparison"]["candidate"][0]["candidate_sha256"] = "fake"
        self.assertEqual(R.unlocked_options([forged], source), [])

    def test_refuted_families_not_repeated_for_same_champion_and_inconclusive_is_bounded(self):
        source = G.render(G.BASE)
        diagnosis = {"estimated_cost_phase_shares": {"optimizer": .12, "clip": .03}, "instrumentation_overhead_ratio": 1.1}
        record = {"type": "research_end", "family": "optimizer_foreach", "champion_sha256": R.champion_key(source), "verdict": "refuted"}
        self.assertNotIn("optimizer_foreach", [h["family"] for h in R.hypotheses(diagnosis, G.BASE, [record], source)])
        self.assertIn("optimizer_foreach", [h["family"] for h in R.hypotheses(diagnosis, G.BASE, [record], source + "\n")])
        inconclusive = {**record, "verdict": "inconclusive"}
        self.assertNotIn("optimizer_foreach", [h["family"] for h in R.hypotheses(diagnosis, G.BASE, [inconclusive] * 2, source)])

    def test_verdict_distinguishes_support_refutation_and_uncertainty(self):
        a, b = G.render(G.BASE), G.render({**G.BASE, "optimizer_impl": "foreach"})
        self.assertEqual(R.verdict(pair(a, b)), "supported")
        self.assertEqual(R.verdict(pair(a, b, 1.1)), "refuted")
        inconclusive = pair(a, b)
        inconclusive["decision"] = {"decision": "deferred", "lower95": .85}
        self.assertEqual(R.verdict(inconclusive), "inconclusive")

    def test_plateau_trigger_excludes_aborts_and_is_not_repeated_every_experiment(self):
        source = G.render(G.BASE)
        records = [{"type": "end", "decision": "rejected"}] * 2 + [{"type": "end", "decision": "aborted"}] * 5
        self.assertTrue(R.should_trigger(records, source, after=2)[0])
        self.assertFalse(R.should_trigger(records, source, after=40)[0])
        records.append({"type": "research_trigger", "champion_sha256": R.champion_key(source), "completed": 2})
        self.assertFalse(R.should_trigger(records, source, after=2)[0])

    def test_cycle_prunes_low_amdahl_family_records_evidence_and_never_promotes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = CampaignStore(root, "state_gpu")
            source = G.render(G.BASE)
            store.publish(dict(G.BASE), source, {"type": "baseline"}, allow_baseline=True)
            class Lab:
                calls = 0
                def trial(self, candidate, seed):
                    self.calls += 1
                    return pair(candidate, candidate)["champion"][0]
                def paired(self, a, b, seeds):
                    self.calls += 10
                    return pair(a, b)
            lab = Lab()
            observed = {"estimated_cost_phase_shares": {"optimizer": .12, "clip": .03}, "instrumentation_overhead_ratio": 1.1}
            def observe(args, report, **kwargs):
                report["diagnosis"] = observed
            with patch.object(R.observation, "run", side_effect=observe), patch.object(R.benchmark_state, "load"), \
                    patch.object(store, "publish", side_effect=AssertionError("Modo B no puede publicar")):
                result = R.cycle(store, {}, {}, {}, root / "research", root / "bootstrap.json", lab, time.monotonic() + 600)
                self.assertEqual(result["unlocked_after"], ["optimizer_impl"])
                self.assertEqual(lab.calls, 12)
                self.assertEqual(store.current_version(), "v0000")
                prior_calls = lab.calls
                with patch.object(R.observation, "run", side_effect=AssertionError("No debe repetir familias resueltas")):
                    again = R.cycle(store, {}, {}, {}, root / "again", root / "bootstrap.json", lab, time.monotonic() + 600)
                self.assertEqual(again["hypotheses"], [])
                self.assertEqual(lab.calls, prior_calls)

    def test_cli_reports_complete_only_for_successful_research(self):
        for status, expected in (("GPU_RESEARCH_COMPLETE", 0), ("FAILED", 40)):
            with tempfile.TemporaryDirectory() as tmp:
                def provision(session, requested, **kwargs):
                    self.assertEqual(requested, "gaia-transformer-cuda-pascal")
                    self.assertFalse(kwargs["prepare"])
                    return Path("/managed/python"), {"GAIA_LOCAL_CONFIG": "/managed/config.json"}
                def command(session, stage, *args, **kwargs):
                    return json.dumps({"status": status})
                with patch.object(bootstrap, "provision", side_effect=provision), patch.object(bootstrap.Session, "command", new=command):
                    self.assertEqual(bootstrap.dispatch(Path(tmp), ["gaia-transformer-research"]), expected)


if __name__ == "__main__":
    unittest.main()
