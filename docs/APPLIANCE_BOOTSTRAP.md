# Preparar el host de construcción de GAIA

Desde la raíz del proyecto, en una terminal local:

```bash
python3 gaia.py appliance-bootstrap
```

Solo requiere Python estándar para arrancar. El perfil inicial admite hosts
Debian/Ubuntu Linux x86_64. Es preparación del **equipo que construye y prueba**
la appliance, no una instalación de la appliance en ese equipo.

## Flujo interactivo

1. Consulta sistema/arquitectura, paquetes y versiones instaladas, herramientas,
   pareja de firmware OVMF, acceso KVM, espacio libre y posibilidad de crear un
   namespace para el rootfs. Registra presencia de UEFI e inventario de metadatos
   de medios sin seriales, WWN ni nombres de volúmenes. La capacidad libre es
   informativa: el mínimo real del build se fijará con las imágenes.
2. Muestra los paquetes ausentes, su función y los dos comandos exactos propuestos.
3. Pregunta `¿Instalar los paquetes mostrados? [s/N]:`. Enter/no cancela.
4. Ejecuta únicamente `apt-get update --error-on=any` y `apt-get install` con la
   lista fija de paquetes que faltan. Si hace falta elevar privilegios, `sudo`
   solicita la contraseña **directamente en la terminal**. GAIA no la pide, lee,
   almacena ni redirige. La salida de apt/sudo permanece en el terminal; el informe
   guarda argumentos, duración y código de salida, no una captura de esa sesión.
5. Vuelve a diagnosticar, ejecuta probes de versión de mmdebstrap/QEMU/qemu-img y
   comunica si las herramientas están listas o persiste un bloqueo.

Catálogo del host: mmdebstrap, qemu-system-x86, qemu-utils, ovmf, uidmap,
smartmontools, mtools, dosfstools, e2fsprogs, binutils y fdisk. Los tres últimos
permiten ext4, UKI y verificación GPT sobre archivos de imagen. Se instalan solo
los ausentes o incompletos.
Los binarios de apt/sudo tienen rutas absolutas, sin shell ni paquetes arbitrarios
aportados por argumentos. `--yes` se usa dentro de apt **después** de la
confirmación del comando; no existe una opción para saltar la confirmación de GAIA.
`--no-remove` evita resolver dependencias mediante eliminación de paquetes.

En ejecuciones posteriores se comprueba el estado real, sin confiar en un marcador
READY antiguo. Si ya están los paquetes, herramientas y firmware, no se instala ni
se pide confirmación/contraseña. Los errores se registran y se puede reejecutar
el mismo comando; no se relanza apt en bucle ni se declara éxito tras una instalación
parcial. Se comparte la exclusión mutua con el bootstrap existente.

## Diagnóstico sin instalación

```bash
python3 gaia.py appliance-bootstrap --preflight
```

No solicita confirmación ni llama a sudo/apt. Guarda el diagnóstico incluso si
faltan paquetes o falla el probe de namespaces. También funciona sin NumPy/Torch:

```bash
python3 -S gaia.py appliance-bootstrap --help
```

El modo normal requiere terminal interactiva si hay algo que instalar. Desde una
herramienta sin TTY devuelve 10 y pide ejecutar el mismo comando en una terminal.
No se debe ejecutar todo GAIA con `sudo` ni configurar sudo global sin contraseña.

## Informes y códigos de salida

Cada ejecución crea `.gaia/reports/<fecha>-<id>/report.json` y `REPORT.md`.
Los probes tienen sus logs stdout/stderr, y el informe contiene diagnóstico
anterior/posterior, comandos propuestos, confirmación y resultado de instalación.

