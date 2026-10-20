"""GaiaTransformer fp32 con atención causal explícita; no depende de kernels Flash/SDPA."""
from dataclasses import dataclass
import math

import torch
from torch import nn
from torch.nn import functional as F


@dataclass(frozen=True)
class ModelConfig:
    dim: int = 64
    layers: int = 2
    heads: int = 2
    context: int = 64
    dropout: float = 0.0

    def __post_init__(self):
        if any(type(n) is not int or n <= 0 for n in (self.dim, self.layers, self.heads, self.context)):
            raise ValueError("Dimensiones deben ser enteros positivos")
        if self.dim % self.heads or not 0 <= self.dropout < 1:
            raise ValueError("Configuración de heads/dropout inválida")


class CausalAttention(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.heads = cfg.heads
        self.qkv = nn.Linear(cfg.dim, 3 * cfg.dim)
        self.proj = nn.Linear(cfg.dim, cfg.dim)
        self.dropout = nn.Dropout(cfg.dropout)
        self.register_buffer("causal", torch.ones(cfg.context, cfg.context, dtype=torch.bool).tril())

    def forward(self, x):
        b, t, d = x.shape
        q, k, v = self.qkv(x).chunk(3, dim=-1)
        q, k, v = [a.reshape(b, t, self.heads, d // self.heads).transpose(1, 2) for a in (q, k, v)]
        score = (q @ k.transpose(-2, -1)) / math.sqrt(d // self.heads)
        score = score.masked_fill(~self.causal[:t, :t], float("-inf"))
        weights = self.dropout(F.softmax(score, dim=-1))
        out = (weights @ v).transpose(1, 2).contiguous().reshape(b, t, d)
        return self.dropout(self.proj(out))


class Block(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.norm1 = nn.LayerNorm(cfg.dim)
        self.attention = CausalAttention(cfg)
        self.norm2 = nn.LayerNorm(cfg.dim)
        self.mlp = nn.Sequential(nn.Linear(cfg.dim, 4 * cfg.dim), nn.GELU(),
                                 nn.Linear(4 * cfg.dim, cfg.dim), nn.Dropout(cfg.dropout))

    def forward(self, x):
        x = x + self.attention(self.norm1(x))
        return x + self.mlp(self.norm2(x))


class GaiaTransformer(nn.Module):
    def __init__(self, cfg=ModelConfig()):
        super().__init__()
        self.cfg = cfg
        self.token = nn.Embedding(256, cfg.dim)
        self.position = nn.Embedding(cfg.context, cfg.dim)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.layers))
        self.norm = nn.LayerNorm(cfg.dim)
        self.head = nn.Linear(cfg.dim, 256, bias=False)
        self.apply(self._init)
        self.head.weight = self.token.weight

    @staticmethod
    def _init(module):
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if isinstance(module, nn.Linear) and module.bias is not None:
                nn.init.zeros_(module.bias)

    def forward(self, tokens, targets=None):
        if tokens.ndim != 2 or not 0 < tokens.shape[1] <= self.cfg.context:
            raise ValueError("tokens debe tener forma B x T con 0 < T <= context")
        if tokens.dtype not in (torch.int32, torch.int64):
            raise ValueError("tokens debe contener índices enteros")
        if targets is not None and targets.shape != tokens.shape:
            raise ValueError("targets de entrenamiento debe tener la misma forma que tokens")
        positions = torch.arange(tokens.shape[1], device=tokens.device)
        x = self.token(tokens) + self.position(positions)[None, :, :]
        for block in self.blocks:
            x = block(x)
        logits = self.head(self.norm(x))
        loss = None if targets is None else F.cross_entropy(logits.reshape(-1, 256), targets.reshape(-1))
        return logits, loss
