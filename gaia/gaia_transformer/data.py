"""Corpus byte-level reproducible sin RNG global, red, reloj ni archivos externos."""
from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class CorpusSpec:
    version: str = "structured_bytes/v1"
    context: int = 64
    train_records: int = 4096
    validation_records: int = 256
    audit_records: int = 256
    train_seed: int = 1701
    validation_seed: int = 2903
    audit_seed: int = 3907

    def __post_init__(self):
        if self.version != "structured_bytes/v1" or self.context != 64:
            raise ValueError("Corpus v1 requiere context=64 y versión conocida")
        counts = (self.train_records, self.validation_records, self.audit_records)
        seeds = (self.train_seed, self.validation_seed, self.audit_seed)
        if any(type(n) is not int or not 0 < n <= 2**20 for n in counts):
            raise ValueError("Número de registros fuera de rango")
        if any(type(s) is not int or not 0 <= s < 2**32 for s in seeds) or len(set(seeds)) != 3:
            raise ValueError("Las semillas de corpus deben ser distintas y uint32")


DEFAULT_SPEC = CorpusSpec()
DOMAINS = {"train": b"T", "validation": b"V", "audit": b"A"}
ALPHABET = b"abcdef0123456789"


def generate_split(spec, split):
    if split not in DOMAINS:
        raise ValueError("Split desconocido: " + split)
    records = []
    for index in range(getattr(spec, split + "_records")):
        seed = getattr(spec, split + "_seed")
        key = f"{spec.version}|{split}|{seed}|{index}".encode("ascii")
        raw = hashlib.sha256(key).digest()
        period = (2, 4, 8)[raw[0] % 3]
        pattern = bytes(ALPHABET[b % len(ALPHABET)] for b in raw[1:1 + period])
        prefix = DOMAINS[split] + f"{index:08x}:".encode("ascii")
        body_size = spec.context + 1 - len(prefix)
        records.append(prefix + (pattern * (body_size // period + 1))[:body_size])
    return b"".join(records)


def manifest(spec=DEFAULT_SPEC):
    parts = {}
    for split in DOMAINS:
        data = generate_split(spec, split)
        parts[split] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                        "records": getattr(spec, split + "_records")}
    payload = {"spec": asdict(spec), "splits": parts, "record_bytes": spec.context + 1,
               "alphabet_hex": ALPHABET.hex(), "domains": {k: v.hex() for k, v in DOMAINS.items()}}
    payload["sha256"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return payload


def records(raw, context=64):
    """Vista uint8 N x (T+1), sin ventanas compartidas entre ejemplos."""
    import numpy as np
    if context != 64 or not raw or len(raw) % (context + 1):
        raise ValueError("Corpus incompleto o context incompatible")
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, context + 1)


def private_validation(raw, context=64):
    rows = records(raw, context)
    # Copias independientes: el array entregado al worker no incluye el byte privado.
    return rows[:, :context].copy(), rows[:, context].copy()
