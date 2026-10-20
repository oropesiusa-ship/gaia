# GAIA 0.6 — Meta-Improvement & Experiment Strategy Learning

## Resultado y alcance

**PASS de etapa; sin merge ni release.** Rama única `feat/gaia-0.6-meta-improvement`,
desde `main` limpio en `bf9449624fd732e5c3f7841618a4482a087fa0a0`, coincidente
con `gaia-v0.5-experimental-learning`. Autoridad conceptual:
[Documento Maestro v3](GAIA_MASTER_ARCHITECTURE_V3.md).

GAIA puede utilizar targets, diagnósticos y conocimiento experimental para
seleccionar y ordenar estrategias de investigación mediante criterios explícitos
y reproducibles. Aquí meta-improvement significa preparar un proceso de
investigación más informado: reutilización de evidencia, discriminación,
replicación, controles y evitación de duplicados. **No se ha demostrado una mejora
general de la calidad o eficiencia del proceso de investigación.** Eso requiere
comparar estrategias y resultados futuros, fuera de esta etapa shadow.

No significa diseñar cualquier experimento científico, ejecutar estrategias,
modificar libremente código ni aumentar inteligencia general.

## Arquitectura y separación de autoridad

Se usa `gaia/experiment_strategy/`, porque `gaia/meta.py` ya pertenece al sistema
evolutivo estable y conserva su comportamiento byte a byte.

| Módulo | Responsabilidad |
| --- | --- |
| `inputs.py` | Validación de prioridades/diagnósticos/learning y contexto explícito |
| `model.py` | Clases, plantillas científicas cerradas y guards inmutables |
| `plans.py` | Candidatos de comparación, alcance, duplicados y conocimiento |
| `policy.py` | Utilidad ordinal visible, penalizaciones y ranking |
| `history.py` | Historia retrospectiva y meta-métricas descriptivas |
| `engine.py` | Composición shadow y límites de candidatos |
| `schema.py` | Envelope, hashes, identidad de planes, guards y consistencia |
| `store.py` | Decisiones/planes/historia/métricas inmutables con commit atómico |
| `query.py`, `report.py`, `cli.py` | Consulta y explicación de decisiones guardadas |

No hay imports o llamadas de ejecución a Engine.run, Strategy.propose, mutate,
worker, publication o rollback. No se recopilan observaciones, ni se ejecutan
diagnósticos, ingestión de learning o priorización automáticamente. De v0.5 sólo
se leen snapshots o batches explícitamente suministrados; su configuración se
valida mediante un helper puro existente. No se modifica la policy a sí misma.

## Schema y modelo de strategy

`schema = "gaia_experiment_strategy_v1"`, intérprete `0.6.0`, policy
`shadow_research_policy_v1`. Cada decisión contiene strategy_id, timestamp,
mode=SHADOW, analysis_mode, context/context_binding, priority_ref, diagnosis_refs,
learning_refs, candidate_plans, ranking, exclusions, history, meta_metrics,
policy, rationale, confidence, limitations, cost y output_hash.

Cada plan tiene identidad/hash propios, target_ref con prioridad/impacto y
diagnosis/issue/hypothesis/evidence refs, knowledge refs, clase, modo, diseño,
variables, controles, baseline, candidate variation, métricas, guards, hipótesis
discriminadas, stopping rules, estimaciones, novelty, duplication, blockers,
rationale, rule_ids y confidence. Utility conserva cada componente y total ordinal;
`calibrated_expected_value=false` impide interpretarlo como probabilidad/ganancia
calibrada. No hay código ni valores numéricos de configuración nuevos.

La ejecución declarada es siempre:

```json
{"mode":"SHADOW","authorized":false,"executed":false,"code_generated":false}
```

Clases iniciales: REPLICATION, DISCRIMINATION, PARAMETER_LOCAL_SEARCH,
CONTROL_EXPERIMENT, MEASUREMENT_REFINEMENT, BASELINE_RECONFIRMATION,
KNOWLEDGE_VALIDATION, EXPLORATION y EXPLOITATION.

