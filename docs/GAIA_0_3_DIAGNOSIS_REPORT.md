# GAIA 0.3 — Diagnosis & Bottleneck Attribution

## Resultado y alcance

**PASS de etapa, sin merge ni release.** Rama `feat/gaia-0.3-diagnosis`, creada
desde `main` limpio en `1da7543c1c0f9b22d38c762c789c275e9fee92f0`, coincidente
con `gaia-v0.2-system-observation`. La rama histórica 0.2 y el tag permanecen intactos.
La autoridad conceptual sigue siendo [Documento Maestro v3](GAIA_MASTER_ARCHITECTURE_V3.md).

GAIA puede convertir observaciones en diagnósticos técnicos estructurados y
trazables, expresando incertidumbre y alternativas. **Diagnosis != proof of causality.**
No demuestra comprensión causal general, capacidad de investigar cualquier
problema, conocimiento de la solución ni incremento de inteligencia general.

La pregunta implementada es «¿Qué podría estar ocurriendo y qué evidencia tengo?».
No se seleccionan problemas a optimizar ni se generan cambios. Una hipótesis
primaria dentro de un issue no constituye una prioridad entre issues. El orden
de issues es el de evaluación de reglas, sin puntuación ni ranking de objetivos.

## Arquitectura y autoridad

Subsistema independiente `gaia/diagnosis/`:

| Módulo | Responsabilidad |
| --- | --- |
| `schema.py` | Envelope canónico, grafo de referencias y hash |
| `evidence.py` | Validación de entradas v0.2 y evidencia scalar allowlist |
| `rules.py` | Once reglas explícitas, detección factual y comparación v0.2 |
| `hypotheses.py` | Explicaciones limitadas, alternativas, contradicciones y datos faltantes |
| `confidence.py` | Política ordinal de confianza y corroboración independiente |
| `engine.py` | Composición diagnóstica sin relación con el Engine evolutivo |
| `store.py` | Historial propio, inmutable y create-only |
| `report.py`, `cli.py` | Informe humano y comandos sobre observaciones guardadas |

Diagnosis no importa collectors, sandbox execution, search, mutate, publication,
rollback ni ledger; no llama Strategy, Engine.run ni evaluadores. Tampoco lee
`/proc`, importa Torch o vuelve a detectar hardware. Sólo interpreta datos
validados ya existentes. La CLI lee configuración allowlisted y entradas
guardadas; los únicos archivos que crea son diagnósticos en su store.

No se cambiaron los 16 módulos de observation ni sus contratos. La integración
se limita al dispatch condicional en `gaia.py` y a defaults `diagnosis` separados
en `gaia/config.py`. El diagnóstico no se conecta al comando `run`.

## Schema, identidades e integridad de entradas

`schema = "gaia_system_diagnosis_v1"`, intérprete `0.3.0`.
Campos obligatorios: diagnosis_id, schema, timestamp, source_observations,
identity, outcome, issues, hypotheses, alternatives, evidence, contradictions,
missing_evidence, confidence, limitations, rules, comparison, cost y diagnosis_hash.

Cada entrada referencia observation_id **y observation_hash**, rol current/baseline,
environment_hash y source_hash. Así se distinguen IDs iguales de stores distintas.
El intérprete registra versión, versión/hash de reglas y hash de thresholds.
La auditoría añade hashes de todos los módulos del intérprete. Git no es necesario
para diagnosticar. Timestamp, coste e ID de persistencia son los únicos datos
variables al reproducir la misma interpretación con los mismos inputs/settings.

Se validan schema/hashes v0.2 y coherencia de identidades: host, runtime cuando
está declarado, fuente/protected y enlace de environment. Se recalculan los
resúmenes estadísticos declarados a partir de sus samples. Corrupción, identidad
contradictoria o resumen falsificado producen fallo explícito, no una hipótesis.
Campos opcionales ausentes no se rellenan con valores imaginados.

El aggregate original de fuente se referencia, pero no puede recalcularse por
completo sin la configuración original, ausente del envelope v0.2. Esto queda
explícito en limitations. La identidad de los módulos nuevos se conserva también
en el audit de diagnosis; el registry cerrado de componentes de observation v0.2
no se amplió silenciosamente.

## Issue detection y reglas versionadas

Reglas `diagnostic_rules_v1`, IDs persistidos en cada interpretación:

