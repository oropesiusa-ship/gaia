# GAIA 0.5 — Experimental Learning & Knowledge Consolidation

## Resultado y alcance

**PASS de etapa, sin merge ni release.** Una única rama:
`feat/gaia-0.5-experimental-learning`, desde `main` limpio en
`f7f25671b4df9dda83888d0050e1717a8eeb3008`, coincidente con
`gaia-v0.4-target-selection`. No se modifican las ramas históricas ni sus tags.
Autoridad conceptual: [Documento Maestro v3](GAIA_MASTER_ARCHITECTURE_V3.md).

GAIA puede convertir historia experimental en conocimiento estructurado,
contextual, trazable y reutilizable. Esto implementa memoria de ingeniería,
conservación de negativos y progreso acumulativo verificable. **History !=
learning != knowledge.** No demuestra aprendizaje neuronal, elección automática
del siguiente experimento óptimo, generalización fuera del contexto ni aumento
de inteligencia general.

El sistema interpreta evidencia guardada, no propone soluciones ni selecciona
nuevas configuraciones. Los valores de configuración que conserva son los que
ya fueron probados; no son propuestas para el próximo experimento. No modifica
prioridades 0.4, Strategy, evaluadores, código ni hardware.

## Arquitectura y autoridad

Subsistema separado `gaia/learning/`:

| Módulo | Responsabilidad |
| --- | --- |
| `schema.py` | Fuentes curadas, learning records/knowledge, canonicalidad, hashes, jerarquía y contabilidad |
| `ingestion.py` | Proyección CPU explícita desde artefactos permitidos y lectura portátil |
| `records.py` | Resultado histórico → claim contextual con evidencia y faltantes |
| `consolidation.py` | Consolidación exacta y síntesis prudente de direcciones observadas |
| `contradictions.py` | Relaciones supports/weakens/contradicts/supersedes sin reescritura |
| `applicability.py` | Contexto explícito, transferibilidad y staleness |
| `engine.py` | Composición determinista, duplicados y comparación de experimentos |
| `store.py` | Artefactos inmutables y batches con punto de commit atómico |
| `query.py` | Filtros relevantes y vistas efectivas de supersession/contradicción |
| `report.py`, `cli.py` | Informes y operaciones explícitas sobre evidencia guardada |

No importa ni llama Engine.run, Strategy, mutate, publication, rollback,
collectors, diagnosis o priorización. El compositor `learning.engine` es ajeno
al Engine evolutivo. Las únicas escrituras son documentos propios de learning
o exports solicitados explícitamente. No hay auto-learn silencioso ni integración
automática al terminar experimentos. Sin dependencias nuevas; usa stdlib y
primitivas canónicas locales existentes.

Tooling: `tools/curate_learning_sources.py` y `tools/audit_learning.py`.
La curación lee artefactos estructurados de un archivo CPU explícito; no importa
ni ejecuta trainers, snapshots o código experimental archivado.

## Schema, identidad y jerarquía

`learning_schema = "gaia_experimental_learning_v1"`; intérprete `0.5.0`.
El mismo envelope distingue `kind=record` y `kind=knowledge`. Incluye learning_id,
source_experiments, source_versions, source_evidence_hashes, domain, component,
claim, claim_type, applicability, supporting_evidence, contradictory_evidence,
confidence, replication_status, status, limitations, created_at, supersedes,
superseded_by, quality, hierarchy y hash.

La fuente portátil es `gaia_learning_sources_v1`; la ejecución interpretativa
`gaia_learning_run_v1` conserva fuentes, settings, records, knowledge, relaciones,
comparaciones, duplicados, coste, versión del intérprete y hash. La cadena de
batches usa `gaia_learning_batch_v1`. Cada nivel tiene su propio hash canónico.

Jerarquía explícita:

```text
OBSERVATION → HYPOTHESIS → EXPERIMENTAL_EVIDENCE
            → REPLICATED_EVIDENCE → OPERATIONAL_KNOWLEDGE
```

Se representa en cada run y en el nivel alcanzado por cada item. Esta fase ingiere
resultados experimentales, no convierte observaciones sueltas en conocimiento.
La validación impide etiquetar un único experimento como REPLICATED_EFFECT,
REPLICATED_EVIDENCE u OPERATIONAL_KNOWLEDGE. Los contadores se recalculan desde
evidencia: no basta con editar independent_evidence_count a dos.

