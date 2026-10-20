import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gaia import config, engine, genome as G, integrity, mutate, search, stats   # noqa: E402
from gaia.protected import benchmark, evaluator, guard                            # noqa: E402
from gaia.store import Store                                                       # noqa: E402

LIM = {"max_ram_mb": 3000, "max_experiment_seconds": 20, "worker_threads": 1}
BENCH = json.loads(json.dumps(benchmark.DEFAULT_SPEC))
BENCH["calibrated"] = {"main": {"target": 0.70}, "audit": {"target": 0.70}}
TMP = Path(tempfile.mkdtemp(prefix="gaia_test_"))


class TestGuard(unittest.TestCase):
    def test_blocks_dangerous_code(self):
        for bad in ["import os", "from subprocess import run", "x = open('f')",
                    "eval('1')", "a = (1).__class__", "import numpy\nimport socket"]:
            with self.assertRaises(guard.GuardError, msg=bad):
                guard.check_source(bad)

    def test_allows_generated_code(self):
        guard.check_source(G.render(G.new_genome()))


class TestWorkloadState(unittest.TestCase):
    def test_state_directories_are_isolated_and_relative(self):
        root = Path(tempfile.mkdtemp(prefix="gaia_state_"))
        try:
            legacy = Store(root)
            gaia_transformer = Store(root, "state_gaia_transformer_cuda")
            legacy.save_state({"workload": "numpy_mlp"})
            gaia_transformer.save_state({"workload": "gaia_transformer_cuda"})
            self.assertEqual(legacy.load_state()["workload"], "numpy_mlp")
            self.assertEqual(gaia_transformer.load_state()["workload"], "gaia_transformer_cuda")
            self.assertNotEqual(legacy.dir, gaia_transformer.dir)
            integrity.write_manifest(root, gaia_transformer.dir)
            self.assertTrue((gaia_transformer.dir / "manifest.json").exists())
            self.assertFalse((legacy.dir / "manifest.json").exists())
            self.assertEqual(integrity.verify(root, gaia_transformer.dir), [])
            with self.assertRaises(ValueError):
                Store(root, "../outside")
        finally:
            shutil.rmtree(root, ignore_errors=True)


class TestGenome(unittest.TestCase):
    def test_fuzzed_genomes_always_render(self):
        rng = np.random.default_rng(0)
        for _ in range(150):
            g = mutate.random_genome(rng)
            for _ in range(3):
                try:
                    g, _ = mutate.apply(mutate.OP_NAMES[rng.integers(len(mutate.OP_NAMES))], g, rng)
                except ValueError:
                    pass
            G.render(g)

    def test_hash_ignores_inactive_hyperparameters(self):
        a = G.new_genome(hp={"momentum": 0.5})        # sgd no usa momentum
        b = G.new_genome(hp={"momentum": 0.99})
        self.assertEqual(G.genome_hash(a), G.genome_hash(b))

    def test_literal_mutation_and_drop_change_the_code(self):
        base = G.new_genome()
        src0 = G.render(base)
        lit = G.literals(G._base_source(base))[0]
        g = json.loads(json.dumps(base))
        g["lits"][lit["key"]] = 123.5
        self.assertIn("123.5", G.render(g))
        g2 = json.loads(json.dumps(base))
        g2["drops"] = ["loss"]
        self.assertNotEqual(G.render(g2), src0)
        g3 = json.loads(json.dumps(base))
        g3["drops"] = ["nope"]
        with self.assertRaises(ValueError):
            G.render(g3)


class TestEvaluator(unittest.TestCase):
    def test_baseline_reaches_target_and_is_measured_by_parent(self):
        r = evaluator.run_trial(G.render(G.new_genome()), BENCH, "main", 0, 0, 20, LIM, TMP)
        self.assertEqual(r["status"], "ok")
        self.assertTrue(r["reached"])
        self.assertGreater(r["cost_s"], 0)
        self.assertGreater(r["peak_rss_mb"], 10)

    def test_same_seed_is_deterministic_in_quality(self):
        src = G.render(G.new_genome())
        a = evaluator.run_trial(src, BENCH, "main", 3, 3, 20, LIM, TMP, target=2.0, max_batches=300)
        b = evaluator.run_trial(src, BENCH, "main", 3, 3, 20, LIM, TMP, target=2.0, max_batches=300)
        self.assertEqual(a["final_acc"], b["final_acc"])

    def test_cheating_candidate_cannot_see_labels_or_escape(self):
        evil = "import os\nclass Trainer: pass\n"
        r = evaluator.run_trial(evil, BENCH, "main", 0, 0, 5, LIM, TMP)
        self.assertEqual(r["status"], "invalid")

    def test_wrong_output_and_crash_are_errors_not_improvements(self):
        bad = ("import numpy as np\nclass Trainer:\n    def __init__(s,X,y,k,seed): pass\n"
               "    def train(s,n): pass\n    def predict(s,X): return np.zeros((len(X),2))\n")
        r = evaluator.run_trial(bad, BENCH, "main", 0, 0, 5, LIM, TMP)
        self.assertEqual(r["status"], "error")
        self.assertFalse(r["reached"])
        crash = ("class Trainer:\n    def __init__(s,X,y,k,seed): raise RuntimeError('x')\n")
        r = evaluator.run_trial(crash, BENCH, "main", 0, 0, 5, LIM, TMP)
        self.assertEqual(r["status"], "error")

    def test_time_cap_stops_a_slow_candidate(self):
        slow = ("import numpy as np\nclass Trainer:\n    def __init__(s,X,y,k,seed): s.k=k\n"
                "    def train(s,n):\n        for _ in range(n): np.linalg.svd(np.ones((120,120)))\n"
                "    def predict(s,X): return np.zeros(len(X),dtype=np.int64)\n")
        r = evaluator.run_trial(slow, BENCH, "main", 0, 0, 0.3, LIM, TMP)
        self.assertFalse(r["reached"])
        self.assertLess(r["wall_s"], 15)