| Regla | Issue factual |
| --- | --- |
| `RULE_PERFORMANCE_001` | Wall aumentado significativamente, con workload exitoso, estable y protocolo compatible |
| `RULE_QUALITY_001` | Calidad disminuida significativamente, con threshold propio |
| `RULE_NOISE_001` | CV elevado en una métrica repetida específica del workload |
| `RULE_MEMORY_001` | MemAvailable/total bajo; no se usa MemFree como sustituto |
| `RULE_CPU_001` | Utilización CPU global alta; consumo del workload se examina por separado |
| `RULE_STORAGE_001` | Disponibilidad relativa de filesystem baja; no prueba de latencia |
| `RULE_GPU_MEMORY_001` | VRAM disponible baja según observación pasiva |
| `RULE_EXECUTION_001` | Fallo/indisponibilidad registrados del workload |
| `RULE_CAPABILITY_001` | Capacidad CPU/sandbox requerida declarada indisponible |
| `RULE_ENVIRONMENT_001` | Identidades hardware/runtime/source diferentes según comparison v0.2 |
| `RULE_RESOURCE_CHANGE_001` | Cambio significativo de RAM/filesystem disponibles, sin atribuir causa |

La variabilidad de CPU global de fondo no se convierte por sí sola en un issue
del workload. La regla de variabilidad cubre wall/train, CPU del evaluador,
CPU del workload cuando existe, cota inferior CPU de descendientes, peak RSS y
calidad. Cada issue conserva el nombre de la métrica; una tendencia de RSS puede
producir variabilidad descriptiva sin demostrar que sea ruido aleatorio.

Los thresholds residen en la sección `diagnosis`: memoria/VRAM bajas 10 %,
filesystem bajo 5 %, CPU global alta 90 %, ratio CPU/wall alto 0,75 y bajo 0,30,
crecimiento relativo peak RSS 20 %, consumo de swap observado 64 MiB,
regresión performance 15 %, calidad 2 %, CV máximo 10 % y mínimo de tres grupos
independientes para elegibilidad HIGH. Rangos y coherencia de configuración se validan.
No se alteran thresholds evolutivos ni los de observation.

## Taxonomía, evidencia y alternativas

Taxonomía limitada: COMPUTE_PRESSURE, MEMORY_PRESSURE, GPU_MEMORY_PRESSURE,
STORAGE_PRESSURE, RUNTIME_REGRESSION, RESOURCE_CONTENTION, MEASUREMENT_NOISE,
QUALITY_REGRESSION, CAPABILITY_GAP, ENVIRONMENT_CHANGE y UNKNOWN_CAUSE.

Cada evidencia tiene evidence_id, observation_ref, field JSON pointer, type,
value, expected_relation, strength, group, supports y contradicts. Tipos:
DIRECT, CORRELATIONAL, NEGATIVE, CONTROL, CONTEXTUAL. Fuerzas: WEAK, MODERATE,
STRONG. Los enlaces evidencia/hipótesis se validan en ambos sentidos.

Las relaciones derivadas, como CPU/wall o RAM disponible/total, son trazables a
numerador, denominador y threshold. Samples repetidos del mismo grupo no se
cuentan como fuentes independientes. La evidencia DIRECT de un error indica que
se observó un error, no que se conozca su causa.

Una CPU global alta junto con ratio CPU/wall alto puede sostener COMPUTE_PRESSURE,
con RESOURCE_CONTENTION y UNKNOWN_CAUSE como alternativas. RAM baja aislada no
demuestra causalidad: se comprueban cambio de ocupación swap y peaks RSS
repetidos; estabilidad/ausencia de crecimiento se registra como contraevidencia.
Ocupación swap no se presenta como actividad de swap I/O. Un ratio bajo derivado
de la cota inferior muestreada de v0.2 tampoco se usa como evidencia CPU exacta baja.

Las fixtures con reloj CPU exacto declaran esa metodología explícitamente; no se
finge que el collector v0.2 la produzca. GPU presente no implica que deba usarse;
VRAM baja no demuestra participación del workload. Código frozen, LLM sin
configurar e Internet no probado no generan gaps artificiales de capacidades.

Si hay ralentización y cambio runtime, RUNTIME_REGRESSION puede ser contributor
plausible. No se expresa como causa probada. Sin señales que discriminen una
ralentización significativa se conserva UNKNOWN_CAUSE, con confianza LOW.

## Contradicciones y confianza

Toda hipótesis guarda supports, contradictions y contradiction_search, incluso
cuando no se encontró contraevidencia fuerte. Las búsquedas incluyen estabilidad,
scope CPU, disponibilidad RAM, ocupación swap, crecimiento RSS y controles ausentes.

Estados: VERY_LOW, LOW, MEDIUM, HIGH. Se parte de grupos de evidencia
independientes: ninguno → VERY_LOW, uno → LOW, varios → MEDIUM. Contradicción
fuerte reduce confianza; medición relevante inestable, búsqueda ausente o datos
críticos faltantes limitan a LOW. UNKNOWN_CAUSE nunca supera LOW.

