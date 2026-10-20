#!/bin/sh
# Runs only inside the mmdebstrap target chroot. No host privilege escalation.
set -eu
test -f /tmp/Python-3.14.4.tar.xz
test -f /tmp/gaia-transformer-cuda-pascal-py314.lock
mkdir -p /tmp/python-build /opt/gaia
tar -xJf /tmp/Python-3.14.4.tar.xz -C /tmp/python-build
cd /tmp/python-build/Python-3.14.4
./configure --prefix=/opt/gaia/python --with-ensurepip=install --disable-test-modules
make -j2
make -j2 install
/opt/gaia/python/bin/python3.14 -m venv /opt/gaia/venv
/opt/gaia/venv/bin/python -m pip --isolated install --disable-pip-version-check --no-cache-dir \
    --only-binary=:all: --require-hashes --index-url https://pypi.org/simple \
    -r /tmp/gaia-transformer-cuda-pascal-py314.lock
/opt/gaia/venv/bin/python -m pip --isolated check
useradd --system --create-home --home-dir /var/lib/gaia --shell /usr/sbin/nologin gaia
runuser -u gaia -- /opt/gaia/venv/bin/python -I -c '
import json, sys, os, ssl, ctypes, numpy as np, torch
sys.path.insert(0, "/opt/gaia/app")
from gaia.gaia_transformer.model import GaiaTransformer
assert sys.version_info[:3] == (3, 14, 4)
assert torch.__version__ == "2.14.0+cu126"
assert torch.version.cuda == "12.6"
assert np.__version__ == "2.3.5"
assert os.geteuid() != 0
torch.set_num_threads(1)
torch.manual_seed(7)
model = GaiaTransformer().eval()
tokens = torch.randint(256, (2, 16))
with torch.no_grad():
    logits, loss = model(tokens, tokens)
assert torch.isfinite(logits).all() and torch.isfinite(loss)
print(json.dumps({"status": "GAIA_RUNTIME_CPU_SMOKE_OK", "python": sys.version,
 "executable": sys.executable, "prefix": sys.prefix, "numpy": np.__version__,
 "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
 "gpu_validation": "pending physical hardware, not tested in build chroot",
 "uid": os.geteuid(), "openssl": ssl.OPENSSL_VERSION,
 "logits_shape": list(logits.shape)}))
' > /opt/gaia/build-runtime.json
cd /
rm -rf /tmp/python-build /tmp/Python-3.14.4.tar.xz /tmp/gaia-transformer-cuda-pascal-py314.lock
