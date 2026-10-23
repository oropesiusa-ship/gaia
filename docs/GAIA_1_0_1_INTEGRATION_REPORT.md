# GAIA 1.0.1 — Integración completa del closed loop

## Estado y alcance

**PASS de integración del ciclo §11.1 del Documento Maestro v3 sobre dos superficies acotadas:**
hiperparámetros del trainer `numpy_mlp` y configuración de inferencia del LLM local (Nivel A).

- **Bytes certificados:**
  - código de `09de7eb`, árbol `gaia/` `d1edb80e…`;
  - identidad de fuentes `3383b6a25ba9d4d179ffe5844a93950763c8f432b112b716d4ed899a8a641290`;
  - protected hash `9376438978e4c78ecee88ca5c839914760b13f312f340f4691905ddc94261e1f`.
- **HEAD durante las ejecuciones:** `c259ca5`. Sólo añade documentación sobre `09de7eb`: el árbol `gaia/` es idéntico (`d1edb80e…`).
- **Resultado:**
  - suite completa en verde: 938 tests, 0 fallos;
  - las 16 campañas pre-registradas, PASS en el informe y en el auditor offline v2;
  - **promoción natural verificada en la serie definitiva** y otras dos en la serie de réplica, con seguimiento (health check) PASS;
  - **rollback natural no ejercitado**: no hubo ninguna regresión que revertir.

Rama única `feat/gaia-1.0.1-integration`, base `fe767aa` / `gaia-v1.0`.

- **Commits funcionales:**
  - `af70650`: integración;
  - `bdce836`: recuperación ante crash;
  - `26c828c`: referencia del campeón vigente, matriz de regresión auditable y revisión cognitiva consultiva;
  - `09de7eb`: re-medición de la referencia tras un rollback como contabilidad del rollback.
- **Pre-registro de la certificación vigente:** `100f0e3` y `765239c`.
- **Certificación anterior:** la de `bdce836` quedó invalidada al cambiar `gaia/`. Se conserva como evidencia de desarrollo en [`development/BDCE836_CERTIFICATION.md`](integration_evidence/development/BDCE836_CERTIFICATION.md).

1.0.1 es la base previa a GAIA 1.1 (endurance). La revisión de `GAIA_1_1_ENDURANCE_PLAN.md`
mostró que el loop 1.0 llamaba a todos los subsistemas 0.1–0.9, pero casi todos quedaban
anulados por filtros, entradas omitidas o atajos. En la práctica sólo había un camino vivo:

> gap de verificación sintético → `UNKNOWN_REQUIRES_EVIDENCE/core` → `CONTROL_EXPERIMENT`
> → genoma baseline idéntico → REJECTED → duplicado → parada.

Ese camino producía exactamente un experimento por campaña y hacía inalcanzable la promoción.
1.0.1 no amplía la autoridad: mismo evaluador, benchmarks, criterios (min_gain 0,05, cinco
pares, screen_slack 1,3), sandbox bwrap, lista `FORBIDDEN`, red desactivada por defecto,
rollback obligatorio y gate determinista. El LLM conserva `authority: NONE`. No se
cambian modelos ni pesos, no se descarga ni instala nada y no se genera código libre.

## Desconexiones de 1.0 y corrección

| Paso §11.1 | 1.0 | 1.0.1 |
| --- | --- | --- |
| 1 Observación | siempre `quick`, sin workload ni baseline | observación completa (workload protegido) en la 1ª iteración y tras la promoción; baseline del linaje renovada sólo tras promoción verificada |
| 2 Diagnóstico | sin baseline ni configuración; regresión, ruido y CPU inalcanzables | `diagnose(ob, baseline, engine_config)`; objetivo de mejora explícito `REQUESTED_OPTIMIZATION_NOT_A_DETECTED_DEFECT` |
| 3 Hipótesis | se perdía al materializar | hipótesis enlazada target → plan → materializado → evaluación → registro; `HYPOTHESIS_ASSESSMENT` derivado de la decisión protegida |
| 4 Diseño | 0.6 sin contexto (todo `UNASSESSED`); sólo 5 clases; un duplicado detenía la campaña | contexto del manifest de ejecución (`context_scope='EXECUTION_MANIFEST'`); 9 clases materializables; previsualización pura y paso al siguiente plan; réplicas intencionadas con tope |
| Generación | `Strategy.propose`/UCB y `hist.seen` sin usar; recompensa siempre 0 | operadores HP existentes ponderados por los pesos aprendidos de v0.1; `parent_cost` real; novedad frente a `hist.seen` del linaje |
| 5–9 Ejecución y decisión | Engine y gates (sin cambios) | igual, más el registro determinista del Anexo B por experimento |
| 10 Promoción | inalcanzable (clases nunca generadas; reserva > compute) | EXPLORATION ACCEPTED → REPLICATION ACCEPTED → gates existentes; v2: 3600 s |
| 11 Seguimiento | sólo verificación inmediata, con `compare` vacío | verificación con observación completa, gates y la matriz de regresión con la política aprobada, más health check del linaje en cada admisión; si falla, rollback al predecesor conocido, re-medición de la referencia y bloqueo del linaje si procede |
| 12 Aprendizaje | store por campaña; `STRATEGY_OUTCOME` sin lector | linaje persistente; 0.6 LINKED con outcomes reales; `meta.tune` restringido a la superficie |
| Cognición | 1 de 7 tipos de tarea, como veto | revisión cognitiva **consultiva** de los planes elegibles: sus citas se registran, pero no influyen en la selección, que es siempre el primer plan elegible del ranking determinista (ver «Revisión cognitiva consultiva») |
| Research 0.7 | detenía la campaña; pregunta fija; salida sin lector | sin autoridad se registra `RESEARCH_NOT_AUTHORIZED` y el loop continúa; pregunta derivada de la hipótesis; resultado importado como evidencia |
| Nivel A (0.8) | `'latest'`, manual, sin transacción | superficie de inferencia con control fresco, guards de 0.8, puntero transaccional y reversible, verificación A–H |

