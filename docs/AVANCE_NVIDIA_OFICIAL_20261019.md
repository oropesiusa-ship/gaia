# NVIDIA oficial: entradas, módulos y rootfs — 2026-10-19

## Estado real de la fase

**Driver oficial resuelto, módulos compilados y rootfs NVIDIA construido y
auditado. F1 NO completada.** La siguiente construcción de imagen está bloqueada
por presupuesto del constructor actual: requiere 84521353216 bytes libres y hay
36912422912. Déficit: 47608930304 bytes. No se lanzó un ensamblado que pudiera
agotar el filesystem. No se declara todavía imagen física, instalador ni GPU
validada. La referencia CPU/VM aceptada se conserva.

El propietario aprobó ampliar la fuente NVIDIA («Si seguimos») y después pidió
continuar hasta cumplir el objetivo completo sin reducir alcance. Se conservan
todos los requisitos pendientes; esta es una parada por recursos, no un cierre.

## 1. Fuente oficial autenticada y congelada

- Repositorio: `https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/`.
- Huella fijada de clave pública: `EB693B3035CD5710E231E123A4B469963BF863CC`.
- Verificación real gpgv de InRelease y SHA-256/tamaño de Packages.gz.
- Driver **580.178.04-1**, superior al mínimo560.28.03, módulo propietario.
- Documentación del driver seleccionado confirma **GTX1060 6GB / PCI1C03**.
- Debian13 NVIDIA empieza en ramas posteriores sin Pascal; se usan exclusivamente
  paquetes580 de la fuente oficial Debian12, resolviendo sus dependencias sobre
  Debian13/snapshot fijado. No se mezclan paquetes Debian12 del sistema operativo.
- Kernel y cabeceras: **6.12.107+deb13-amd64 / 6.12.107-1**.
- Perfil compute-only: libcuda1, libnvidia-ml1, nvidia-smi, módulo y dependencias.
  No se selecciona módulo open, toolkit ni cuda-compat. Lock Python/Torch intacto.
- Evidencia y archivos descargados:
  `.gaia/reports/20261019T102204Z-922ea833/REPORT.md`,
  **NVIDIA_OFFICIAL_COMPUTE_INPUTS_VERIFIED**. `official-inputs.json` conserva
  nombres/versiones/hashes/tamaños de todos los .deb descargados.

## 2. Compilación real de módulos

`.gaia/reports/20261019T103018Z-602c9ef1/REPORT.md`,
**NVIDIA_KERNEL_MODULES_BUILT**. Compilación mediante DKMS dentro de mmdebstrap
unshare; sin cargar módulos ni tocar el kernel del anfitrión.

Verificados nvidia, nvidia_modeset, nvidia_drm y nvidia_uvm: versión580.178.04 y
vermagic del kernel fijado. La licencia NVIDIA del módulo principal demuestra
que no se ha elegido el módulo open. DRM/UVM tienen sus propias licencias MIT/
DualMIT-GPL, sin confundirlas con la elección del módulo principal. Se conservan
archivo tar de módulos, modinfo, estado DKMS y make.log.

Las claves MOK de compilación que DKMS genera dentro del entorno desechable son
distintas de la clave de release del propietario. No hubo uso de privada de
release ni se afirma SecureBoot; el plan requiere SecureBoot desactivado.

## 3. Rootfs integrado y lectura de comprobación

`.gaia/reports/20261019T103937Z-05e8888d/REPORT.md`,
**NVIDIA_RUNTIME_ROOTFS_BUILT**.

- Artefacto: `rootfs.tar`, **8519598080 bytes**.
- SHA-256: `d347405889851b87266774d408b74b543bdd26590fca5e5dcd6ba6d764444572`.
- Derivado del runtime fijado original; Python/NumPy/Torch no se recompilan ni
  reinstalan. Se conservan los inventarios y la procedencia anterior.
- Instalación offline de bibliotecas compute580 y nvidia-smi desde .deb verificados.
- Integración de los cuatro módulos ya compilados, depmod y blacklist de nouveau.
- Carga de libcuda.so.1/libnvidia-ml.so.1 comprobada por ctypes dentro del rootfs;
  no equivale a cuInit ni a cargar el módulo en hardware.
- Inventario dpkg real leído del tar y versiones comprobadas.
- Auditor independiente vuelve a leer los cuatro módulos del tar de runtime y
  compara byte a byte sus hashes con los de la compilación independiente.
- `gpu_tested=false`; el smoke CPU heredado es evidencia del runtime padre, no
  una nueva ejecución CPU ni un ensayo CUDA de este rootfs.
- Sigue siendo rootfs de construcción: retiro final de toolchain, ajuste del
  servicio CUDA, initramfs/UKI y aceptación arrancable pendientes.

Auditoría:
`.gaia/reports/20261019T105034Z-cb1bf2cc/REPORT.md`,
**NVIDIA_IMAGE_WORKSPACE_BLOCKED**, con `integrated_module_readback_ok=true`.
Reproducción: `python3 docs/audit_nvidia_runtime_20261019.py`.

