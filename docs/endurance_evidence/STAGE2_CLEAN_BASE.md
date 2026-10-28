# Stage 2 — base operativa limpia, sin ejecutar sesiones

## Política y preservación

El operador autoriza archivar datos operativos sin sacrificar certificaciones cerradas.
Los 442 directorios históricos no se declaran stale, regenerables ni descartables por
su edad. Se retienen **todos** en su ubicación original y en una copia archivística
verificada bajo `.gaia/archives/backend-scratch-retained-copy-20261026/`.
No se eliminan ni mueven archivos ni se modifican informes, manifests, receipts o referencias
históricas. El localizador original→archivo permite resolver referencias antiguas sin
reescribir la evidencia. No se tocan modelos, runtimes instalados, selección cualificada,
stores certificados, Git commits/tags ni evidencia curada.

El modo rename se detuvo antes de mover nada porque procesos del mismo UID (servicios
de escritorio) no permitían inspeccionar sus FDs. No se relaja ese gate. Se utiliza
COPY con comparación antes/después de los originales; una copia inconsistente falla
y no altera el original. No se afirma inactividad global demostrada. Nunca se termina
un proceso ajeno para despejar el gate.

## Archivo verificable

Herramienta: `tools/archive_backend_scratch.py --copy-retain-originals`. Antes de copiar
conserva inventario completo y snapshot de procesos/locks. Verifica que los originales
conservan inode/device, contenido y metadatos, excepto posible atime por lectura; la copia
tiene nuevos inodes y se verifica por nombres de directorio, tamaño y SHA-256 de todos
los archivos. Persiste inventarios antes/después, receipt y localizador. Directorios y
archivos de la copia se publican mediante fsync. Las fixtures del modo rename siguen
probando recuperación tras interrupción, pero ese modo no se aplicó a los históricos.

La comprobación de evidencia externa cubre `docs/`, `.gaia/stage0/`, `.gaia/stage1/`,
las referencias Git y el smoke de discovery identificado por el incidente. No se
presenta como un re-audit de todas las certificaciones: los demás stores no se escriben,
y se preservan íntegros incluso los scratch cuyo papel en un claim no está resuelto.
Un fallo intermedio exige inspección/manual recovery; no hay rollback ni merge automático.

## Ownership y lifecycle desde la nueva base

Las campañas Stage 2 usan exclusivamente `tools/stage2_campaign.py`, que instrumenta
el adapter **sin cambiar bytes de `gaia/`**, argumentos del sandbox ni autoridad.
`tools/stage2_scratch.py` registra externamente:

- intención durable antes de `mkdir`, journal fsynced y latch de escritura pendiente;
- PID/start-time/boot del dueño, session/campaign, ruta, hash de stack y job;
- metadata local del dueño, job fsynced antes de lanzar y PID/start-time del hijo;
- load/unload/release y fallos; si falla el journal, no se puede afirmar un release;
- cleanup independiente de disponibilidad de journal, sin borrar scratch.

Todos los archivos nuevos bajo el workdir heredan ese binding. La garantía se limita
a los adapters ejecutados dentro del wrapper de Stage 2; una CLI externa directa no
queda instrumentada. No se usan esos caminos externos durante las sesiones Stage 2.
El scratch terminal se retiene con lifecycle explícito; no se elimina automáticamente.
El root nuevo es `<intento>/backend-work`, con ruta absoluta, device e inode congelados.
El wrapper redirige las asignaciones allí sin escribir en el scratch histórico.
La admisión exige ese scratch operativo vacío y rechaza symlinks o root sustituido. Los nuevos tools
forman parte del freeze administrativo.

Se preserva la identidad de fuentes de Stage 0/1: no se mezclan implementaciones ni
se cambia la política que exigiría reiniciar Stage 0 tras tocar `gaia/`.

## Pruebas y revisión

Fixtures desechables prueban archivo sin pérdida, inode y evidencia curada intactos,
traversal/symlinks, rechazo de referencias vivas o procesos propios inaccesibles,
interrupción después del rename, journal parcial, fallo real de Popen y fallos de
journal CHILD/LOADED con hijo vivo y cleanup. La revisión independiente final no
identifica bloqueos adicionales para archivo + preparación READY dentro de este alcance.

Los resultados actuales, commit/tree, manifest y contrato se guardan bajo
`.gaia/stage2/clean-base-validation/` y el intento limpio; no se inicia S1 ni S2.
El contrato anterior queda histórico y no se reutiliza.

Resultado de copia real: `ARCHIVED_COPY_VERIFIED`, 1.768 archivos; cero eliminados y
cero movidos. Inventarios, receipt y localizador están en el root archivístico indicado.
Los originales, las referencias Git y la evidencia externa del alcance descrito
permanecieron intactos durante la operación.

Regresión específica: 9 tests de archivo, 7 de inventario y 58 Stage 2, PASS.
La suite completa previa al aislamiento pasó 1.076 tests (9 skips). La suite final
sobre la implementación aislada pasó **1.085 tests, 9 skips**, en 1.175,225 s,
con `-B -W error::ResourceWarning`, sin reintentos. Su log se conserva en
`.gaia/stage2/clean-base-validation/final-full-suite.log`.
