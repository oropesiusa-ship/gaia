# GAIA 0.4 — Target Selection & Prioritization

## Resultado y alcance

**PASS de etapa; sin merge ni release 0.4.** Rama `feat/gaia-0.4-target-selection`
desde `main` limpio en `4fbbdef6693796effefab8ea935d66914983cfeb`.

Se creó, publicó y verificó el tag anotado autorizado `gaia-v0.3-diagnosis`,
mensaje `GAIA v0.3 — Diagnosis & Bottleneck Attribution`, apuntando exactamente
a esa base. Objeto de tag local/remoto: `f83904013fb12c3bd7ffdb55b0e1fae1129f9e5a`.
No se alteraron los tags anteriores ni las ramas históricas.

GAIA puede seleccionar y ordenar objetivos de investigación a partir de
diagnósticos estructurados mediante criterios explícitos y trazables.
**Target != solution. Priority != recommendation.** No significa conocer la
mejor solución, diseñar el experimento óptimo, poder modificar el sistema ni
haber mejorado su inteligencia general.

Autoridad conceptual: [Documento Maestro v3](GAIA_MASTER_ARCHITECTURE_V3.md).
Esta etapa materializa selección temprana de problemas por valor informativo,
impacto observado y restricciones. No implementa aprendizaje experimental o
metaoptimización empíricamente validada. La pregunta es «¿Qué merece que
investigue primero y por qué?», no «¿Qué debo cambiar?».

## Arquitectura y autoridad

`gaia/prioritization/`:

| Módulo | Responsabilidad |
| --- | --- |
| `targets.py` | Vocabulario cerrado, perfiles conceptuales, magnitud, consolidación y dependencias |
| `policy.py` | Dimensiones ordinales, reglas, tiers y desempate lexicográfico |
| `engine.py` | Validación y composición sobre diagnósticos guardados |
| `schema.py` | Envelope, referencias, grafo y consistencia de policy/hash |
| `store.py` | Historial independiente, canónico, inmutable y atómico |
| `report.py`, `cli.py` | Informe humano y entradas explícitas |

No hay imports de collectors ni autoridad para observar, diagnosticar,
ejecutar workloads, diseñar experimentos, cambiar configuración, llamar Strategy,
Engine.run, publication o rollback. El módulo `prioritization.engine` es un
compositor puro, distinto de `gaia.engine`. La CLI sólo lee snapshots/config y
persiste prioridades. No se integra con `run`.

Las observaciones v0.2 se consumen mediante las referencias y evidencia del
diagnóstico v0.3; no se reabren ni recopilan silenciosamente. La entrada explícita
es uno o varios diagnósticos válidos. Para verificar los campos originales de
observación se usa la auditoría de diagnosis existente; la auditoría de prioridad
verifica la cadena desde el snapshot diagnóstico exacto, no autentica al productor.

## Schema y target model

`schema = "gaia_target_prioritization_v1"`, intérprete `0.4.0`.
Cada ejecución contiene ID `pNNNNNN`, timestamp con timezone, source_diagnoses,
source_observations, candidate_targets, ordering, exclusions, blockers, rationale,
limitations, policy, cost y prioritization_hash. JSON canónico y SHA-256 cubren
todo salvo el propio hash. Política/configuración tienen identidad independiente.

Un target contiene target_id, component_id, target_class, source_refs con
diagnosis ID/hash + issue + hypothesis + evidence IDs, dimensions, dimension_basis,
information_needed, dependencies, blocked_by, exclusion_reasons, priority,
rule_ids, reasons e intent. Intent es ACQUIRE_EVIDENCE o INVESTIGATE_ISSUE;
LOW/VERY_LOW exige ACQUIRE_EVIDENCE, nunca problema causal confirmado.

Dimensiones preservadas por separado:

- `impact`: UNKNOWN, LOW, MEDIUM, HIGH.
- `diagnostic_confidence`: VERY_LOW, LOW, MEDIUM, HIGH, heredada de v0.3.
- `investigation_cost`: VERY_LOW, LOW, MEDIUM, HIGH.
- `risk`: LOW, MEDIUM, HIGH.
- `reversibility`: EASY, MODERATE, DIFFICULT, UNKNOWN.
- `information_value`: LOW, MEDIUM, HIGH.
- `blocking_power`: NONE, LOW, MEDIUM, HIGH.
- `evidence_completeness`: PARTIAL o SUFFICIENT respecto a datos diagnósticos faltantes.