## Targets, diagnósticos y contexto

La prioridad v0.4 se valida, no se recalcula ni se cambia. Targets DEFER,
bloqueados o GPU/appliance FROZEN no reciben planes. Riesgo HIGH o reversibilidad
DIFFICULT/UNKNOWN producen blocker adicional: no son permiso para investigar.
Una priority NO_SIGNIFICANT_ISSUE sin targets produce cero planes.

Se valida correspondencia clase/componente y formatos de refs. Si se suministran
diagnósticos originales, su ID/hash/outcome y enlaces issue/hypothesis/evidence
se cotejan exactamente (`EXACT_SOURCES_CHECKED`). Si no, la dependencia es
`PRIORITY_REFERENCES_ONLY`: no se afirma haber reabierto la observación o el
diagnóstico original. No se rellenan inputs ausentes mediante recolección.

CURRENT_TARGET con contexto explícito exige que la identidad environment coincida
con las observaciones current referenciadas por la prioridad. Si hay múltiples
environments actuales incompatibles, no se declaran todos como contexto exacto.
Sin contexto, el knowledge no se explota; las propuestas de reutilización quedan
CONTEXT_NOT_BOUND. Los planes genéricos de control/medición pueden permanecer
como diseños no ejecutables sobre el target explícito.

HISTORICAL_ANALYSIS exige scope completo y etiqueta
CONTROLLED_HISTORICAL_SCOPE_NOT_CURRENT_HOST. Permite estudiar Test B con un
target controlado compatible sin fabricar un problema del host actual.

## Knowledge integration y exploration / exploitation / verify

Se validan hashes/jerarquía de runs v0.5, cada record/knowledge, evidencias
enlazadas, policy de replicación y relaciones entre snapshots. Una historia con
supersession pero sin sus items anteriores es incompleta y se rechaza, en vez de
suponer que el último HIGH es vigente. Los sources explícitos pueden omitir
historia posterior desconocida; esto permanece como limitación.

Las vistas contextuales se calculan usando applicability v0.5, sin releer el
host. Knowledge superseded no se usa; weakened/contradicted se considera
contradictorio para explotación. Nunca se explota un conocimiento stale,
unbound o NOT_TRANSFERABLE. El alcance inicial de contextos es CPU numpy_mlp,
igual que las fuentes de learning soportadas; no se generaliza a LLM/GPU.

- **VERIFY:** aceptado sin replicación independiente → REPLICATION; prometedor
  inconcluso → DISCRIMINATION pareada; contradicciones → discriminación; stale o
  compatibilidad limitada → KNOWLEDGE_VALIDATION antes de cualquier reutilización.
- **EXPLOIT:** punto favorable contextual → búsqueda local simbólica; operational
  knowledge replicado exacto → EXPLOITATION, siempre junto a controles y sin
  afirmar que sea el siguiente experimento óptimo.
- **EXPLORE:** ausencia de knowledge aplicable o variación cercana no excluida por
  un negativo. Sin historia no se afirma NEW_REGION: novelty queda UNKNOWN.

Una repetición conocida no se penaliza igual si es replicación intencional o
discriminación justificada. Un punto rechazado no veta su región vecina. La
confianza del plan no excede la menor entre target y knowledge; scope stale o
contraevidencia la limita a LOW.

## Diseños y stopping rules

REPLICATION compara configuración histórica y baseline correspondientes mediante
nueva ejecución/mediciones; conservar protocolo pareado no significa copiar los
resultados anteriores. Para un resultado inconcluso se busca nueva evidencia
pareada sobre el mismo punto, no se cambia arbitrariamente un factor no relacionado.

Sin knowledge y con incertidumbre diagnóstica, DISCRIMINATION puede declarar
parallelism como factor para distinguir compute, memoria, contención o artefacto.
Los demás factores, benchmark, protocolo de datos/seeds y guards se mantienen
controlados. Búsquedas locales son OFAT simbólicas iniciales, no una imposición
universal de OFAT.