## Arquitectura añadida

- `gaia/autonomy/lineage.py`. Linaje `al<24hex>` con:
  - contrato inmutable (objetivo, superficie, identidad de fuentes);
  - journal encadenado;
  - flock por linaje (`LINEAGE_BUSY`) y lock de experimentación del host (`HOST_EXPERIMENT_BUSY`), para no medir numpy e inferencia a la vez;
  - `state()` como pliegue puro (inspección sin lock ni reparación).

  Un cambio de fuentes obliga a crear un linaje nuevo. Bloquean el linaje, hasta `autonomy-lineage-unblock` con motivo explícito: un intent ambiguo, un rollback fallido, un health check fallido o una parada entre un efecto comprometido y su aprendizaje o verificación.
- Contrato `gaia_closed_loop_campaign_v2`. Tabla cerrada objetivo → superficie, perfil, clases de target, componentes y clases promovibles. Topes como en 1.0 (5/5/3600/3600). Los contratos v1 y la evidencia 1.0 validan sin cambios.
- `materializer.materialize_v2`. EXPLORATION de un solo factor sobre los 13 operadores HP (o el factor que nombre el plan). REPLICATION, KNOWLEDGE_VALIDATION y DISCRIMINATION con referencia exacta. Factorial lr/wd con niveles fijos. PARAMETER_LOCAL_SEARCH y EXPLOITATION desde una referencia ACCEPTED cualificada. `parallelism` se declara no materializable en HP y se salta.
- `hypothesis.py` y `records.py`: efecto esperado según una tabla cerrada; valoración sólo a partir del evaluador; registro del Anexo B ensamblado de forma determinista.
- `inference_surface.py` (Nivel A):
  - variación de un factor de `threads`, `context`, `gpu_layers`, `kv` o `backend` (sólo backends ya cualificados), con runtime, modelo, pesos y cuantización fijados por hash;
  - medición con `campaign.run_stack` (screen + benchmark completo) contra un control re-benchmarkeado en el mismo experimento;
  - decisión con las tolerancias de `selection.POLICY`: quality, structured output, reliability y tool intent no peores, latencia STABLE y mejora de latencia de tarea por encima del ruido;
  - la promoción genera la SELECTION con el `select()` existente y mueve el puntero transaccional (`IntelligenceStore.set_pointer`, que `'latest'` respeta); el rollback vuelve a apuntar a la selección anterior;
  - la verificación ejecuta los 11 casos A–H de 0.9 en un store privado, más la matriz de regresión.
- **Referencia del campeón** (`services.measure_reference`/`current_reference`):
  - se re-mide con el `Engine.refresh_ref` de v0.1 en la admisión de cada campaña CONTROLLED numpy (con el guard de deriva), tras la promoción y tras cualquier rollback;
  - además, se exige ligada a la versión vigente antes de cada intent de ejecución;
  - cada medición es un artefacto `REFERENCE_MEASUREMENT` y un evento `REFERENCE_MEASURED` del linaje, y cada registro del Anexo B lleva su `screen_reference`;
  - una deriva o una referencia no fiable paran la campaña y bloquean el linaje.
- **Matriz de regresión** (`services.regression_matrix`, `regression.py`):
  - la política aprobada por el operador está descrita en «Política de la matriz de regresión»;
  - cada intento se registra en el journal con los IDs de los tests fallidos y sus tracebacks, y se reanuda tras un crash sin repetir intentos ya decididos;
  - el primer fallo es una señal explícita (`REGRESSION_SIGNAL`).
  - Las campañas v1 conservan la ejecución única de 1.0.
