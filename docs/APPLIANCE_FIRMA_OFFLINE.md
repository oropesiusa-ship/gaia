# Firma offline GAIA — procedimiento del propietario (§6.3)

Estado: **USB preparados, pública y firmas de prueba/paquete lab verificadas;
instalación/reparación VM 3/3. Pendientes confirmaciones humanas de custodia/registro
y los restantes criterios S1/F1.**
El agente no genera, lee, exporta ni solicita la privada o sus contraseñas.

Huella esperada comunicada por el propietario:
`6BF5C62DC530889F3D7C644F678D00EC8B5BF748`, registrada en
`keys/gaia-release-signing.fingerprint.txt`. Públicas `.pub.asc`/`.pub.gpg` recibidas
y comprobadas: misma clave binaria y huella, primaria Ed25519 de firma. Informe
`.gaia/reports/20261016T133757Z-78fc1d87/REPORT.md`.
Firma de prueba del propietario verificada en
`.gaia/reports/20261016T134648Z-33248432/REPORT.md`; la ubicación física del backup
y la anotación externa requieren confirmación explícita del propietario.
El [procedimiento de firma del paquete lab](APPLIANCE_FIRMA_INSTALACION_VM.md) ya
se ejecutó, con resultado definitivo `VM_SIGNED_RECOVERY_VALIDATED` en
`.gaia/reports/20261018T203350Z-9e9b020a/REPORT.md`. No repetir esa firma.
Acción humana vigente: [firma del candidato CPU depurado](APPLIANCE_FIRMA_CANDIDATO_CPU.md),
un artefacto nuevo con runtime persistente y toolchain retirado. La clave sigue
siendo la misma; solo el manifiesto del nuevo hash requiere una nueva firma.
El procedimiento de
[backup de clave](APPLIANCE_BACKUP_CLAVE.md) se conserva como referencia; no
repetir copia ni generación a ciegas. No se regenera la clave ni se reformatea.

## 1. Decisiones y alcance

- Generación y firma humanas en el PC personal del propietario, separado del
  entorno de ejecución de la appliance. GAIA y sus workers detenidos durante firma.
- Clave exclusiva **Ed25519 en formato OpenPGP/GnuPG**, primaria con capacidad
  de firma; no una clave SSH ni una clave PEM de OpenSSL.
- Custodia primaria: USB antes etiquetado `Ventoy`, ProductCode, 31457280000
  bytes, serie observada localmente terminada en `E424`.
- Backup: USB antes etiquetado `KALI LINUX`, mismo modelo/capacidad, serie
  terminada en `BED3`. Se inicializa con LUKS propio: no clonar el contenedor LUKS.
- Ambos USB autorizados expresamente para borrado y uso exclusivo de firma.
  Esta autorización es distinta de la instalación de la appliance. No habilita
  escribir Shared, discos diarios ni el HDD de recuperación antes de sus puertas.
- Privada protegida por contraseña y por **LUKS2/Argon2id**; copia independiente
  en el segundo USB cifrado. Contraseñas fuera del proyecto y fuera de argumentos.
- El HDD instalador/recuperación solo recibe pública, huella y firmas; nunca
  GNUPGHOME, privada, certificados de revocación ni contraseñas.
- Huella de confianza: **OpenPGP v4 completa, 40 dígitos hexadecimales**,
  confirmada por el propietario desde una herramienta confiable y conservada
  también fuera de los USB. Los SHA-256 de archivos identifican sus bytes; no
  sustituyen esa confirmación ni se confunden con la huella OpenPGP.

Las rutas `/dev/sde` y `/dev/sdf` fueron observaciones de una sesión, no destinos
persistentes. Se utilizan rutas `/dev/disk/by-id/usb-*` verificadas localmente.
No se almacenan las series completas en evidencia exportada.

## Preparación asistida de los USB autorizados