Los IDs son derivados de identidades de evidencia/contexto/configuración de
interpretación; el hash completo cubre el payload. `created_at` conserva el
timestamp de disponibilidad de la evidencia fuente (máximo al consolidar), no
pretende medir el instante de escritura en disco. Esto permite reinterpretación
semántica reproducible e ingestión idempotente; la derivación queda identificada
por versión/hash del intérprete y receipts, no por un reloj actual inventado.

Un experimento se distingue por genome/config hash, baseline, contexto completo,
benchmark, workload y versión de fuente. ID `e00001` por sí solo nunca basta.
La ejecución se conserva como hash; evidencia, manifest y artefactos tienen
identidades independientes. Variaciones de código del genoma se representan
mediante hash, sin copiar código o texto arbitrario.

## Ingestión y fidelidad de fuentes

La curación CPU lee únicamente baseline manifest/genome, benchmark, ledger,
manifest/evidence/genome de IDs experimentales explícitos o del directorio
`experiments/`, y artefactos de promoción relacionados. Las referencias se
validan dentro de la raíz suministrada; no hay recorrido arbitrario del repo.
Se verifican hashes de manifests/evidence, genomas y benchmark, cadena de ledger,
completion links, parent genotype y enlaces de promoción. Se conservan hashes
de artefactos originales y de eventos de ledger relevantes.

La proyección allowlist retiene decisiones, screen, confirmación pareada, estados
de calidad, configuración, identidad, versiones, promoción y contexto de rollback.
No copia paths personales, stderr, mensajes arbitrarios, runtime dumps o secrets.
Se valida ratio contra costes pareados, número de pares frente a trials que
alcanzaron calidad, umbral e intervalo de confirmación. Rechazo, inconcluso y
aceptación no son etiquetas intercambiables.

Los consumidores portátiles validan canonicalidad/schema/hash de la proyección.
El aggregate de archivo histórico es una referencia de custodia verificada
externamente, no se recalcula sobre todo el archivo por este lector acotado.
**Sin los artefactos originales no se puede probar criptográficamente que una
proyección sea fiel sólo a partir de su hash.** La validación de esta etapa sí
reprodujo la proyección desde el archivo local real y comparó los bytes.
No constituye recertificación integral de la campaña CPU original.

## Claims, negativos e inconclusos

Vocabulario limitado: OBSERVED_EFFECT, PROMISING_DIRECTION, REJECTED_DIRECTION,
STABLE_CONFIGURATION_FACT, CONTEXT_DEPENDENT_EFFECT, REPLICATED_EFFECT,
INCONCLUSIVE_RESULT. STABLE_CONFIGURATION_FACT está reservado en el vocabulario;
no se inventan hechos de estabilidad que la evidencia experimental no demuestre.

Los claims son plantillas/datos estructurados, no texto generativo libre:

- Aceptado confirmado → OBSERVED_EFFECT, normalmente MEDIUM; no éxito universal.
- Inconcluso con señal favorable → PROMISING_DIRECTION LOW, outcome INCONCLUSIVE
  y evidencia faltante de resolución del intervalo.
- Inconcluso sin señal suficiente → INCONCLUSIVE_RESULT.
- Pareto/resource tradeoff → INCONCLUSIVE_RESULT con resolución de tradeoff
  pendiente, no una falsa afirmación de que falló el intervalo de coste.
- Rechazo → REJECTED_DIRECTION: falta de ganancia verificada, calidad no alcanzada
  o ejecución no exitosa, según evidencia. Un timeout no se convierte en causa
  runtime probada.

Negativos con confirmación suficiente o corroboración independiente pueden
identificar reutilización negativa de **esa configuración exacta bajo contexto
equivalente**. Un rechazo aislado de screening queda HISTORICAL_REJECTION_ONLY:
informa, pero no justifica evitar una región entera ni impone bloqueos de búsqueda.
No se adopta esa información dentro de Strategy en esta fase.

El evento histórico de ledger `candidate_rejected` no basta para llamar fallo
a un experimento: e00002 se ingiere desde su decisión `deferred` y se conserva
como INCONCLUSIVE. El rollback histórico exacto de verificación se distingue de
contraevidencia adversa; un motivo desconocido reduce confianza por incertidumbre.

## Applicability, transferibilidad y staleness

Todo item fija workload, trainer family, environment/host/runtime/benchmark/source
hashes, quality threshold, versión GAIA de la fuente y baseline version. Las
versiones estables relacionadas se enumeran; no se afirma compatibilidad con
todas las versiones intermedias o futuras.

