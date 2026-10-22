# GAIA 1.0.1 — Integración completa del closed loop

## Estado y alcance

**PASS de integración del ciclo §11.1 del Documento Maestro v3 sobre dos superficies acotadas:**
hiperparámetros del trainer `numpy_mlp` y configuración de inferencia del LLM local (Nivel A).
Rama única `feat/gaia-1.0.1-integration`, base `fe767aa` / `gaia-v1.0`. Commits funcionales
`af70650` (integración) y `bdce836` (correcciones de recuperación tras revisión independiente);
la evidencia y este informe van en un commit documental separado.

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
| 11 Seguimiento | sólo verificación inmediata, con `compare` vacío | verificación con observación completa + health check del linaje en cada admisión; si falla, rollback al predecesor conocido y bloqueo del linaje |
| 12 Aprendizaje | store por campaña; `STRATEGY_OUTCOME` sin lector | linaje persistente; 0.6 LINKED con outcomes reales; `meta.tune` restringido a la superficie |
| Cognición | 1 de 7 tipos de tarea, como veto | `COMPARE` sobre los planes elegibles con el resultado anterior; elección extractiva limitada a los candidatos previsualizados |
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
- 0.6 LINKED: `outcome_statistics` reproducible y validada, con bonus por clase acotado a ±3 y `static_ranking` para comparar. Los `DEFAULTS` de la política no cambian.
- `search.Strategy` y `meta` aceptan un subconjunto de operadores. La ruta por defecto es idéntica a 1.0: 60 propuestas × 5 semillas dan el mismo digest con el código de `fe767aa`, y queda fijado en un test.
- `tools/audit_closed_loop.py` añade la rama v2: reproducción estructural del journal, presupuestos, previsualización = materialización, superficie y novedad frente al linaje previo, selección dentro de los candidatos, `authorize`, valoraciones, registros, decisión pareada protegida (numpy) o decisión 0.8 frente a los benchmarks guardados (inferencia), y promoción sólo bajo política. La elección de operador por pesos no se re-muestrea; se verifica por superficie y novedad.

## Certificación real definitiva

Todo se ejecutó sobre los bytes de `bdce836`: identidad de fuentes
`48041114f55406f06ba3db0cf43f0ff169f7ea219225c382eaa3866593d5370b`, protected hash
`9376438978e4c78ecee88ca5c839914760b13f312f340f4691905ddc94261e1f`.

- Se usó un estado nuevo, `state_integration_final2`, con dos linajes nuevos.
- Cada linaje corrió la serie DRY_RUN → SHADOW → 2 × CONTROLLED_AUTONOMOUS.
- La serie empezó justo después de la suite completa en verde.
- Las 8 campañas terminan PASS en el informe y en el auditor offline v2; ninguna es un registro interrumpido.
- El ledger CPU es válido y todas las trazas cognitivas pasan la auditoría.

La evidencia portable está en `docs/integration_evidence/final/`.

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
| AUTONOMOUS_PROMOTION | **NOT_EXERCISED** en la serie definitiva | NOT_EXERCISED |
| AUTONOMOUS_ROLLBACK | NOT_EXERCISED | NOT_EXERCISED |

No se forzó ninguna mejora ni se provocó una regresión, y no se lanzaron campañas
adicionales hasta conseguir una promoción, porque eso sería seleccionar el resultado.

La cadena de promoción natural sí se observó en dos series completas sobre bytes anteriores,
cuya ruta de experimentación numpy es la misma (las correcciones posteriores afectan a la
recuperación ante crash, a la contabilidad del linaje y al filtro de presupuesto de inferencia):

- en `state_integration` (identidad `cd4a41d2…`): `init_scale` 1,0→0,4857;
- en `state_integration_final` (identidad `2a93e2be…`, export en `docs/integration_evidence/superseded-af70650/`): `hidden` 64→32.

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

Los rollbacks (verificación fallida, health check fallido, puntero de selección) y la
promoción de inferencia se prueban sólo con tests de coordinación.

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

- **Selección cognitiva:** en las 12 decisiones CONTROLLED de la serie definitiva, igual que en todas las anteriores, el modelo citó el plan que ya era primero en el ranking determinista. La comparación cognitiva está integrada y acotada, pero **no hay evidencia de que mejore la selección**.
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

## Historia de desarrollo

`docs/integration_evidence/development-history.json` conserva las 19 campañas de desarrollo y
superadas, en `state_integration` y `state_integration_final`, con cuatro identidades de
fuentes distintas a la definitiva. No se combinan con la serie definitiva.

- La primera CONTROLLED falló en LEARNING porque el schema de learning rechazaba `gaia-v1.0.1`. Se corrigió aceptando versiones con parche y bloqueando el linaje si un experimento ejecutado no se aprende.
- Un test de inferencia detectó re-benchmarks repetidos del control. Se corrigió con un control por campeón, deducido de los registros del linaje.
- Dos series numpy anteriores ejercitaron la cadena completa de promoción natural (descrita arriba). Las series de inferencia anteriores no encontraron mejora.

