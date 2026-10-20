"""The campaign candidate budget includes research, including its boundary."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from gaia import config, engine, research


class ResearchBudget(unittest.TestCase):
    def test_cycle_with_no_remaining_candidates_does_not_observe(self):
        eng = SimpleNamespace(state={}, log=lambda *args: None)
        with patch.object(research, "observe") as observe:
            result = research.cycle(eng, max_experiments=0)
        observe.assert_not_called()
        self.assertFalse(result["improved"])

    def test_run_counts_research_and_passes_remaining_budget(self):
        cfg = config.load("/tmp/opencode")
        cfg["meta"]["enabled"] = False
        cfg["research"]["trigger_after"] = 1
        eng = object.__new__(engine.Engine)
        eng.cfg, eng.lim, eng.acc = cfg, cfg["limits"], cfg["acceptance"]
        eng.root, eng.log = "/tmp/opencode", lambda *args: None
        eng.state = {"n_experiments": 0, "since_promotion": 0, "ref": {"cost": 1}}
        eng.bench = {"calibrated": {"main": {"target": 0.5}}}
        eng.store = SimpleNamespace(dir="/tmp/opencode", lock=lambda: None, unlock=lambda: None,
            stop_requested=lambda: False, disk_mb=lambda: 0,
            load_version=lambda: ({}, "source"), current_version=lambda: "v0000",
            save_state=lambda st: None)
        eng.init = eng._load = lambda: None
        eng._recover = lambda: 0
        eng.refresh_ref = lambda src: 1
        calls = []

        def experiment():
            eng.state["n_experiments"] += 1
            eng.state["since_promotion"] += 1
            return "rejected"

        def cycle(deadline, max_experiments):
            calls.append(max_experiments)
            eng.state["n_experiments"] += min(2, max_experiments)
            return {"improved": False}

        eng.experiment, eng.research_cycle = experiment, cycle
        with patch.object(engine.integrity, "verify", return_value=[]), \
                patch("gaia.provenance.prerequisites", return_value={"ok": True, "reasons": []}), \
                patch("gaia.readiness.run_gates", return_value={"status": "READY_FOR_CAMPAIGN"}):
            self.assertEqual(eng.run(until="budget", minutes=5, max_experiments=3, meta=False), "budget")
        self.assertEqual(eng.state["n_experiments"], 3)
        self.assertEqual(calls, [2])


if __name__ == "__main__":
    unittest.main()
