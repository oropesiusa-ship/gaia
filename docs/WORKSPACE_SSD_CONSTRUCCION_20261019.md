# Workspace ext4 en SSD autorizado — 2026-10-19

## Estado

**Actualización:** montaje completado por el propietario en `111130Z-503c0ab6`,
reverificado por agente en `111229Z-47cd4091`. Builder y fixtures ya usan el SSD;
imagen NVIDIA construida y matriz VM completa. No repetir el montaje salvo que
se haya desmontado. Estado vigente y siguiente firma humana:
[VALIDACION_NVIDIA_WORKSPACE_20261019.md](VALIDACION_NVIDIA_WORKSPACE_20261019.md).
El contenido inferior conserva el procedimiento de preparación original.

**Archivo ext4 preparado y comprobado; montaje pendiente de sudo humano.**
No se declara resuelto todavía el ensamblado ni completada F1. El propietario
aprobó expresamente crear el contenedor en el SSD después de la propuesta.

- SSD: Samsung870EVO1TB, capacidad1000204886016 bytes, identidad completa comprobada
  localmente; partición de datos UUID `661EC3B41EC37C15`, NTFS3, montada read/write.
- Archivo nuevo: `/run/media/mingororo/661EC3B41EC37C15/GAIA-build-workspace.ext4`.
- Tamaño y asignación real: **128849018880 bytes / 120GiB**. No es archivo sparse
  sin reserva; fallocate asignó su capacidad en el volumen anfitrión.
- Ext4 UUID: `40b184e0-21a2-43e9-8d02-df296c6d28af`, etiqueta `GAIA-BUILD`.
- Propietario del directorio raíz ext4: UID1000/GID1000, fijado al crear filesystem.
- e2fsck -f -n: cinco pasadas correctas, salida0.
- Estado: `.gaia/build-workspace.json`.
- Informe: `.gaia/reports/20261019T110456Z-3a1a67b0/REPORT.md`,
  **EXT4_WORKSPACE_FILE_READY_AWAITING_MOUNT**.

Se creó exclusivamente ese archivo; no hubo cambios de particiones ni de archivos
anteriores. No se tocó Shared, medios de claves o HDD de recuperación.

## Intervención humana exacta

Desde `~/Projects/GAIA`, ejecutar este bloque en la terminal del propietario:

```bash
(
set -euo pipefail
IMAGE=/run/media/mingororo/661EC3B41EC37C15/GAIA-build-workspace.ext4
WORK=/mnt/gaia-build
EXPECTED_UUID=40b184e0-21a2-43e9-8d02-df296c6d28af
test -f "$IMAGE"
test ! -L "$IMAGE"
test "$(stat -c %s "$IMAGE")" = 128849018880
test "$(blkid -p -s UUID -o value "$IMAGE")" = "$EXPECTED_UUID"
test ! -L "$WORK"
if mountpoint -q "$WORK"; then
    test "$(findmnt -n -o UUID --target "$WORK")" = "$EXPECTED_UUID"
else
    sudo install -d -m 0755 "$WORK"
    sudo mount -t ext4 -o loop,nosuid,nodev "$IMAGE" "$WORK"
fi
python3 docs/verify_build_workspace_20261019.py
)
```

No se ejecuta mkfs otra vez. Se mantiene ejecución de binarios dentro del ext4
porque el constructor necesita chroot; nosuid y nodev limitan el montaje anfitrión.
No se añade montaje permanente a fstab. Si termina correctamente devolverá
`LINUX_BUILD_WORKSPACE_READY` con la ruta del informe. El agente volverá a comprobar
el estado antes de construir. No basta con ejecutar sudo -v en otra terminal:
el paso necesario es montar realmente el archivo.

## Verificación posterior e integración

El verificador comprueba montaje ext4, UUID, loop backing exacto, propietario,
espacio suficiente y operaciones reales de permisos, hardlinks, symlinks, xattrs
y archivos sparse en un temporal propio. Crea tmp/reports/artifacts solo dentro
del filesystem autorizado, valida propiedad y registra resultado. Es una prueba
real tras montar, no ejecutada todavía por el agente.

Después de ese resultado se continuará con la integración del workspace en el
constructor: **temporales y salidas voluminosas deben ir al SSD**. Cambiar solo
TMPDIR no basta porque el constructor actual también comprueba el espacio del
proyecto y publica allí imágenes. Se conservarán informes/procedencia en el
proyecto y se registrarán rutas/hash de los artefactos externos. Falta realizar
esa integración, construir imagen CUDA/instalador y las demás validaciones físicas
según el plan; no se da por superado ese trabajo al crear el contenedor.

## Incidencia y comprobaciones

Primer intento `20261019T110446Z-80e6efb3` abortó antes de crear el archivo por
inventario lsblk sin árbol; se añadió --tree explícito para reconstruir la relación
disco/partición incluso al no pedir columna NAME. Segunda ejecución completada.
No hubo sobrescrituras ni reintentos de formato de un archivo existente.

Sudo no interactivo devuelve `interactive authentication is required`. El montaje
no puede completarse desde el agente con los permisos actuales. Informe de parada:
archivo120GiB creado, ext4 comprobado, plan actualizado; solo se requiere el bloque
anterior. El alcance completo de F1 permanece abierto.