El caso Test B permite un diseño CONTROLLED_FACTORIAL sobre learning_rate y
weight_decay para separar efectos/interacción/confounding. Se basa en que ambos
factores aparecen cambiados en la historia, **no en interacción ya demostrada**.
No se generan niveles numéricos ni trainer.py. Su budget conceptual mínimo es
20 condition-trial observations; con presupuesto insuficiente queda bloqueado.

CONTROL_EXPERIMENT y BASELINE_RECONFIRMATION comparan baseline con baseline
idéntico: ambos hashes de configuración deben coincidir. No se confunde un control
con la candidata aceptada. KNOWLEDGE_VALIDATION compara alcance actual explícito
con el declarado, sin afirmar que runtime permanezca controlado si precisamente
se investiga compatibilidad entre contextos.

Cada plan declara success/rejection/inconclusive conditions, presupuesto máximo
y mínimo, unidad de evidencia, nueva ejecución independiente, parada por fallo
de guard y `automatic_extension=false`. Defaults: máximo conceptual 20 trials y
24 planes. No hay loops de campaña, comandos ejecutables ni autoridad implícita.
Las condiciones remiten a criterios protegidos existentes: no cambian acceptance,
benchmark, quality threshold o sandbox para facilitar un resultado favorable.

## Information value, improvement potential, costes y utility

Information value y improvement potential son dimensiones separadas LOW/MEDIUM/HIGH
(improvement también UNKNOWN). Replicar puede tener información HIGH y mejora
inmediata LOW. Coste conceptual VERY_LOW/LOW/MEDIUM/HIGH, riesgo LOW/MEDIUM/HIGH,
reversibilidad EASY/MODERATE/DIFFICULT/UNKNOWN. Los perfiles de planes acotados no
son coste total de resolver un target completo; éste se conserva por separado.

Cuando existe, se muestra mediana histórica de costes hasta calidad de las
confirmaciones usadas. **No es wall time futuro**: future_seconds_estimate=null.
La variante simbólica todavía necesita diseño operacional y autorización futura.

Utility registra sumandos explícitos: información, potencial de mejora,
confianza, replicación, verificación, validación de scope, explotación y
penalizaciones de coste/riesgo/reversibilidad/duplicación. El total es ordinal,
no valor esperado científico calibrado. Ranking conserva primero el tier v0.4,
luego utility y desempates deterministas; nunca reordena silenciosamente targets
de menor prioridad por encima de otro tier de investigación.

Reglas versionadas META_REPLICATE, META_INCONCLUSIVE, META_CONTRADICTION,
META_STALE, META_NEGATIVE, META_MEASUREMENT, META_EXPLORE, META_EXPLOIT,
META_BASELINE, META_FACTORIAL, META_AUTHORITY y META_BUDGET (`_001`). La selección
limitada de candidatos registra exclusiones por presupuesto. Un exploration_floor
acotado conserva candidatos de exploración cuando no hay cobertura exacta, no
premia novelty por sí sola ni obliga a experimentar.

Config separada `meta_strategy`: replication_bonus=4, exact_repeat_penalty=20,
information_value_weight=3, improvement_potential_weight=1, cost_penalty=2,
risk_penalty=3, verification_bonus=2, exploitation_bonus=3,
knowledge_validation_bonus=3, exploration_floor=1, max_candidate_plans=24,
max_trials_per_plan=20. Todos los valores se validan; la policy no se autoedita.

## Novelty y duplicados

Novelty: EXACT_REPEAT, NEAR_REPEAT, KNOWN_REGION, NEW_REGION, UNKNOWN. No existe
bonus de novelty. Config hashes, baseline, contexto, familia y variables separan
repetición intencional de una repetición accidental de escaso valor.

