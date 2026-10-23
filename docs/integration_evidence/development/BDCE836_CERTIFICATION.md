# GAIA 1.0.1: certificación anterior en `bdce836` (invalidada)

Esta es la certificación de `bdce836` y la evidencia post-certificación pre-registrada que vino
después. Se conserva íntegra como **evidencia de desarrollo**. Los tres defectos que encontró se
corrigieron en `26c828c` y `09de7eb`, y eso cambió `gaia/`, por lo que esta certificación ya no vale
para los bytes actuales. No se combina con la certificación vigente, descrita en
[`GAIA_1_0_1_INTEGRATION_REPORT.md`](../../GAIA_1_0_1_INTEGRATION_REPORT.md).

Evidencia: [`bdce836-final/`](bdce836-final/), [`bdce836-post-certification/`](bdce836-post-certification/),
[`bdce836-tests.json`](bdce836-tests.json).

## Certificación real definitiva

Todo se ejecutó sobre los bytes de `bdce836`: identidad de fuentes
`48041114f55406f06ba3db0cf43f0ff169f7ea219225c382eaa3866593d5370b`, protected hash
`9376438978e4c78ecee88ca5c839914760b13f312f340f4691905ddc94261e1f`.

- Se usó un estado nuevo, `state_integration_final2`, con dos linajes nuevos.
- Cada linaje corrió la serie DRY_RUN → SHADOW → 2 × CONTROLLED_AUTONOMOUS.
- La serie empezó justo después de la suite completa en verde.
- Las 8 campañas terminan PASS en el informe y en el auditor offline v2; ninguna es un registro interrumpido.
- El ledger CPU es válido y todas las trazas cognitivas pasan la auditoría.

La evidencia portable está en `docs/integration_evidence/development/bdce836-final/`.

### Linaje numpy `al6cecd0cecf0548b49de379f6` (`IMPROVE_NUMPY_MLP_EXISTING_CRITERIA`)

| Campaña | Experimentos | Parada | Wall (s) |
| --- | ---: | --- | ---: |
| DRY_RUN | 0 | `DRY_RUN_COMPLETE_NO_EXPERIMENT_EXECUTED` | 19 |
| SHADOW | 0 | `SHADOW_COMPLETE_NO_EXPERIMENT_EXECUTED` | 20 |
| CONTROLLED 1 (`acd232995e7b494bb5a051362a`) | 3 | `NO_PROGRESS` | 402 |
| CONTROLLED 2 (`acbc3e837fd8de4ca1b253cd16`) | 3 | `NO_PROGRESS` | 375 |

| Exp. | Clase | Cambio | Resultado | Hipótesis |
| --- | --- | --- | --- | --- |
| e00001 | CONTROL_EXPERIMENT | — | REJECTED (0,857 s frente a 0,857 s) | SUPPORTED (control consistente) |
| e00002 | EXPLORATION | `hp.clip` 0→0,5 | REJECTED (no alcanza el objetivo; acc 0,548) | NOT_SUPPORTED |
| e00003 | EXPLORATION | `hp.lr` 0,05→0,01706 | REJECTED (acc 0,598) | NOT_SUPPORTED |
| e00004 | EXPLORATION | `hp.hidden` 64→96 | REJECTED (acc 0,621) | NOT_SUPPORTED |
| e00005 | EXPLORATION | `hp.depth` 2→3 | REJECTED (acc 0,610) | NOT_SUPPORTED |
| e00006 | EXPLORATION | `hp.hidden` 64→128 | REJECTED (acc 0,613) | NOT_SUPPORTED |

- **Sin repeticiones:** la 2ª campaña no repitió ningún genoma de la 1ª ni volvió a medir el control del mismo campeón (`CONTROL_ALREADY_EXECUTED_FOR_CURRENT_CHAMPION`). Se saltaron 11 planes, 5 como duplicados, y el learning se consultó con vistas `EXACT_CONTEXT`.
- **meta.tune:** corrió una ronda pareada sobre la superficie HP (32 evaluaciones nuevas del paisaje, 66 s) y no adoptó cambios (`descartada`).
- **Sin promoción:** ningún candidato alcanzó el criterio protegido.

### Linaje de inferencia `alde0dadd3a32f4eacbc0a76af` (`IMPROVE_LOCAL_INFERENCE_EXISTING_CRITERIA`)

