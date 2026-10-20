"""Biblioteca de componentes del entrenador (el 'genoma de código' de GAIA).

Cada opción de cada 'slot' es una técnica CONOCIDA: si GAIA la elige no cuenta
como descubrimiento autónomo (procedencia 'known').  Las líneas marcadas con
`# @opt:<id>` pueden ser eliminadas por el operador `drop` y las constantes
float pueden ser mutadas por el operador `lit` (procedencia 'generated').
"""

TEMPLATE = '''import math
import numpy as np

HP = __HP__
DT = np.__DTYPE__

__SLOT_act__

__SLOT_sampler__

__SLOT_backward__

__SLOT_optimizer__


def lr_at(t):
    lr = HP["lr"]
    w = HP["warm"]
    if w and t < w:
        lr = lr * (t + 1) / w
    if HP["sched"] == "cosine":
        frac = min(1.0, t / HP["horizon"])
        lr = lr * (0.1 + 0.9 * 0.5 * (1.0 + math.cos(math.pi * frac)))
    return lr


def clip_grads(grads):
    c = HP["clip"]
    if c <= 0:
        return grads
    n = math.sqrt(sum(float((g * g).sum()) for g in grads))
    if n > c:
        s = c / (n + 1e-6)
        grads = [g * s for g in grads]
    return grads


class Trainer:
    def __init__(self, Xtr, ytr, n_classes, seed):
        rng = np.random.default_rng(seed)
        self.X = np.ascontiguousarray(Xtr, dtype=DT)
        self.y = np.asarray(ytr, dtype=np.int64)
        self.k = n_classes
        dims = [self.X.shape[1]] + [HP["hidden"]] * HP["depth"] + [n_classes]
        W, b = [], []
        for i in range(len(dims) - 1):
            s = HP["init_scale"] * math.sqrt(2.0 / dims[i])
            W.append((rng.standard_normal((dims[i], dims[i + 1])) * s).astype(DT))
            b.append(np.zeros(dims[i + 1], dtype=DT))
        self.W, self.b = W, b
        self.opt = Opt(W + b)
        self.X, self.y = reorder(self.X, self.y, rng)
        self.next_idx = make_sampler(len(self.X), HP["batch"], rng)
        self.t = 0

    def train(self, n_batches):
        for _ in range(n_batches):
            idx = self.next_idx()
            xb = self.X[idx]
            yb = self.y[idx]
            loss, gW, gb = forward_backward(self.W, self.b, xb, yb, self.k)
            grads = gW + gb
            grads = clip_grads(grads)  # @opt:clip
            self.opt.step(self.W + self.b, grads, lr_at(self.t))
            self.t += 1

    def predict(self, X):
        h = np.asarray(X, dtype=DT)
        last = len(self.W) - 1
        for i in range(last + 1):
            z = h @ self.W[i] + self.b[i]
            h = act(z) if i < last else z
        return np.argmax(h, axis=1)
'''

SLOTS = {}
SLOTS["dtype"] = {"float64": "", "float32": ""}   # solo selecciona np.<dtype>

SLOTS["act"] = {
"relu": '''def act(z):
    return np.maximum(z, 0.0)


def dact(z, a):
    return (z > 0).astype(z.dtype)
''',
"tanh": '''def act(z):
    return np.tanh(z)


def dact(z, a):
    return 1.0 - a * a
''',
"leaky": '''def act(z):
    return np.where(z > 0, z, 0.01 * z)


def dact(z, a):
    return np.where(z > 0, 1.0, 0.01).astype(z.dtype)
''',
"gelu": '''def act(z):
    return 0.5 * z * (1.0 + np.tanh(0.79788456 * (z + 0.044715 * z ** 3)))


def dact(z, a):
    u = 0.79788456 * (z + 0.044715 * z ** 3)
    t = np.tanh(u)
    return 0.5 * (1.0 + t) + 0.5 * z * (1.0 - t * t) * 0.79788456 * (1.0 + 3.0 * 0.044715 * z * z)
''',
}

SLOTS["sampler"] = {
"randint": '''def reorder(X, y, rng):
    return X, y


def make_sampler(n, batch, rng):
    def nxt():
        return rng.integers(0, n, batch)
    return nxt
''',
"permutation": '''def reorder(X, y, rng):
    return X, y


def make_sampler(n, batch, rng):
    st = {"perm": rng.permutation(n), "pos": 0}

    def nxt():
        if st["pos"] + batch > n:
            st["perm"] = rng.permutation(n)
            st["pos"] = 0
        i = st["pos"]
        st["pos"] += batch
        return st["perm"][i:i + batch]
    return nxt
''',
"shuffled_slices": '''def reorder(X, y, rng):
    p = rng.permutation(len(X))
    return np.ascontiguousarray(X[p]), y[p]


def make_sampler(n, batch, rng):
    st = {"pos": 0}

    def nxt():
        if st["pos"] + batch > n:
            st["pos"] = 0
        i = st["pos"]
        st["pos"] += batch
        return slice(i, i + batch)
    return nxt
''',
}