El propietario ha solicitado ejecutar el formateo. Se reidentificaron los dos USB
por serie completa, modelo, capacidad y ruta by-id. Cryptsetup ya está instalado.
El propietario ejecutó el helper desde terminal y completó ambos USB. Informe
`.gaia/signing-usb-preparation.json`: `CUSTODY_USB_PREPARED`, ambos roles y ninguna
clave GPG generada. Su salida acredita e2fsck correcto en los dos ext4.
El agente comprobó después solo metadatos: identidades correctas, ambos
`crypto_LUKS`, sin montajes ni mappers abiertos. **No repetir el formateo**;
continuar más abajo con apertura del primario, generación humana y backup.

Comando de inicialización ya ejecutado correctamente, conservado como referencia:

```bash
python3 gaia/appliance_key_usb.py
```

Este comando usa las identidades autorizadas de
`.gaia/signing-usb-targets.json` (local, ignorado, no exportar). Pide sudo y las
contraseñas LUKS directamente en la terminal; prepara ambos contenedores como
LUKS2/Argon2id + ext4, comprueba ext4, asigna la raíz al usuario con modo 0700,
desmonta y cierra cada volumen. No genera claves GPG ni crea `gnupg/`.
Revalida identidades antes de borrar, protege sistemas esenciales y se niega a
reformatear un LUKS ya existente. Se detiene ante el primer fallo, sin reintentos.
`--role primary`/`--role backup` limita el trabajo al USB indicado si hace falta
preparar solo el otro; no fuerza el reformateo de uno ya cifrado.

Corrección de montaje: el inventario solicita explícitamente `lsblk --tree` para
incluir las particiones en `children` del JSON aunque la columna sea PATH.
Se desmontan las particiones del USB autorizado y se revalida el inventario antes
de wipefs. El primer intento del propietario falló porque faltaba ese árbol;
corregido con prueba de regresión y 9 tests del helper correctos. Si umount falla,
se detiene antes del borrado, sin forzarlo. Evidencia de diagnóstico y pruebas:
`.gaia/reports/20261016T132211Z-8e1293e9/REPORT.md`.

Informe: `.gaia/signing-usb-preparation.json`, con roles procesados y estado.
Para preparación de ambos, exigir `CUSTODY_USB_PREPARED` y
`prepared=["primary","backup"]`. No se da por hecho con solo iniciar el comando.

**Después de éxito no volver a ejecutar wipefs/luksFormat/mkfs de §4 o §7.**
Usar §2 para el entorno de GPG y §3 para definir/verificar las rutas. Abrir el
primario ya preparado:

```bash
sudo cryptsetup open "$PRIMARY_DISK" gaia-signing-primary
sudo install -d -m 0700 /mnt/gaia-signing-primary
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-primary /mnt/gaia-signing-primary
export PRIMARY_HOME=/mnt/gaia-signing-primary/gnupg
install -d -m 0700 "$PRIMARY_HOME"
```

Seguir §5 y §6 para generar/exportar manualmente la clave. Para el backup,
abrir el contenedor ya preparado, sin repetir su inicialización:

```bash
sudo cryptsetup open "$BACKUP_DISK" gaia-signing-backup
sudo install -d -m 0700 /mnt/gaia-signing-backup
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-backup /mnt/gaia-signing-backup
export BACKUP_HOME=/mnt/gaia-signing-backup/gnupg
```

Continuar §7 desde «Detener los servicios de GnuPG» para copiar y cerrar, y §8
para probar ambas reaperturas y la firma del backup independientemente.
Las secciones de inicialización manual siguientes son una alternativa al helper,
no pasos adicionales sobre los USB ya preparados.

## 2. Herramientas y terminal humana

En el PC personal, en tu terminal. No grabar la sesión ni pasar contraseñas por
CLI, variables o archivos de respuesta. `sudo`, cryptsetup y pinentry las piden
directamente. Si una comprobación falla, no continuar con el bloque destructivo.

```bash
sudo apt-get update
sudo apt-get install cryptsetup gnupg gpgv
gpg --version
cryptsetup --version
export GPG_TTY="$(tty)"
umask 077
```