| Campaña | Experimentos | Parada | Wall (s) |
| --- | ---: | --- | ---: |
| DRY_RUN | 0 | completada sin ejecutar | 17 |
| SHADOW | 0 | completada sin ejecutar | 17 |
| CONTROLLED 1 (`aca92d162469fe426783b32cb7`) | 3 | `NO_PROGRESS` | 357 |
| CONTROLLED 2 (`acc03bb16130854fe4a04e276c`) | 3 | `NO_PROGRESS` | 490 |

| Exp. | Clase | Cambio | Latencia tarea control → candidato (s) | Resultado |
| --- | --- | --- | --- | --- |
| i00001 | CONTROL_EXPERIMENT | — | 0,744 → 0,740 | REJECTED, control consistente |
| i00002 | EXPLORATION | threads 8→2 | 0,735 → 0,741 | REJECTED (sin ganancia verificada) |
| i00003 | EXPLORATION | context 1024→512 | 0,745 → — | REJECTED (no supera la cualificación 0.8) |
| i00004 | EXPLORATION | kv f16→q8_0 | 0,743 → 0,766 | REJECTED |
| i00005 | EXPLORATION | threads 8→6 | 0,747 → 0,751 | REJECTED |
| i00006 | EXPLORATION | gpu_layers 999→12 | 0,753 → 1,817 | INCONCLUSIVE (latencia no STABLE) |

La configuración primaria (KoboldCpp + SmolLM3-3B Q4_K_M, Vulkan, offload completo, KV f16)
no fue mejorada por ninguna variación de un factor. El puntero de selección no se movió.
El offload parcial es mucho más lento, pero su latencia no fue STABLE y la regla de 0.8
exige estabilidad antes de comparar; por eso queda INCONCLUSIVE y no REJECTED, lo que es
conservador y queda declarado.

### Niveles

| Nivel | numpy | inferencia |
| --- | --- | --- |
| PIPELINE_CLOSED_LOOP | PASS | PASS |
| AUTONOMOUS_EXECUTION | PASS | PASS |
| AUTONOMOUS_LEARNING | PASS | PASS (registros de linaje; el schema 0.5 es específico de numpy) |
| AUTONOMOUS_PROMOTION | **NOT_EXERCISED** en la serie definitiva; **PASS** en la serie de réplica pre-registrada sobre los mismos bytes (v0002 verificada y health check PASS) | NOT_EXERCISED |
| AUTONOMOUS_ROLLBACK | NOT_EXERCISED en la serie definitiva; **EXERCISED_TRIGGER_UNDETERMINED** en la réplica (rollback v0001→v0000 completo; disparador probablemente un falso positivo de la matriz) | NOT_EXERCISED |

No se forzó ninguna mejora ni se provocó una regresión, y no se lanzaron campañas
adicionales hasta conseguir una promoción, porque eso sería seleccionar el resultado.

La cadena de promoción natural sí se observó en dos series completas sobre bytes anteriores,
cuya ruta de experimentación numpy es la misma (las correcciones posteriores afectan a la
recuperación ante crash, a la contabilidad del linaje y al filtro de presupuesto de inferencia):

- en `state_integration` (identidad `cd4a41d2…`): `init_scale` 1,0→0,4857;
- en `state_integration_final` (identidad `2a93e2be…`, export en `docs/integration_evidence/development/af70650-final/`): `hidden` 64→32.

En ambas, la secuencia fue:

1. EXPLORATION ACCEPTED (coste 0,701× frente a la referencia, IC95 sup. 0,857, en el segundo caso);
2. promoción denegada por política;
3. REPLICATION independiente ACCEPTED (0,690×);
4. promoción v0000→v0001 con gates;
5. verificación PASS;
6. baseline renovada;
7. KNOWLEDGE_VALIDATION del baseline antiguo;
8. control del nuevo campeón;
9. health check PASS en la campaña siguiente.

Ambas series pasaron el auditor v2 sobre su propia identidad. **Es evidencia de desarrollo,
no se combina con la certificación definitiva.**

En la serie definitiva, los rollbacks y la promoción de inferencia sólo estaban probados con
tests de coordinación. La serie de réplica pre-registrada (sección «Evidencia
post-certificación») ejercitó la promoción y el rollback numpy reales sobre los mismos bytes.
El rollback por health check fallido y el del puntero de selección siguen probados sólo con
tests de coordinación.

### Métricas agregadas (serie definitiva)

