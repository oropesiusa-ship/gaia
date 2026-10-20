"""Tests de Modo B (Research Engine), puertas G0-G5 y handshake de runtime."""
import json
import tempfile
import unittest
from pathlib import Path

from gaia import genome as G
from gaia import mutate, readiness, research, snippets
from gaia.protected import evaluator, runtime
import numpy as np


class FakeEng:
    """Solo lo que usan select/infer/diagnose-sin-laboratorio."""
    cfg = {"research": {"min_expected_gain": 0.05, "max_hypotheses": 4}}

    def __init__(self, recs=()):
        self.recs = list(recs)
        self.store = type("S", (), {"records": lambda s: self.recs})()


class TestRuntime(unittest.TestCase):
    def test_fingerprint_estable_y_diff(self):
        a, b = runtime.fingerprint(), runtime.fingerprint()
        self.assertEqual(runtime.digest(a), runtime.digest(b))
        b["numpy"] = "0.0"
        self.assertIn("numpy", runtime.diff(a, b))

    def test_worker_mismatch_bloquea_trial(self):
        import gaia.protected.evaluator as ev
        real = runtime.fingerprint
        try:
            ev.runtime.fingerprint = lambda with_torch=False: {**real(with_torch), "torch": "otro"}
            from gaia.protected import benchmark
            r = ev.run_trial(G.render(G.new_genome()), json.loads(json.dumps(benchmark.DEFAULT_SPEC)), "main",
                             0, 0, 1e9, {"max_ram_mb": 2000, "max_experiment_seconds": 30, "worker_threads": 1},
                             tempfile.mkdtemp(), target=2.0, max_batches=50)
        finally:
            ev.runtime.fingerprint = real
        self.assertNotEqual(r["status"], "ok")
        self.assertIn("WORKER_RUNTIME_MISMATCH", r["error"])


class TestArquitecturaGPU(unittest.TestCase):
    def test_pascal_con_torch_cu126_si_y_cu130_no(self):
        cu126 = ["sm_50", "sm_60", "sm_70", "sm_75", "sm_80", "sm_86", "sm_90"]
        cu130 = ["sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120"]
        self.assertTrue(runtime.arch_supports(cu126, [6, 1]))
        self.assertFalse(runtime.arch_supports(cu130, [6, 1]))
        self.assertTrue(runtime.arch_supports(cu130, [7, 5]))
        self.assertFalse(runtime.arch_supports(["sm_80"], [7, 5]))
        self.assertFalse(runtime.arch_supports([], [6, 1]))


class TestLimitador(unittest.TestCase):
    def _as(self, as_limit):
        import subprocess, sys
        p = subprocess.run([sys.executable, "-c", "import resource;print(resource.getrlimit(resource.RLIMIT_AS)[0])"],
                           capture_output=True, text=True, preexec_fn=evaluator._limiter(100, 10, as_limit=as_limit))
        return int(p.stdout.strip())

    def test_as_limit_se_aplica_salvo_modo_torch(self):
        self.assertEqual(self._as(True), 100 * 2**20)
        self.assertEqual(self._as(False), -1)          # RLIM_INFINITY

    def test_modo_torch_por_entorno(self):
        import os
        os.environ["GAIA_FP_TORCH"] = "1"
        try:
            self.assertTrue(evaluator._torch_mode())
        finally:
            os.environ.pop("GAIA_FP_TORCH")
        self.assertFalse(evaluator._torch_mode())


class TestHuellaPadreWorker(unittest.TestCase):
    def test_huella_padre_usa_mismo_criterio_que_worker(self):
        import os, subprocess, sys
        os.environ["GAIA_FP_TORCH"] = "1"
        try:
            parent = runtime.digest(readiness.runtime_fp())
            code = ("import sys,importlib.util;sys.path.insert(0,'gaia/protected');import runtime;"
                    "print(runtime.digest(runtime.fingerprint(with_torch=True)))")
            w = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True,
                               env={"PATH": os.environ["PATH"]}).stdout.strip()
            self.assertIn("torch", readiness.runtime_fp())
        finally:
            os.environ.pop("GAIA_FP_TORCH")
        self.assertEqual(parent, w)
        self.assertNotIn("torch", {k for k, v in readiness.runtime_fp().items() if v})