- 0.6 LINKED: `outcome_statistics` reproducible y validada, con bonus por clase acotado a ±3 y `static_ranking` para comparar. Los `DEFAULTS` de la política no cambian.
- `search.Strategy` y `meta` aceptan un subconjunto de operadores. La ruta por defecto es idéntica a 1.0: 60 propuestas × 5 semillas dan el mismo digest con el código de `fe767aa`, y queda fijado en un test.
- `tools/audit_closed_loop.py` añade la rama v2: reproducción estructural del journal, presupuestos, previsualización = materialización, superficie y novedad frente al linaje previo, selección dentro de los candidatos, `authorize`, valoraciones, registros, decisión pareada protegida (numpy) o decisión 0.8 frente a los benchmarks guardados (inferencia), promoción sólo bajo política, selección determinista (la revisión consultiva no influye), referencia de cribado ligada al campeón y re-medida tras cada rollback, y reproducción de la política de la matriz a partir de sus intentos registrados. La elección de operador por pesos no se re-muestrea; se verifica por superficie y novedad.

## Correcciones que motivan la re-certificación

Tras certificar `bdce836`, una evaluación pre-registrada encontró tres defectos (detalle en
[`development/BDCE836_CERTIFICATION.md`](integration_evidence/development/BDCE836_CERTIFICATION.md)).
El operador aprobó corregir los tres, con la política de matriz descrita abajo. Se corrigieron en
`26c828c`. Las dos revisiones independientes del diff añadieron seis correcciones:

- la matriz de v1 queda como estaba;
- cada intento de la matriz y el primer fallo se registran en el journal, sin ventana de crash que los pierda;
- los tests fallidos dentro de un subTest o de un fixture se re-ejecutan por su test o clase padre;
- la deriva bloquea el linaje, como el `NeedsHuman` de v0.1;
- el rollback va ligado a su evaluación;
- el auditor reproduce la política y la contabilidad de los intentos.

| Defecto | Evidencia | Corrección |
| --- | --- | --- |
| Referencia del campeón obsoleta tras un rollback; sin recalibración en el loop | Tras revertir v0001, e00006 (0,360 s) se cribó contra 0,357 s, el coste de la versión revertida, cuando v0000 cuesta ≈0,84 s. Un candidato de ≈0,43× quedó REJECTED y así se aprendió. | Re-medición en la admisión (con el guard de deriva), tras la promoción, tras cualquier rollback y siempre que no esté ligada al campeón vigente; `screen_reference` en cada registro; el auditor lo comprueba |
| Matriz de regresión no auditable | Un rollback real se disparó por la matriz, que sólo guardaba hashes. No se pudo saber qué test falló; 3 re-ejecuciones pasaron. | IDs exactos y tracebacks proyectados de cada test fallido; política aprobada; primer fallo como señal explícita |
| Selección cognitiva degenerada | Contrabalanceo: 27/27 primera posición y 0/5 casos decisivos en la ruta certificada | Se renombra como revisión consultiva y no influye en la selección (ver abajo) |

**La ejecución interrumpida en `26c828c` encontró un defecto más,** corregido en `09de7eb`:

- La primera re-certificación se interrumpió desde fuera: la sesión del operador se cerró mientras se verificaba una promoción natural (`hidden` 64→32).
- Se reanudó por la recuperación normal, como exigía el pre-registro. Con el presupuesto agotado, la verificación falló y v0001 se revirtió.
- Pero la re-medición obligatoria de la referencia restaurada fue rechazada por el control de presupuesto por prueba. El linaje quedó bloqueado y el auditor marcó la campaña `ROLLBACK_WITHOUT_REFERENCE_REMEASUREMENT`.
- **Corrección:** la re-medición tras un rollback es contabilidad del propio rollback. Corre bajo la gracia acotada de 600 s y el tope por prueba, nunca como experimento.

Evidencia en [`development/26c828c-interrupted/`](integration_evidence/development/26c828c-interrupted/).

### Política de la matriz de regresión (aprobada por el operador)

La matriz es fija: 615 tests de los módulos críticos de v0.1 y de los relevantes de 0.2–1.0. Corre en un
proceso limpio separado.

1. Si la matriz completa pasa, se mantiene la promoción.
2. Si falla, se registran los IDs de los tests fallidos y sus tracebacks, y se emite la señal `REGRESSION_SIGNAL`.
3. Se re-ejecutan sólo esos tests, una vez, en un proceso limpio. Si alguno vuelve a fallar, hay rollback.
4. Si todos pasan, la matriz completa corre una vez más. Si pasa, se mantiene la promoción; cualquier fallo provoca rollback.
5. No hay más reintentos, no cambia ningún umbral y no se excluye ningún test por haber fallado.

Casos que no admiten re-ejecución selectiva:

- Un fallo sin tests identificables (timeout o sin informe) provoca rollback directamente.
- También un test que no puede volver a cargarse por nombre, como un error de importación.

El primer fallo nunca se borra: queda en el journal de la campaña, en el linaje y en la verificación,
marcado como transitorio si la promoción se mantuvo.

### Revisión cognitiva consultiva

Lo que antes se llamaba «selección cognitiva del plan» se llama ahora **revisión cognitiva consultiva**
(`ADVISORY_COGNITIVE_REVIEW`):