Transferibilidad: EXACT_CONTEXT, SAME_WORKLOAD, RELATED_CONTEXT, UNKNOWN_TRANSFER,
NOT_TRANSFERABLE. EXACT_CONTEXT requiere un contexto completo explícito igual.
Un filtro sólo por workload da SAME_WORKLOAD, no equivalencia. Sin contexto
explícito se devuelve UNKNOWN_TRANSFER/UNASSESSED; nunca se relee el host.
Un workload/familia distinto no se considera transferible: no hay salto CPU MLP
→ LLM/GPU.

Cambios de entorno, benchmark, workload, familia, implementación/source, versión,
baseline o calidad reducen aplicabilidad. Runtime/hardware causan STALE por
defecto. Desactivar uno de esos flags no vuelve EXACT_CONTEXT una identidad
diferente. STALE es una vista contextual, no una edición del documento histórico.
Las consultas omiten stale por defecto; `--include-stale` permite inspeccionarlo.

## Repetición, replicación y confidence

Estados: SINGLE_OBSERVATION, SINGLE_EXPERIMENT, REPEATED_WITHIN_EXPERIMENT,
REPLICATED_INDEPENDENTLY y CONTRADICTED. Los seeds/pares internos cuentan como
repetición, no como experimentos independientes.

Se detectan EXACT_DUPLICATE, EXACT_MEASUREMENT_DUPLICATE,
EXACT_CONFIGURATION_REPEAT, NEAR_DUPLICATE e INDEPENDENT_REPLICATION.
Cambiar IDs de experimento/ejecución no duplica un payload de confirmación
copiado. La identidad de mediciones se basa en confirmación si existe; variar
el screening no convierte una confirmación copiada en replicación.

Para una configuración exacta, evidencia de ejecuciones distintas y mediciones
distintas puede contar como replicación independiente. Dentro de una ejecución
se cuenta una fuente independiente; mediciones reutilizadas se asignan
conservadoramente a una sola ejecución. La independencia se apoya en metadatos
de fuente y payloads distintos, no en una prueba de independencia estadística o
de causalidad frente a un productor hostil.

Confidence: VERY_LOW/LOW/MEDIUM/HIGH. Un aceptado aislado queda MEDIUM; una
promoción no suma independencia. HIGH exige al menos las replicaciones
independientes configuradas, contexto exacto y ausencia de contradicciones.
Sólo una configuración exacta, replicada y HIGH puede ser operational_knowledge.
No es un óptimo global y su utilización requiere aplicabilidad EXACT_CONTEXT.

Se registran evidence_count, independent_evidence_count, independent_positive_count
cuando corresponde, contradictions_count, record_count y context_specificity.
Los contadores no se confunden con el número de seeds ni de archivos duplicados.

## Consolidación, contradicciones y supersession

La agrupación exige mismo dominio/componente y contexto completo compatible.
Hay dos formas iniciales:

1. Configuración exacta y baseline exacto: corroboración/contradicción del punto.
2. Dirección HIGHER_LR_REGION bajo familia/estructura compatibles: síntesis
   contextual de **puntos realmente probados**, conservando cambios de weight
   decay u otros hiperparámetros como posibles confounders. No estima un rango
   numérico continuo ni una causalidad aislada.

Knowledge ACTIVE puede ser un resumen de un solo record; **no equivale a
operational knowledge**. La síntesis de una dirección nunca se promueve a
replicación exacta por mezclar configuraciones diferentes.

Nuevos rechazos/rollback adverso pueden debilitar o contradecir evidencia previa.
Se conserva todo; una contradicción reduce confidence y marca estado/repetición
CONTRADICTED. Screening débil o rollback incierto puede generar relación weakens,
no refutación confirmada. No se elimina la evidencia favorable anterior.

Una consolidación más fuerte con soporte estrictamente ampliado y sin
contraevidencia puede superseder una interpretación anterior del mismo grupo.
El nuevo item guarda supersedes. Los bytes antiguos permanecen intactos;
superseded_by y status SUPERSEDED se resuelven mediante relaciones append-only
y vistas de query. No se puede simultáneamente reescribir el antiguo payload
y llamarlo inmutable. La vista también reduce effective_confidence ante nueva
contraevidencia y evita que un antiguo HIGH siga utilizable como operational.

## Store, consulta y CLI

```text
<state>/learning/
  sources/       # proyecciones canónicas explícitas
  records/       # interpretaciones de resultados individuales
  knowledge/     # síntesis y conocimiento contextual
  batches/       # índices commit-only con cadena de hashes
```

