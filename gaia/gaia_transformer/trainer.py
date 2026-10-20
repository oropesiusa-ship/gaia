"""Entrenador baseline conocido, sin acceso a corpus ni targets de validación."""
from dataclasses import asdict, dataclass
import hashlib
import os
import random

import numpy as np
import torch

from .model import ModelConfig, GaiaTransformer


@dataclass(frozen=True)
class TrainConfig:
    batch: int = 32
    lr: float = 0.003
    weight_decay: float = 0.01
    clip_norm: float = 1.0


def configure_cuda(seed, max_vram_mb):
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") != ":4096:8":
        raise RuntimeError("Falta CUBLAS_WORKSPACE_CONFIG=:4096:8 antes de importar Torch")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("La baseline requiere exactamente una GPU CUDA visible")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.cuda.set_device(0)
    prop = torch.cuda.get_device_properties(0)
    torch.cuda.set_per_process_memory_fraction(min(1.0, max_vram_mb * 2**20 / prop.total_memory), 0)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def state_digest(model):
    digest = hashlib.sha256()
    for key, tensor in sorted(model.state_dict().items()):
        array = tensor.detach().cpu().contiguous().numpy()
        digest.update(key.encode())
        digest.update(str(array.dtype).encode())
        digest.update(str(array.shape).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


class Trainer:
    def __init__(self, training_records, seed, model_cfg=ModelConfig(), train_cfg=TrainConfig(), device="cuda:0"):
        if (training_records.dtype != np.uint8 or training_records.ndim != 2
                or training_records.shape[1] != model_cfg.context + 1 or len(training_records) == 0):
            raise ValueError("Se requieren registros train uint8 de tamaño context+1")
        self.device = torch.device(device)
        self.cfg = train_cfg
        self.model = GaiaTransformer(model_cfg).to(self.device)
        self.data = torch.tensor(training_records.astype(np.int64), device=self.device)
        self.rng = torch.Generator(device="cpu").manual_seed(seed)
        self.optimizer = torch.optim.AdamW(self.model.parameters(), lr=train_cfg.lr,
                                           weight_decay=train_cfg.weight_decay, foreach=False, fused=False)
        self.steps = 0
        self.losses = []

    def step(self):
        self.model.train()
        idx = torch.randint(len(self.data), (self.cfg.batch,), generator=self.rng).to(self.device)
        rows = self.data[idx]
        _, loss = self.model(rows[:, :-1], rows[:, 1:])
        if not torch.isfinite(loss).item():
            raise RuntimeError("Loss no finita")
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.cfg.clip_norm,
                                       error_if_nonfinite=True, foreach=False)
        self.optimizer.step()
        value = loss.item()
        self.steps += 1
        self.losses.append(value)
        return value

    @torch.inference_mode()
    def predict_last(self, contexts):
        if contexts.ndim != 2 or contexts.shape[1] != self.model.cfg.context or contexts.dtype != np.uint8:
            raise ValueError("Solo se aceptan contextos uint8 B x context")
        mode = self.model.training
        self.model.eval()
        predictions = []
        try:
            for start in range(0, len(contexts), self.cfg.batch):
                x = torch.tensor(contexts[start:start + self.cfg.batch].astype(np.int64), device=self.device)
                logits, _ = self.model(x)
                predictions.append(logits[:, -1, :].cpu().numpy())
            return np.concatenate(predictions)
        finally:
            self.model.train(mode)

    def gradient_digest(self):
        digest = hashlib.sha256()
        for name, parameter in sorted(self.model.named_parameters()):
            if parameter.grad is not None:
                digest.update(name.encode())
                digest.update(parameter.grad.detach().cpu().contiguous().numpy().tobytes())
        return digest.hexdigest()

    def configuration(self):
        return {"model": asdict(self.model.cfg), "training": asdict(self.cfg)}