- El LLM revisa los planes elegibles y cita hechos (plan_id, riesgo, resultado anterior).
- Sus citas se guardan para trazabilidad (`advisory_cited_candidates`), pero **no influyen en la selección**. El plan es siempre el primer elegible del ranking determinista (`DETERMINISTIC_FIRST_ELIGIBLE_PLAN`). El auditor rechaza cualquier selección distinta.

El motivo está en el experimento contrabalanceado sobre la ruta certificada en `bdce836`
([`cognitive-selection.json`](integration_evidence/development/bdce836-post-certification/cognitive-selection.json)):

- **Ruta de producción:**
  - eligió la primera posición en 27 de 27 presentaciones y nunca el mismo plan en todas las rotaciones;
  - acertó 0 de 5 casos con respuesta fijada de antemano.
  - El constructor de contexto 0.9 sólo admite 8 hechos y nunca le mostraba el campo que distingue los planes.
- **Mismo modelo con toda la información:**
  - acertó 4 de 5 casos, pero sólo los que el ranking determinista ya pondera;
  - falló el único caso que exigía razonar más allá del ranking;
  - y prefería saltarse el control que el diseño exige.

Alcance: la revisión consultiva es trazabilidad y no selección. No hay evidencia de que mejore las decisiones.
Las métricas `advisory_cognitive_reviews` y `advisory_reviews_citing_selected_plan` describen lo que hace,
no un valor añadido.

## Certificación vigente (`09de7eb`)

Pre-registrada en [`PREREGISTRATION.md`](integration_evidence/PREREGISTRATION.md) (`100f0e3`, `765239c`) antes de ejecutar
nada sobre estos bytes. Las ejecuciones se lanzaron desacopladas de la sesión y con el host en reposo.

**Incidencia del lanzador, declarada.**

- El script de la serie reutilizaba la variable `C` para el modo y para el ID de campaña.
- Al terminar la serie numpy, las CONTROLLED de inferencia (2) y de réplica (6) se intentaron crear con un modo inválido y **no llegaron a crearse**: no hay ninguna campaña parcial ni ningún estado tocado.
- Con el script corregido se crearon exactamente esas 8 campañas, en los mismos linajes y en el orden pre-registrado (`CONTINUATION_AFTER_RUNNER_BUG`).
- No se repitió, añadió ni descartó ninguna campaña.

### Suite

938 tests, OK, 9 skips (frozen de `gaia_transformer_model`, sin Torch/CUDA), 0 fallos y 0 errores, en
1049,1 s con `-B -W error::ResourceWarning`, en ventana de host en reposo ([`tests.json`](integration_evidence/tests.json)).

### Serie definitiva ([`final/`](integration_evidence/final/), estado `state_integration_cert4`)

**Linaje numpy `alb433bab3d4ad415098728c77`:**

| Campaña | Exps. | Parada | Wall (s) | Auditor |
| --- | ---: | --- | ---: | --- |
| DRY_RUN | 0 | completada sin ejecutar | 18 | PASS |
| SHADOW | 0 | completada sin ejecutar | 19 | PASS |
| CONTROLLED 1 (`ac77b0ab…`) | 3 | `NO_PROGRESS` | 420 | PASS |
| CONTROLLED 2 (`ace92f79…`) | 5 | `STOPPED_BUDGET` (tope de 5 experimentos) | 1169 | PASS |

| Exp. | Clase | Cambio | Resultado | Referencia de cribado |
| --- | --- | --- | --- | --- |
| e00001 | CONTROL | — | REJECTED (0,855 s frente a 0,855 s) | v0000, 0,855 s (admisión) |
| e00002 | EXPLORATION | `init_scale` 1,0→0,946 | REJECTED (0,959×, IC sup. 1,026) | v0000, 0,855 s |
| e00003 | EXPLORATION | `sched` const→cosine | REJECTED (acc 0,561) | v0000, 0,855 s |
| e00004 | EXPLORATION | `depth` 2→1 | **ACCEPTED** (0,476×, IC95 sup. 0,542) | v0000, 0,849 s (admisión) |
| e00005 | REPLICATION | `depth` 2→1 | **ACCEPTED** (0,475×, IC95 sup. 0,529) → **promoción v0000→v0001** | v0000, 0,849 s |
| e00006–08 | KNOWLEDGE_VALIDATION | volver a `depth` 2, solo o con otros factores | REJECTED (no alcanzan el objetivo) | v0001, 0,344 s (post-promoción) |

- La verificación de v0001 pasó: gates, mejora persistente y **matriz completa a la primera**, sin primer fallo. La baseline se renovó.
- No hubo campaña posterior en este linaje, así que el health check de v0001 no se ejercitó aquí; sí en la serie de réplica.
- La referencia se re-midió en cada admisión y tras la promoción, con deriva de 0,855→0,849 s, y cada registro lleva la suya.
- `meta.tune` corrió una vez y no adoptó cambios.

**Linaje de inferencia `al5ef661cebdd341bb8a48ff50`:**