HIGH requiere conjuntamente al menos tres grupos independientes, dos reglas,
evidencia directa/controlada fuerte, estabilidad, búsqueda de contradicciones,
alternativa debilitada, ausencia de contradicciones y de faltantes críticos.
Las reglas causales actuales carecen de intervenciones/control causal: **no se
certifica aquí ningún HIGH de atribución causal**. El camino HIGH de la política
se prueba con evidencia controlada sintética, no con una afirmación sobre el host.
Los niveles son criterios ordinales, no probabilidades calibradas.

## Missing evidence y resultados sin problema

Cada hipótesis declara datos faltantes: por ejemplo per-core CPU, frecuencia
bajo carga, bandwidth de memoria, competencia de procesos, scheduler wait,
latencia/tiempo I/O, participación GPU, eventos de asignación o comparación runtime
controlada. Se nombran datos discriminantes; no se diseña ni se ejecuta una
campaña para obtenerlos. No se generan acciones de optimización.

Outcomes: ISSUES_DETECTED, NO_SIGNIFICANT_ISSUE, INSUFFICIENT_EVIDENCE.
NO_SIGNIFICANT_ISSUE no tiene issues ni hipótesis artificiales. Requiere wall
repetido, estable y exitoso, inventario completo y, al comparar, baseline estable
y protocolo compatible. Se refiere al alcance observado, no a una certificación
universal de salud o ausencia de cuellos de botella. Una quick sin workload suele
quedar INSUFFICIENT_EVIDENCE para atribución. La falta de baseline se declara para
inferencia temporal aunque pueda haber una conclusión absoluta limitada.

## Persistencia, CLI y privacidad

`<state>/diagnoses/dNNNNNN.json`: JSON canónico, SHA-256, flock, staging,
fsync de archivo/directorio y hard-link create-only. Permisos 0444; EEXIST al
intentar sobrescribir un ID. Lectura valida hash, grafo, confianza, canonicalidad
e identidad del nombre. Se rechazan traversal y symlinks de diagnóstico/store.
No se reutilizan observations como tabla ni se escribe ledger, CURRENT o stable.

```sh
python gaia.py diagnose o000001 --state-dir state_local
python gaia.py diagnose o000003 --baseline o000002 --state-dir state_local
python gaia.py diagnose docs/observation_evidence/final/o000003.json --baseline docs/observation_evidence/final/o000002.json --state-dir state_local
python gaia.py diagnoses --state-dir state_local
python gaia.py diagnosis latest --state-dir state_local
```

Todos admiten `--json`. Inputs por id/latest o archivo guardado; errores retornan
código 2 y mensaje sanitizado, sin rutas ni traceback. Se puede usar Python sin
NumPy para interpretar snapshots existentes; no hay aprovisionamiento automático.

Allowlist de salida: métricas numéricas/bools, estados conocidos, hashes,
referencias y vocabulario fijo del motor. No se copian dumps, contexto privado,
mensajes arbitrarios ni valores de fields cambiados. Comparison sólo conserva
identidades booleanas y métricas admitidas, no su lista arbitraria de fields.
Canaries de username, hostname, home y secretos se prueban como inputs excluidos.

## Validación real

Artefactos curados en [diagnosis_evidence/](diagnosis_evidence/); estados operativos
se mantuvieron fuera del repositorio. Host real: i7-4790, 4 cores/8 hilos, 14,99 GiB,
Python 3.14.4 y NumPy 2.3.5. Sólo se usó el workload conocido protegido; sin campañas A/B.

| Caso | Resultado final | Evidencia y alcance |
| --- | --- | --- |
| Actual adicional estable, `d000007` | NO_SIGNIFICANT_ISSUE | 5/5 trials; wall mediano 0,479488 s, CV 2,42 %; todas las métricas workload STABLE; calidad 0,5816 |
| Actual anterior, `d000004` | ISSUES_DETECTED | Wall STABLE, CV 6,39 %, pero CPU del evaluador CV 15,32 %; issue específico de variabilidad, MEASUREMENT_NOISE LOW y UNKNOWN_CAUSE LOW |
| Histórica o000002 vs o000003 de v0.2, `d000005` | NO_SIGNIFICANT_ISSUE | Comparación reutilizada: wall +0,60 %, dentro del ruido; cero hipótesis y ninguna regresión inventada |
| Quick bajo carga controlada, `d000006` | INSUFFICIENT_EVIDENCE | Sin workload repetido ni atribución fuerte; declara muestras wall faltantes |

La carga controlada fue explícita en el harness de validación externo, nunca
activada por diagnosis: un proceso con nice +10, duty cycle 15 %, objetivo de
3 s; duración observada 3,04844 s por sobrecoste de scheduling/último intervalo,
CPU consumida 0,44622 s. Sin carga de memoria/disco/red ni cambios de hardware.
El motor no recibe la explicación del harness como si fuera evidencia observada.