class TestStats(unittest.TestCase):
    def _runs(self, costs, reached=True, mem=50):
        return [{"cost_s": c, "reached": reached, "peak_rss_mb": mem} for c in costs]

    def test_accepts_clear_gain_rejects_noise(self):
        acc = config.DEFAULTS["acceptance"]
        champ = self._runs([1.0, 1.02, 0.98, 1.01, 0.99])
        self.assertEqual(stats.decide(champ, self._runs([0.6, 0.62, 0.59, 0.61, 0.6]), acc)["decision"], "accepted")
        self.assertEqual(stats.decide(champ, self._runs([1.0, 1.01, 0.99, 1.02, 0.98]), acc)["decision"], "rejected")

    def test_faster_but_less_quality_is_not_better(self):
        acc = config.DEFAULTS["acceptance"]
        champ = self._runs([1.0] * 5)
        cand = self._runs([0.3] * 5)
        cand[0]["reached"] = cand[1]["reached"] = False
        self.assertEqual(stats.decide(champ, cand, acc)["decision"], "rejected")

    def test_memory_tradeoff_goes_to_pareto(self):
        acc = config.DEFAULTS["acceptance"]
        d = stats.decide(self._runs([1.0] * 5), self._runs([0.5, 0.52, 0.5, 0.49, 0.51], mem=200), acc)
        self.assertEqual(d["decision"], "pareto_alternative")