| Campaña | Exps. | Parada | Wall (s) | Auditor |
| --- | ---: | --- | ---: | --- |
| DRY_RUN / SHADOW | 0 | completadas sin ejecutar | 16 / 16 | PASS / PASS |
| CONTROLLED 1 (`ac2a985c…`) | 3 | `NO_PROGRESS` | 463 | PASS |
| CONTROLLED 2 (`acf0d19e…`) | 3 | `NO_PROGRESS` | 574 | PASS |

- **Stacks probados:** 6, contra el control re-medido en cada experimento:
  - el control;
  - `gpu_layers` 999→12, 18 y 24;
  - `backend` Vulkan→CPU;
  - y `context` 1024→512, que no pasó la cualificación 0.8.
- **Resultado:** ninguno mejoró la latencia de tarea con los guards de 0.8, y el puntero de selección no se movió.
- **Health check:** el de la selección actual pasó en ambas admisiones.

### Serie de promoción y rollback ([`replication/`](integration_evidence/replication/), estado `state_integration_cert4_replication`)

Linaje numpy `al948ec97f15b342bc978fac02`, con DRY_RUN y SHADOW (PASS) y exactamente 6 CONTROLLED, todas PASS en
el informe y en el auditor:

| Campaña | Exps. | Parada | Wall (s) | Hechos |
| --- | ---: | --- | ---: | --- |
| CONTROLLED 1 | 3 | `NO_PROGRESS` | 446 | CONTROL; `warm` 0→50 y `clip` 0→5, REJECTED |
| CONTROLLED 2 | 3 | `NO_PROGRESS` | 347 | `depth` 2→3, `warm` 0→20 y `batch` 64→16, REJECTED |
| CONTROLLED 3 | 5 | `STOPPED_BUDGET` | 1178 | `depth` 2→1 ACCEPTED (0,489×) → REPLICATION ACCEPTED (0,484×) → **promoción v0000→v0001**, verificación PASS (matriz a la primera) → 3 KNOWLEDGE_VALIDATION REJECTED |
| CONTROLLED 4 | 3 | `NO_PROGRESS` | 328 | **health check PASS de v0001**; 3 KNOWLEDGE_VALIDATION REJECTED |
| CONTROLLED 5 | 5 | `STOPPED_BUDGET` | 1371 | health check PASS de v0001; CONTROL; `hidden` 64→48 ACCEPTED (0,873×, IC95 sup. 0,931) → REPLICATION ACCEPTED (0,874×) → **promoción v0001→v0002**, verificación PASS → CONTROL del nuevo campeón; `depth` 1→2 REJECTED |
| CONTROLLED 6 | 3 | `NO_PROGRESS` | 424 | **health check PASS de v0002**; `depth` 1→3, `clip` 0→1 y `lr` 0,05→0,0125, REJECTED |

- **Linaje:** 22 experimentos y 0 duplicados no intencionados.
- **Clases:** CONTROL, EXPLORATION, REPLICATION y KNOWLEDGE_VALIDATION.
- **Ranking:** el ranking aprendido cambió el plan elegido 2 veces.
- **Campeón final:** v0002 (`depth` 1, `hidden` 48), con un coste de ≈0,36× el de v0000 en el workload sintético `numpy_mlp`.
- **Matriz de regresión:** 0 primeros fallos y 0 señales transitorias; cada verificación pasó a la primera.

### Lo que se pidió comprobar

| Pregunta | Respuesta, con evidencia |
| --- | --- |
| ¿La referencia del campeón queda bien refrescada? | **Sí.** 11 mediciones (3 en la definitiva numpy y 8 en la réplica): una en cada admisión, con el guard de deriva (deriva máxima 2,6 %), y una tras cada promoción. Ningún cribado usó una referencia de otra versión: cada `screen_reference` coincide con `version_before`, y el auditor lo verifica en las 16 campañas. Tras promover, el cribado pasó a la referencia de la versión nueva (0,849 → 0,344 s; 0,351 → 0,309 s). La re-medición tras un rollback está probada con tests y en el `BoundedEngine` real con el presupuesto agotado; en estas series no hubo ningún rollback. |
| ¿Qué tests disparan algún rollback? | **Ninguno.** No hubo ningún rollback. Las 3 verificaciones de promoción ejecutaron la matriz completa (615 tests) una sola vez y pasaron. |
| ¿Hubo señales transitorias? | **No.** 0 `REGRESSION_SIGNAL` en los tres linajes y 0 primeros fallos de la matriz. |
| ¿Promoción y rollback realmente ejercitados? | **Promoción: sí, tres veces de forma natural** (v0001 en la definitiva; v0001 y v0002 en la réplica). Todas tuvieron réplica independiente, gates, verificación con matriz y renovación de la baseline, y dos tuvieron además health check PASS en las campañas siguientes. **Rollback: NOT_EXERCISED en la certificación vigente**, porque ninguna verificación ni health check falló. Los rollbacks reales se observaron en la evidencia de desarrollo: uno natural en `bdce836`, con disparador sin determinar, y otro por presupuesto agotado en `26c828c`. En esta certificación se cubren con tests de coordinación, no se fabricaron. |
| Nueva denominación y alcance de la cognición | **Revisión cognitiva consultiva** (`ADVISORY_COGNITIVE_REVIEW`). Las 42 revisiones de las 16 campañas se registran sin influir: la selección fue siempre `DETERMINISTIC_FIRST_ELIGIBLE_PLAN` y el auditor lo comprueba. Que las 42 citen el plan seleccionado es coherente con la limitación estructural del contexto de 8 hechos, no un acuerdo informado. |
| HEAD y árbol certificados | Código `09de7eb` (árbol `gaia/` `d1edb80e…`, identidad `3383b6a2…1290`). Las ejecuciones corrieron con HEAD `c259ca5`, que tiene el mismo árbol `gaia/`. Este informe va en un commit documental posterior que no toca `gaia/`. |
| Suite y serie definitiva finales | Suite: 938, OK, 0 fallos. Serie definitiva: 8/8 PASS. Serie de réplica: 8/8 PASS. Auditor offline v2: 16/16 PASS. |