No se ocultan en un único score. No hay probabilidades ni precisión numérica
falsa. Los costes registrados en `cost` son coste computacional de priorizar;
`investigation_cost` es una categoría conceptual de investigación futura.

Clases iniciales: CPU_RUNTIME_EFFICIENCY, MEMORY_EFFICIENCY,
GPU_RUNTIME_EFFICIENCY, STORAGE_IO, RESOURCE_CONTENTION, RUNTIME_CONFIGURATION,
QUALITY_REGRESSION, CAPABILITY_GAP, MEASUREMENT_QUALITY,
ENVIRONMENT_COMPATIBILITY, UNKNOWN_REQUIRES_EVIDENCE.

## Derivación de dimensiones

Impacto se deriva del issue, no del nombre de hipótesis:

- Fallo registrado del workload o capacidad requerida indisponible con evidencia:
  HIGH, limitado al alcance de ese workload/capacidad.
- Regresión significativa: MEDIUM; HIGH si la magnitud relativa absoluta alcanza
  30 % por defecto. El diagnóstico ya debe establecer significancia.
- Variabilidad aislada: LOW, sin pérdida funcional demostrada.
- Resto: UNKNOWN, sin inventar pérdida ni ganancia potencial.

La confianza no se recalcula como si repetir diagnósticos la mejorara. Se conserva
la más baja entre contribuciones agrupadas. Una confianza baja con impacto alto
y alto valor informativo puede justificar P1 **para adquirir evidencia**.

Coste, riesgo y reversibilidad son perfiles deterministas **conceptuales**, no
mediciones ni garantías sobre una intervención aún no diseñada. Ejemplos:
calidad de medición VERY_LOW/LOW/EASY; investigación de runtime
MEDIUM/MEDIUM/MODERATE; GPU HIGH/MEDIUM/MODERATE además de FROZEN.
No se describen procedimientos, herramientas ni cambios concretos para realizarlos.

Información faltante se filtra al vocabulario v0.3 permitido. Varias hipótesis
alternativas sobre un issue de impacto MEDIUM/HIGH elevan information_value a HIGH;
otros faltantes conocidos suelen MEDIUM; sin faltantes, LOW. Esto representa
discriminación potencial, no una estimación calibrada de information gain.

Un fallo de capacidad/workload puede tener blocking_power HIGH; calidad de
medición adquiere HIGH cuando un target derivado de la misma diagnosis depende
de wall measurements más fiables. Ruido de CPU del evaluador no se convierte
por sí solo en bloqueo global de inferencia de CPU o wall.

## Política explícita y tiers

`research_attention_v1`, siete reglas identificadas:

| Regla | Decisión |
| --- | --- |
| `POLICY_BLOCKED_001` | Blocker presente → DEFER |
| `POLICY_CRITICAL_001` | HIGH impacto/confianza/bloqueo, evidencia suficiente, bajo coste/riesgo y reversibilidad fácil → P0 |
| `POLICY_INFORMATION_001` | VERY_LOW confianza + LOW information_value → DEFER |
| `POLICY_BLOCKING_001` | Bloqueo HIGH, coste LOW/VERY_LOW y riesgo LOW con alguna confianza → P1 |
| `POLICY_VALUE_001` | Alto impacto y soporte o valor informativo, coste permitido → P1; valor útil no crítico → P2 |
| `POLICY_CAUTION_001` | Coste HIGH, riesgo MEDIUM/HIGH o reversibilidad DIFFICULT/UNKNOWN reduce P1/P2 a P3 |
| `POLICY_DEFAULT_001` | Valor actual limitado → P3 |

P0 es investigación imprescindible por bloqueo crítico fuertemente respaldado,
no permiso de ejecución. Ninguno de los casos reales recibe P0. Su exigencia
se prueba en fixtures de policy; no se fabrica confianza HIGH en v0.3 para lograrlo.

Dentro de cada tier el orden es lexicográfico: impacto, información, confianza,
coste, riesgo, reversibilidad e ID estable. Dependencias bloqueadas quedan DEFER;
el target de evidencia habilitante aparece antes. No existe score absoluto de
utilidad ni ejecución automática al elegir el primero.

Configuración separada `prioritization`:
large_regression_relative=0.30, min_impact_for_p1=HIGH, max_cost_for_p1=LOW,
blocking_priority_boost=true, frozen_component_policy=DEFER.
Valores desconocidos/inseguros se rechazan. No se permite descongelar por config.
Defaults evolutivos, diagnósticos y observacionales anteriores permanecen idénticos.

## Duplicados, exclusiones y blockers