No se escribe ledger evolutivo. Lock flock, staging local, fsync, permisos 0444
y hard-link atómico create-only. Un batch sólo se hace visible después de
persistir sus fuentes/items; huérfanos de un fallo previo al commit no aparecen
como conocimiento comprometido. No se sobrescribe: contenido idéntico permite
idempotencia, contenido distinto bajo el mismo ID produce error. Un store fija
su policy de interpretación; cambiarla requiere otro store explícito.

Las vistas de queries filtran componente, workload, environment, claim type,
confidence mínima, transferibilidad y replicación. Una query sin ningún filtro
de relevancia se rechaza; listados explícitos siguen disponibles. No hay búsqueda
semántica. Mostrar un item por ID conserva el payload histórico; para su estado
efectivo y aplicabilidad se usa query, no se infiere del antiguo status aislado.

```sh
python gaia.py learn-experiments docs/learning_evidence/test-b-sources.json --state-dir state_local
python gaia.py learning-records --state-dir state_local
python gaia.py learning-record <learning_id> --state-dir state_local
python gaia.py knowledge --state-dir state_local
python gaia.py knowledge-item latest --state-dir state_local
python gaia.py query-knowledge --component cpu_evolution --workload numpy_mlp --state-dir state_local
python gaia.py query-knowledge --claim-type REJECTED_DIRECTION --state-dir state_local
```

Todos admiten `--json`. `--context <json>` es explícito; `--include-stale`,
`--include-superseded` y `--replicated-only` permiten inspección de historia.
Sin datos válidos la CLI retorna 2 con error sanitizado; no lanza campañas para
rellenar datos ni instala dependencias.

## Test B real

Fuente portátil: `docs/learning_evidence/test-b-sources.json`, 3 experimentos.
Se reprodujo desde el archivo histórico local y se validaron sus enlaces.
No se copia el estado completo ni se depende de una ruta personal para consumirlo.
El aggregate de custodia es el histórico documentado en v0.1:
`da15a56bf3c508955ebea945a925b0d886131601eb98674ad6a80fa039f3cab9`.

| Resultado | Learning | Confianza | Alcance |
| --- | --- | --- | --- |
| e00001: 96×2 SGD, lr 0,05; screening coste 1,365 s | REJECTED_DIRECTION | LOW | Screening negativo local, no prohibición regional |
| e00002: lr 0,0763, wd 0; ratio 0,8894, upper95 0,9784 | PROMISING_DIRECTION; INCONCLUSIVE | LOW | Señal favorable; intervalo no supera umbral 0,95 |
| e00003: lr 0,0763, wd 0,003888; ratio 0,5310, upper95 0,5626 | OBSERVED_EFFECT | MEDIUM | Confirmación y promoción histórica v0001; rollback de verificación no adverso |

Se generan tres records y cuatro knowledge items: tres resúmenes de configuración
exacta y una síntesis contextual e00002/e00003. Esta última registra lr probado
0,0763 y wd probados 0/0,003888, confianza MEDIUM, independent_evidence_count=1.
Sugiere que esos puntos de mayor lr fueron prometedores en ese contexto y que
la configuración con wd moderado obtuvo efecto confirmado; **no demuestra que
wd por sí solo causara el cambio**. No hay operational knowledge real HIGH ni
replicación independiente en Test B: comparten una ejecución histórica.

Query por CPU evolution/numpy_mlp devuelve cuatro items pertinentes; query de
negativos devuelve el rechazo exacto; no se devuelve lo mismo para LLM/GPU.
El uso posterior como prior no está conectado a decisiones 0.4 o Strategy.

## Validación sintética y auditoría

Casos controlados, expresamente **sintéticos**, sin nuevos experimentos:

- Un aceptado → OBSERVED_EFFECT MEDIUM, repetición interna, no replicación.
- Duplicado exacto o confirmación copiada → una fuente independiente, no HIGH.
- Dos confirmaciones de ejecuciones distintas y mediciones diferentes →
  REPLICATED_EFFECT HIGH, OPERATIONAL_KNOWLEDGE para contexto exacto.
- Añadir rechazo contradictorio → CONTRADICTED LOW; el antiguo HIGH permanece
  en historia, pero su vista deja de ser utilizable como operational.
- Nueva evidencia más fuerte → supersedes/superseded_by sin cambiar bytes previos.
- Contexto runtime hipotéticamente distinto → STALE y transferencia limitada,
  sin escanear ni modificar el host actual.