## Revisión independiente y correcciones antes de la serie definitiva

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
desarrollo: corrieron sobre bytes anteriores. La serie definitiva se repitió desde cero
sobre los bytes corregidos.

## Tests y regresión

- **Suite completa sobre los bytes definitivos (`bdce836`), sin carga concurrente, justo antes de la serie: 919 tests, OK, 9 skips, 0 fallos y 0 errores**, en 1.037,7 s, con `-B -W error::ResourceWarning` (`docs/integration_evidence/tests.json`).
  - Los 9 skips son tests frozen de `gaia_transformer_model`: no hay Torch ni CUDA en el perfil NumPy.
  - Dos ejecuciones sobre bytes anteriores tuvieron un único fallo cada una en tests de medición en tiempo real:
    - `test_core…short_autonomous_run`, en una ejecución con exportación y auditoría en paralelo;
    - `test_ledger…orphan`, por un G2 `BASELINE_UNSTABLE` con CV 0,22 en bytes previos.

    Ninguno de los dos se reprodujo al aislarlo (3/3 PASS cada uno) ni en la ejecución limpia. Se declaran como dependientes de la temporización del host, no como fallos resueltos por cambios.
- Tests nuevos (`tests/test_autonomy_integration.py`, 69) cubren:
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
  - recuperación ante crash y presupuesto: gracia de contabilidad, pausa diferida, admisión, health check, cierre y bloqueo idempotentes, `meta.tune` interrumpido, error de verificación con rollback, recuperación de inferencia ligada al linaje y presupuesto de host respetado.
- Byte-idénticos a `fe767aa`: `gaia/protected/`, `engine.py`, `mutate.py`, `genome.py`, `publication.py`, `rollback.py`, `store.py`, `stats.py`, `readiness.py`, `local_intelligence/{benchmark,selection,campaign}.py`, `cognition/benchmark.py`, `learning/engine.py` y `gaia_transformer/` (frozen).
- Cambios opt-in, con ruta por defecto preservada: `diagnosis` (objetivo de mejora), `prioritization` (dos clases de target), `experiment_strategy` (contexto de manifest, LINKED), `search`/`meta` (subconjunto de operadores), `learning/schema` (versión con parche), `local_intelligence/store` (puntero), `cognition/evidence` (paquete de comparación).
- Auditorías de evidencia histórica:
  - la de 1.0 está ligada a sus bytes, así que pasa desde `fe767aa` y, con el auditor nuevo, también pasa tomando la identidad del propio bundle;
  - la de 0.9 (`IMPLEMENTATION_CHANGED_SINCE_REAL_TASKS`) **ya fallaba en `fe767aa`**, porque 1.0 modificó `gaia.py` y `cognition/evidence.py`; no es una regresión de 1.0.1;
  - la de 0.8 (`audit_local_intelligence`) y la de 0.3 (`audit_diagnosis`) pasan;
  - 0.4 y 0.6 reproducen su evidencia dentro de sus suites de tests, que pasan.

## Limitaciones y certificación

Lo que 1.0.1 demuestra, separando las tres afirmaciones de §18:

1. **La infraestructura de automejora funciona.** Sí, en este host y para estas dos superficies: observación con baseline, diagnóstico, priorización, learning con contexto y persistente entre campañas de un linaje, estrategia enlazada a outcomes, cognición acotada, experimentación protegida con varios experimentos reales y distintos por campaña, evaluación, valoración de hipótesis, stopping correcto, seguimiento y metaoptimización restringida. La promoción natural se observó en series de desarrollo, no en la definitiva.
2. **Un experimento concreto mejora.** No en la serie definitiva. En las series de desarrollo, `hidden` 64→32 e `init_scale` 1,0→0,4857 redujeron el coste hasta el objetivo del workload sintético `numpy_mlp` (≈0,69–0,70× con réplica en el primer caso). Son mejoras locales de un trainer CPU, no del LLM ni de GAIA.
3. **GAIA es globalmente más capaz.** **No se afirma.**

No demuestra endurance (es el objetivo de 1.1), memoria cognitiva general (Nivel B),
cambios de modelo o pesos (Nivel C), superficies de slots o código, ni que la comparación
cognitiva mejore las decisiones. Tampoco demuestra un rollback autónomo real, una
promoción de inferencia real ni una promoción en la serie definitiva. La certificación es
específica del host y de la configuración evaluados.

PASS significa: «GAIA ejecuta el ciclo §11.1 completo de forma autónoma y acotada, con
varios experimentos reales y distintos por campaña y aprendizaje persistente entre campañas
de un linaje, sobre dos superficies contratadas, sin ampliar su autoridad». La promoción
natural queda demostrada como capacidad en desarrollo y NOT_EXERCISED en la serie definitiva.