Diagnósticos repetidos se deduplican por hash. Targets se consolidan por
clase/componente y conservan todas las fuentes. No hay cinco targets iguales por
cinco diagnósticos. Impacto se combina conservando la mayor magnitud observada,
confianza con el mínimo y completeness con PARTIAL si alguna contribución lo es.
La agrupación no declara que todos los entornos históricos sean equivalentes.

UNKNOWN_CAUSE no genera un segundo target equivalente cuando ya existen
explicaciones nombradas para el mismo issue: permanece trazable como alternativa
en el diagnóstico. Si es la única explicación de un issue real, genera
UNKNOWN_REQUIRES_EVIDENCE, no un target de optimización confirmado.

NO_SIGNIFICANT_ISSUE → cero targets, obligatoriamente. INSUFFICIENT_EVIDENCE
sin issues también se excluye y registra el motivo. No se crea un problema
por el hecho de haber una entrada con información incompleta.

Blockers:

- FROZEN_COMPONENT para GPU; schema también exige este blocker para appliance.
  GPU/appliance no se descongelan y la prioridad es DEFER. El vocabulario v0.3 no
  ofrece atribución appliance específica: no se inventa un target appliance.
- DEPENDENT_TARGET: p.ej. CPU/memoria/contención requieren resolver calidad de
  medición wall de su misma diagnosis. El target de medición recibe mayor
  blocking_power/information_value; el dependiente permanece DEFER.
- CAPABILITY_UNAVAILABLE limita CPU/quality research cuando el mismo diagnóstico
  declara una capacidad requerida ausente. Investigar el gap en sí no queda
  bloqueado por el mismo gap, evitando un bloqueo circular artificial.

Se valida ausencia de ciclos y referencias colgantes. Si se agrupan fuentes con
algún bloqueo, éste se conserva; no se ignora por agregar otra fuente sin bloqueo.
No hay aprobación humana automática ni flujo para descongelar componentes.

## Store, CLI y report

`<state>/priorities/pNNNNNN.json`, separado de diagnoses/observations/experiments.
Lock flock, staging local, fsync de archivo/directorio, hard-link atómico
create-only, permisos 0444 y EEXIST al intentar sobrescribir. Lectura verifica
canonicalidad, hash, grafo, tiers, ordering, identidad de policy e ID del archivo.
Traversal y symlinks de store/artefactos se rechazan. Hashes detectan corrupción,
no sustituyen firmas frente al propietario hostil del filesystem.

```sh
python gaia.py prioritize d000004 --state-dir state_local
python gaia.py prioritize d000005 d000007 --state-dir state_local
python gaia.py prioritize latest --state-dir state_local
python gaia.py prioritize docs/diagnosis_evidence/current-diagnosis.json --state-dir state_local
python gaia.py priorities --state-dir state_local
python gaia.py priority latest --state-dir state_local
```

Inputs explícitos por ID/latest o JSON guardado, uno o varios; todos los comandos
admiten `--json`. No se ejecuta diagnosis si falta el input: exit 2 y error
sanitizado. El informe muestra tiers, targets, intent, dimensiones, razones,
blockers, dependencias, información faltante y reglas. Sin soluciones concretas.

## Validación real y caso controlado

Sólo se leyeron diagnósticos existentes. Sin nuevas observaciones, carga sobre
el host, campañas ni GPU execution para esta validación. CLI real con store
temporal externa, eliminada al terminar; sólo se exportó evidencia estática curada.

| Caso | Resultado |
| --- | --- |
| `d000005` y `d000007` históricos reales sin issue | `p000001`: cero targets, exclusiones NO_SIGNIFICANT_ISSUE |
| `d000004`, ruido específico de CPU del evaluador y confianza LOW | `p000002`: MEASUREMENT_QUALITY P3, impacto LOW, información MEDIUM, coste VERY_LOW, intent ACQUIRE_EVIDENCE |
| Tres diagnósticos sintéticos controlados | `p000003`: siete targets con coste, riesgo, dependencia y frozen diferenciados |

Orden del caso sintético controlado:

1. P1 QUALITY_REGRESSION: impacto HIGH e información HIGH, coste LOW/riesgo LOW;
   confianza LOW significa adquirir evidencia, no solución confirmada.
2. P1 MEASUREMENT_QUALITY: información/bloqueo HIGH y coste VERY_LOW.
3. P3 RUNTIME_CONFIGURATION: impacto HIGH y confianza MEDIUM, reducido por
   coste MEDIUM y riesgo MEDIUM.
