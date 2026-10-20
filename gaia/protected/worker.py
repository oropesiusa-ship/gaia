"""Proceso aislado que ejecuta el entrenador candidato. Protocolo por stdin/stdout.

No conoce etiquetas de validación ni el objetivo de calidad. El tiempo lo mide
el padre (evaluador), no este proceso.
"""
import importlib.util
import json
import os
import sys

import numpy as np


def correctness(mod):
    rng = np.random.default_rng(0)
    dims = [6, 5, 4, 3]
    W = [rng.standard_normal((dims[i], dims[i + 1])) * 0.5 for i in range(3)]
    b = [rng.standard_normal(dims[i + 1]) * 0.1 for i in range(3)]
    xb, yb = rng.standard_normal((7, 6)), rng.integers(0, 3, 7)

    def loss():
        return mod.forward_backward([w.copy() for w in W], [x.copy() for x in b], xb.copy(), yb, 3)[0]

    _, gW, gb = mod.forward_backward([w.copy() for w in W], [x.copy() for x in b], xb.copy(), yb, 3)
    worst = 0.0
    for P, g in ((W, gW), (b, gb)):
        for a, ga in zip(P, g):
            for _ in range(4):
                i = tuple(int(rng.integers(0, s)) for s in a.shape)
                old = a[i]
                a[i] = old + 1e-6
                lp = loss()
                a[i] = old - 1e-6
                lm = loss()
                a[i] = old
                worst = max(worst, abs((lp - lm) / 2e-6 - ga[i]))
    sampler = mod.make_sampler(100, 32, np.random.default_rng(0))
    X = np.arange(100.0)
    return {"gradient_error": worst, "sampler_valid": all(len(X[sampler()]) == 32 for _ in range(10))}


def main():
    wd = sys.argv[1]
    helper = importlib.util.spec_from_file_location("cpu_sandbox", os.path.join(os.path.dirname(__file__), "sandbox.py"))
    isolation = importlib.util.module_from_spec(helper)
    helper.loader.exec_module(isolation)
    isolation.worker_handshake()
    proto = os.fdopen(os.dup(1), "w", buffering=1)
    sys.stdout = open(os.devnull, "w")      # lo que imprima el candidato se descarta
    try:
        with np.load("/lab/data.npz", allow_pickle=False) as d:
            Xtr, ytr, Xva, k = d["Xtr"], d["ytr"], d["Xva"], int(d["k"])
        spec = importlib.util.spec_from_file_location("cand", "/lab/trainer.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        trainer = None
        # G0: huella del runtime que realmente ejecuta al candidato (el padre la compara)
        rs = importlib.util.spec_from_file_location("gaia_runtime", os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime.py"))
        rt = importlib.util.module_from_spec(rs)
        rs.loader.exec_module(rt)
        fp = rt.fingerprint(with_torch=os.environ.get("GAIA_FP_TORCH") == "1")
        proto.write("READY " + json.dumps(fp, sort_keys=True) + "\n")
        for line in sys.stdin:
            parts = line.split()
            cmd = parts[0]
            if cmd == "INIT":
                trainer = mod.Trainer(Xtr, ytr, k, int(parts[1]))
            elif cmd == "STEPS":
                trainer.train(int(parts[1]))
            elif cmd == "PRED":
                p = np.asarray(trainer.predict(Xva))
                np.save(os.path.join(wd, "pred.npy"), p)
            elif cmd == "CHECK":
                proto.write("CHECKED " + json.dumps(correctness(mod)) + "\n")
                continue
            elif cmd == "QUIT":
                proto.write("BYE\n")
                break
            proto.write("OK\n")
    except BaseException as e:   # noqa: BLE001  (se informa al padre)
        proto.write("ERR " + repr(e)[:300].replace("\n", " ") + "\n")
        sys.exit(1)
    finally:
        proto.close()
        sys.stdout.close()


main()