class TestSearchSpace(unittest.TestCase):
    def test_opcion_research_only_bloqueada_hasta_unlock(self):
        snippets.set_unlocked([])
        rng = np.random.default_rng(0)
        for _ in range(300):
            self.assertNotEqual(mutate.random_genome(rng)["slots"]["sampler"], "shuffled_slices")
        snippets.set_unlocked([["sampler", "shuffled_slices"]])
        seen = {mutate.random_genome(rng)["slots"]["sampler"] for _ in range(300)}
        snippets.set_unlocked([])
        self.assertIn("shuffled_slices", seen)

    def test_opcion_research_se_puede_renderizar(self):
        compile(G.render(G.new_genome(slots={"sampler": "shuffled_slices"})), "x", "exec")

    def test_gradientes_todas_las_opciones(self):
        self.assertTrue(readiness.g1_correctness()["ok"])


class TestInferencia(unittest.TestCase):
    def end(self, **k):
        return {"reason": "r", "id": "e1", **k}

    def test_veredictos(self):
        c = {"ratio": 0.8, "ratio_upper95": 0.9}
        self.assertEqual(research.infer("accepted", self.end(confirm=c))[0], "supported")
        self.assertEqual(research.infer("deferred", self.end(confirm=c))[0], "inconclusive")
        self.assertEqual(research.infer("rejected", self.end(confirm={"ratio": 1.0, "ratio_upper95": 1.1}))[0], "refuted")
        self.assertEqual(research.infer("rejected", self.end(screen={"reached": True}))[0], "refuted_screen")
        self.assertEqual(research.infer("rejected", self.end(screen={"reached": False}))[0], "inconclusive")

    def test_sorpresa_si_supera_la_cota(self):
        c = {"ratio": 0.7, "ratio_upper95": 0.8}
        _, why = research.infer("accepted", self.end(confirm=c), {"upper_bound": 0.08})
        self.assertIn("SORPRESA", why)


class TestSeleccion(unittest.TestCase):
    def hyp(self, hid, fam, kind, ub):
        return {"id": hid, "family": fam, "kind": kind, "upper_bound": ub}

    def test_poda_amdahl_sin_gastar_experimento(self):
        eng = FakeEng()
        keep, drop = research.select(eng, [self.hyp("a", "f1", "implementation", 0.02),
                                           self.hyp("b", "f2", "implementation", 0.30)], "v0000")
        self.assertEqual([h["id"] for h in keep], ["b"])
        self.assertIn("Amdahl", drop[0][1])

    def test_no_repite_refutada_en_mismo_campeon_pero_si_en_otro(self):
        eng = FakeEng([{"type": "research_result", "family": "f2", "champion": "v0000", "status": "refuted"}])
        h = [self.hyp("b", "f2", "implementation", 0.3)]
        self.assertEqual(research.select(eng, h, "v0000")[0], [])
        self.assertEqual(len(research.select(eng, h, "v0001")[0]), 1)

    def test_prior_aprende_de_resultados(self):
        eng = FakeEng([{"type": "research_result", "family": "f", "status": "refuted"}] * 3)
        self.assertLess(research.priors(eng)["f"], 0.5)


class TestPuertas(unittest.TestCase):
    def test_identidad_detecta_cambio_de_config(self):
        from gaia import config
        c = config.load(Path(tempfile.mkdtemp()))
        h1 = readiness.config_hash(c)
        c["limits"]["max_total_minutes"] += 1
        self.assertNotEqual(h1, readiness.config_hash(c))


if __name__ == "__main__":
    unittest.main()