En la comprobación del agente estaban disponibles gpg/gpgv/gpgconf y faltaba el
binario cryptsetup. No se ha instalado automáticamente.

## 3. Identificar los USB antes de borrar

```bash
lsblk --bytes --output NAME,PATH,TYPE,TRAN,MODEL,SERIAL,SIZE,FSTYPE,LABEL,MOUNTPOINTS
ls -l /dev/disk/by-id/usb-*
read -r -p 'Ruta by-id del USB primario, disco completo, sin -partN: ' PRIMARY_DISK
read -r -p 'Ruta by-id del USB backup, disco completo, sin -partN: ' BACKUP_DISK
```

Comprobar serie **completa**, modelo, capacidad y asociación física; las etiquetas
y los últimos caracteres de serie solo ayudan a localizar, no autentican el medio.
Los discos de 250 GB/1 TB y los SATA no son ninguno de estos dos USB.

```bash
test -b "$PRIMARY_DISK"
test -b "$BACKUP_DISK"
test "$(readlink -f "$PRIMARY_DISK")" != "$(readlink -f "$BACKUP_DISK")"
test "$(lsblk -dn -o TYPE "$PRIMARY_DISK" | xargs)" = disk
test "$(lsblk -dn -o TYPE "$BACKUP_DISK" | xargs)" = disk
test "$(lsblk -dn -o TRAN "$PRIMARY_DISK" | xargs)" = usb
test "$(lsblk -dn -o TRAN "$BACKUP_DISK" | xargs)" = usb
test "$(lsblk -bdn -o SIZE "$PRIMARY_DISK" | xargs)" = 31457280000
test "$(lsblk -bdn -o SIZE "$BACKUP_DISK" | xargs)" = 31457280000
lsblk --bytes --output PATH,TYPE,TRAN,MODEL,SERIAL,SIZE,FSTYPE,LABEL,MOUNTPOINTS "$PRIMARY_DISK" "$BACKUP_DISK"
```

Estos comandos son para una **inicialización única**, no para USB con la nueva
clave ya guardada. Al reabrir se omiten wipefs/luksFormat/mkfs.

## 4. Inicializar el primario — borra el antiguo Ventoy

Tras verificarlo, desmontar sus sistemas existentes, sin actuar sobre otros discos:

```bash
while IFS= read -r node; do
    if findmnt -rn --source "$node" >/dev/null; then
        sudo umount -- "$node" || break
    fi
done < <(lsblk -nrpo PATH "$PRIMARY_DISK")
lsblk --output PATH,FSTYPE,MOUNTPOINTS "$PRIMARY_DISK"
```

No continuar si queda algo montado, hay un mapper criptográfico abierto o la
identidad no coincide. Este es el punto de comprobación humana antes del borrado:

```bash
sudo wipefs --all "$PRIMARY_DISK"
sudo cryptsetup luksFormat --type luks2 --pbkdf argon2id --label GAIA-SIGNING-PRIMARY "$PRIMARY_DISK"
sudo cryptsetup open "$PRIMARY_DISK" gaia-signing-primary
sudo mkfs.ext4 -L GAIA-KEY-PRIMARY /dev/mapper/gaia-signing-primary
sudo install -d -m 0700 /mnt/gaia-signing-primary
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-primary /mnt/gaia-signing-primary
sudo chown "$(id -u):$(id -g)" /mnt/gaia-signing-primary
chmod 0700 /mnt/gaia-signing-primary
export PRIMARY_HOME=/mnt/gaia-signing-primary/gnupg
install -d -m 0700 "$PRIMARY_HOME"
```

## 5. Generar la clave — solo tú, en el USB primario

Elegir contraseña no vacía y distinta de LUKS en el diálogo pinentry. No usar
`--passphrase`, `--passphrase-file`, `--pinentry-mode loopback` ni `--batch` para
suprimir ese diálogo. El `0` final significa sin caducidad: pérdida/compromiso
requiere revocación/rotación humana desde recuperación, no continuidad automática.