### Niveles (certificación vigente)

| Nivel | numpy | inferencia |
| --- | --- | --- |
| PIPELINE_CLOSED_LOOP | PASS | PASS |
| AUTONOMOUS_EXECUTION | PASS | PASS |
| AUTONOMOUS_LEARNING | PASS | PASS (registros de linaje) |
| AUTONOMOUS_PROMOTION | **PASS** (definitiva y réplica, con verificación y seguimiento) | NOT_EXERCISED (sin ganancia 0.8) |
| AUTONOMOUS_ROLLBACK | NOT_EXERCISED (sin regresión natural) | NOT_EXERCISED |

### Criterios del plan

| Criterio | Serie definitiva |
| --- | --- |
| ≥3 experimentos distintos por campaña (numpy) | Cumple (3 y 5) |
| ≥2 clases distintas además de CONTROL (numpy) | **Cumple** (EXPLORATION, REPLICATION y KNOWLEDGE_VALIDATION) |
| Vistas `EXACT_CONTEXT` usadas | Cumple |
| Hipótesis valorada y `EXPERIMENT_RECORD` en cada experimento | Cumple (14/14 en la definitiva) |
| Observación completa con baseline → diagnóstico real | Cumple |
| 2ª campaña sin repetir genomas, partiendo del campeón | Cumple |
| Outcomes 0.6 enlazados | Cumple |
| 0 duplicados no intencionados, 0 intervenciones | Cumple |
| Promoción y rollback sólo si son naturales | Cumple (promoción natural; rollback NOT_EXERCISED) |
| Inferencia: ≥3 stacks distintos con control re-medido, decisión con los guards 0.8 | Cumple (6 stacks) |

## Historia de desarrollo

Nada de lo que sigue se combina con la certificación vigente. La evidencia está en
[`integration_evidence/development/`](integration_evidence/development/).

| Etapa | Bytes | Qué mostró |
| --- | --- | --- |
| Series de desarrollo (19 campañas, `development-history.json`) | cuatro identidades anteriores | primeros defectos de integración; dos cadenas completas de promoción natural numpy |
| Primera serie final (`af70650-final/`) | `af70650` | cadena de promoción natural completa; invalidada por las correcciones de `bdce836` |
| Certificación anterior (`bdce836-final/`) | `bdce836` | 8 campañas PASS, sin promoción |
| Evidencia post-certificación pre-registrada (`bdce836-post-certification/`) | `bdce836` | promoción natural verificada y un rollback natural con disparador sin determinar; selección cognitiva degenerada; referencia obsoleta tras rollback. Los tres defectos se corrigieron en `26c828c`. |
| Re-certificación interrumpida (`26c828c-interrupted/`) | `26c828c` | promoción natural interrumpida, recuperada y revertida; re-medición tras rollback rechazada por presupuesto. Corregido en `09de7eb`. |
| Dos ejecuciones de la suite en `09de7eb` (`09de7eb-suite-attempts.json`) | `09de7eb` | 1 fallo de 938 en cada una, en dos tests distintos de `test_rollback` (código de v0.1 sin cambios). Ambos por G2 `BASELINE_UNSTABLE`/`BASELINE_DRIFT` con CV 0,22–0,24 bajo carga de escritorio interactiva. El primero pasa aislado 3/3. La certificación se trasladó a una ventana con el host en reposo. |

Defectos de las series de desarrollo:

- La primera CONTROLLED falló en LEARNING porque el schema de learning rechazaba `gaia-v1.0.1`. Se corrigió aceptando versiones con parche y bloqueando el linaje si un experimento ejecutado no se aprende.
- Un test de inferencia detectó re-benchmarks repetidos del control. Se corrigió con un control por campeón, deducido de los registros del linaje.

## Revisiones independientes