| Estado | Código | Qué significa |
|---|---|---|
| `APPLIANCE_HOST_READY` | 0 | Herramientas, firmware y probes iniciales disponibles; no certifica un build |
| `APPLIANCE_HOST_PACKAGES_MISSING` | 10 | Diagnóstico: faltan paquetes/herramientas/firmware |
| `NEEDS_INTERACTIVE_TERMINAL` | 10 | Ejecutar el comando en terminal local para confirmar e instalar |
| `APPLIANCE_HOST_TOOLS_READY_ROOTFS_BLOCKED` | 10 | Herramientas listas, pero el probe de namespaces falla |
| `CANCELLED` / `INTERRUPTED` | 130 | Usuario cancela, EOF o Ctrl+C |
| `FAILED` | 40 | Host no admitido, exclusión mutua, apt/sudo/probe fallido o instalación incompleta |

La prueba principal utiliza `mmdebstrap --unshare-helper` y verifica también un
namespace de montaje. En Ubuntu el perfil AppArmor de mmdebstrap puede permitir
esta operación aunque el `unshare` genérico falle; ambos resultados quedan en el
informe, sin confundirlos. Si también falla el helper real, el comando no modifica
AppArmor/sysctl para forzarlo: queda pendiente resolver la vía rootless o definir
una ejecución privilegiada delimitada del constructor.
La falta de acceso KVM y la ausencia de UEFI en el host se registran; no prueban que
QEMU no pueda emular o que el destino físico carezca de UEFI. S0 físico conserva
sus comprobaciones propias de firmware, salud e identidad.

## Relación con el plan maestro