```bash
gpg --homedir "$PRIMARY_HOME" \
  --quick-generate-key 'GAIA Release Signing <gaia-release@local>' ed25519 sign 0
gpg --homedir "$PRIMARY_HOME" --fingerprint --list-secret-keys
read -r -p 'Copia la huella COMPLETA de 40 hex que acabas de comprobar: ' FPR
test "${#FPR}" -eq 40
[[ "$FPR" =~ ^[[:xdigit:]]{40}$ ]]
export FPR
gpg --homedir "$PRIMARY_HOME" --fingerprint "$FPR"
```

Comprobar una única clave primaria Ed25519, con firma habilitada. Registrar la
huella completa en papel u otro registro confiable independiente. GnuPG genera
un certificado de revocación en `openpgp-revocs.d/`: permanece en los USB cifrados,
junto a la custodia, y entra en el backup; no se publica en el proyecto.

## 6. Publicar únicamente la pública

En la misma terminal. La ruta del proyecto se ajusta si se ha trasladado.

```bash
export GAIA_PROJECT="$HOME/Projects/GAIA"
install -d -m 0755 "$GAIA_PROJECT/keys"
gpg --homedir "$PRIMARY_HOME" --armor --export "$FPR" > "$GAIA_PROJECT/keys/gaia-release-signing.pub.asc"
gpg --homedir "$PRIMARY_HOME" --export "$FPR" > "$GAIA_PROJECT/keys/gaia-release-signing.pub.gpg"
printf '%s\n' "$FPR" > "$GAIA_PROJECT/keys/gaia-release-signing.fingerprint.txt"
chmod 0644 "$GAIA_PROJECT/keys/gaia-release-signing.pub.asc" "$GAIA_PROJECT/keys/gaia-release-signing.pub.gpg" "$GAIA_PROJECT/keys/gaia-release-signing.fingerprint.txt"
gpg --homedir "$PRIMARY_HOME" --show-keys --with-fingerprint "$GAIA_PROJECT/keys/gaia-release-signing.pub.asc"
sha256sum "$GAIA_PROJECT/keys/gaia-release-signing.pub.asc" "$GAIA_PROJECT/keys/gaia-release-signing.pub.gpg" "$GAIA_PROJECT/keys/gaia-release-signing.fingerprint.txt"
```

Comparar la huella con el registro externo. No aceptar como anclaje una huella
leída únicamente del mismo medio que entrega la clave y los artefactos.

## 7. Inicializar backup — borra el antiguo KALI LINUX

Recomprobar su identidad completa con §3 antes de este bloque, aunque se haya
hecho el primario. No reutilizar las órdenes de inicialización para un backup ya
creado. Contraseña LUKS del backup bajo custodia del propietario, fuera del repo.

```bash
while IFS= read -r node; do
    if findmnt -rn --source "$node" >/dev/null; then
        sudo umount -- "$node" || break
    fi
done < <(lsblk -nrpo PATH "$BACKUP_DISK")
lsblk --output PATH,FSTYPE,MOUNTPOINTS "$BACKUP_DISK"
```

Si todo está desmontado y la identidad es correcta:

```bash
sudo wipefs --all "$BACKUP_DISK"
sudo cryptsetup luksFormat --type luks2 --pbkdf argon2id --label GAIA-SIGNING-BACKUP "$BACKUP_DISK"
sudo cryptsetup open "$BACKUP_DISK" gaia-signing-backup
sudo mkfs.ext4 -L GAIA-KEY-BACKUP /dev/mapper/gaia-signing-backup
sudo install -d -m 0700 /mnt/gaia-signing-backup
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-backup /mnt/gaia-signing-backup
sudo chown "$(id -u):$(id -g)" /mnt/gaia-signing-backup
chmod 0700 /mnt/gaia-signing-backup
export BACKUP_HOME=/mnt/gaia-signing-backup/gnupg
```

