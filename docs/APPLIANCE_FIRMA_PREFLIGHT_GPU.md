# Firma del primer diagnóstico físico NVIDIA — 2026-10-19

## Objeto exacto

**Propósito lab, diagnóstico GPU en HDD externo autorizado.** No es firma de
aceptación F1 ni paquete de instalación interna. La imagen CPU/VM anterior queda
cerrada como referencia; esta solicitud vincula el primer perfil NVIDIA construido
y probado en sus escenarios VM. Hace falta comprobar GPU real antes de aceptar
el perfil físico. No se pide regenerar claves ni repetir la firma CPU.

- Imagen: `/mnt/gaia-build/artifacts/20261019T111348Z-95cd9936/disk.raw`.
- Bytes: `25075646464`.
- SHA-256: `63dc4c7ee9d905edcf2cd61a0f107c7861d03d7bad8c36332e1f0cd5f795b0a4`.
- Driver580.178.04, kernel6.12.107+deb13-amd64; arranque normal requiere GPU
  y el driver exacto, sin fallback CPU silencioso.
- Manifiesto:
  `/mnt/gaia-build/artifacts/20261019T125118Z-1bba0062/gpu-preflight-manifest.json`.
- SHA-256 del manifiesto:
  `2f2401fe2092e3e9bfd5a82780270eb05addb88683966dfede7fce4b0a973c77`.
- Tipo `gaia-physical-gpu-preflight-v1`, propósito `lab`, autoridad L0.
- Diez escenarios VM3/3, 63 boots seleccionados, 88 tests appliance OK.
  GPU física aún no probada; no se traslada la salud CPU de VM a CUDA.

## Bloque humano

Desde `~/Projects/GAIA`, revisar el manifiesto y ejecutar en tu terminal:

```bash
(
set -euo pipefail
FPR=6BF5C62DC530889F3D7C644F678D00EC8B5BF748
REQUEST=/mnt/gaia-build/artifacts/20261019T125118Z-1bba0062/gpu-preflight-manifest.json
EXPECTED=2f2401fe2092e3e9bfd5a82780270eb05addb88683966dfede7fce4b0a973c77
test "$(sha256sum "$REQUEST" | cut -d ' ' -f 1)" = "$EXPECTED"
test ! -e "${REQUEST}.asc"
python3 - "$REQUEST" "$FPR" <<'PY'
import sys
from pathlib import Path
from gaia.appliance_verify import verify_artifacts
p = Path(sys.argv[1])
rows = verify_artifacts(p.read_bytes(), p.parent, sys.argv[2], "lab")
print("Artefactos íntegros:", ", ".join(row["name"] for row in rows))
PY
PRIMARY_DISK="$(python3 -c 'import json; print(json.load(open(".gaia/signing-usb-targets.json"))["primary"]["by_id"])')"
export GPG_TTY="$(tty)"
sudo cryptsetup open "$PRIMARY_DISK" gaia-signing-primary
sudo install -d -m 0700 /mnt/gaia-signing-primary
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-primary /mnt/gaia-signing-primary
gpg --homedir /mnt/gaia-signing-primary/gnupg --local-user "${FPR}!" \
  --armor --detach-sign --output "${REQUEST}.asc" "$REQUEST"
gpgconf --homedir /mnt/gaia-signing-primary/gnupg --kill all
sync
sudo umount /mnt/gaia-signing-primary
sudo cryptsetup close gaia-signing-primary
python3 gaia.py appliance-verify \
  --public-key keys/gaia-release-signing.pub.gpg --fingerprint "$FPR" \
  --manifest "$REQUEST" --signature "${REQUEST}.asc" \
  --artifacts-dir "$(dirname "$REQUEST")" --purpose lab
)
```

Devolver `SIGNED_ARTIFACTS_VERIFIED` o su informe. Si falla, comunicar el comando
y salida; no recrear claves ni sobrescribir firma existente. Este bloque no escribe
el HDD externo de recuperación: solo crea la firma detached pública en el SSD de
construcción y usa el USB offline como en el procedimiento ya establecido.

## Reanudación

Verificar firma exacta; preparar controlador de escritura/readback del HDD externo
con identidad revalidada y su autorización registrada. Su ejecución privilegiada
requerirá terminal humana. Después desconectar discos diarios/ajenos y USB de
claves, arrancar el HDD y obtener evidencia del servicio CUDA no root. No se ejecuta
instalación en Shared como consecuencia de esta firma. El instalador físico,
dimensionamiento DATA, baseline, robustez y recuperaciones S0/S2–S4 siguen abiertos.
