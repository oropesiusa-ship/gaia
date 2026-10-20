# Paso humano: firmar el paquete de instalación/recuperación de laboratorio

**Estado actualizado: firma recibida y verificada; instalación/reparación VM
positivas 3/3 completadas. S1 y F1 siguen abiertas por sus otros requisitos.**
Informe definitivo: `.gaia/reports/20261018T203350Z-9e9b020a/REPORT.md`.
Este documento conserva el procedimiento ejecutado, no una orden de repetir la
firma ni la prueba. Detalle en
[VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md](VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md).

## Objeto exacto

- Huella: `6BF5C62DC530889F3D7C644F678D00EC8B5BF748`.
- Propósito: **lab**, no release físico ni autorización de borrar un HDD real.
- Imagen: `.gaia/reports/20261018T182432Z-f0a96e77/disk.raw`, 22577938432 bytes.
- SHA-256 de imagen: `216be2f81c1ec29a726859085d6f89d9caadf911489c1090b829a93a05275c6f`.
- Manifiesto a firmar:
  `.gaia/reports/20261018T191315Z-018272b8/install-bundle/install-manifest.json`.
- SHA-256 **del manifiesto exacto**:
  `0d0333fc6a7035cb7367b09b1ba160daadc2d1fad99971528a6b62705e25b0a2`.
- Informe de solicitud:
  `.gaia/reports/20261018T191315Z-018272b8/REPORT.md`,
  `AWAITING_OWNER_VM_INSTALL_SIGNATURE`.

La imagen del bundle es un hardlink del artefacto probado, no una segunda copia.
No modificar los artefactos después de comprobarlos/firmarlos. El manifiesto
contiene nombre, tamaño y hash de la imagen y de su metadato; solo permite como
destino de la prueba `GAIA-LAB-TARGET`. El instalador de este perfil comprueba QEMU
y la identidad virtual antes de escribir. No es aún el instalador físico de S2.

## 1. Revisar y firmar tú desde tu PC confiable

Desde `~/Projects/GAIA`, lee primero el manifiesto indicado. El siguiente bloque
Bash verifica su hash fijo y los hashes de los dos artefactos **antes** de abrir
el USB privado. Se firma con el primario, usando pinentry y tu contraseña; el
agente no ejecuta este bloque. No se genera ninguna clave ni se formatea un USB.

```bash
(
set -euo pipefail
FPR=6BF5C62DC530889F3D7C644F678D00EC8B5BF748
REQUEST="$PWD/.gaia/reports/20261018T191315Z-018272b8/install-bundle/install-manifest.json"
EXPECTED=0d0333fc6a7035cb7367b09b1ba160daadc2d1fad99971528a6b62705e25b0a2
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

La comprobación lee una imagen de unos 21 GiB; puede tardar. Si un comando falla,
el bloque se detiene: comunicar el error antes de repetir. Si el fallo ocurre con
el primario abierto, conservar el estado para cerrarlo ordenadamente; no volver
a inicializar el contenedor ni borrar la custodia. No se sobrescribe una firma
preexistente sin revisarla.

## 2. Resultado y reanudación del agente

Exigir `SIGNED_ARTIFACTS_VERIFIED`. Devolver solo la salida final/ruta de informe;
la firma `.json.asc` es pública y queda junto al manifiesto. Confirmar también:

- Que la huella coincide con tu registro externo independiente.
- Que la prueba anterior de backup se firmó desde el segundo USB con el primario
  cerrado, y ambos USB terminan cerrados/desconectados.

Tras verificar esa firma, el agente puede ejecutar:

```bash
python3 gaia.py appliance-recovery \
  --image-dir .gaia/reports/20261018T182432Z-f0a96e77 \
  --bundle-dir .gaia/reports/20261018T191315Z-018272b8/install-bundle \
  --repeats 3
```

El controlador verifica la firma primero, crea un bundle en otro disco virtual,
arranca la recuperación desde USB emulado e instala en un destino virtual vacío.
Después arranca el destino sin el USB, corrompe B, vuelve al USB y repara las
particiones de sistema conservando DATA. Debe comprobar tres repeticiones con
readback/hash y continuidad de evidencia. **Actualización:** la ejecución positiva
ya está superada 3/3, incluida reparación con DATA conservada y seis boots posteriores
sin el USB. La negativa de firma y las pruebas unitarias también están documentadas.
La aceptación global de S1/F1 sigue pendiente.

La posterior preparación del HDD externo físico, S0, S2–S4, NVIDIA, benchmark y
recuperación física siguen sujetos al plan maestro. Esta firma lab no los habilita.
