# Plan por fases: TinyGPT → GaiaTransformer

Status: Historical — not current operational guidance

## Objetivo acordado

Renombrar integralmente TinyGPT como **GaiaTransformer**, conservando el
comportamiento y las capacidades actuales de GAIA. Reconstruir el entorno y la
evidencia experimental con la nueva identidad hasta alcanzar el nivel funcional
actual y, una vez verificado, eliminar los artefactos obsoletos del nombre antiguo.

Este documento es el registro de ejecución del cambio. Guardar el plan no inicia
el renombrado ni ejecuta experimentos o eliminaciones.

Este trabajo forma parte de la **F0 de transición del
[plan maestro](PLAN_MAESTRO_GAIA.md#121-fase-0--transición-y-consolidación-de-la-base)**.
La numeración 0–6 de este documento es local al renombrado. La retirada de
`legacy_v0/` requiere previamente el traspaso verificable de sus activos y
capacidades; el desarrollo de texto/generación seguirá en F4/F5 del plan maestro.

## Regla de avance

- Ejecutar las fases **una a una y en orden**.
- Mantener como máximo una fase en desarrollo.
- **No comenzar la siguiente hasta que la fase en desarrollo esté OK**:
  tareas realizadas, comprobaciones superadas y evidencia registrada aquí.
- Si una comprobación falla, resolverla dentro de esa fase y registrar el bloqueo.
- Al cerrar cada fase, anotar archivos afectados, comandos y resultados reales,
  ubicación de evidencia y asuntos pendientes. No marcar OK basándose en intención.
- Las mediciones nuevas deben registrarse como nuevas: recuperar capacidades no
  significa exigir tiempos idénticos ni inventar los resultados históricos.

## Convención definitiva de nombres

| Elemento | Nombre nuevo |
|---|---|
| Nombre visible y clase del modelo | `GaiaTransformer` |
| Paquete Python | `gaia.gaia_transformer` |
| Directorio del paquete | `gaia/gaia_transformer/` |
| Prefijo CLI | `gaia-transformer-` |
| Perfil CUDA | `gaia-transformer-cuda-pascal` |
| Workload | `gaia_transformer_cuda` |
| Contrato | `gaia_transformer_cuda/v1.1` |
| Benchmark | `gaia_transformer_benchmark/v1` |
| Metaprotocolo | `gaia_transformer_meta/v1` |
| Lockfile | `requirements/gaia-transformer-cuda-pascal-py314.lock` |
| Estado local | `state_gaia_transformer_cuda_<huella>/` |
| Directorio reservado | `state_gaia_transformer_cuda/` |
| Prefijo de tests | `test_gaia_transformer_` |
| Prefijo de estados específicos | `GAIA_TRANSFORMER_` |

Las claves específicas de informes usarán `gaia_transformer_*`. Los estados
genéricos `GPU_*`, los argumentos CLI y los códigos de salida conservarán su
semántica. No se añadirán alias de comandos o imports antiguos.

## Estado global

| Fase | Descripción | Estado |
|---|---|---|
| 0 | Inventario y referencia verificable | OK |
| 1 | Renombrado integral de código y configuración | OK |
| 2 | Tests, documentación y revisión de consistencia | OK |
| 3 | Reconstrucción del runtime, baseline y laboratorio | OK |
| 4 | Benchmark y campaña con identidad nueva | OK |
| 5 | Observación, investigación y metaestudio | OK |
| 6 | Limpieza definitiva y validación de cierre | OK |

## Fase 0 — Inventario y referencia verificable

### Tareas

- Inventariar las variantes `tinygpt`, `TinyGPT`, `tinyGPT` y `TINYGPT` en
  código, rutas, tests, documentos, configuración y artefactos generados.
- Identificar configuraciones de usuario, estados, perfiles, informes y entornos
  administrados afectados; distinguirlos de los pertenecientes a NumPy/CPU u
  otros componentes del proyecto.
- Registrar las capacidades y los parámetros actuales: baseline, laboratorio,
  calibración, G0–G5, campeón y versiones, ledger, observación, investigación,
  estrategia adoptada y estado de consumo del holdout del metaestudio.
- Usar los documentos de validación de fases existentes y los artefactos reales
  para definir la referencia funcional que se debe reconstruir.
- Registrar las comprobaciones previas y sus resultados para poder distinguir
  problemas preexistentes de regresiones del renombrado.
- Preparar una relación exacta de artefactos antiguos que se retirarán en fase 6.
- Inventariar también `legacy_v0/`, incluidos datos o archivos generados no
  versionados. Preparar `docs/TRANSICION_LEGACY_V0.md` según F0 del plan maestro:
  capacidades, formatos, configuración, corpus, checkpoints e historial realmente
  existentes, hashes, destino y prueba prevista de cada capacidad futura.
- Clasificar cada activo legacy como preservado, sustituido o descartado con
  justificación. No aplicar a estos activos la eliminación automática de estados
  sintéticos antiguos. Conservar en rutas neutrales verificadas los datos o
  conocimientos únicos que necesiten F4/F5, sin un segundo motor mantenido.

### Puerta de salida

Inventario completo, referencia funcional documentada y lista de limpieza
delimitada. Ninguna campaña debe estar escribiendo en los estados durante el cambio.
El inventario legacy y la matriz de traspaso deben estar completos antes de
autorizar cualquier retirada. Los destinos pendientes bloquearán su eliminación.

## Fase 1 — Renombrado integral de código y configuración

### Tareas

- Mover `gaia/tinygpt/` a `gaia/gaia_transformer/`, incluido `lab/`.
- Renombrar `TinyGPT` a `GaiaTransformer` y actualizar imports, referencias,
  mensajes, fuentes renderizadas y puntos de entrada de workers/subprocesos.
- Cambiar en `gaia.py`, `gaia/bootstrap.py` y demás consumidores los ocho comandos:
  `baseline`, `lab`, `benchmark`, `prepare`, `run`, `observe`, `research` y `meta`,
  con el prefijo `gaia-transformer-`.
- Aplicar la convención de nombres a catálogo de perfiles, workload, contrato,
  benchmark, metaprotocolo, estados específicos y claves de informes.
- Renombrar el lockfile y actualizar referencias conservando dependencias y hashes.
- Actualizar rutas de estado nuevas y `.gitignore`.
- Actualizar los tests afectados y sus nombres al mismo tiempo que sus
  consumidores, incluidos patrones de descubrimiento y rutas embebidas en strings.
- Conservar arquitectura, corpus, semillas, precisión, optimizadores, espacio de
  búsqueda, límites, criterios de aceptación, aislamiento y recuperación.

### Puerta de salida

Imports, renderizado y despachador CLI coherentes con la identidad nueva;
comprobaciones pertinentes superadas, sin cambios algorítmicos ajenos al renombrado.

## Fase 2 — Tests, documentación y revisión de consistencia

### Tareas

- Completar la actualización de pruebas, incluido
  `tests/gpu_campaign_recovery_check.py`, conservando casos y asercciones.
- Renombrar documentos `*TINYGPT*`, actualizar enlaces, README, ayuda CLI,
  contrato, corpus y documentación de bootstrap.
- Identificar expresamente las mediciones históricas como tales hasta disponer
  de resultados nuevos; no presentarlas como ejecuciones de GaiaTransformer.
- Comprobar todos los comandos nuevos mediante ayuda y validación de argumentos.
- Ejecutar la suite en un runtime adecuado con NumPy/Torch, dejando registrados
  resultados y posibles skips. La validación CUDA posterior exigirá las pruebas
  correspondientes sin omisiones.
- Buscar referencias antiguas en código, tests, configuración y documentación
  operativa. Las referencias históricas explícitas y este plan se registrarán
  como excepciones justificadas, no como identificadores activos.
- Completar la especificación de transición legacy y verificar los activos
  preservados antes de retirar el prototipo. Mientras exista `legacy_v0/` a la
  espera de la limpieza final, sus nombres antiguos serán una excepción temporal
  inventariada, sin integrarlo ni publicitarlo como runtime activo.

### Puerta de salida

Suite pertinente correcta, documentación enlazada y comandos nuevos coherentes.
Ninguna referencia antigua ejecutable en la base activa ni alias de compatibilidad;
el prototipo pendiente de retirada queda limitado a la excepción indicada.

## Fase 3 — Reconstrucción del runtime, baseline y laboratorio

### Tareas

- Aprovisionar un entorno con el perfil nuevo; no renombrar directamente un venv
  existente, que puede contener rutas absolutas.
- Ejecutar y registrar:

  ```bash
  python3 gaia.py bootstrap --profile gaia-transformer-cuda-pascal
  python3 gaia.py doctor --profile gaia-transformer-cuda-pascal
  python3 gaia.py gaia-transformer-baseline
  python3 gaia.py gaia-transformer-lab
  ```

- Emplear los parámetros fijados en fase 0 cuando difieran de los valores por defecto.
- Comprobar dependencias, GPU, determinismo, causalidad, pérdida privada,
  aislamiento, telemetría y casos de fallo del laboratorio.

### Puerta de salida

Runtime y laboratorio válidos, baseline reproducible, pruebas CUDA requeridas
ejecutadas sin skips y evidencia generada bajo la nueva identidad.

## Fase 4 — Benchmark y campaña con identidad nueva

### Tareas

- Crear una calibración nueva y un estado `state_gaia_transformer_cuda_<huella>/`:

  ```bash
  python3 gaia.py gaia-transformer-benchmark
  python3 gaia.py gaia-transformer-prepare
  python3 gaia.py gaia-transformer-run --max-experiments 1 --minutes 15
  ```

- Ajustar el número de ejecuciones al objetivo funcional registrado en fase 0,
  manteniendo presupuestos explícitos y los criterios actuales de promoción.
- Verificar baseline congelada, manifiestos, hashes, puertas G0–G5, campeón,
  versiones estables, ledger, parada y recuperación según las pruebas existentes.
- Registrar procedencia y relación con el estado previo, sin copiar sus hashes,
  tiempos o confirmaciones como evidencia nueva.

### Motivo de la recalibración

`benchmark_state.load` compara configuración, runtime, especificación e identidad
de fuentes. `CampaignStore.verify_versions` compara las fuentes estables con el
renderizado actual. Las rutas y el nombre de clase cambian esos identificadores:
editar manifiestos antiguos para forzar su aceptación invalidaría su procedencia.

### Puerta de salida

Benchmark nuevo válido, campaña operativa y estado estable íntegro. Toda promoción
debe contar con confirmación real; no se exige obtener una mejora para dar por
correcto el renombrado.

## Fase 5 — Observación, investigación y metaestudio

### Tareas

- Ejecutar con los parámetros de referencia y registrar:

  ```bash
  python3 gaia.py gaia-transformer-observe
  python3 gaia.py gaia-transformer-research --minutes 10
  python3 gaia.py gaia-transformer-meta
  ```

- Verificar paridad numérica del perfilado, diagnósticos, hipótesis, contrastes,
  memoria de investigación y estrategia de búsqueda persistida.
- Completar el metaestudio con sus presupuestos, separación ajuste/holdout y
  reglas actuales. Una adopción requiere evidencia nueva favorable.
- Registrar el consumo del holdout nuevo y comprobar que no permite reutilizarlo
  para nuevos ajustes; no repetir el estudio buscando un resultado favorable.
- Actualizar la documentación de validación con resultados reales y rutas nuevas.
- Contrastar las capacidades reconstruidas con la referencia de fase 0.

### Puerta de salida

Observación, investigación y metaestudio completos y verificables, con sus
resultados reales documentados. Cualquier diferencia respecto a los resultados
anteriores debe explicarse, sin falsear una adopción o promoción.

## Fase 6 — Limpieza definitiva y validación de cierre

### Condición de entrada

Todas las fases anteriores deben estar OK. La evidencia nueva debe permitir
verificar las capacidades actuales antes de eliminar la anterior.
Además, el traspaso legacy de F0 del plan maestro debe tener sus requisitos,
destinos y comprobaciones completos: la recalibración sintética no reemplaza
corpus, pesos ni capacidades de lenguaje del prototipo.

### Tareas

- Eliminar los directorios obsoletos `state_tinygpt_*` y `state_tinygpt_cuda/`,
  según el inventario y después de trasladar la documentación reservada pertinente.
- Eliminar configuraciones, marcadores y entornos administrados vinculados al
  perfil antiguo en `.gaia/`.
- Eliminar informes de bootstrap antiguos asociados a TinyGPT y cachés obsoletas.
  Revisar informes mixtos antes de retirarlos para conservar la evidencia vigente
  de otros workloads.
- Revisar rutas absolutas, enlaces, residuos y referencias operativas; no borrar
  toda `.gaia/` indiscriminadamente.
- Retirar `legacy_v0/` tras verificar el manifiesto de transición, las copias de
  activos útiles y los requisitos transferidos a F4/F5. Registrar rutas finales y
  hashes; no borrar corpus, checkpoints o historial únicos sin destino o decisión
  justificada. Eliminar referencias operativas a scripts legacy ya retirados.
- Ejecutar la suite final, diagnóstico del perfil nuevo, comprobación de integridad
  del estado y smoke checks de comandos. Repetir experimentos solo si una
  modificación o un fallo nuevo lo requiere; no volver a consumir el holdout.
- Confirmar que el código y la documentación operativa usan exclusivamente la
  identidad nueva, y registrar cualquier mención histórica justificada.
- Cerrar este documento con resumen de cambios, resultados, rutas definitivas
  y relación de artefactos eliminados.

### Puerta de salida

Proyecto operativo como GaiaTransformer, evidencia nueva íntegra y completa,
artefactos TinyGPT retirados y componentes NumPy/CPU y otros datos del proyecto
preservados. La eliminación de evidencia antigua es definitiva.
Los activos legacy identificados como útiles quedan preservados según su
manifiesto, separados del estado activo, y las capacidades aún no implementadas
quedan declaradas como pendientes de F4/F5. Esta excepción no conserva un runtime
legacy ni permite reutilizar sus resultados como evidencia experimental nueva.

## Registro de ejecución por fase

Completar esta ficha para cada fase al iniciarla y cerrarla:

```text
Fase:
Estado: Pendiente / En desarrollo / Bloqueada / OK
Fecha de inicio:
Fecha de cierre:
Cambios y archivos:
Comandos ejecutados y resultados:
Evidencia:
Bloqueos o diferencias respecto a la referencia:
Comprobación de la puerta de salida:
```

### Situación al guardar este plan

- Plan acordado y guardado.
- Fases 0–6 pendientes; ninguna iniciada.
- El renombrado, la reconstrucción y la limpieza se ejecutarán siguiendo estas puertas.

### Fase 0 — Inicio 2026-10-16

Estado: OK. Cierre: 2026-10-16. Inventario y referencia en
`REFERENCIA_RENOMBRADO_GAIA_TRANSFORMER.md`, manifiesto en
`TRANSICION_LEGACY_V0.md`, evidencia en `evidencia_renombrado/`.
Comprobación previa: 145 tests OK sin skips (16.586 s) en runtime Torch existente.
Sin campañas activas. Copia neutral `archives/text_prototype/sample_corpus.txt`
verificada por `cmp` y `sha256sum`: 24120 bytes, hash del manifiesto coincidente.
Inventario final: 1785 archivos, 15247 líneas antiguas (incluye documentos nuevos
de procedencia). Lista delimitada de limpieza JSON generada. Puerta de salida OK;
sin activos legacy útiles sin destino ni bloqueos.

### Fase 1 — Inicio 2026-10-16

Estado: OK. Inicio/cierre 2026-10-16. Renombrado de los 31 archivos del paquete,
ocho tests específicos, consumidores en bootstrap, CLI, engine y tests generales,
catálogo y lockfile. `.gitignore` usa estados nuevos. Sin alias antiguos.
`python -m unittest discover -s tests` en venv Torch anterior: **145 OK, sin skips,
17.093 s**. Búsqueda case-insensitive en gaia/tests: cero referencias antiguas.
Imports, renderizado y despacho pasan pruebas existentes; cambios solo identidad.
Estados/informes históricos intactos. Puerta de salida OK, sin bloqueos.

### Fase 2 — Inicio 2026-10-16

Estado: OK. Inicio/cierre 2026-10-16. Nueve documentos *TINYGPT* renombrados,
README, BOOTSTRAP, contrato/corpus y plan maestro actualizados. Validaciones
anteriores y plan completado se marcan históricos, manteniendo procedencia real.
Script `docs/verify_rename.py`: 8 ayudas, 8 rechazos de argumento desconocido,
5 rangos inválidos y suite completa correctos. Logs y comandos exactos en
`evidencia_renombrado/fase2_checks.json` y `fase2_check_*.log`; sin skips.
Enlaces Markdown locales resueltos. Comparación inversa SHA-256 demuestra cambios
solo de identidad en fuentes/tests/configuración/lockfile (JSON fase1_identidad*).
Excepciones: documentación histórica, plan/referencia/inventario de migración,
utilidades documentales de verificación, artefactos antiguos hasta fase 6 y
prototipo temporal inventariado. No hay referencias antiguas en código activo.
Traspaso legacy especificado y muestra neutral verificada. Puerta OK, sin bloqueos.

### Fase 3 — Inicio 2026-10-16

Estado: OK. Inicio/cierre 2026-10-16. Comandos reales:
`python3 gaia.py bootstrap --profile gaia-transformer-cuda-pascal`,
`python3 gaia.py doctor --profile gaia-transformer-cuda-pascal`,
`python3 gaia.py gaia-transformer-baseline`, `python3 gaia.py gaia-transformer-lab`.
Venv nuevo `.gaia/venvs/gaia-transformer-cuda-pascal-df1f7863934daabc/`,
config `.gaia/configs/df1f7863934daabc.json`. Instalación fijada con hashes,
pip-check, probes normal/aislado y repetición CUDA correctos. Bootstrap/doctor:
`.gaia/reports/20261016T074444Z-8b56c232/`, `20261016T074619Z-7a73545b/`.
Baseline: `20261016T074630Z-13d974fc/phase1/result.json`, READY, 3 trials de
100 pasos, semillas 9000/9000/9001, repetibilidad bit a bit y targets privados.
9 tests modelo OK, incluida causalidad CUDA, sin skips. Laboratorio:
`20261016T074658Z-98db08bf/phase2/result.json`, 17/17 escenarios OK, 13 tests OK,
bwrap y NVML exigidos. Suite completa ejecutada también en el venv nuevo con
`bin/python docs/verify_rename.py`: 145 OK sin skips; logs fase2_checks actualizados
con esta comprobación del runtime nuevo. Puerta OK, sin bloqueos.

### Fase 4 — Inicio 2026-10-16

Estado: OK. Inicio/cierre 2026-10-16. Comandos prescritos ejecutados:
`python3 gaia.py gaia-transformer-benchmark`, `gaia-transformer-prepare --minutes 15`,
`gaia-transformer-run --max-experiments 1 --minutes 15` (todos vía `python3 gaia.py`).
Benchmark nuevo 71 trials: `.gaia/reports/20261016T074910Z-76ced823/phase3/result.json`.
Prepare 26 trials: `20261016T075534Z-9c325f3c/campaign/result.json`, G0–G5 OK.
Run 38 trials: `20261016T075821Z-4c8a0867/campaign/result.json`, experimento e00001
rechazado tras cinco pares; ninguna promoción, campeón v0000. Coste nuevo
4.019073079005466 s; CE 0.2596790841227193 coincide por reproducibilidad real.
Fuente nueva SHA-256 d0b32da1824bee59bf942d85f707dc8710247f4c0ce52afcdb2dc7a0125cad9a.
Recuperación real con `tests/gpu_campaign_recovery_check.py --config
.gaia/configs/df1f7863934daabc.json --bootstrap-report
.gaia/reports/20261016T075821Z-4c8a0867/report.json --output
docs/evidencia_renombrado/recuperacion_fase4` en Python CUDA: RECOVERY_VERIFIED.
e00002 interrumpido SIGKILL, aborted, próximo ID3, v0000 intacto, recuperación
idempotente y temporales eliminados; sin procesos huérfanos detectados.
`docs/audit_rename_state.py fase4`: STATE_INTEGRITY_OK, fuentes/runtime/baseline,
versiones y ledger íntegros; 8 eventos. Evidencia integridad_fase4.json.
Puerta OK. No se han copiado manifiestos ni mediciones de los estados anteriores.

### Fase 5 — Inicio 2026-10-16

Estado: OK. Inicio/cierre 2026-10-16. Comandos `python3 gaia.py
gaia-transformer-observe --steps 100`, `gaia-transformer-research --minutes 10`,
`gaia-transformer-meta` y prepare posterior --minutes 15.
Observe: `.gaia/reports/20261016T080610Z-5e8f6c5e/observation/result.json`,
GPU_OBSERVATION_READY, paridad numérica, optimizer dominante, sobrecarga 1.13x.
Research: `20261016T080635Z-85f84ea0/research/result.json`, 12 trials de contraste,
optimizer_foreach inconclusive, clip_foreach pruned, sin opciones desbloqueadas.
La diferencia de veredicto respecto al histórico responde a cotas/timing nuevos,
no a cambios de criterio; no se repite buscando apoyo. Memoria persistida en ledger.
Meta: `20261016T080758Z-b50b1272/meta/result.json`, 60 trials nuevos, GPU_META_COMPLETE,
verified_transfer_on_cached_tasks, v1 adoptada (1.0,0.1,0.3). Protocolo nuevo digest
5ea0c743ad926fdf53ac6b33de5d2b94b43d2a76600e2d790fa4742b646c38aa.
Ajuste ΔAUC=-0.06137077, superior=-0.02785612; holdout contra previa -0.05730434,
superior=-0.04651426; contra azar -0.06412629, superior=-0.05138532.
`audit_rename_state.py fase5`: carga verificada estrategia, holdout bloquea run antes
de medir/ajustar, hashes selection/completed/ledger intactos; integridad_fase5.json.
Prepare posterior `20261016T081402Z-47ef5fb8/campaign/result.json`: G0–G5 OK,
26 trials, estrategia v1 cargada, sin candidatos/promociones. Campeón v0000.
Paridad funcional con referencia recuperada, tiempos/contrastes son nuevos.
Puerta OK, sin bloqueos. Holdout nuevo consumido; no volver a ejecutar el estudio.

### Fase 6 — Inicio 2026-10-16

Estado: OK. Inicio/cierre 2026-10-16. Fases 0–5 OK antes de eliminar.
README reservado trasladado y actualizado en `state_gaia_transformer_cuda/`.
`python3 docs/cleanup_rename_artifacts.py --apply`: 38 raíces concretas retiradas:
2 estados, 2 venvs CUDA (con sus marcadores), 2 configuraciones, 22 informes
exclusivos del workload anterior y 10 cachés/rutas de bytecode. Raíces exactas,
revisión de cada informe y archivos/hashes eliminados en
`evidencia_renombrado/limpieza_fase6_aplicada.json`; 13 informes CPU/mixtos
conservados. Caché compartida bootstrap conservada; no tiene identidad exclusiva
del perfil anterior. `gaia/tinygpt/` residual de bytecode retirado.
Los 12 archivos legacy retirados tras verificar hashes y copia del corpus;
directorios vacíos retirados. Manifiesto actualizado, sin runtime legacy paralelo.

Incidencia resuelta en esta fase: la primera clasificación de los dos informes
históricos de recuperación esperaba un campo identity inexistente. La aserción
detuvo el script **antes de eliminar nada**; inspección real confirmó runtime del
venv antiguo y hashes gaia/tinygpt en G3. Se corrigió solo la utilidad documental
de clasificación y la limpieza posterior terminó correctamente. Sin cambio al
evaluador, criterios de aceptación, benchmark ni protocolo. No hay bloqueo pendiente.

Comprobaciones finales:
- `python3 gaia.py doctor --profile gaia-transformer-cuda-pascal`: CUDA_ENVIRONMENT_READY,
  `.gaia/reports/20261016T082001Z-115f4c7f/REPORT.md`.
- Python del venv nuevo `docs/verify_rename.py fase6`: **145 tests OK, 16.902 s,
  cero skips**; ocho ayudas y rechazo de argumentos/rangos correctos. Evidencia
  `fase6_checks.json` y 22 logs. Persisten ResourceWarning CPU preexistentes,
  registrados antes del cambio, sin fallo de pruebas.
- `docs/audit_rename_state.py fase6`: STATE_INTEGRITY_OK, G0–G5 OK, 17 eventos,
  campeón v0000, e00001 rejected/e00002 aborted, estrategia v1 verificable,
  holdout protegido. 178 archivos CPU/otros informes/estados coinciden con hashes
  iniciales; corpus neutral verificado y antiguo import inexistente.
- Búsqueda de nombres de archivo antiguos: cero coincidencias; fuentes/tests y
  documentación operativa usan identidad nueva. Excepciones históricas explícitas:
  validaciones del 15-10-2026, plan completado, este plan, referencia/inventario,
  manifiestos/logs y utilidades de migración, e informes CPU/mixtos conservados.

Puerta de salida OK: identidad nueva operativa y evidencia íntegra; datos CPU y
activos útiles preservados. Sin alias, regresiones detectadas ni asuntos que
requieran intervención humana. No se volvió a consumir el holdout ni se repitieron
experimentos después de la limpieza.

## Cierre global — 2026-10-16

**Fases 0–6 OK.** Informe completo:
`docs/VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.
Rutas definitivas: `gaia/gaia_transformer/`, lockfile
`requirements/gaia-transformer-cuda-pascal-py314.lock`, perfil
`gaia-transformer-cuda-pascal`, entorno/config huella `df1f7863934daabc`,
estado `state_gaia_transformer_cuda_df1f7863934daabc/`, informes nuevos
`.gaia/reports/20261016*/`, evidencia de migración `docs/evidencia_renombrado/`,
muestra `archives/text_prototype/sample_corpus.txt` y traspaso
`docs/TRANSICION_LEGACY_V0.md`. Campeón v0000 sin promoción, estrategia v1 adoptada
con contraste nuevo favorable acotado; holdout consumido una sola vez.
F0 del plan maestro cerrada; capacidades de lenguaje F4/F5 siguen pendientes.
