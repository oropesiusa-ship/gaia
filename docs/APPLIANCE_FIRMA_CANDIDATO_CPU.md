# Firma humana del candidato CPU depurado — 2026-10-19

Estado: **firma recibida y verificada**, informe
`.gaia/reports/20261019T091206Z-a19b9124/REPORT.md`.
La instalación/reparación positiva del nuevo hash terminó 3/3 en
`20261019T091600Z-78c27069`, y la auditoría CPU/VM se aceptó en
`20261019T100144Z-91a97bb3`. El bloque humano y la reanudación inferiores se
conservan como procedimiento histórico; no deben repetirse.

## Objeto de esta firma

- Perfil `cpu-delivery-candidate`, autoridad L0, propósito de firma **lab**.
- Imagen: `.gaia/reports/20261019T075104Z-0bda6b85/disk.raw`.
- SHA-256: `195cd3661217bd6cc4de8af38e314786a097994940cd61288ed4d1de2a9ed4de`.
- Se retiraron 34 paquetes nativos de compilación/cabeceras; 174 conservados con
  versiones iguales. El runtime Python/Torch y sus bibliotecas se comprobaron
  realmente en VM, como UID 997, con pip check y enlaces del intérprete correctos.
- Arranque predeterminado: servicio L0 persistente. El probe de aceptación se
  selecciona explícitamente en VM; no es el servicio operativo de apagado automático.
- Manifiesto a firmar:
  `.gaia/reports/20261019T085624Z-4770def7/install-bundle/install-manifest.json`.
- SHA-256 del manifiesto:
  `7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26`.

La firma anterior sigue describiendo la imagen anterior. Este mensaje vincula el
nuevo hash y su metadato; no autoriza instalar sobre el HDD físico ni certifica GPU.

## Bloque humano único

Desde `~/Projects/GAIA`, leer el manifiesto y ejecutar el bloque en tu terminal.
Verifica los hashes antes de abrir el USB y usa pinentry; el agente no lo ejecuta.

```bash
(
set -euo pipefail
FPR=6BF5C62DC530889F3D7C644F678D00EC8B5BF748
REQUEST="$PWD/.gaia/reports/20261019T085624Z-4770def7/install-bundle/install-manifest.json"
EXPECTED=7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26
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

Devolver salida `SIGNED_ARTIFACTS_VERIFIED` o ruta del informe. La firma generada
es pública. Si falla un comando, detenerse y comunicarlo; el volumen puede quedar
abierto para revisión. No repetir inicialización, regenerar clave ni sobrescribir
una firma existente sin verificar el estado.

## Reanudación del agente

Tras verificar la firma se ejecutará el controlador, no lo necesitas lanzar tú:

```bash
python3 gaia.py appliance-recovery \
  --image-dir .gaia/reports/20261019T075104Z-0bda6b85 \
  --bundle-dir .gaia/reports/20261019T085624Z-4770def7/install-bundle --repeats 3
```

Deberá instalar y reparar tres veces conservando DATA, con arranque operativo
persistente posterior a cada operación. Después se auditarán los restantes
criterios de entrega/S1 antes de preparar el medio físico. La compatibilidad
NVIDIA y S0/S2–S4 siguen sus pruebas físicas; F1 no se declara completada aquí.