Rechazo exacto suficientemente respaldado en contexto equivalente genera
EXACT_REJECTED_CONFIGURATION y excluye la repetición del ranking. Esta búsqueda
es transversal: un resumen regional no puede volver a introducir el mismo punto
rechazado como supuesto inconcluso. El plan bloqueado enlaza también el knowledge
negativo exacto que lo causó. Variaciones simbólicas cercanas permanecen permitidas.

Screening aislado histórico sólo penaliza fuertemente, sin bloqueo regional ni
certeza de refutación. El candidato duplicado puede conservarse como alternativa
AVOID con sus razones, pero no se ejecuta. En cambios locales simbólicos,
duplication_risk=MEDIUM advierte posible solapamiento: todavía no existe un nuevo
genome hash que certifique novedad exacta. Plan IDs iguales se consolidan; no se
afirma que toda variación simbólica distinta sea un experimento futuro distinto.

## Test B histórico y casos reales/controlados

Se usaron outputs reales existentes v0.4/v0.5, sin nueva observación ni workload.
El target CPU para Test B es explícitamente **controlado/histórico**, no un
diagnóstico actual del host. El informe conserva HISTORICAL_ANALYSIS.

En la decisión final `s000003`, ocho candidatos:

- Rank 1: REPLICATION / VERIFY del efecto aceptado e00003, por falta de
  replicación independiente; conserva referencias a baseline/config probados.
- e00002: DISCRIMINATION / VERIFY de la señal prometedora inconclusa mediante
  nueva evidencia pareada, sin convertirla en fracaso ni éxito.
- e00001: repetición accidental exacta de 96×2 penalizada; su rechazo de screening
  no se convierte en prohibición de toda la región.
- Búsquedas locales/control factorial posibles, con alcance y confounders visibles.

La historia original certificó que e00003 aprovechó historia local previa.
Los snapshots learning usados aquí conservan resultados/configuraciones, no una
etiqueta causal de metodología que permita atribuirle un plan propuesto en 0.6.
Por eso esos experimentos permanecen UNATTRIBUTED_HISTORICAL_EXPERIMENT: no se
inventa que ejecutaron estos nuevos planes ni que una clase haya sido óptima.

| Caso | Resultado final |
| --- | --- |
| Prioridad real sin issue | s000001: cero planes |
| Target real de ruido específico, P3 | s000002: MEASUREMENT_REFINEMENT / VERIFY; prioridad original preservada |
| Aceptado sintético no replicado | REPLICATION / VERIFY favorecido |
| Prometedor inconcluso sintético | DISCRIMINATION pareada / VERIFY favorecida |
| Rechazo exacto fuerte | Repetición bloqueada incluso vía resumen regional; variación cercana disponible |
| Ruido wall que bloquea targets | MEASUREMENT_REFINEMENT primero; dependientes DEFER excluidos |
| Knowledge contradicho | DISCRIMINATION; ninguna explotación |
| Knowledge stale | KNOWLEDGE_VALIDATION; ninguna explotación |
| Operational knowledge sintético | EXPLOITATION disponible; control barato puede rankear antes según perfil |
| Sin knowledge | Control + exploración acotada, novelty UNKNOWN |

Los casos sintéticos están separados por filename y no son mediciones del host.
Se reinterpretó el caso operational desde los mismos snapshots al reforzar la
identidad de baseline control. No se ejecutó ningún plan para validar la fase.

## History, strategy learning y meta-métricas

Cada decisión guarda planes propuestos y contexto; executed_by_subsystem=false,
eventual_execution=UNKNOWN_UNLINKED, linked_experiments=[], outcome/information/
improvement/actual_cost=null. No se llama «no ejecutado nunca» a algo cuya futura
ejecución externa se desconoce; sólo se garantiza que este subsistema no lo ejecutó.

Cuando dos experimentos exactos de contexto/configuración tienen ejecución y
mediciones distintas, se puede registrar un episodio retrospectivo REPLICATION,
con corroboración o contradicción/unresolved. No se atribuye causalidad de
estrategia ni vínculo a un plan nuevo. En Test B no existe tal replicación exacta;
la utilidad de clases queda sin demostrar. El ejemplo sintético prueba el contrato
de registro sin afirmar una mejora científica general.