Detener los servicios de GnuPG **de ese homedir** antes de copiar; no copiar un
homedir activo con sockets/locks. El backup se escribe directamente dentro del
segundo LUKS. No se exportan claves secretas a archivos intermedios del PC.

```bash
gpgconf --homedir "$PRIMARY_HOME" --kill all
sync
test ! -e "$BACKUP_HOME"
cp -a -- "$PRIMARY_HOME" "$BACKUP_HOME"
sync
gpg --homedir "$BACKUP_HOME" --fingerprint --list-secret-keys "$FPR"
gpgconf --homedir "$BACKUP_HOME" --kill all
sudo umount /mnt/gaia-signing-primary
sudo cryptsetup close gaia-signing-primary
sudo umount /mnt/gaia-signing-backup
sudo cryptsetup close gaia-signing-backup
```

Si GnuPG no elimina un socket/lock al detenerse, no borrar archivos a ciegas ni
copiar mientras siga activo: revisar el proceso. La copia original se conserva.

## 8. Probar el backup independientemente

Primero comprobar que el primario vuelve a abrirse después del cierre:

```bash
sudo cryptsetup open "$PRIMARY_DISK" gaia-signing-primary
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-primary /mnt/gaia-signing-primary
gpg --homedir "$PRIMARY_HOME" --fingerprint --list-secret-keys "$FPR"
gpgconf --homedir "$PRIMARY_HOME" --kill all
sudo umount /mnt/gaia-signing-primary
sudo cryptsetup close gaia-signing-primary
```

Mantener el primario cerrado/desconectado. Reabrir **solo** el backup para probar
su contraseña LUKS y una firma real con la copia privada. No basta listar la clave.

```bash
sudo cryptsetup open "$BACKUP_DISK" gaia-signing-backup
sudo mount -o nodev,nosuid,noexec /dev/mapper/gaia-signing-backup /mnt/gaia-signing-backup
export BACKUP_HOME=/mnt/gaia-signing-backup/gnupg
printf 'GAIA offline backup signing check\n' > /mnt/gaia-signing-backup/backup-check.txt
gpg --homedir "$BACKUP_HOME" --local-user "${FPR}!" --armor --detach-sign \
  --output /mnt/gaia-signing-backup/backup-check.txt.asc /mnt/gaia-signing-backup/backup-check.txt
install -d -m 0700 /mnt/gaia-signing-backup/public-check
gpgv --homedir /mnt/gaia-signing-backup/public-check --keyring "$GAIA_PROJECT/keys/gaia-release-signing.pub.gpg" \
  /mnt/gaia-signing-backup/backup-check.txt.asc /mnt/gaia-signing-backup/backup-check.txt
gpgconf --homedir "$BACKUP_HOME" --kill all
sync
sudo umount /mnt/gaia-signing-backup
sudo cryptsetup close gaia-signing-backup
```

Exigir firma válida de la identidad anotada. El sufijo `!` fuerza esa clave exacta
en GnuPG. Guardar los USB cerrados/desconectados en lugares separados. Conservar
fuera del PC las contraseñas necesarias según la custodia del propietario.

## 9. Protocolo preparado para los artefactos GAIA

Se firma **el manifiesto exacto**, que vincula nombres, tamaños y SHA-256 de todos
los artefactos. El exportador de release/recuperación aún debe integrarse con sus
puertas; esta herramienta de verificación no declara S1 completada.

Formato `release-manifest.json` (ejemplo de estructura, no un release real):

```json
{
  "schema": "gaia-signed-artifacts-v1",
  "purpose": "release",
  "signing_fingerprint": "HUELLA_COMPLETA_CONFIRMADA_DE_40_HEX",
  "artifacts": [
    {"name": "disk.raw", "bytes": 123, "sha256": "SHA256_REAL_DE_64_HEX"}
  ]
}
```