4. P3 ENVIRONMENT_COMPATIBILITY: impacto UNKNOWN y confianza LOW.
5. DEFER CPU_RUNTIME_EFFICIENCY: depende de medición.
6. DEFER GPU_RUNTIME_EFFICIENCY: FROZEN_COMPONENT.
7. DEFER RESOURCE_CONTENTION: depende de medición.

Fixtures controladas no son datos del host. Se mantienen separadas de los casos
reales y se exportan los tres diagnósticos sintéticos que permiten reproducir
la policy. La prioridad no implica diseñar cómo investigar esos targets.

## Auditoría, privacidad, coste y tests

`tools/audit_prioritization.py` verifica schema, hashes, fuentes exactas,
issue/hypothesis/evidence refs, consistencia de policy, blockers, orden y ausencia
de targets desde no-issue. Reproduce todos los campos semánticos a partir de los
mismos diagnósticos/settings; sólo ID, timestamp y duración son variables.
La inspección AST comprueba imports permitidos y ausencia de llamadas de
ejecución/recolección. No equivale a una prueba formal de seguridad de Python.

La privacidad se basa en allowlist: enums, hashes, IDs con formato validado,
referencias y vocabulario fijo. No se copian claims, limitations privadas,
mensajes o campos arbitrarios del input. Las referencias a observación se
reconstruyen con sus cinco campos permitidos, excluyendo posibles extensiones.
El audit de reproducción rechaza recomendaciones añadidas o contenido ajeno.

Auditoría final CLI: **tres resultados, PASS**. Evidencia en
[prioritization_evidence/](prioritization_evidence/): 10 JSON canónicos,
**80.021 bytes**. Incluye validación, audit, tests con hashes de logs y regresión.

Coste medido de interpretación: no-issue **0,822 ms**, noisy **0,741 ms**, caso
controlado **1,727 ms**. Incluye validación/composición; no impresión ni fsync.
Se registran diagnoses_processed, targets_generated y reglas evaluadas por target.
Es determinismo semántico, no igualdad del reloj o timestamp.

| Suite | Recogidos | Ejecutados | Skips | Failures/errors/warnings |
| --- | ---: | ---: | ---: | --- |
| Prioritization | 39 | 39 | 0 | 0 / 0 / 0 |
| Diagnosis | 46 | 46 | 0 | 0 / 0 / 0 |
| Observation | 34 | 34 | 0 | 0 / 0 / 0 |
| Crítica v0.1 | 171 | 170 | 1 | 0 / 0 / 0 |
| Completa | 525 | 514 | 11 | 0 / 0 / 0 |

Todas con `-B -W error::ResourceWarning` y comprobación de warnings unraisable.
Suite completa: **738,482 s**. Exactamente nueve skips Torch ausente previstos
y dos exclusiones administrativas conocidas: nueva Prueba A real y test de
campaña autónoma. No se alteraron los tests previos para aplicar exclusiones.

39 tests nuevos cubren schema/policy, confianza/coste/riesgo/reversibilidad/
información, consolidación, dependencias, no-issue, unknown, frozen, autoridad,
privacidad, reproducción, store concurrente/atómica y CLI real.

## No regresión y limitaciones

390 de los 392 archivos de la base v0.3 están idénticos byte a byte. Se preservan
16 módulos observation, 10 diagnosis, ocho protegidos y 66 frozen. Los únicos
archivos preexistentes modificados son `gaia.py` (dispatch) y `gaia/config.py`
(sección prioritization). Todos los defaults anteriores y experimental_config
se verificaron idénticos. Código final validado: `9be0c9d`.

La prioridad es una política inicial explícita, no una utilidad científicamente
calibrada. Coste/riesgo/reversibilidad son perfiles conservadores de clases, no
conocimiento de todos los recursos necesarios. Magnitud e impacto funcional se
limitan al alcance del diagnóstico. Varias fuentes pueden corresponder a entornos
distintos; agrupar no implica que se haya probado una causa común.

El motor hereda limitaciones de v0.3: las hipótesis no son prueba causal, ni la
confianza es una probabilidad. La evidencia faltante queda nominal, sin diseñar
procedimientos. No se analiza el contenido semántico arbitrario de documentos.
La store usa primitivas POSIX; no se certifica otra plataforma aquí.

No implementado: recommendations, experiment design, solution generation, LLM,
Internet, auto-modification. Sin desarrollo de 0.5, merge o ceremonia de release 0.4.

Siguiente etapa propuesta: **GAIA 0.5 — Experimental Learning & Knowledge Consolidation**.