`tools/audit_learning.py` reproduce runs desde fuentes exactas y, para historia,
desde knowledge previo. Verifica schema/hash, duplicados, independencia, confianza,
scope, contradicciones, supersession, contabilidad y allowlist reproducida.
La inspección AST de imports/llamadas verifica autoridad restringida; no pretende
ser una prueba formal de seguridad de Python.

Auditorías definitivas: `verified-test-b-audit.json`,
`verified-synthetic-history-audit.json`, `verified-duplicates-audit.json`.
Los cinco snapshots auditados reproducen su interpretación final. Se conservan
también receipts de revisiones previas, con sus propios hashes de fuente; no se
confunden con los `verified-*` autoritativos. Las comprobaciones finales de pares
válidos y tradeoffs no alteraron la salida histórica Test B ya exportada.

Ejemplo sin nuevas campañas:

```sh
python tools/audit_learning.py --run docs/learning_evidence/test-b-run.json --source docs/learning_evidence/test-b-sources.json
```

Para auditar supersession portátil se pasan `--run synthetic-run-1.json`,
`--run synthetic-run-2.json`, `--run synthetic-run-3.json` en orden y sus tres
fuentes con `--source`; `--state-dir` audita directamente una store completa.

## Privacidad, coste y regresión

Allowlist de campos, estados y slots conocidos; hashes para identidad sensible,
paths de artefactos relativos y acotados. Sin usernames/hostnames/IP/MAC,
home paths, tokens, dumps de env o código arbitrario. Datos no admitidos fallan
explícitamente; las excepciones no se persisten como texto privado.

Test B: 3 records procesados, 4 knowledge items, **5,305 ms** de interpretación.
Caso sintético final: 3 records, 2 knowledge items, **3,021 ms**. Se registra
duration/records_processed/knowledge_items_generated. No incluye lectura,
impresión/fsync; el tamaño histórico usado es pequeño y el coste no certifica
escalabilidad ilimitada. Comparación de duplicados es cuadrática en esta versión.

| Suite | Recogidos | Ejecutados | Skips | Failures/errors/warnings |
| --- | ---: | ---: | ---: | --- |
| Learning definitivo | 52 | 52 | 0 | 0 / 0 / 0 |
| Prioritization | 39 | 39 | 0 | 0 / 0 / 0 |
| Diagnosis | 46 | 46 | 0 | 0 / 0 / 0 |
| Observation | 34 | 34 | 0 | 0 / 0 / 0 |
| Crítica v0.1 | 171 | 170 | 1 | 0 / 0 / 0 |
| Completa definitiva | 577 | 566 | 11 | 0 / 0 / 0 |

Todas con `-B -W error::ResourceWarning` y comprobación de warnings unraisable.
Suite completa definitiva: **761,469 s**. Nueve skips GPU previstos por Torch
ausente y dos exclusiones administrativas conocidas: nueva Prueba A real y test
de campaña autónoma. No se modifican los tests previos para excluirlos. Las
revisiones previas también pasaron y sus logs permanecen archivados; el receipt
definitivo es `verified-tests.json`.

Auditoría de delta: 411 de 413 archivos originales idénticos; se conservan 16
módulos observation, 10 diagnosis, 8 prioritization, 8 protected y 66 frozen.
Sólo cambian dispatch CLI y defaults `learning` en fuentes preexistentes. Defaults
anteriores y experimental_config permanecen idénticos. Tags v0.1–v0.4 intactos.
Detalle: `verified-regression.json`; código funcional definitivo: `7a68dbb`.

## Limitaciones y certificación

La implementación inicial ingiere CPU numpy_mlp con schema/proyección concretos;
no interpreta cualquier repo, runtime o resultado científico. La confianza es
ordinal, no una probabilidad calibrada. La independencia inferida de fuentes
distintas no prueba independencia estadística ni causalidad. Claims locales no
se generalizan a LLM, GPU, razonamiento o inteligencia general.

Los hashes detectan corrupción/coherencia, no autentican un productor hostil ni
demuestran por sí solos la fidelidad de una proyección curada. La store usa POSIX
y no certifica otras plataformas. Las vistas efectivas son necesarias para no
reutilizar un knowledge histórico superseded/contradicted/stale como actual.

PASS significa memoria experimental estructurada, contextual y trazable,
incluidos negativos e inconclusos, con consolidación conservadora y consulta
relevante. No hay selección automática del próximo experimento, generación de
soluciones, diseño de campañas, LLM, Internet o auto-modificación.

Siguiente etapa propuesta: **GAIA 0.6 — Meta-Improvement & Experiment Strategy Learning**.
