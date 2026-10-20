"""Pruebas CPU/CUDA del modelo; Torch es opcional en la suite NumPy."""
import importlib.util
import os
import unittest

import numpy as np

HAS_TORCH = importlib.util.find_spec("torch") is not None
if HAS_TORCH:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    from gaia.gaia_transformer.model import ModelConfig, GaiaTransformer
    from gaia.gaia_transformer.trainer import Trainer, state_digest


@unittest.skipUnless(HAS_TORCH, "Torch no está instalado en el perfil NumPy")
class TestGaiaTransformerModel(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        torch.manual_seed(7)
        torch.use_deterministic_algorithms(True)
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        self.cfg = ModelConfig(dim=32, layers=2, heads=2, context=64)

    def test_shapes_tied_weights_and_finite_backward(self):
        model = GaiaTransformer(self.cfg)
        tokens = torch.randint(256, (2, 16))
        logits, loss = model(tokens, tokens)
        self.assertEqual(logits.shape, (2, 16, 256))
        self.assertIs(model.head.weight, model.token.weight)
        loss.backward()
        self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters()))

    def assert_causal(self, device):
        model = GaiaTransformer(self.cfg).to(device).eval()
        before = torch.randint(256, (2, 16), device=device)
        changed = before.clone()
        changed[:, 8:] = (changed[:, 8:] + 17) % 256
        with torch.inference_mode():
            a, _ = model(before)
            b, _ = model(changed)
        torch.testing.assert_close(a[:, :8], b[:, :8], rtol=0, atol=0)
        self.assertFalse(torch.equal(a[:, 8:], b[:, 8:]))

    def test_future_tokens_cannot_change_prefix_cpu(self):
        self.assert_causal("cpu")

    def test_targets_only_affect_loss_not_logits(self):
        model = GaiaTransformer(self.cfg).eval()
        tokens = torch.randint(256, (2, 16))
        with torch.inference_mode():
            a, loss_a = model(tokens, torch.zeros_like(tokens))
            b, loss_b = model(tokens, torch.full_like(tokens, 255))
        torch.testing.assert_close(a, b, rtol=0, atol=0)
        self.assertNotEqual(loss_a.item(), loss_b.item())

    def test_future_tokens_cannot_change_prefix_cuda(self):
        if not torch.cuda.is_available():
            self.skipTest("Sin CUDA")
        self.assert_causal("cuda:0")

    def test_shapes_and_configuration_fail_explicitly(self):
        with self.assertRaises(ValueError):
            ModelConfig(dim=63, heads=2)
        model = GaiaTransformer(self.cfg)
        with self.assertRaises(ValueError):
            model(torch.zeros((2, 65), dtype=torch.long))
        with self.assertRaises(ValueError):
            model(torch.zeros((2, 8)))

    def test_same_seed_initializes_identical_models(self):
        a = state_digest(GaiaTransformer(self.cfg))
        torch.manual_seed(7)
        self.assertEqual(a, state_digest(GaiaTransformer(self.cfg)))
        torch.manual_seed(8)
        self.assertNotEqual(a, state_digest(GaiaTransformer(self.cfg)))

    def test_predict_only_consumes_contexts_and_preserves_training_mode(self):
        rows = np.tile(np.arange(65, dtype=np.uint8), (8, 1))
        trainer = Trainer(rows, 7, self.cfg, device="cpu")
        trainer.step()
        before = state_digest(trainer.model)
        self.assertTrue(trainer.model.training)
        predictions = trainer.predict_last(rows[:, :64])
        self.assertEqual(predictions.shape, (8, 256))
        self.assertEqual(predictions.dtype, np.float32)
        self.assertTrue(trainer.model.training)
        self.assertEqual(before, state_digest(trainer.model))
        with self.assertRaises(ValueError):
            trainer.predict_last(rows)

    def test_rendered_candidate_runs_with_changed_architecture_and_sgd(self):
        from gaia.gaia_transformer import genome as G
        from types import ModuleType
        import sys
        module = ModuleType("gaia_candidate_model_test")
        sys.modules[module.__name__] = module
        try:
            g = {**G.BASE, "dim": 32, "layers": 1, "heads": 4, "batch": 16, "optimizer": "sgd"}
            exec(compile(G.render(g), "<known-candidate>", "exec"), module.__dict__)
            rows = np.tile(np.arange(65, dtype=np.uint8), (16, 1))
            candidate = module.Candidate(rows, 7, device="cpu")
            candidate.train(1)
            self.assertEqual(candidate.model.cfg.dim, 32)
            self.assertEqual(candidate.model.cfg.layers, 1)
            self.assertIsInstance(candidate.optimizer, torch.optim.SGD)
            self.assertEqual(candidate.predict(rows[:, :64]).shape, (16, 256))
        finally:
            sys.modules.pop(module.__name__, None)

    def test_research_foreach_options_train_and_predict(self):
        from gaia.gaia_transformer import genome as G
        from types import ModuleType
        import sys
        module = ModuleType("gaia_candidate_foreach_test")
        sys.modules[module.__name__] = module
        try:
            g = {**G.BASE, "optimizer_impl": "foreach", "clip_impl": "foreach"}
            exec(compile(G.render(g), "<research-candidate>", "exec"), module.__dict__)
            rows = np.tile(np.arange(65, dtype=np.uint8), (16, 1))
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            candidate = module.Candidate(rows, 7, device=device)
            candidate.train(2)
            self.assertTrue(candidate.optimizer.defaults["foreach"])
            self.assertEqual(candidate.predict(rows[:, :64]).shape, (16, 256))
            self.assertTrue(np.isfinite(candidate.losses).all())
        finally:
            sys.modules.pop(module.__name__, None)


if __name__ == "__main__":
    unittest.main()