class TestSearchLearns(unittest.TestCase):
    def test_operator_statistics_shift_probability(self):
        rng = np.random.default_rng(0)
        h = search.History()
        base = G.new_genome()
        h.add(base, 1.0, "ok", None, [])
        for _ in range(12):
            h.add(base, 0.5, "ok", 1.0, ["lr"])           # 'lr' siempre ayuda
            h.add(base, None, "ok", 1.0, ["act"])          # 'act' nunca alcanza el objetivo
        w = search.Strategy({}, rng)._op_weights(h)
        names = mutate.OP_NAMES
        self.assertGreater(w[names.index("lr")], 3 * w[names.index("act")])
        w2 = search.Strategy({"learn": False}, rng)._op_weights(h)
        self.assertAlmostEqual(w2[0], w2[-1])

    def test_proposals_are_new_and_valid(self):
        rng = np.random.default_rng(1)
        h = search.History()
        h.add(G.new_genome(), 1.0, "ok", None, [])
        s = search.Strategy({}, rng)
        for _ in range(40):
            g, ops, _, pc = s.propose(h)
            self.assertNotIn(G.genome_hash(g), h.seen)
            G.render(g)
            h.add(g, 1.0, "ok", pc, ops)


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="gaia_root_"))
        shutil.copytree(ROOT / "gaia", self.root / "gaia", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(ROOT / "gaia.py", self.root / "gaia.py")
        self.cfg = config.load(self.root)
        self.cfg["meta"]["enabled"] = False

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _engine(self):
        e = engine.Engine(self.root, self.cfg, log=lambda *a: None)
        # benchmark mínimo para que la prueba sea rápida
        b = json.loads(json.dumps(BENCH))
        b["calibrated"] = {"main": {"target": 0.70, "ref_cost_s": 0.5, "cv": 0.05, "q_ref": 0.71, "ref_costs": []},
                           "audit": {"target": 0.70, "ref_cost_s": 0.5, "cv": 0.05, "q_ref": 0.71, "ref_costs": []}}
        # Keep numerical calibration small, but use real snapshot, manifest,
        # runtime and sandbox verification instead of bypassing prerequisites.
        with patch.object(benchmark, "calibrate", return_value=b):
            e.init(initialize_mvp=True)
        return e

    def test_orphan_experiments_are_marked_aborted_not_valid(self):
        # Historical non-certifiable API stays readable; CPU MVP never repairs
        # orphan ledger events automatically (tested in test_ledger.py).
        historical = Store(self.root, "historical")
        historical.append({"type": "start", "id": "e00001"})
        self.assertEqual(historical.close_orphans(), 1)
        end = [r for r in historical.records() if r["type"] == "end"][0]
        self.assertEqual(end["decision"], "aborted")
        self.assertEqual(historical.close_orphans(), 0)

    def test_recovery_no_reutiliza_ids_y_limpia_tmp(self):
        """Regresión: kill -9 en mitad del experimento 7 con state.json en 6 -> el siguiente es e00008."""
        e = self._engine()
        e.state["n_experiments"] = 6
        e.store.save_state(e.state)
        # A validated completed event at id 7 is the immutable high-water mark.
        from gaia import manifest
        from gaia import readiness
        g, src = e.store.load_version()
        context = e.source_context()
        report = readiness.run_gates(e, genome=g, source=src)
        self.assertEqual(report["status"], "READY_FOR_CAMPAIGN", report)
        e._campaign_context = {key: report[key] for key in ("campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")}
        document = manifest.build_experiment(e, "e00007", context, g, src, g, src)
        directory = e.store.dir / "experiments/e00007"
        manifest.write_manifest(directory / "manifest.json", document)
        manifest.write_manifest(directory / "genome.json", g)
        (directory / "trainer.py").write_text(src)
        e.store.append({"type": "start", "id": "e00007", "genome": g, "source_sha": document["candidate_trainer_hash"],
                        **e._campaign_context,
                        "stable_version": "v0000", "environment_hash": document["environment_hash"],
                        "experiment_manifest_hash": document["manifest_hash"]})
        e.store.append({"type": "end", "id": "e00007", "decision": "aborted", "reason": "controlled interrupt"})
        e.store.tmp.mkdir(parents=True, exist_ok=True)
        (e.store.tmp / "trial_muerto").mkdir()
        (e.store.tmp / "trial_muerto" / "x.bin").write_bytes(b"0" * 1000)
        self.assertEqual(e._recover(), 0)
        self.assertEqual(e.state["n_experiments"], 7)
        self.assertEqual(e.store.load_state()["n_experiments"], 7)
        self.assertEqual(list(e.store.tmp.iterdir()), [])
        self.assertEqual(e._recover(), 0)

    def test_truncated_last_ledger_line_blocks_mvp(self):
        e = self._engine()
        with e.store.ledger.open("a") as f:
            f.write('{"type": "end", "id": ')
        with self.assertRaisesRegex(RuntimeError, "LEDGER_TRUNCATED_OR_PARTIAL"):
            e.store.records()

    def test_integrity_detects_tampering_with_evaluator(self):
        self._engine()
        self.assertEqual(integrity.verify(self.root), [])
        with (self.root / "gaia" / "protected" / "evaluator.py").open("a") as f:
            f.write("\n# manipulado\n")
        self.assertIn("gaia/protected/evaluator.py", integrity.verify(self.root))

    def test_stop_file_has_priority(self):
        e = self._engine()
        (self.root / "STOP").write_text("x")
        self.assertEqual(e.run(until="budget", minutes=5, meta=False), "stopped")
        other = Store(self.root)
        other.lock()
        other.unlock()

    def test_tampered_protected_file_asks_for_human(self):
        e = self._engine()
        with (self.root / "gaia" / "protected" / "task.py").open("a") as f:
            f.write("\n# x\n")
        self.assertEqual(e.run(until="budget", minutes=5, meta=False), "needs_human")
        self.assertTrue((self.root / "NEEDS_HUMAN.md").exists())

    def test_unvalidated_promotion_cannot_bypass_certified_store(self):
        e = self._engine()
        g = G.new_genome(hp={"lr": 0.08})
        with self.assertRaises(ValueError):
            e.store.promote(g, G.render(g), {"x": 1})
        self.assertEqual(e.store.current_version(), "v0000")

    def test_short_autonomous_run_logs_every_experiment(self):
        e = self._engine()
        out = e.run(until="budget", max_experiments=3, minutes=3, meta=False)
        self.assertIn(out, ("budget", "improved", "needs_human"))
        ends = [r for r in e.store.records() if r["type"] == "end"]
        starts = [r for r in e.store.records() if r["type"] == "start"]
        self.assertGreater(len(starts), 0)
        self.assertEqual(len(starts), len(ends))
        self.assertTrue(all("hypothesis" in s and "accept_rule" in s["hypothesis"] for s in starts))


if __name__ == "__main__":
    unittest.main()
