#!/bin/sh
# Only inside the mapped-root runtime tree; modules were built independently.
set -eu
export DEBIAN_FRONTEND=noninteractive
cp /tmp/nvidia-debs/*.deb /var/cache/apt/archives/
apt-get --yes --no-download --no-install-recommends install \
    /tmp/nvidia-debs/libnvidia-*.deb /tmp/nvidia-debs/libcuda1_*.deb /tmp/nvidia-debs/nvidia-smi_*.deb
mkdir -p /tmp/prebuilt-modules /lib/modules/6.12.107+deb13-amd64/updates/dkms
tar -xf /tmp/nvidia-modules.tar -C /tmp/prebuilt-modules
cp /tmp/prebuilt-modules/*.ko* /lib/modules/6.12.107+deb13-amd64/updates/dkms/
depmod -a 6.12.107+deb13-amd64
printf 'blacklist nouveau\noptions nouveau modeset=0\n' > /etc/modprobe.d/gaia-nvidia.conf
/opt/gaia/venv/bin/python -I -c '
import ctypes, json, subprocess
ctypes.CDLL("libcuda.so.1")
ctypes.CDLL("libnvidia-ml.so.1")
kernel = "6.12.107+deb13-amd64"
modules = {}
for name in ("nvidia", "nvidia_modeset", "nvidia_drm", "nvidia_uvm"):
    path = subprocess.check_output(["modinfo", "-k", kernel, "-n", name], text=True).strip()
    row = {field: subprocess.check_output(["modinfo", "-F", field, path], text=True).strip()
           for field in ("version", "vermagic", "license")}
    assert row["version"] == "580.178.04" and row["vermagic"].startswith(kernel + " ")
    if name == "nvidia":
        assert row["license"] == "NVIDIA"
    modules[name] = row
print(json.dumps({"status": "NVIDIA_RUNTIME_LINKS_AND_MODULES_OK", "driver": "580.178.04",
                  "kernel": kernel, "modules": modules, "gpu_tested": False}))
' > /opt/gaia/build-nvidia.json
rm -rf /tmp/prebuilt-modules
