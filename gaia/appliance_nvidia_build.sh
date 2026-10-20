#!/bin/sh
# Executed only in an mmdebstrap mapped-root chroot, never on the host.
set -eu
export DEBIAN_FRONTEND=noninteractive
# --no-download consumes APT's authenticated cache, not arbitrary local argv.
cp /tmp/nvidia-debs/*.deb /var/cache/apt/archives/
apt-get --yes --no-download --no-install-recommends install /tmp/nvidia-debs/*.deb
dkms autoinstall -k 6.12.107+deb13-amd64
depmod -a 6.12.107+deb13-amd64
mkdir -p /tmp/module-output
for module in nvidia nvidia_modeset nvidia_drm nvidia_uvm; do
    path="$(modinfo -k 6.12.107+deb13-amd64 -n "$module")"
    test "$(modinfo -F version "$path")" = 580.178.04
    modinfo -F vermagic "$path" | grep -q '^6.12.107+deb13-amd64 '
    if test "$module" = nvidia; then
        test "$(modinfo -F license "$path")" = NVIDIA
    fi
    cp "$path" /tmp/module-output/
    modinfo "$path" > "/tmp/module-output/${module}.modinfo"
done
dkms status > /tmp/module-output/dkms-status.txt
cp /var/lib/dkms/nvidia/580.178.04/6.12.107+deb13-amd64/x86_64/log/make.log /tmp/module-output/make.log
tar -cf /tmp/nvidia-modules.tar -C /tmp/module-output .
if test -x /opt/gaia/venv/bin/python; then
    /opt/gaia/venv/bin/python -I -c '
import ctypes, json, subprocess
ctypes.CDLL("libcuda.so.1")
ctypes.CDLL("libnvidia-ml.so.1")
kernel = "6.12.107+deb13-amd64"
modules = {}
for name in ("nvidia", "nvidia_modeset", "nvidia_drm", "nvidia_uvm"):
    path = subprocess.check_output(["modinfo", "-k", kernel, "-n", name], text=True).strip()
    modules[name] = {field: subprocess.check_output(["modinfo", "-F", field, path], text=True).strip()
                     for field in ("version", "vermagic", "license")}
print(json.dumps({"status": "NVIDIA_RUNTIME_LINKS_AND_MODULES_OK", "driver": "580.178.04",
                  "kernel": kernel, "modules": modules, "gpu_tested": False}))
' > /opt/gaia/build-nvidia.json
fi