Baseline Test B, muestra **n=3**:

- ACCEPTED=1, REJECTED=1, INCONCLUSIVE=1.
- Accepted improvement rate e inconclusive rate: 1/3 cada una.
- Exact duplicate evidence count=0; tasa descriptiva=0.
- Experiments per accepted improvement=3.
- Information-producing/useful proxy=3/3: resultados con evidencia de outcome,
  confirmación, calidad o screening comparable. **No significa 100 % de utilidad
  científica o de eficiencia estratégica.** La definición del proxy es explícita.
- Candidate confirmation costs conocidos suman 13,214888 s, únicamente costes
  hasta calidad de samples disponibles; no wall time ni coste total de campaña.
- Cost per useful experiment=null: la proyección no conserva coste experimental
  total suficiente para ese cociente.

La tasa de duplicados usa identidades de evidencia duplicada distintas sobre
evidencia única más esas identidades, no frecuencia de ingestión. Repetir snapshots
no infla n. Las métricas son por decisión/fuentes explícitas; queries no suman
snapshots repetidos como si fueran nuevos experimentos. small_sample=true y
strategy_utility_improvement_demonstrated=false permanecen explícitos.

## Store, queries y CLI

`<state>/experiment-strategies/`: `decisions/`, `plans/`, `history/`, `metrics/`.
Artefactos canónicos, hashes, flock, staging, fsync y hard-link create-only,
permisos 0444. Planes idénticos pueden reutilizarse sin overwrite. El índice de
decisión es el punto de commit después de persistir sidecars; fallos previos no
exponen decisiones parciales. Los IDs huérfanos no se reutilizan silenciosamente.
Lectura valida schema/hash y coincidencia de cada plan/history/metrics.

```sh
python gaia.py plan-experiments <priority-id-or-json> --state-dir state_local
python gaia.py plan-experiments <priority-json> --learning-run <saved-run-json> --context <context-json> --analysis-mode HISTORICAL_ANALYSIS --state-dir state_local
python gaia.py experiment-strategies --state-dir state_local
python gaia.py experiment-strategy latest --state-dir state_local
python gaia.py experiment-strategies --target t0001 --priority-hash <hash> --state-dir state_local
python gaia.py experiment-strategies --class REPLICATION --state-dir state_local
python gaia.py experiment-strategies --knowledge <knowledge-id> --state-dir state_local
python gaia.py experiment-strategies --duplicates --state-dir state_local
python gaia.py experiment-strategies --highest --state-dir state_local
python gaia.py strategy-metrics latest --state-dir state_local
```

`--json` disponible. `--diagnosis` permite cotejar diagnósticos exactos;
`--learning-state` lee batches existentes sin ingerir ni actualizar learning.
Highest significa mayor rank en la decisión coincidente más reciente, no
competición global de contextos diferentes. Para target IDs locales repetidos,
`--priority-hash` desambigua. Metrics incluye strategy_id, decision_hash y fuentes.
Errores explícitos/sanitizados, sin autoprovisionamiento o ejecución de planes.

## Auditoría, privacidad y coste

`tools/audit_meta_strategy.py` valida schema, hashes, refs de inputs, ranking,
uso contextual de knowledge, duplicados y métricas reproduciendo la decisión
con las mismas fuentes/policy. Sólo strategy_id, timestamp y coste de cálculo
pueden variar. Comprueba guard SHADOW, ausencia de código y autoridad de mutación.
La inspección AST no es una prueba formal contra Python hostil: sus imports y
llamadas se revisan además como parte del delta de esta fase.

Auditoría CLI final: **11 decisiones, PASS**, receipt `final/verified-audit.json`.
Evidencia autoritativa en `docs/meta_strategy_evidence/final/`; el directorio padre conserva una validación
preliminar identificada como tal y no constituye certificación del intérprete final.
No son ejecuciones experimentales adicionales ni replicaciones independientes.