`purpose=lab` separa bundles de laboratorio: el verificador exige `release` por
defecto y no acepta un bundle lab sin seleccionar explícitamente ese propósito.
Los nombres son archivos planos relativos, sin `..`, rutas absolutas ni symlinks.

### Firmar una futura entrega, solo el propietario

Con el primario abierto/montado, GAIA detenida, revisar el manifiesto y comprobar
sus hashes en el entorno confiable antes de firmar. No firmar automáticamente
resultados no inspeccionados. No se cambia `lab` a `release` para saltar puertas.

```bash
gpg --homedir /mnt/gaia-signing-primary/gnupg --local-user "${FPR}!" \
  --armor --detach-sign --output release-manifest.json.asc release-manifest.json
gpgconf --homedir /mnt/gaia-signing-primary/gnupg --kill all
sync
sudo umount /mnt/gaia-signing-primary
sudo cryptsetup close gaia-signing-primary
```

### Verificar sin privada

Usar la huella del registro externo, no una huella autoafirmada por el bundle.
La clave pública puede viajar en el medio, pero debe coincidir con ese anclaje.

```bash
python3 gaia.py appliance-verify \
  --public-key keys/gaia-release-signing.pub.gpg \
  --fingerprint "$FPR" \
  --manifest /ruta/entrega/release-manifest.json \
  --signature /ruta/entrega/release-manifest.json.asc \
  --artifacts-dir /ruta/entrega
```

La herramienta usa un homedir aislado público, gpg/gpgv y ningún keyserver/agent
de firma. Rechaza privada/subclaves, clave distinta, algoritmos no Ed25519,
estados de revocación/caducidad, firmas ambiguas, JSON con campos duplicados y
artefactos alterados. `SIGNED_ARTIFACTS_VERIFIED` significa firma e integridad,
**no instalación autorizada, prevención de rollback ni cierre de fase**. El
instalador deberá verificar de nuevo al consumir/copiar y aplicar sus políticas
de versión, identidad del destino y aceptación. Esa integración sigue pendiente.

## 10. Qué devolver y puerta de salida humana

Solo:

1. Los tres archivos **públicos** de `keys/` y su SHA-256.
2. La huella completa confirmada por ti contra el registro externo.
3. Confirmación de que ambos LUKS se reabren y de que la copia firma correctamente
   con el primario cerrado; ambos USB terminan cerrados y desconectados.

No entregar `gnupg/`, `private-keys-v1.d/`, `.rev`, exports secretos, contraseña
LUKS ni contraseña de la clave. No regenerar una clave si se duda de un comando:
revisar el estado existente antes de repetir pasos destructivos.

Con ese material podrá fijarse la raíz pública e integrarse la recuperación
firmada. La ausencia actual de material público mantiene abierta esa puerta S1.

## 11. Validación del mecanismo, sin privada GAIA

- 8 tests nuevos de pin de identidad, algoritmo/curva, rechazo de material no
  público, estados gpgv, rutas/symlinks, alteración de artefactos y orden de gates.
- Suite completa: **191 tests OK, 17.121 s, sin skips**.
  `.gaia/reports/20261016T124320Z-b4935330/REPORT.md`.
- Comprobación criptográfica real con metadatos **públicos de Debian trixie** y
  su clave pública Ed25519 instalada por la distribución: firma correcta aceptada
  por gpgv y por el parser de estado; contenido alterado rechazado con BADSIG.
  `.gaia/reports/20261016T124245Z-b08e3dd6/REPORT.md`,
  `PUBLIC_CRYPTO_CHECKS_PASSED`. No se generaron claves y no se adoptó Debian como
  identidad de firma GAIA. Se verificó también el formato de su pública con gpg.
- Ayuda CLI real sin site-packages: `python3 -S gaia.py appliance-verify --help`.
- La prueba end-to-end con pública/firma del propietario y la integración en el
  instalador siguen pendientes. No se han formateado ni abierto los USB por el
  agente, instalado cryptsetup ni alterado los ensayos VM anteriores.
