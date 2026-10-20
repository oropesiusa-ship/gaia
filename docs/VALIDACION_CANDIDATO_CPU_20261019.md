# Candidato CPU depurado y limpieza continua

Fecha: 2026-10-19. **Candidato CPU/VM firmado y ACEPTADO.**
Actualización final: tres instalaciones/reparaciones firmadas y seis boots
operativos correctos, informe `20261019T091600Z-78c27069`; auditoría
`20261019T100144Z-91a97bb3`, `S1_CPU_VM_ACCEPTED`.
La entrega física y F1 siguen abiertas. Cierre y transición:
[CIERRE_CPU_VM_20261019.md](CIERRE_CPU_VM_20261019.md).
Los apartados siguientes describen el historial previo a esa aceptación.

## 1. Limpieza autorizada y ejecutada

El propietario autorizó limpieza continua de pruebas prescindibles. Se implementó
`gaia/appliance_artifacts.py`, política local `.gaia/artifact-retention.json`.
Solo se retiran archivos identificados de `.gaia/reports`: se comprueban productor,
propietario, mtime, procesos, hashes y dependencias. Hijos antes de bases; archivos
desconocidos, activos, modificados, enlaces y referencias por inode se conservan.
No se borran directorios, logs, manifiestos, código, claves, corpus/checkpoints o
estados. Las bases firmadas vigentes y el último destino reparado quedan retenidos.

Plan: `20261019T070828Z-3bb4297f`; aplicación:
`.gaia/reports/20261019T071450Z-23655ad1/REPORT.md`,
**DISPOSABLE_ARTIFACTS_CLEANED**: 147 archivos, **84787912704 bytes asignados**,
espacio libre final **103532826624 bytes**. Son 53 overlays dependientes, dos
revisiones RAW retiradas, un bundle reconstruible y 91 staging FAT.
Los inputs firmados, firmas y evidencias de los ensayos siguen disponibles.
Una segunda limpieza automática posterior retiró staging completado de esta
revisión: `.gaia/reports/20261019T085951Z-6e28bdb0/REPORT.md`.

## 2. Nueva imagen e identidad

- `.gaia/reports/20261019T075104Z-0bda6b85/disk.raw`, 22577938432 bytes lógicos.
- SHA-256: `195cd3661217bd6cc4de8af38e314786a097994940cd61288ed4d1de2a9ed4de`.
- CORE SHA-256: `8592b02e4403081aacbfa12b7edf23b2d545b197b34971245ae60eff5a663f81`.
- Perfil `cpu-delivery-candidate`; `release_image=false`, `signed=false` mientras
  no se cumplan firma del nuevo paquete y aceptación final del perfil.
- Origen rootfs y lock Python/Torch fijados originales; no se recompiló Python.

El constructor simula la purga, exige que no afecte paquetes fuera de su lista,
elimina **34 paquetes** de ejecutables/cabeceras y compara el resultado real.
Se conservan **174 paquetes con versiones iguales**; no hay autoremove. Se mantienen
libgcc/libstdc++/libgomp, SSL y demás bibliotecas de ejecución. Binutils-common y
sus bibliotecas se conservan deliberadamente para evitar una retirada transitiva.
La lista exacta antes/después está en `image-manifest.json`, no se infiere solo de
la ausencia de un comando. No se purgó ningún paquete del Ubuntu del propietario.

## 3. Arranque operativo separado del probe

- `gaia-mode.service` selecciona un servicio fijo por modo: runtime normal o
  probe explícito `gaia.mode=vm-test` con perfil lab.
- `gaia-runtime.service`: usuario gaia, NoNewPrivileges, capacidades vacías,
  sistema protegido, dispositivos privados, red privada/AF_UNIX y escritura
  únicamente en su área DATA. Comprueba firma pública, runtime causal CPU y catálogo
  L0; publica estado atómico/sincronizado y permanece en espera offline.
- No se habilita L2 ni se atribuyen aún benchmarks Host Lab, investigación general
  o validación CUDA. El nivel L0 y el perfil CPU quedan explícitos en el estado.
- Hostname/hosts normalizados a `gaia` en esta construcción.

Tres arranques operativos independientes:
`.gaia/reports/20261019T080658Z-5d9d1767/REPORT.md`,
**CPU_DELIVERY_RUNTIME_VALIDATED**. Cada uno registra:

- UID 997, NoNewPrivs/capacidades comprobadas por el servicio.
- Python 3.14.4, NumPy 2.3.5, Torch 2.14.0+cu126, CUDA runtime 12.6 (GPU no probada).
- `pip check`: `No broken requirements found.`
- `ldd` del intérprete sin bibliotecas ausentes e imports nativos SSL/sqlite/bz2/
  lzma/zstd/ffi/readline/curses/gdbm/uuid correctos, más inferencia causal finita.
- Firma pública del propietario válida y una operación inventory del guardián.
- VM viva diez segundos después de readiness y parada controlada por QMP del
  harness. No se presenta QMP quit como ensayo físico de apagado/persistencia S4.

## 4. Matriz de aceptación repetida sobre el nuevo hash

Informes `.gaia/reports/20261019T081025Z-4e6e623f/REPORT.md` y
`.gaia/reports/20261019T083236Z-4b77c01a/REPORT.md`:
**diez escenarios, todos 3/3, 63 arranques** del mismo hash nuevo.

A, B, agotamiento/fallback, B corrupto, staging parcial, DATA lógico/restauración,
SIGKILL del publicador, bendición saludable, rechazo de salud y USB emulado.
Las UKI de test seleccionan explícitamente el probe sin modificar la imagen base.
No se importan los resultados anteriores como aprobación de la nueva identidad.

Negativa de firma en recuperación 3/3, destino intacto:
`.gaia/reports/20261019T085227Z-678598b8/REPORT.md`.
Se suma a tres arranques persistentes: **69 arranques de las ejecuciones finales
aceptadas** (incluyen fallos inyectados/esperados de la matriz y rechazo de firma).
No se cuentan intentos de desarrollo fallidos como repeticiones satisfactorias.

## 5. Incidencias y decisiones de ingeniería

- `073853Z-4e8b390b` y diagnóstico `074230Z-67430ede`: la simulación inicial
  quería retirar tres bibliotecas por dependencia de binutils-common; el guard
  abortó antes de la purga. Se conservó ese paquete común y la siguiente simulación
  autorizó exactamente 34 paquetes, comprobados tras la retirada.
- `074610Z-9fdc4388`: purga completada en rootfs temporal; bind /dev de validación
  chroot bloqueado por el namespace. Esa alternativa se retiró; no se relajó
  AppArmor ni se repitieron montajes. ABI/pip/smoke se validan en la VM real de
  destino. Las raíces temporales se descartaron; la referencia firmada anterior
  nunca se alteró.
- `075104Z-0bda6b85`: imagen construida, servicio llegó a READY; el primer runner
  interpretó un fragmento de línea serie antes de recibir el JSON completo.
  Corregido para esperar newline y exigir un único registro completo. Después
  pasaron tres arranques operativos sobre ese artefacto ya construido.

No queda un bucle de esos fallos. Todos se registraron; no se atribuye una
validación satisfactoria a los intentos fallidos ni a metadatos de paquetes solos.

## 6. Código y siguiente puerta humana

- 224 tests OK, 27.284 s sin skips:
  `.gaia/reports/20261019T085227Z-7811da92/REPORT.md`.
- Cinco pruebas de retención, cuatro de retirada/lectura completa de readiness,
  más suite existente. Las operaciones destructivas de tests usan fixtures/mocks.
- No hubo formato de medios físicos ni acceso/copia de privada por el agente.

Se prepara `.gaia/reports/20261019T085624Z-4770def7/REPORT.md`,
**AWAITING_OWNER_VM_INSTALL_SIGNATURE**, para el nuevo candidato.
Manifiesto SHA-256 `7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26`.
La firma del paquete anterior no puede verificar estos nuevos bytes. Comandos
humanos exactos: [APPLIANCE_FIRMA_CANDIDATO_CPU.md](APPLIANCE_FIRMA_CANDIDATO_CPU.md).

Pendientes instalación/reparación positivas firmadas del nuevo hash, auditoría
final de S1 y preparación física según el plan. El perfil CPU todavía no acredita
driver NVIDIA/Pascal en Debian ni S0/S2–S4; F1/F2 no se adelantan.