| Métrica | numpy | inferencia |
| --- | ---: | ---: |
| Experimentos ejecutados | 6 | 6 |
| Genomas o stacks distintos | 6 | 6 |
| Clases ejercitadas | CONTROL, EXPLORATION | CONTROL, EXPLORATION |
| Factores variados | clip, lr, hidden, depth | threads, context, kv, gpu_layers |
| Accepted / rejected / inconclusive | 0 / 6 / 0 | 0 / 5 / 1 |
| Planes saltados (como duplicado) | 11 (5) | 5 (5) |
| Duplicados no intencionados ejecutados | 0 | 0 |
| Estrategias con outcomes enlazados / top cambiado por lo aprendido | 5 / 0 | 5 / 0 |
| Selecciones cognitivas (de ellas, el primer plan del ranking) | 6 (6) | 6 (6) |
| meta.tune ejecutado / adoptado | 1 / 0 | — |
| Intervenciones humanas durante campañas | 0 | 0 |
| Red / research | 0 / 0 | 0 / 0 |

Limitaciones medidas:

- **Selección cognitiva:** en las 12 decisiones CONTROLLED de la serie definitiva, igual que en todas las anteriores, el modelo citó el plan que ya era primero en el ranking determinista. La evaluación contrabalanceada posterior muestra que en la ruta certificada esto ocurre **por construcción** (27/27 primera posición, 0/5 casos decisivos), no por acuerdo con el ranking. Ver «Evidencia post-certificación».
- **Ranking aprendido:** el ranking LINKED no cambió el plan elegido en esta serie; sí lo hizo una vez en la serie superada.
- **Diagnóstico numpy:** en la serie definitiva, el diagnóstico con baseline sólo produjo el objetivo de mejora. En series anteriores produjo además issues reales (`HIGH_MEASUREMENT_VARIABILITY`, `RESOURCE_AVAILABILITY_CHANGED`, `PERFORMANCE_REGRESSION`), siempre sin causalidad establecida.
- **Diagnóstico de inferencia:** el linaje de inferencia diagnostica sin baseline de observación; su referencia comparable es el control re-medido en cada experimento.

### Criterios del plan

| Criterio | Serie definitiva |
| --- | --- |
| ≥3 experimentos distintos por campaña (numpy) | **Cumple** (3 y 3, todos genomas distintos) |
| ≥2 clases distintas además de CONTROL (numpy) | **No cumple**: sólo EXPLORATION. REPLICATION, KNOWLEDGE_VALIDATION y PLS dependen de un ACCEPTED natural, que no apareció. Se cumplió en las dos series anteriores. |
| Vistas `EXACT_CONTEXT` usadas | Cumple |
| Hipótesis valorada y `EXPERIMENT_RECORD` en cada experimento | Cumple (12/12) |
| Observación completa con baseline → diagnóstico real | Cumple (baseline del linaje usada desde la 2ª campaña) |
| 2ª campaña sin repetir genomas, partiendo del campeón | Cumple |
| Outcomes 0.6 enlazados | Cumple |
| 0 duplicados no intencionados, 0 intervenciones | Cumple |
| Promoción/rollback sólo si son naturales | Cumple (NOT_EXERCISED, declarado) |
| Inferencia: ≥3 stacks distintos con control re-medido, decisión con los guards 0.8 | Cumple (6 stacks) |

## Evidencia post-certificación (pre-registrada)

Tras la certificación se analizó qué evidencia adicional podía obtenerse sin falsear la
serie definitiva. El diseño se commiteó antes de ejecutar nada: el pre-registro está en
[`PREREGISTRATION.md`](bdce836-post-certification/PREREGISTRATION.md) (`98ea9f4`) y el harness
cognitivo en `b169fa6`/`8ee4075`. La serie definitiva no se modificó, no se extendió ni se repitió.
Todo corrió sobre los mismos bytes certificados (identidad `48041114…370b`), sin cambiar
evaluador, benchmarks, criterios, políticas, umbrales ni presupuestos. Los ficheros de
`tools/` quedan fuera de la identidad de fuentes. Evidencia:
[`bdce836-post-certification/`](bdce836-post-certification/).

### Clasificación previa

| Evidencia | Clasificación | Motivo |
| --- | --- | --- |
| Promoción natural numpy | Demostrable de forma legítima | Una serie independiente con tamaño fijo y todas sus campañas reportadas no selecciona el resultado. |
| Rollback numpy | Natural sólo si ocurre; en otro caso, un drill declarado | Provocar una regresión sería fabricarla. El drill (presión de memoria, sin tocar estado ni fuentes) sólo estaba previsto si hubiera promoción y no hubiera rollback natural. |
| Promoción y rollback de inferencia | Siguen en `NOT_EXERCISED` | El puntero sólo se mueve tras una ganancia real con los guards 0.8; un drill necesitaría una promoción fabricada. |
| Valor de la selección cognitiva | Evaluable con escenarios controlados | Se usa la ruta certificada sin cambios, sobre entradas reales y contrabalanceadas, más casos con respuesta fijada de antemano. |