Tras una primera serie final, un test nuevo detectó que los candidatos de inferencia podían
heredar valores del primario fuera del presupuesto activo del host. El adapter de 0.8 los
habría rechazado igualmente. Dos rondas de revisión independiente del diff encontraron,
además, defectos de recuperación ante crash y de contabilidad del linaje que las
ejecuciones normales no ejercitan. Todos se corrigieron con un test de regresión cada uno
(commit `bdce836`):

- Presupuesto agotado al reanudar: el experimento comprometido se recupera, se aprende y se registra bajo una gracia acotada (600 s) que nunca inicia otro experimento. Antes paraba sin aprender.
- Health check: se controla con su propio flag y se actúa sobre un fallo persistido tras un crash.
- Admisión, health check, cierre y bloqueo del linaje: idempotentes; se reconcilian también tras un crash dentro de `report()`.
- Una pausa o un STOP en una fase en vuelo se difiere hasta completar el aprendizaje y la verificación.
- Un error inesperado o un presupuesto agotado durante la verificación hacen rollback de la promoción comprometida.
- Un `meta.tune` interrumpido se registra una sola vez y no se repite.
- Los recibos del puntero de selección enlazan linaje y candidato. Así la recuperación de un linaje no puede atribuirse la promoción de otro.
- El disco antes de la admisión no carga todo el linaje a la campaña nueva.
- Auditor v2: toda evaluación debe tener su registro; contabilidad de intents; política de promoción sobre todas las evaluaciones; `preview_hash` ligado al candidato elegible. Los journals interrumpidos se auditan como registro de integridad de un linaje bloqueado, nunca como loop certificable.

La primera serie final (`state_integration_final`) y sus campañas pasan a ser historia de
desarrollo, porque corrieron sobre bytes anteriores.

El diff de `26c828c` pasó por dos rondas más de revisión independiente antes del commit. Los
defectos que se corrigieron, cada uno con su test:

- la nueva política de matriz alcanzaba a las campañas v1;
- los intentos de la matriz y el primer fallo se escribían sólo al final, de modo que un crash podía borrar el primer fallo o provocar una ejecución de más;
- los fallos dentro de un subTest o de un fixture no podían re-ejecutarse por ID;
- un `KeyError` en las métricas aparecía con journals anteriores;
- la deriva de referencia no bloqueaba;
- el rollback quedaba ligado sólo por la existencia de un recibo;
- había tests que pasaban sin comprobar nada.

Quedó documentado, sin cambiarlo, que la reserva de verificación de 1600 s puede no cubrir el
peor caso de la nueva política (ver «Limitaciones»).

## Tests y regresión

- **Suite completa sobre los bytes certificados, con el host en reposo: 938 tests, OK, 9 skips, 0 fallos y 0 errores**, en 1049,1 s con `-B -W error::ResourceWarning` ([`tests.json`](integration_evidence/tests.json)).
  - Los 9 skips son tests frozen de `gaia_transformer_model`: no hay Torch ni CUDA en el perfil NumPy.
  - Ejecuciones anteriores sobre `09de7eb` bajo carga de escritorio: 1 fallo de temporización cada una, documentado en «Historia de desarrollo».
- Tests nuevos (`tests/test_autonomy_integration.py`, 90) cubren:
  - contratos v2 y escalado de autoridad; linaje (alcance, cambio de fuentes, `LINEAGE_BUSY`, journal corrupto, inspección pura, bloqueo y desbloqueo);
  - ≥3 experimentos distintos por campaña; la 2ª campaña sin repetir genomas;
  - selección dentro de candidatos; review fallida; research no autorizado que continúa; EXPLORATION no promovible;
  - health check con rollback; experimento no aprendido;
  - 0.6 LINKED acotado y a prueba de manipulación; tabla de valoraciones; presupuesto de disco v2;
  - superficie de inferencia (un factor, runtime y modelo fijos, `threads` para `parallelism`, guards antes que latencia);
  - promoción, rechazo, denegación, crash antes del puntero y rollback del puntero;
  - materialización con referencia de learning (PLS y EXPLOITATION de un factor, REPLICATION/KV exactas, réplica de un REJECTED prohibida, factorial lr/wd de 4 celdas fijas y referencia fuera de la superficie HP rechazada);
  - digest de `search` por defecto fijado; búsqueda restringida que nunca sale de HP;
  - auditoría offline v2 con detección de manipulación;
  - recuperación ante crash y presupuesto: gracia de contabilidad, pausa diferida, admisión, health check, cierre y bloqueo idempotentes, `meta.tune` interrumpido, error de verificación con rollback, recuperación de inferencia ligada al linaje y presupuesto de host respetado;
  - referencia del campeón: re-medición en la admisión con el guard de deriva, deriva y referencia no fiable bloqueantes, referencia no ligada al campeón re-medida antes del cribado, re-medición tras el rollback de verificación y del health check (también con el presupuesto agotado, en el `BoundedEngine` real), y el caso de referencia obsoleta de extremo a extremo;
  - política de la matriz: los cinco caminos, la reanudación a mitad de la secuencia sin repetir intentos, la contabilidad de intents, el primer fallo registrado antes de la re-ejecución, la ejecución única en v1, el módulo `regression` con IDs re-ejecutables (incluido un subTest) y un proceso real con un test que falla y rutas privadas proyectadas;
  - revisión consultiva: la selección es siempre el primer plan elegible, aunque el modelo cite otro, y el auditor rechaza lo contrario.