Allowlist de IDs/hashes, contextos v0.5, enums, métricas y plantillas cerradas.
No se copian claims/razones arbitrarios desde inputs. Además del schema v0.5,
se validan explícitamente enums de outcome/scope y escalares históricos usados en
history/estimaciones: un snapshot re-sellado con strings privados en esos campos
no se acepta como canal de salida. Sin usernames, hostname,
network identifiers, rutas personales, secrets o dumps de entorno nuevos.
No se buscan datos privados ni se relee el host para completar contexto.

Coste registrado de composición en los snapshots: no-issue 0,421 ms, ruido real 1,013 ms, Test B histórico
3,847 ms. Se registran targets_processed, plans_generated, plans_considered y
learning_runs_processed. Incluye validación/composición; no impresión ni fsync.
Es coste observado al producir esos snapshots, no una comparación de rendimiento
entre revisiones del intérprete.
Las stores temporales de validación estuvieron fuera del repo y se eliminaron;
los exports son evidencia estática curada, no estados de campaña.

## Tests y no regresión

Todas las suites con `-B -W error::ResourceWarning`, incluyendo warnings unraisable:

| Suite | Recogidos | Ejecutados | Skips | Failures/errors/warnings |
| --- | ---: | ---: | ---: | --- |
| Meta strategy final | 55 | 55 | 0 | 0 / 0 / 0 |
| Learning | 52 | 52 | 0 | 0 / 0 / 0 |
| Prioritization | 39 | 39 | 0 | 0 / 0 / 0 |
| Diagnosis | 46 | 46 | 0 | 0 / 0 / 0 |
| Observation | 34 | 34 | 0 | 0 / 0 / 0 |
| Crítica v0.1 | 171 | 170 | 1 | 0 / 0 / 0 |
| Completa final | 632 | 621 | 11 | 0 / 0 / 0 |

Suite completa final: **745,603 s**. Nueve skips Torch ausente previstos y dos
exclusiones administrativas conocidas: Prueba A real y test de campaña autónoma.
No se modifican sus fuentes/assertions. Los 55 tests nuevos cubren clases,
ingestión, casos A–H, seguridad contextual, exact negatives transversales, guards,
stopping, utilidad, costes/riesgo/reversibilidad, determinismo, store concurrente,
queries, CLI, audit, privacidad y ausencia de llamadas evolutivas.

462 de los 464 archivos originales permanecen idénticos byte a byte. Se preservan
16 módulos observation, 10 diagnosis, 8 prioritization, 12 learning, 8 protected,
66 frozen y `gaia/meta.py`. Sólo se modifican dispatch CLI y defaults nuevos en
`gaia.py`/`gaia/config.py`. Defaults antiguos y experimental_config idénticos.
Código funcional validado: `0ca014b`; receipts y hashes de logs definitivos en
`final/verified-tests.json` y `final/verified-regression.json`. Las validaciones
anteriores se conservan como historia de desarrollo con sus propios hashes.
Sin merge ni trabajo sobre una rama 0.7.

## Limitaciones de shadow mode

Las plantillas iniciales son acotadas y CPU numpy_mlp; no diseñan cualquier
experimento científico. Utility, information value y perfiles de coste son
ordinales/no calibrados. Los planes simbólicos todavía pueden solaparse y no son
especificaciones listas para un executor. La validez se limita a snapshots,
contexto y evidencia suministrados; el futuro puede añadir contradicciones.

La policy conserva evidencia para comparar procesos después, pero no se ha
comparado contra otra estrategia ni demostrado mejora general del proceso.
No hay ejecución automática, código generado, investigación web, LLM, cambios
de seguridad/evaluador/benchmark o auto-modificación irrestricta.

Siguiente etapa propuesta: **GAIA 0.7 — External Research & Evidence Acquisition**.