### Serie de réplica independiente (numpy)

Estado nuevo `state_integration_replication` y linaje nuevo `ale7725b87d8e948cda002115c`.
La serie fue DRY_RUN → SHADOW → exactamente 6 CONTROLLED, sin parada anticipada. **Las 8 campañas terminan PASS
en el informe y en el auditor offline v2.**

| Campaña | Exps. | Parada | Wall (s) | Hechos |
| --- | ---: | --- | ---: | --- |
| CONTROLLED 1 | 3 | `NO_PROGRESS` | 406 | CONTROL; `sched` const→cosine y `clip` 0→5, REJECTED |
| CONTROLLED 2 | 2 | `POST_PROMOTION_REGRESSION_ROLLED_BACK` | 923 | EXPLORATION `depth` 2→1 ACCEPTED (0,489×, IC95 sup. 0,562) → REPLICATION ACCEPTED (0,485×) → **promoción v0000→v0001** → verificación FAIL → **rollback autónomo a v0000** (COMPLETED, validaciones PASS) |
| CONTROLLED 3 | 5 | `STOPPED_BUDGET` | 1190 | PLS `depth`1+`init_scale` REJECTED (ver defecto 1) → PLS `hidden` 64→32 + `depth` 2→1 ACCEPTED (0,426×, IC95 sup. 0,515) → **promoción v0000→v0002** → **verificación PASS** (gates, mejora persistente, matriz) → 3 KNOWLEDGE_VALIDATION REJECTED |
| CONTROLLED 4 | 3 | `NO_PROGRESS` | 307 | **health check PASS de v0002** en la admisión; 2 KNOWLEDGE_VALIDATION y 1 EXPLORATION REJECTED |
| CONTROLLED 5 | 3 | `NO_PROGRESS` | 375 | EXPLORATION `batch`, `warm`, `depth`, REJECTED |
| CONTROLLED 6 | 3 | `NO_PROGRESS` | 362 | EXPLORATION `sched`, `batch` ×2, REJECTED |

- **Resultado pre-registrado:** `PROMOTION_REACHED`.
- **Clases ejercitadas:** CONTROL, EXPLORATION, REPLICATION, PARAMETER_LOCAL_SEARCH y KNOWLEDGE_VALIDATION. Sobre los bytes certificados se cumple el criterio «≥2 clases además de CONTROL» que la serie definitiva no alcanzó.
- **Ranking aprendido:** el ranking LINKED cambió una vez el plan elegido.
- **Linaje:** 19 experimentos, 0 duplicados no intencionados, 0 intervenciones.
- **Campeón final:** v0002 (`hidden` 32, `depth` 1), con un coste de ≈0,43× el de v0000 en el workload sintético `numpy_mlp`.
- **Drill de memoria:** no se ejecutó. Hubo un rollback natural y el pre-registro sólo preveía el drill si no lo hubiera.

**Causa del rollback de v0001.** Los gates pasaron y la mejora persistía. Lo que falló fue
la matriz de regresión: 615 tests fijos en un proceso separado. La matriz sólo guarda
hashes de stdout y stderr, y stdout lleva UUIDs aleatorios, así que el test que falló no puede
recuperarse. La causa queda **sin determinar**, con indicios de que no fue una regresión del genoma:

- la matriz se re-ejecutó 3 veces después de la serie, sobre el estado final, y pasó todas (615 tests, OK);
- los tests usan estados temporales propios, que no dependen del campeón del linaje;
- v0002, que contiene el mismo cambio `depth` 2→1, pasó la matriz en la campaña siguiente;
- la matriz incluye `test_ledger`, uno de los tests de temporización ya documentados como inestables.

El mecanismo de rollback sí se ejercitó de verdad y de forma autónoma: intent, Engine
rollback, ledger, validaciones y parada. Pero lo más probable es que el disparador fuera un
**falso positivo** de la matriz, no una regresión del candidato. Por eso se clasifica como
`AUTONOMOUS_ROLLBACK: EXERCISED_TRIGGER_UNDETERMINED`, no como «rollback por regresión real».

### Selección cognitiva del plan (contrabalanceada)

`tools/eval_cognitive_selection.py` (`cognitive-selection.json`) tiene dos partes:

- **PRODUCTION** ejecuta el `Services.compare` certificado sin cambios. Lo aplica a las 6 entradas reales con más de un candidato de la serie definitiva, bajo todas las rotaciones del orden (17 presentaciones). Además usa 5 casos con respuesta fijada de antemano, en ambos órdenes (10 presentaciones): repetir un factor que acaba de fallar, valor de información, repetición exacta de un rechazado, réplica pendiente de un aceptado, y coste/riesgo.
- **PROBE** pregunta al mismo backend 0.8, fuera de la ruta certificada, con todos los campos visibles.

| | PRODUCTION | PROBE |
| --- | ---: | ---: |
| Elige la primera posición | **27/27** | 10/27 |
| Mismo plan en todas las rotaciones (entradas reales) | 0/6 | 2/6 |
| Casos acertados en ambos órdenes | **0/5** | 4/5 |
| La rotación 0 reproduce la decisión registrada | 6/6 | — |

Conclusiones:

1. **En la ruta certificada, la cognición no aporta valor: reproduce la posición, no el contenido.** La causa es estructural y está registrada en los artefactos CONTEXT:
   - el constructor de contexto 0.9 admite como máximo 8 hechos;
   - la relevancia por palabras del objetivo prioriza `plan_id` y `risk`, así que el campo que distingue los planes (`change`) y el resultado anterior nunca llegan al modelo;
   - el contrato de salida sugiere `["f1"]`, que es el `plan_id` del candidato 0.

   Además, en la serie definitiva los candidatos empatados en todas las estimaciones aparecían ordenados por `plan_id`, que es un hash. El «primero del ranking» era, por tanto, un desempate arbitrario.
2. **Con toda la información, el modelo lee los campos** y acierta 4 de 5 casos en ambos órdenes. Pero esos 4 casos dependen de campos que el ranking determinista ya pondera: valor de información, coste, riesgo, penalización de repetición y bono de réplica. Falló el único caso que exigía razonar más allá del ranking, con el resultado anterior: acertó en un orden y no en el otro. Además, en las dos entradas reales CONTROL frente a EXPLORATION eligió saltarse el control, que el diseño exige primero. **No hay evidencia de que mejore la selección. Hay indicios de que, si viera más, podría empeorarla.**

## Defectos detectados por la evidencia post-certificación

Estos defectos son reales y la serie definitiva no los cubría. No se han corregido todavía: corregir `gaia/` cambia la
identidad de fuentes e invalida la certificación, que habría que repetir.

1. **Referencia del campeón obsoleta tras un rollback; sin recalibración en el loop.**
   - **Qué hace v0.1:** `Engine.run` re-mide la referencia al empezar y cada `recalibrate_every` experimentos, con el guard de deriva.
   - **Qué hace 1.0.1:** el loop llama a `Engine.experiment()` directamente y sólo refresca la referencia en `verify()`, sobre la versión promovida.
   - **Consecuencia observada:** tras el rollback a v0000, e00006 (0,360 s) se cribó contra 0,357 s, el coste de la v0001 revertida, en lugar de ≈0,84 s, el coste real de v0000 re-medido en e00007. Un candidato de ≈0,43× quedó REJECTED y así se aprendió.
   - **Efecto:** el error es conservador (no puede promover nada malo, porque la confirmación re-mide al campeón), pero contamina el aprendizaje y anula el guard de deriva de v0.1 en campañas largas, lo que afecta directamente a 1.1.
   - **Corrección propuesta:** re-medir la referencia, con el guard de deriva, en la admisión de cada campaña CONTROLLED y tras cada rollback.
2. **La matriz de regresión no es auditable y es sensible a tests inestables.** No persiste qué tests fallaron, y un solo fallo de temporización revierte una promoción válida.
   - **Corrección mínima, sin cambio de política:** persistir los IDs de los tests que fallan.
   - **Decisión que corresponde al operador, porque cambia el criterio de rollback:** re-ejecutar una vez sólo los tests que fallaron, o estabilizar los tests de temporización.
3. **La comparación cognitiva en la ruta certificada es degenerada** (ver arriba). Opciones:
   - **(a)** declararla como lo que es: un ancla de trazabilidad cuyo resultado coincide por construcción con el primer candidato, con método renombrado y métricas que no la cuenten como «selección cognitiva»;
   - **(b)** rediseñar la proyección y el contrato, y re-evaluar con un conjunto pre-registrado mayor antes de dejarla influir.

   Dado (2) de las conclusiones, la opción recomendada es (a).