Se conservó la observación con variabilidad real; no se descartó para lograr PASS.
Tras mejorar el scope de la regla se reinterpretaron los mismos inputs guardados,
sin recolección silenciosa. Los diagnósticos previos siguen inmutables en el
historial externo. Los exports finales corresponden al intérprete final.

Además se auditaron cuatro casos sintéticos, etiquetados como tales: compute
combinado → MEDIUM; memoria combinada → MEDIUM con posible variabilidad RSS;
wall variable → MEASUREMENT_NOISE LOW; ralentización sin atribución → UNKNOWN_CAUSE LOW.
No se presentan fixtures como mediciones del host real.

## Auditoría, coste y tests

`tools/audit_diagnosis.py` valida schema/hash, fuente exacta por hash, cada
JSON pointer/value y reproducibilidad completa de la interpretación con los
mismos thresholds. Recalcula confianza, contradicciones y alternativas; rechaza
contenido añadido no perteneciente a la allowlist reproducida. La inspección AST
comprueba ausencia de imports/llamadas de autoridad evolutiva, red o LLM.
No obtiene datos del host. Auditoría CLI real: **8 diagnósticos, PASS**.

Ejemplo reproducible, sin nuevas observaciones:

```sh
python tools/audit_diagnosis.py --diagnosis docs/diagnosis_evidence/historical-comparative-diagnosis.json --observation docs/observation_evidence/final/o000002.json --observation docs/observation_evidence/final/o000003.json
```

Coste del diagnóstico: estable actual **7,70 ms**, caso con variabilidad
**9,44 ms**, comparación histórica **21,70 ms**, quick controlada **4,96 ms**.
Once reglas evaluadas; conteo de hipótesis persistido. Estas duraciones incluyen
validación/interpretación, no impresión ni persistencia. Los benchmarks pertenecen
exclusivamente a observation y al harness explícito, no al motor diagnóstico.

| Suite | Total recogido | Ejecutados | Skips | Failures/errors/warnings |
| --- | ---: | ---: | ---: | --- |
| Diagnosis final | 46 | 46 | 0 | 0 / 0 / 0 |
| Observation | 34 | 34 | 0 | 0 / 0 / 0 |
| Crítica v0.1 | 171 | 170 | 1 | 0 / 0 / 0 |
| Completa final | 486 | 475 | 11 | 0 / 0 / 0 |

Todas con `-B -W error::ResourceWarning`, incluyendo seguimiento de ResourceWarning
unraisable. Suite completa final: **734,630 s**. Los nueve skips GPU previstos
son por Torch ausente. Las dos exclusiones administrativas son Prueba A real y
test que lanza campaña autónoma. No se modificaron sus fuentes/assertions para
excluirlos. La suite final incluye de nuevo todos los tests críticos autorizados.

Cobertura nueva: schema/identidades/hashes, reglas A–F, señales engañosas,
contradicciones, confianza independiente, UNKNOWN, no significant issue,
reproducción, store concurrente/atómico, CLI real, privacidad, fallos e integración
de comparación v0.2. Receipts y hashes de logs en `tests.json`.

Auditoría de regresión: 356 de 358 archivos originales idénticos, incluidos los
16 módulos observation, ocho protegidos y 66 frozen. Sólo cambian dispatch CLI
y nuevos defaults diagnosis en archivos preexistentes. Defaults antiguos y
experimental_config idénticos. Tag v0.2 y rama histórica 0.2 intactos. Detalles en
`regression-audit.json`; el código final auditado es `fa60b82`.

## Limitaciones y alcance de certificación

Las reglas son limitadas, conservadoras y no exhaustivas. Medias/medianas y
coocurrencia temporal no identifican causalidad. Una variación puede ser una
tendencia real, no ruido aleatorio. No hay test estadístico causal, diagnóstico
general de software ni calibración probabilística de confianza. La evidencia
de fuente agregada no reconstruye la configuración experimental original.

Los recursos globales y los del workload tienen scopes distintos. CPU muestreada
de descendientes es una cota inferior; RSS repetido no equivale a un timeline
de asignaciones del mismo proceso; swap ocupado no equivale a swap I/O. Faltan
controles y mediciones discriminantes que se declaran, no se ejecutan.

Privacidad y reproducción están verificadas para la allowlist implementada;
SHA-256 detecta corrupción accidental y no es firma ante un propietario hostil.
La store usa primitivas POSIX y no se certifican aquí otras plataformas.

PASS significa interpretación técnica estructurada, trazable y explícitamente
incierta. No significa saber qué solución aplicar, investigar cualquier problema
ni aumentar la inteligencia general de GAIA.

No implementado: recommendations, target selection, experiment design, LLM,
Internet, auto-modification. Sin merge en esta etapa.

Siguiente etapa propuesta: **GAIA 0.4 — Target Selection & Prioritization**.
