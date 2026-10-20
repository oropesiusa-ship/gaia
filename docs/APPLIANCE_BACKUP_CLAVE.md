# Paso humano actual: copiar y probar la custodia de GAIA

Estado actualizado: **firma pública de esta prueba verificada** en
`.gaia/reports/20261016T134648Z-33248432/REPORT.md`. Pendiente la confirmación humana
explícita de independencia del backup y registro externo. Este documento conserva
el procedimiento, no es una orden de repetir la copia sobre una custodia existente.
Paso humano vigente: [firma de instalación VM](APPLIANCE_FIRMA_INSTALACION_VM.md).
Los dos USB ya están formateados/cerrados. Aquí no se inicializa ningún disco ni
se genera una clave. Ejecutar solo el propietario en el PC confiable, desde
`~/Projects/GAIA`, con ambos USB conectados y con los volúmenes inicialmente
cerrados. El agente no abre ni copia la custodia privada.

Huella esperada: `6BF5C62DC530889F3D7C644F678D00EC8B5BF748`.
Confirma también su coincidencia con tu registro externo independiente.

## 1. Copiar la custodia al backup, sin sobrescribir una copia existente

El bloque completo es un subshell Bash: se detiene si un comando falla. Si el
backup ya contiene `gnupg/`, se detiene antes de copiar; comunicarlo para revisar
la copia existente sin sobrescribirla. Si falla algo, conservar el estado y pasar
el error antes de continuar; los volúmenes podrían quedar abiertos para revisión.

```bash
(
set -euo pipefail
PRIMARY_DISK="$(python3 -c 'import json; print(json.load(open(".gaia/signing-usb-targets.json"))["primary"]["by_id"])')"
BACKUP_DISK="$(python3 -c 'import json; print(json.load(open(".gaia/signing-usb-targets.json"))["backup"]["by_id"])')"
PRIMARY_HOME=/mnt/gaia-signing-primary/gnupg
BACKUP_HOME=/mnt/gaia-signing-backup/gnupg

sudo cryptsetup open "$PRIMARY_DISK" gaia-signing-primary
sudo cryptsetup open "$BACKUP_DISK" gaia-signing-backup
sudo install -d -m 0700 /mnt/gaia-signing-primary /mnt/gaia-signing-backup
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-primary /mnt/gaia-signing-primary
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-backup /mnt/gaia-signing-backup

test -d "$PRIMARY_HOME/private-keys-v1.d"
test ! -e "$BACKUP_HOME"
gpgconf --homedir "$PRIMARY_HOME" --kill all
sync
cp -a -- "$PRIMARY_HOME" "$BACKUP_HOME"
sync

sudo umount /mnt/gaia-signing-primary
sudo cryptsetup close gaia-signing-primary
sudo umount /mnt/gaia-signing-backup
sudo cryptsetup close gaia-signing-backup
echo 'Copia guardada; primario y backup cerrados.'
)
```

La privada viaja únicamente entre los dos USB cifrados. Se conserva también
`openpgp-revocs.d` dentro de la custodia cifrada, no en el proyecto. El agente GPG
del primario está detenido antes de la copia para no copiar bases activas.

## 2. Reabrir solo el backup y firmar la prueba pública

Con el primario cerrado (puedes desconectarlo físicamente), el siguiente bloque
reabre únicamente el backup. El diálogo GPG solicita la contraseña de la clave
privada original; la apertura de LUKS utiliza la contraseña del contenedor backup.

Se firma `keys/gaia-custody-backup-check.json`, un manifiesto **de laboratorio**
preparado para esta prueba. Contiene la huella esperada, el desafío público de esta
sesión y los hashes de las tres exportaciones públicas verificadas. Puedes leerlo
antes de firmar. No autoriza un release, instalación o cambio del sistema.

```bash
(
set -euo pipefail
BACKUP_DISK="$(python3 -c 'import json; print(json.load(open(".gaia/signing-usb-targets.json"))["backup"]["by_id"])')"
FPR=6BF5C62DC530889F3D7C644F678D00EC8B5BF748
BACKUP_HOME=/mnt/gaia-signing-backup/gnupg
export GPG_TTY="$(tty)"
umask 077

test ! -e /dev/mapper/gaia-signing-primary
test ! -e keys/gaia-custody-backup-check.json.asc
sudo cryptsetup open "$BACKUP_DISK" gaia-signing-backup
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-backup /mnt/gaia-signing-backup
gpg --homedir "$BACKUP_HOME" --fingerprint --list-secret-keys "$FPR"
gpg --homedir "$BACKUP_HOME" --local-user "${FPR}!" --armor --detach-sign \
  --output keys/gaia-custody-backup-check.json.asc keys/gaia-custody-backup-check.json
gpgconf --homedir "$BACKUP_HOME" --kill all
sync
sudo umount /mnt/gaia-signing-backup
sudo cryptsetup close gaia-signing-backup

python3 gaia.py appliance-verify \
  --public-key keys/gaia-release-signing.pub.gpg \
  --fingerprint "$FPR" \
  --manifest keys/gaia-custody-backup-check.json \
  --signature keys/gaia-custody-backup-check.json.asc \
  --artifacts-dir keys --purpose lab
)
```

La única salida nueva en el proyecto es una **firma pública** `.json.asc` y el
informe del verificador público. Al ejecutar `appliance-verify` ambos volúmenes ya
están cerrados. Exigir `SIGNED_ARTIFACTS_VERIFIED` y conservar el informe.

## 3. Qué comunicar

- Salida final o ruta del informe de `appliance-verify`.
- Confirmación de que el primario estaba cerrado durante la firma y ambos USB
  terminaron cerrados/desconectados.
- Confirmación de que la huella coincide con la anotada en el registro externo.

No compartir privada, `gnupg/`, revocación ni contraseñas. No repetir un bloque
destructivo de inicialización: estos contenedores ya están preparados.

Una firma correcta acredita posesión/uso de la clave correspondiente. La ubicación
física de la copia y su independencia del primario se acreditan además por la
ejecución y confirmación del propietario. Esta prueba no cierra por sí sola S1.
