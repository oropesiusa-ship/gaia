"""Tarea sintética: clasificación con un 'profesor' (red tanh fija) + ruido Gumbel.

El evaluador es el único que conoce las etiquetas de validación. El candidato
solo recibe (X_train, y_train) y X_val sin etiquetas.
"""
import numpy as np

_CACHE = {}


def make_dataset(spec, data_seed):
    key = (tuple(sorted(spec.items())), data_seed)
    if key in _CACHE:
        return _CACHE[key]
    d, h, k = spec["d"], spec["teacher_hidden"], spec["k"]
    tr = np.random.default_rng(spec["teacher_seed"])
    W1 = tr.standard_normal((d, h)) / np.sqrt(d)
    W2 = tr.standard_normal((h, k)) * spec["teacher_gain"]
    rng = np.random.default_rng([spec["data_salt"], int(data_seed)])

    def draw(n):
        X = rng.standard_normal((n, d))
        z = np.tanh(X @ W1 * 1.5) @ W2 + spec["noise"] * rng.gumbel(size=(n, k))
        return X, z.argmax(axis=1)

    Xtr, ytr = draw(spec["n_train"])
    Xva, yva = draw(spec["n_val"])
    if len(_CACHE) > 24:
        _CACHE.clear()
    _CACHE[key] = (Xtr, ytr, Xva, yva)
    return _CACHE[key]