Este comando implementa el aprovisionamiento inicial de herramientas de F1/S1.
**Todavía no invoca un constructor de imágenes ni un instalador o ensayo VM**;
la construcción de rootfs se ejecuta por separado como se indica abajo, y los
ensayos VM siguen pendientes. El informe
permite retomarlo con el estado real del host. No particiona/formatea medios ni
escribe su contenido. Las autorizaciones de Shared y del HDD externo permanecen
registradas en el [plan maestro](PLAN_MAESTRO_GAIA.md#13-fase-1-ejecutable-instrumento-de-host).

Las dependencias del host no se convierten automáticamente en dependencias de
la appliance: la imagen Debian tendrá su snapshot, manifiesto, Python y runtime
fijados, instalados al construir. El sistema final funcionará con sus componentes
locales y no necesitará instalar QEMU/mmdebstrap para arrancar GAIA. La facilidad
de uso del bootstrap no sustituye la instalación/recuperación física aún pendiente.

## Construir la base Debian de S1

```bash
python3 gaia.py appliance-rootfs
```

Construye un tar de Debian trixie/amd64 desde el snapshot
`20261015T000000Z`, con mmdebstrap en modo unshare, sin sudo. APT exige firmas de
Debian y hashes de los paquetes; se desactiva únicamente la caducidad temporal de
los metadatos históricos. El tar se inspecciona sin extraerlo en el host para
verificar los paquetes instalados, kernel, initramfs y binarios EFI. Guarda el
manifiesto de versiones y SHA-256 en el directorio del informe, junto al artefacto.
`DEBIAN_BASE_ROOTFS_BUILT` **no significa imagen arrancable ni S1 completo**.

Para incorporar el runtime de construcción de GAIA:

```bash
python3 gaia.py appliance-rootfs --with-runtime
```

Esta opción compila Python 3.14.4 dentro del Debian, verificando el SHA-256 de la
fuente publicado en Python.org, y crea `/opt/gaia/venv` desde cero. Instala Torch,
NumPy y dependencias con el lock existente y `pip --require-hashes`, y exige un
smoke del modelo causal en CPU con un usuario no root. No copia el venv del host.
Las herramientas de compilación se instalan dentro de este rootfs de construcción;
su retirada de la imagen de release sigue pendiente. El driver NVIDIA y la prueba
CUDA real no se validan desde este chroot.

Presupuesto temporal: 2 GiB para la base y 16 GiB para el runtime; además se exige
espacio de trabajo en el proyecto (8/32 GiB respectivamente). Son presupuestos
conservadores de construcción, **no una capacidad mínima medida para el USB**.
El comando comprueba el espacio y el acceso de los usuarios mapeados antes de
descargar/compilar. Si el temporal predeterminado es pequeño o inaccesible, prueba
`/var/tmp`; registra la selección y los candidatos descartados. Para fijarlo:

```bash
python3 gaia.py appliance-rootfs --with-runtime --tmpdir /var/tmp
```

No cambia permisos del home, políticas de namespaces ni montajes del host. El
directorio elegido debe existir y ser accesible; mmdebstrap crea su subdirectorio
temporal. Tras corregir el selector, la ejecución real de
`appliance-rootfs --with-runtime` terminó con **DEBIAN_RUNTIME_ROOTFS_BUILT**:
`.gaia/reports/20261016T102648Z-70fc2c5a/REPORT.md`. Seleccionó `/var/tmp` sin
parámetros adicionales y pasó el smoke CPU no root. Tar de 7817448960 bytes,
hash e inventario contrastados con el artefacto. Esto completa la construcción
del runtime, pero no la imagen arrancable ni los ensayos de aceptación S1.
Detalles y evidencias en `EJECUCION_PLAN_MAESTRO_GAIA.md`.

## Imágenes UEFI y pruebas VM de S1

```bash
python3 gaia.py appliance-image --rootfs-manifest .gaia/reports/20261016T102648Z-70fc2c5a/rootfs-manifest.json
```

Construye una imagen **de laboratorio** y ejecuta tres arranques smoke de VM.
La fuente se valida contra hash e inventario antes de extraer. Se construyen GPT,
ESP, CORE, A/B y DATA sobre archivos regulares, sin sudo, loop devices ni montajes
del host; mmdebstrap transfiere entradas/salidas sin ampliar permisos del home.
La construcción utiliza un presupuesto de espacio calculado a partir del rootfs.

Para reutilizar las imágenes y ejecutar los escenarios implementados:

```bash
python3 gaia.py appliance-image --image-dir .gaia/reports/20261016T113055Z-a9d2a6f2 --boot-scenarios
```

Cada escenario utiliza overlays desechables y tiene timeout. Por defecto son
tres repeticiones; `--scenario` selecciona ámbitos y `--repeats 1..3` sirve para
desarrollo. `--refresh-core` crea una revisión nueva del CORE/UKI sin recompilar
Python/Torch, conservando ambos root slots y DATA; si cambian las unidades de
servicio del rootfs, exige reconstrucción. Se detiene ante el primer fallo y
conserva logs, sin reintentos automáticos. Las imágenes anteriores no se alteran.

Estados: `VM_FOUNDATION_VALIDATED` y `VM_BOOT_SELECTION_VALIDATED` certifican
únicamente los ámbitos registrados. **No equivalen a S1/F1 OK ni a imagen de
release firmada.** Los scripts del payload se ejecutan solo dentro de la VM.
Resultados y punto humano de firma: [VALIDACION_APPLIANCE_S1_VM.md](VALIDACION_APPLIANCE_S1_VM.md).

Actualización 2026-10-18: matriz actual de diez escenarios 3/3, DATA, SIGKILL del
publicador, bendición/rechazo por salud y USB emulado, con verificación pública
del propietario en Debian. Informe vigente:
[VALIDACION_APPLIANCE_S1_20261018.md](VALIDACION_APPLIANCE_S1_20261018.md).
El controlador `appliance-recovery` prepara solicitudes con `--image-dir` y
ejecuta los casos positivos con `--bundle-dir` solo tras verificar firma lab.
Estos positivos están pendientes de firma humana. La negativa de firma en USB
ya pasó 3/3 con target intacto. No equivale a un instalador físico autorizado.

Firma lab recibida y caso positivo completado después: **tres instalaciones,
tres reparaciones que conservan DATA y seis boots independientes**. Informe
`.gaia/reports/20261018T203350Z-9e9b020a/REPORT.md` y
[validación firmada](VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md).
`appliance-recovery --resume-report DIR` puede reutilizar el bundle y prefijo
verificado de una suite fallida, junto con `--image-dir` y `--bundle-dir`.
Comprueba la misma firma/fuente, hash del cache, estructura y ausencia de cambios
del target antes de reanudar; no es un modo para omitir validaciones.