_FWD = '''    hs = [xb]
    zs = []
    h = xb
    L = len(W)
    for i in range(L - 1):
        z = h @ W[i] + b[i]
        zs.append(z)
        h = act(z)
        hs.append(h)
    logits = h @ W[L - 1] + b[L - 1]
    B = xb.shape[0]
'''
_BWD = '''    gW = [None] * L
    gb = [None] * L
    for i in range(L - 1, -1, -1):
        gW[i] = hs[i].T @ d
        gb[i] = d.sum(axis=0)
        if i > 0:
            d = (d @ W[i].T) * dact(zs[i - 1], hs[i])
    return loss, gW, gb
'''
SLOTS["backward"] = {
"naive": "def forward_backward(W, b, xb, yb, k):\n" + _FWD + '''    m = logits.max(axis=1, keepdims=True)
    e = np.exp(logits - m)
    p = e / e.sum(axis=1, keepdims=True)
    loss = 0.0
    loss = -np.log(p[np.arange(B), yb] + 1e-12).mean()  # @opt:loss
    onehot = np.zeros_like(p)
    onehot[np.arange(B), yb] = 1.0
    d = (p - onehot) / B
''' + _BWD,
"fused": "def forward_backward(W, b, xb, yb, k):\n" + _FWD + '''    logits -= logits.max(axis=1, keepdims=True)
    np.exp(logits, out=logits)
    logits /= logits.sum(axis=1, keepdims=True)
    p = logits
    loss = 0.0
    loss = -np.log(p[np.arange(B), yb] + 1e-12).mean()  # @opt:loss
    p[np.arange(B), yb] -= 1.0
    p *= 1.0 / B
    d = p
''' + _BWD,
}

SLOTS["optimizer"] = {
"sgd": '''class Opt:
    def __init__(self, params):
        pass

    def step(self, params, grads, lr):
        for p, g in zip(params, grads):
            g = g + HP["wd"] * p  # @opt:wd
            p -= lr * g
''',
"momentum": '''class Opt:
    def __init__(self, params):
        self.v = [np.zeros_like(p) for p in params]

    def step(self, params, grads, lr):
        mu = HP["momentum"]
        for p, g, v in zip(params, grads, self.v):
            g = g + HP["wd"] * p  # @opt:wd
            v *= mu
            v += g
            p -= lr * v
''',
"adam": '''class Opt:
    def __init__(self, params):
        self.m = [np.zeros_like(p) for p in params]
        self.v = [np.zeros_like(p) for p in params]
        self.t = 0

    def step(self, params, grads, lr):
        self.t += 1
        b1 = HP["beta1"]
        b2 = HP["beta2"]
        c1 = 1.0 - b1 ** self.t
        c2 = 1.0 - b2 ** self.t
        for p, g, m, v in zip(params, grads, self.m, self.v):
            g = g + HP["wd"] * p  # @opt:wd
            m[:] = b1 * m + (1.0 - b1) * g
            v[:] = b2 * v + (1.0 - b2) * g * g
            p -= lr * (m / c1) / (np.sqrt(v / c2) + 1e-8)
''',
"adam_inplace": '''class Opt:
    def __init__(self, params):
        self.m = [np.zeros_like(p) for p in params]
        self.v = [np.zeros_like(p) for p in params]
        self.tmp = [np.zeros_like(p) for p in params]
        self.t = 0

    def step(self, params, grads, lr):
        self.t += 1
        b1 = HP["beta1"]
        b2 = HP["beta2"]
        c1 = 1.0 - b1 ** self.t
        c2 = math.sqrt(1.0 - b2 ** self.t)
        step = lr / c1
        for p, g, m, v, tmp in zip(params, grads, self.m, self.v, self.tmp):
            g = g + HP["wd"] * p  # @opt:wd
            m *= b1
            m += (1.0 - b1) * g
            v *= b2
            v += (1.0 - b2) * g * g
            np.sqrt(v, out=tmp)
            tmp /= c2
            tmp += 1e-8
            np.divide(m, tmp, out=tmp)
            tmp *= step
            p -= tmp
''',
}

# Etiquetas para informes: ¿es una técnica conocida?
KNOWN_NOTES = {
    "dtype:float32": "precisión simple (técnica conocida)",
    "optimizer:adam": "Adam (técnica conocida)",
    "optimizer:momentum": "momentum (técnica conocida)",
    "optimizer:adam_inplace": "Adam con operaciones in-place (técnica conocida)",
    "backward:fused": "softmax/gradiente fusionado in-place (técnica conocida)",
    "sampler:permutation": "muestreo por épocas (técnica conocida)",
}

# Opciones que la BÚSQUEDA no puede elegir hasta que el Research Engine (Modo B) aporte
# evidencia de que merecen entrar en el espacio. Siempre se pueden renderizar y evaluar.
RESEARCH_ONLY = {("sampler", "shuffled_slices")}
UNLOCKED = set()


def set_unlocked(items):
    UNLOCKED.clear()
    UNLOCKED.update(tuple(i) for i in items)


def search_options(slot):
    return [o for o in SLOTS[slot] if (slot, o) not in RESEARCH_ONLY or (slot, o) in UNLOCKED]
