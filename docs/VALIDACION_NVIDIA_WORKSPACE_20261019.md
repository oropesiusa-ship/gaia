# Workspace operativo e imagen NVIDIA: validación actual

Fecha2026-10-19. **Candidato NVIDIA construido y matriz VM completa; firma de
diagnóstico físico pendiente. F1 abierta; GPU real no probada.**

## 1. Workspace desbloqueado de forma real

Propietario aporta `20261019T111130Z-503c0ab6`, `LINUX_BUILD_WORKSPACE_READY`.
Nueva comprobación del agente `20261019T111229Z-47cd4091`, mismo estado:
ext4 UUID40b184e0-21a2-43e9-8d02-df296c6d28af, loop backing exacto del SSD
autorizado, usuario1000, enlaces/permisos/xattrs/sparse y capacidad correctos.

Se implementa `gaia/appliance_workspace.py` y `appliance-image --workspace`:
el builder usa `/mnt/gaia-build/tmp` y publica los artefactos grandes bajo
`/mnt/gaia-build/artifacts/<id>`. Sus gates comprueban ese filesystem, no el espacio
del disco diario. VM fixtures también usan SSD; `WorkspaceSession` refleja
report.json/REPORT.md en `.gaia/reports/<id>`, con rutas de logs/fixtures externos.
Logs completos y discos VM siguen en el SSD. No se ocultan como archivos locales.
Se vuelve a verificar montaje/UUID/backing antes de cada sesión externa.

## 2. Construcción NVIDIA realizada

Comando ejecutado:

```bash
python3 gaia.py appliance-image \
  --rootfs-manifest .gaia/reports/20261019T103937Z-05e8888d/rootfs-manifest.json \
  --workspace --nvidia-candidate --build-only
```

Informe `.gaia/reports/20261019T111348Z-95cd9936/REPORT.md`,
**NVIDIA_DELIVERY_CANDIDATE_BUILT**.

- Artefactos: `/mnt/gaia-build/artifacts/20261019T111348Z-95cd9936/`.
- Imagen25075646464 bytes (25.08GB lógicos), SHA256
  `63dc4c7ee9d905edcf2cd61a0f107c7861d03d7bad8c36332e1f0cd5f795b0a4`.
- Perfil `nvidia-delivery-candidate`, L0, NVIDIA580.178.04/kernel6.12.107.
- Se instala el helper nvidia-modprobe del cache verificado; se incluyen módulos
  NVIDIA en initramfs y blacklist de nouveau antes de construir UKI.
- Retirada protegida del toolchain: 34 paquetes eliminados, sin autoremove;
  inventario retenido/versión antes y después conservado en image-manifest.json.
- Servicio fijo gaia-gpu carga módulos y crea nodos GPU; runtime sin root,
  capacidades vacías, NoNewPrivileges, red privada/AF_UNIX, DevicePolicy=closed
  con allowlist nvidia0/nvidiactl/nvidia-uvm y escritura solo en su DATA.
- Runtime CPU fija ABI/pip/modelo como antes y después exige CUDA, driver exacto,
  una GPU Pascal con memoria suficiente y GaiaTransformer CUDA finito. No pasa
  a estado READY usando CPU si falta GPU. Código preparado; no probado en hardware.
- El test VM sigue seleccionando explícitamente gaia.mode=vm-test sobre UKI de
  fixture. Ese probe no habilita CUDA ni representa el runtime físico normal.

La CPU anterior no se reconstruyó ni cambió de hash. Esta nueva identidad conserva
release_image=false y gpu_tested=false hasta completar las puertas correspondientes.

## 3. Matriz VM: diez escenarios3/3 sobre el nuevo hash

Primera ejecución:
`/mnt/gaia-build/artifacts/20261019T112849Z-1a4842c4/report.json`.
Terminó por límite global de3600s de la herramienta, no por fallo de aceptación.
Se comprobó que no quedaban QEMU/controlador activos. Su registro conserva status
running porque la terminación externa no permitió al proceso finalizar el informe;
no se presenta ese estado como suite final satisfactoria.

De ese registro se seleccionan **solo los ocho primeros escenarios completamente
guardados, tres repeticiones cada uno**: A, B, agotamiento/fallback, staging parcial,
B corrupto, DATA/restauración, interrupción real de publicación y salud/bendición.