- Byte-idénticos a `fe767aa`: `gaia/protected/`, `engine.py`, `mutate.py`, `genome.py`, `publication.py`, `rollback.py`, `store.py`, `stats.py`, `readiness.py`, `local_intelligence/{benchmark,selection,campaign}.py`, `cognition/benchmark.py`, `learning/engine.py` y `gaia_transformer/` (frozen).
- Cambios opt-in, con ruta por defecto preservada: `diagnosis` (objetivo de mejora), `prioritization` (dos clases de target), `experiment_strategy` (contexto de manifest, LINKED), `search`/`meta` (subconjunto de operadores), `learning/schema` (versión con parche), `local_intelligence/store` (puntero), `cognition/evidence` (paquete de comparación).
- Auditorías de evidencia histórica:
  - la de 1.0 está ligada a sus bytes, así que pasa desde `fe767aa` y, con el auditor nuevo, también pasa tomando la identidad del propio bundle;
  - la de 0.9 (`IMPLEMENTATION_CHANGED_SINCE_REAL_TASKS`) **ya fallaba en `fe767aa`**, porque 1.0 modificó `gaia.py` y `cognition/evidence.py`; no es una regresión de 1.0.1;
  - la de 0.8 (`audit_local_intelligence`) y la de 0.3 (`audit_diagnosis`) pasan;
  - 0.4 y 0.6 reproducen su evidencia dentro de sus suites de tests, que pasan.

## Limitaciones y certificación

Lo que 1.0.1 demuestra, separando las tres afirmaciones de §18:

1. **La infraestructura de automejora funciona.** Sí, en este host y para estas dos superficies. El ciclo §11.1 completo funciona de forma autónoma y acotada:
   - varios experimentos reales y distintos por campaña, y aprendizaje persistente entre las campañas de un linaje;
   - promoción natural con réplica, verificación (incluida la matriz con la política aprobada) y seguimiento;
   - una referencia de cribado siempre ligada al campeón vigente;
   - todo ello sin ampliar la autoridad.
2. **Un experimento concreto mejora.** Sí, localmente: `depth` 2→1 redujo el coste hasta el objetivo del workload sintético `numpy_mlp` a ≈0,48× con réplica independiente, en dos linajes. `hidden` 64→48 sobre esa versión lo redujo a ≈0,87× más. Son mejoras de un trainer CPU sintético, no del LLM ni de GAIA.
3. **GAIA es globalmente más capaz.** **No se afirma.**

PASS significa: «GAIA ejecuta el ciclo §11.1 completo de forma autónoma y acotada sobre dos superficies contratadas, con promoción natural verificada y seguimiento, sin ampliar su autoridad». No significa que el rollback natural esté ejercitado (no lo está en esta certificación), ni que la cognición mejore decisiones.

Limitaciones conocidas, independientes del resultado:

- **Reserva de verificación.**
  - Una promoción exige 1600 s restantes, y ese umbral no se cambió.
  - Si la matriz falla una vez, el peor caso de la política aprobada son dos matrices completas (≈620 s cada una) más la re-ejecución, la observación completa, los gates y la re-medición, cerca del límite.
  - Si el presupuesto se agota durante la verificación, la promoción se revierte (`VERIFICATION_BUDGET_EXHAUSTED`) y se conservan los intentos ya registrados. Es conservador, pero puede revertir una promoción válida.
- **Interrupciones externas.** Si el proceso muere durante una verificación, la promoción se revierte al reanudar, porque el presupuesto ya no cubre la verificación. Ocurrió de verdad en `26c828c`. Por eso las certificaciones corren desacopladas de la sesión del operador.
- **Host.** Las medidas y los tests G2 de v0.1 dependen de la temporización. Con carga de escritorio interactiva, la suite falló dos veces en tests distintos que pasan aislados, así que la certificación exige el host en reposo. La deriva de referencia en la admisión (umbral 35 %) para la campaña y bloquea el linaje hasta revisión humana.
- **Cognición.** La revisión consultiva no aporta valor de decisión demostrado. Con el contexto de 8 hechos de 0.9 no puede aportarlo.
- **Inferencia.** Su referencia es el control re-medido en cada experimento, no una referencia almacenada. No necesita re-medición tras un rollback.

No demuestra endurance (objetivo de 1.1), memoria cognitiva general (Nivel B), cambios de modelo
o pesos (Nivel C) ni superficies de slots o código. La certificación es específica del host y de
la configuración evaluados.
