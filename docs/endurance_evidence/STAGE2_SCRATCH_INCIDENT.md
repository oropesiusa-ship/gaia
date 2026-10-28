# Stage 2 — SHARED_BACKEND_SCRATCH_BUSY

## Decisión

**BLOCKED_PREEXECUTION. No cleanup, archivado, movimiento ni reintento de Stage 2.**
El intento `.gaia/stage2/s1-authorized-20261026/` se detuvo antes de crear sesión,
recibo de autorización o campaña; el ledger agregado no tiene reservas ni eventos.

## Inventario y ownership

La captura inicial está en
`.gaia/stage2/scratch-incident-20261026/inventory.json`:

- 442 directorios `inference-*`, 1.768 archivos, 5.309.857 bytes de contenido.
- Cada archivo tiene ruta, tamaño, SHA-256, inode/device, uid/gid, modo y tiempos
  mtime/ctime/atime previos a lectura. Los metadatos JSON se preservan íntegros.
- Los archivos observados son `job.json`, `worker.stderr`, `runtime.stdout` y
  `runtime.stderr`; no se encontró manifest/receipt/lock de propietario por directorio.
- Los jobs describen runtime/knobs/presupuestos, no una vinculación duradera de
  PID/start-time/boot/session/campaign. No se puede asignar ownership por edad.
- **442 UNKNOWN_OWNER** en la captura inicial. Cero clasificación como descartable,
  stale probado o reproducible probado. No equivale a afirmar que los trabajos no
  acabaron; significa que falta prueba de ownership y retención reconciliada.
- Se inspeccionan `/proc` cmdline, cwd/root, FDs, maps, PID/ppid/pgid/sid/start ticks,
  boot ID y `/proc/locks`. No se encontró referencia viva visible al scratch ni backend
  candidato en la captura; 219 procesos no eran inspeccionables por permisos.
  Esta limitación impide afirmar ausencia global de propietario.
- La búsqueda inicial de referencias por nombre recorrió 22.600 archivos de texto;
  registra archivos omitidos y errores. No pretende probar ausencia en archivos
  binarios, grandes, externos al repositorio o inaccesibles.

`inference-hbh_azo3` está referenciado por
`state_local_intelligence/discovery/smoke-mistralrs-CPU.json`, como smoke FAILED histórico
(`RUNTIME_NOT_READY`, error de CPU rng). Esa referencia debe conservarse y reconciliarse;
no demuestra por sí sola un propietario durable ni autoriza borrar un fallo histórico.
El README de evidencia 0.8 declara scratch privado retenido fuera del export portable:
`docs/local_intelligence_evidence/README.md:7-8`. No se deduce que todo el scratch sea
evidencia descartable ni se atribuye cada directorio a una release sin prueba.

## Causa raíz

`gaia/local_intelligence/backend.py:93-105` crea un directorio con `mkdtemp` y guarda un
job sin identidad de propietario. `close_failed():180-195` termina procesos/cierra
handles, pero no elimina ni registra el ciclo de vida del directorio. El gate nuevo de
S1 exige scratch compartido vacío: la retención histórica sin ownership durable se
detecta ahora como ocupación ambigua. No es evidencia de una campaña Stage 2 fallida.

No se encontró una policy que declare estos directorios concretos descartables. Tampoco
se ha probado ausencia de referencias activas o reproducibilidad completa. Por ello no
se cumplen las cinco condiciones del operador para cleanup automático.

## Acción y preservación

Se añade únicamente una herramienta administrativa read-only de inventario/diagnóstico
y tests de regresión. No cambia `gaia/`, el backend, policies ni el gate de ejecución.
No se toman locks ni se reparan stores; sólo se observa `/proc/locks`. Leer archivos
puede actualizar atime por el filesystem: no se restablecen tiempos escribiendo sobre
evidencia. La comparación inicial confirmó bytes y metadatos invariantes salvo posible
atime. No se inicia ningún backend para comprobar reproducibilidad.

No es seguro archivar/mover ahora: podría romper la referencia relativa `work` o
perder la ubicación esperada por evidencia histórica. Una copia archivística futura
puede referenciar hashes sin mover los originales, pero no desbloquearía por sí sola
el scratch y requiere reconciliación/autorización separada.

El diagnóstico posterior usa sólo `scratch_gate()` read-only. Un gate ocupado permanece
BLOCKED: no se vuelve a invocar `run-first-session`, no se crea linaje nuevo ni sesión.
El commit anterior del contrato de S1 deja de ser HEAD tras esta corrección; ese contrato
no se reutiliza. No se emite un contrato de ejecución READY con ownership pendiente.

## Regresión de esta corrección

7 tests específicos del inventario y 37 tests Stage 2: PASS con `-B` y
`-W error::ResourceWarning`. No hay cambios en fuentes protegidas respecto a `feda4cb`.
La ampliación de búsqueda por hashes y la tabla por directorio se guardan en el mismo
directorio de incidente; sus límites de búsqueda quedan explícitos en cada captura.