Los restantes se ejecutaron explícitamente:

```bash
python3 gaia.py appliance-image \
  --image-dir /mnt/gaia-build/artifacts/20261019T111348Z-95cd9936 \
  --workspace --boot-scenarios --scenario health-reject --scenario usb-smoke --repeats 3
```

Informe externo `20261019T122929Z-aa6cdca6/REPORT.md`,
**VM_BOOT_SELECTION_VALIDATED**, reflejado también en `.gaia/reports`.

Auditoría `.gaia/reports/20261019T125118Z-1bba0062/REPORT.md` comprueba:
hash común, exactamente30 pares únicos escenario/repetición satisfactorios y
**63 arranques** seleccionados. No suma el health-reject completo duplicado ni
el parcial del intento interrumpido. No es una repetición global del trabajo CPU:
es aceptación de la imagen NVIDIA nueva, cuyo rootfs/kernel/initramfs/servicios
han cambiado. No hay bucle de errores; el único incidente de esta matriz fue el
límite temporal global y se continuó mediante escenarios concretos pendientes.

## 4. Código y comprobaciones

- Nuevos flags --workspace, --nvidia-candidate, --build-only con validación CLI.
- Builder registra salida externa y procedencia/payload hashes localmente.
- Extracción tar usa exclusiones /dev ancladas para conservar rutas internas.
- Servicio GPU/allowlist y smoke CUDA añadidos sin conceder L2.
- Tres tests nuevos verifican rechazo de montaje/UUID/tipo alterados, espejo de
  informes y rechazo CUDA por driver incorrecto o GPU ausente, sin fallback CPU.
- **88 tests appliance correctos, sin skips, 0.970s**, ejecutados después de cambios:
  `python3 -m unittest discover -s tests -p 'test_appliance_*.py'`.
- No se atribuyen a estos tests una ejecución GPU ni toda la suite del proyecto.

## 5. Parada humana concreta: firma del diagnóstico físico

Manifiesto preparado sin privada mediante
`python3 docs/prepare_nvidia_gpu_preflight_20261019.py`, informe
`.gaia/reports/20261019T125118Z-1bba0062/REPORT.md`,
**AWAITING_OWNER_PHYSICAL_GPU_PREFLIGHT_SIGNATURE**.

Manifiesto `/mnt/gaia-build/artifacts/20261019T125118Z-1bba0062/gpu-preflight-manifest.json`.
SHA256 `2f2401fe2092e3e9bfd5a82780270eb05addb88683966dfede7fce4b0a973c77`.
Tipo `gaia-physical-gpu-preflight-v1`, lab, L0. Vincula imagen y manifiesto por
hardlinks del mismo filesystem, sin duplicar25GB. **No es un instalador físico ni
firma final de F1.** Debe haber arranque GPU real para aceptar el perfil CUDA.
Procedimiento exacto: [APPLIANCE_FIRMA_PREFLIGHT_GPU.md](APPLIANCE_FIRMA_PREFLIGHT_GPU.md).

Tras firma: preparar controlador de escritura/readback para HDD externo ya
autorizado, ejecutar esa preparación privilegiada con humano, desconexión de
discos ajenos/claves y arranque diagnóstico. Esa preparación física todavía no
se ha ejecutado. El instalador interno real, dimensionamiento DATA, robustez,
baseline y recuperación S0/S2–S4 conservan requisitos pendientes; no se declaran
implementados ni superados. No se solicita otra decisión sobre el HDD diagnosticado.

## 6. Estado al parar

Espacio al final de validación:43.70GB libres en ext4 de construcción y36.85GB en
filesystem del proyecto. La construcción y los fixtures grandes usaron el SSD;
no reaparece el bloqueo anterior del disco diario durante este ensayo.
Fixtures/manifiestos/logs se conservan; no se aplicó borrado automático externo.

Solo se escribieron archivos de construcción/pruebas dentro del SSD autorizado
y documentación/código/informes del proyecto. No se instaló el driver en el host,
no se escribieron particiones ni el HDD de recuperación, no se abrieron claves.
La firma offline es la primera necesidad humana tras validar la matriz.
**Objetivo completo pendiente: F1 NO terminada; esta parada no reduce su alcance.**