## 4. Incidencias y correcciones

Se conservan también informes fallidos; no se contabilizan como validaciones:

1. `102056Z-81289138`: clave NVIDIA válida en gpgv, pero el primer APT exterior
   de mmdebstrap no veía la ruta signed-by del chroot. Abortó antes de instalar.
2. `102127Z-4da22341`: --keyring no era aditivo y la ruta bajo home privado no
   era atravesable por _apt. Corregido con keyring público combinado temporal,
   ruta atravesable y permisos644; sin cambiar permisos del home ni desactivar firmas.
   El siguiente probe `102204Z-922ea833` completó resolución y descarga verificadas.
3. `102930Z-79705fba`: APT --no-download con .deb locales necesitaba los archivos
   en su cache. Se copiaron los paquetes ya verificados a esa cache; la siguiente
   compilación `103018Z-602c9ef1` terminó correctamente.
4. `103349Z-cbbb243f`: intentar recompilar DKMS dentro del runtime importado falló
   y aparecieron errores de módulos faltantes al regenerar initramfs. No se aceptó
   el rootfs. Se descartó esa recompilación redundante, integrando en cambio los
   módulos independientes ya verificados. Además, las exclusiones tar de /dev se
   anclaron a raíz para no excluir directorios internos llamados dev. No se atribuye
   causa exacta del fallo de make sin su log interno, que no se exportó en ese intento.
   El siguiente rootfs `103937Z-05e8888d` se construyó correctamente y pasó readback.

No queda un bucle de esos intentos. El bloqueo actual es espacio antes del siguiente
ensamblado, no un reintento de cualquiera de esos fallos.

## 5. Limpieza y comprobaciones de código

Se comprobó que la limpieza interrumpida no seguía ejecutándose. Se reanudó la
política autorizada, conservando ambas bases de referencia, rootfs padre y últimos
targets reparados, incorporando la retención del target CPU actual.
Retirados cache bundle regenerable y ESP staging elegibles, con hashes/procedencia/
uso: `.gaia/reports/20261019T102627Z-16fa1bc7/REPORT.md`,
**DISPOSABLE_ARTIFACTS_CLEANED**. No se borraron carpetas de informes ni claves.

Código nuevo/extendido:

- `gaia/appliance_nvidia.py`: CLI resolución, evaluación, fuente oficial,
  compilación de módulos e integración de runtime.
- `gaia/appliance_nvidia_source.py`: autenticación, fijación, resolución y build.
- `gaia/appliance_nvidia_build.sh`: compilación aislada.
- `gaia/appliance_nvidia_integrate.sh`: integración offline de bibliotecas/módulos.
- `tests/test_appliance_nvidia.py`: seis pruebas del gate y parsers.
- `docs/audit_nvidia_runtime_20261019.py`: identidad/readback/presupuesto.

Comprobaciones ejecutadas:

```bash
python3 -m unittest discover -s tests -p 'test_appliance_*.py' -v
sh -n gaia/appliance_nvidia_build.sh gaia/appliance_nvidia_integrate.sh
```

**85 tests correctos, 0 skips, 0.665s**. Sintaxis shell correcta.
No se presenta esto como suite completa del proyecto ni como prueba GPU física.

## 6. Bloqueo actual y continuación exacta

El presupuesto de imagen se calcula con la misma fórmula de `appliance_image.build`
y el tamaño real del rootfs nuevo. Requiere **84.52GB decimales / 78.72GiB** libres;
disponibles **36.91GB / 34.38GiB**; faltan **47.61GB / 44.34GiB**.
Es pico conservador del constructor, no tamaño final de imagen ni mínimo del HDD.
La limpieza ya autorizada aplicada no alcanza bajo las referencias retenidas actuales.

Hay que refinar el presupuesto antes del ensamblado: proporcionar filesystem Linux
de construcción con cabida o revisar explícitamente la retención de referencias
anteriores/estrategia de construcción para alcanzar ese margen. No se usa como
scratch el disco diario ajeno ni se formatea el HDD externo para resolverlo de forma
implícita. No se pide repetir autorizaciones de limpieza de fixtures ya elegibles.

Después: construir perfil arrancable CUDA e instalador físico con gates S0,
validación VM pertinente, firma del paquete físico listo, preparación del medio
autorizado, arranque físico S0 y S2–S4. La prueba GPU real requerirá la intervención
física humana prevista. **No se afirma que esos trabajos estén hechos.**

## Informe de parada

La ampliación de fuente aprobada se ha ejecutado hasta entradas oficiales,
compilación y rootfs integrado verificados. La sustitución del HDD dejó de ser
bloqueo por decisión del propietario. No hubo formateos, montajes de custodia,
instalación en medios físicos ni cambios del driver del Ubuntu anfitrión.
Se para por presupuesto comprobado insuficiente de imagen, con alcance completo
conservado y sin declarar F1 terminada ni pedir una firma de un paquete no preparado.
