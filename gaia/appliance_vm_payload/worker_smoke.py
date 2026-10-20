"""Executed as gaia in a guest-only bwrap sandbox; never on the host."""
import errno
import json
import os
from pathlib import Path
import socket
import sys

assert os.geteuid() != 0
status = Path("/proc/self/status").read_text()
assert "CapEff:\t0000000000000000" in status
assert "NoNewPrivs:\t1" in status
assert os.stat("/proc/self/ns/net").st_ino != int(sys.argv[1])
assert not Path("/dev/vda").exists()
for path in ("/core/guardian.py", "/opt/gaia/app/gaia.py", "/data/evidence/ledger.jsonl"):
    try:
        with open(path, "ab"):
            pass
    except OSError as exc:
        assert exc.errno in (errno.EACCES, errno.EROFS) or (
            path == "/data/evidence/ledger.jsonl" and exc.errno == errno.ENOENT)
    else:
        raise AssertionError("Protected path writable: " + path)
with socket.socket() as connection:
    connection.settimeout(1)
    try:
        connection.connect(("192.0.2.1", 80))
    except OSError:
        pass
    else:
        raise AssertionError("Unexpected worker networking")
sys.path.insert(0, "/opt/gaia/app")
import torch
from gaia.gaia_transformer.model import GaiaTransformer
torch.set_num_threads(1)
torch.manual_seed(7)
with torch.no_grad():
    model = GaiaTransformer().eval()
    tokens = torch.randint(256, (2, 16))
    logits, loss = model(tokens, tokens)
assert list(logits.shape) == [2, 16, 256]
assert torch.isfinite(logits).all() and torch.isfinite(loss)
Path("/data/agent/worker-result.json").write_text(json.dumps({"uid": os.geteuid(), "smoke": "ok"}))
print(json.dumps({"status": "SANDBOX_CPU_OK", "uid": os.geteuid(), "logits_shape": list(logits.shape)}))
