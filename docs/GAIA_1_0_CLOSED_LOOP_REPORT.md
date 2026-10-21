# GAIA 1.0 — Closed-Loop Autonomous Improvement

## Estado y alcance

**PASS limitado al closed loop de verificación `numpy_mlp`, con ejecución y
aprendizaje autónomos reales.** Promotion y rollback no fueron ejercitados en la
campaña y no se certifican como logros nuevos de 1.0.
Rama única `feat/gaia-1.0-closed-loop`, base
`1c5d6235c03ba35ef31e7b92d45142a128643ea0` /
`gaia-v0.9-cognitive-orchestration`. Autoridad conceptual: Documento Maestro v3.

El alcance inicial es **verificación experimental autónoma de `numpy_mlp`** bajo
los criterios existentes de v0.1. No evolución arbitraria de GAIA, entrenamiento
del LLM ni una prueba de AGI. Una campaña puede cerrar correctamente con rechazo,
aprendizaje y parada: no se requiere fabricar mejora o promoción.

## Arquitectura y subsistemas reutilizados

`gaia/autonomy/` coordina, no sustituye, los motores anteriores:

| Módulo | Responsabilidad |
| --- | --- |
| `schema` | Campaign contract y perfil de autoridad cerrados |
| `store` | Journal inmutable, cursor durable, locks, fsync y controles humanos |
| `policy` | Autoridad, límites, superficie y huellas de fuentes/protected/frozen |
| `materializer` | Plan simbólico permitido → genoma mediante mecanismos existentes |
| `services` | Adapters de 0.1–0.9, ejecución, aprendizaje y verificación |
| `controller` | Máquina de estados, recuperación y stopping policy |
| `deadline` | Watchdog wall-clock del controller, con cleanup de recursos |
| `research` | Solicitudes 0.7 justificadas y preautorizadas, sólo evidencia |
| `regression` | Matriz fija posterior a promoción; no comandos del modelo |
| `cli` | Crear, ejecutar, inspeccionar, pausar, reanudar y detener |

La generación de candidatos sigue usando `gaia.genome`/operadores existentes.
La ejecución llama a `Engine.experiment`, con worker, bwrap, benchmark, manifest,
provenance, gates G0–G5, evaluación pareada y criterios protegidos existentes.
No hay un evaluador alternativo ni un benchmark elegido por el LLM.

## Campaign model y autoridad

`gaia_closed_loop_campaign_v1` contiene campaign_id, objective, modo, referencias
iniciales, authority profile, targets/componentes/clases permitidos, forbidden
actions, límites de iteraciones/experimentos/tiempo/compute/disco/red, promotion
policy, rollback policy, stopping conditions, estado inicial y trace hash.
La creación parte de objetivo; las referencias a observación aparecen después en
el journal, no se inventa una observación previa en el contrato inmutable.

Objetivo inicialmente soportado: `VERIFY_NUMPY_MLP_EXISTING_CRITERIA`.
Una nueva formulación de objetivo requiere diseño explícito, no interpretar texto
libre como una ampliación de autoridad.

Perfil: `bounded_numpy_mlp_v1`. Autoriza lecturas existentes, NETWORK_READ acotado
con autorización, LOCAL_COMPUTE en el sandbox existente y cambios exclusivamente
en la superficie de hiperparámetros de genomas `numpy_mlp`. Promotion y rollback
sólo por sus mecanismos existentes. Se prohíben shell, edición arbitraria de
fuentes/evaluadores/benchmarks/policy, ampliación de permisos, instalación,
drivers/kernel y modificación de componentes frozen.

La configuración experimental se captura antes de la campaña y se fija por hash.
Sólo se restringen límites normales para ajustarlos al contrato; acceptance,
seeds, quality threshold, benchmark y controles no se afinan tras observar datos.
El estado CPU se asigna a un directorio nuevo `state_closed_loop_cpu_<id>`.

Defaults de campaña: tres iteraciones, tres experimentos, 1800 s de wall,
1200 s de compute, 512 MiB de disco, cero requests externos y 20 s por trial.
**Compute significa tiempo local transcurrido de campaña**, incluyendo setup y
cognición; no se presenta como CPU-seconds ni FLOPs. El techo efectivo temporal
es el menor de wall/compute. Los límites de proceso del candidato siguen siendo
los del sandbox v0.1. La inferencia conserva sus límites 0.8 y restringe el disco
privado al espacio restante de la campaña.

El watchdog del controller requiere main thread y rechaza conflictos con timers
existentes. Los checks de disco/RSS privados son supervisados y muestreados, no
cuotas atómicas de cgroup ni garantías ante kernel/driver comprometido. Las fases
de persistencia/cleanup no autorizan otro experimento cuando se agota presupuesto.

## State machine y flujo

Estados explícitos: CREATED, OBSERVING, DIAGNOSING, PRIORITIZING, RETRIEVING,
RESEARCHING, PLANNING, REVIEWING, AUTHORIZING, MATERIALIZING, EXPERIMENTING,
EVALUATING, LEARNING, PROMOTING, VERIFYING, ROLLING_BACK, REEVALUATING,
COMPLETED, STOPPED, FAILED y PAUSED.

Flujo: objetivo → observación real → diagnóstico → prioridades → consulta de
learning → research si se justifica → estrategia 0.6 → revisión 0.9 → gate
determinista → setup de referencia si hace falta → materialización → ejecución
v0.1 → clasificación independiente → learning 0.5 → decisión de publicación /
verificación / rollback → nueva observación, diagnóstico y prioridad → continuar
o parar. La calibración de la referencia ocurre **después de la autorización**,
no antes de observar/diagnosticar/planificar.

El Engine v0.1 acopla aceptación y publicación en una llamada. Se añade un callback
restrictivo opcional: sin callback, el comportamiento anterior permanece; un
callback jamás permite saltar gates. Si deniega publicación, la evidencia sigue
ACCEPTED y se registra sin promover. Si permite publicar, primero se ejecuta y
persiste una interpretación 0.5, marcada pre-publicación/no operacional. Después
se aplican los gates y publication existentes. La ingestión canónica de learning
se hace con metadata de publicación ya final; no se sobrescribe una proyección
0.5 anterior con metadata distinta. PROMOTING del controller registra/coordina
el resultado, no vuelve a publicar una versión ya committed.

## Diagnóstico, prioridad y estrategia

Se amplía `diagnose` de forma opt-in con `verification_objective`. El protocolo
de observación rápida no establece evidencia pareada cost-to-quality. Ante el
objetivo explícito se registra `WORKLOAD_VERIFICATION_GAP`, con scope
`MISSING_CONTROLLED_VERIFICATION_NOT_A_DETECTED_REGRESSION`. No se inventa un
slowdown, un fallo del host ni una causalidad para conseguir un target.

0.4 conserva su política ordinal y 0.6 sus planes shadow. El controller recorre
su ranking y filtra clases/superficie autorizadas. No inserta un candidato ganador.
La prioridad baja o la incertidumbre no se reinterpretan como un defecto probado;
las comparaciones de control pueden adquirir evidencia sin aceptar una hipótesis
causal. Fuentes nuevas pueden cambiar el diagnóstico o eliminar el gap.

Observation y los manifests de ejecución tienen esquemas de identidad distintos.
No se finge que sus environment hashes coincidan. La consulta 0.5 usa el contexto
real del manifest. La estrategia 0.6 recibe sus learning runs sin inventar un
binding exacto a la identidad observation; no se explota conocimiento unbound,
stale o contradicho. El scheduler comprueba además duplicados contra el contexto
experimental real antes de ejecutar.

## Materialización y seguridad

`ExperimentMaterializer` permite control, reconfirmación, refinamiento, replicación
y búsqueda local sólo cuando se cumplen sus contratos. Replicación/búsqueda local
requieren una configuración de learning exacta y cualificada; no se reutiliza un
ganador histórico incompatible. Sólo se soporta el factor LR para búsqueda local,
mediante el operador existente. Cambios en slots, AST literals o drops se rechazan.
La certificación inicial no prueba todas esas clases: reporta la realmente usada.

Se registra plan/target, autorización, seed, genoma, hashes de genoma/trainer,
baseline, método y diff exacto. El orden de claves se canoniza **antes** de renderizar
y hashear el trainer, para que persista igual al reabrirlo. Código de un template
conocido no equivale a generación libre de código por el LLM.

El gate independiente comprueba scope, componentes, clase, presupuesto, riesgo,
reversibilidad, bwrap y source/protected identities. Rechaza planes que intenten
alterar guards o concederse ejecución. Hashes de todos los módulos Python GAIA,
incluidos frozen/protected, se comprueban entre fases; el Engine conserva además
sus verificaciones de snapshot y entorno en cada trial.

## Cognición y research

La revisión usa `PrimaryLocalIntelligenceBackend` mediante cognition 0.9, sin
acoplar autonomy al nombre del runtime/modelo. Resuelve la selección 0.8 existente:
KoboldCpp v1.123.1 + SmolLM3-3B Q4_K_M + Vulkan + full offload + f16 KV.
El claim heredado es BEST_BALANCED_TESTED, no BEST_AVAILABLE.

`ExperimentReview` enlaza target, resumen de evidencia, rationale de la estrategia,
información esperada, riesgos, missing evidence e incertidumbre. Los claims del
modelo son extractivos/citados, no autoridad final ni reasoning interno libre.
El resultado no firma su autorización: un gate determinista separado decide.

Research 0.7 sólo se solicita si hay una necesidad de requisitos/runtime/capacidad,
URLs explícitas y autorización/budget de red. Se reserva el presupuesto antes de
la adquisición para evitar replays gratuitos. Sigue EVIDENCE_ONLY: no se ejecutan
soluciones, comandos o instalaciones de una fuente. Si no es necesario se registra
`RESEARCH_NOT_NEEDED`; no se fuerza Internet para una demostración. Las reservas
de requests son conservadoras; el artefacto 0.7 conserva los contadores de fetch.

## Aprendizaje, continuación y stopping

ACCEPTED, REJECTED e INCONCLUSIVE son resultados separados. Deferred y alternativas
Pareto se conservan como inconclusos, sin convertirlos en fracaso o aceptación.
Cada experimento finalizado cualificado se proyecta desde manifests/ledger mediante
`curate_archive`, y se ingiere en `LearningStore` 0.5. No se descartan negativos.
El outcome se enlaza a su estrategia/mode, coste, información producida y mejora.
La policy 0.6 no se autoedita.

La evidencia puede evitar una repetición exacta de un punto rechazado. Un rechazo
sólo de screening mantiene `HISTORICAL_REJECTION_ONLY`: diferir su repetición por
presupuesto no significa demostrar que la configuración o su región siempre
fallarán. No se transforma esa retención en una prohibición científica general.
Evidencia pareada suficiente puede satisfacer el gap de verificación sin afirmar
mejora. Las decisiones influidas por learning se registran con sus refs y scope.

Después de aprender se vuelven a ejecutar observación, diagnóstico y priorización.
Se puede iniciar otra iteración o parar por objetivo, ausencia de target/experimento
autorizado, duplicación, presupuesto, inconclusos repetidos, riesgo, salud o control
humano. No se mantiene un target artificial para agotar todos los slots.

## Promotion, verificación y rollback

Promotion requiere ACCEPTED, trial evidence promotable, gate de campaña, clase
promotable, permiso explícito y reserva de tiempo para la matriz posterior. El
callback no evita `readiness.pre_promotion` ni publication. No se fuerza promotion
de controles ni se rebajan umbrales para conseguir una versión nueva.

Si se promueve: nueva observation 0.2, comparación pre/post, gates G0–G5, benchmark
específico y persistencia de la mejora bajo el mismo criterio, más la matriz crítica
v0.1 y subsistemas relevantes. Fallos de verificación o de salud usan el rollback
existente a la versión anterior. Una excepción después de un publication committed
se reconcilia con los receipts nativos, conserva aprendizaje y dispara verificación
fallida/rollback; no vuelve a ejecutar el experimento ni a publicar silenciosamente.

No se provoca una regresión destructiva para ejercitar rollback. Los niveles
AUTONOMOUS_PROMOTION/AUTONOMOUS_ROLLBACK sólo serán PASS si se ejercitan realmente;
en otro caso NOT_EXERCISED con referencia a v0.1. Los tests de coordinación no se
presentan como un rollback autónomo real de la campaña.

## Persistencia, recuperación y control humano

`<state>/autonomy/campaigns/<id>/`: contract/configuration inmutables, artifacts
content-addressed, eventos encadenados, current durable y controles separados.
Lock no bloqueante por campaña, escritura atómica, fsync de archivo/directorio y
rechazo de symlinks en referencias. El journal es el commit point; current es una
proyección recuperable, no otra fuente de verdad.

Un intent de ejecución se registra antes del Engine. Al reabrir, se reconcilian
publication y ledger existentes y se comprueba identidad del experimento. Un intent
ambiguo sin receipt completo detiene en NEEDS_RECOVERY, nunca repite el candidato.
LearningStore es idempotente sobre fuentes ya ingeridas. Campañas terminales devuelven
su report sin repetir acciones. Un rollback ambiguo también exige recuperación.

Hay tests de muerte real de proceso entre journal fsync y cursor, reanudación,
crash después de evidencia committed, ausencia de doble experimento y protección
contra doble publication. Pausar conserva el reloj inicial; reanudar no amplía
presupuestos. STOP se aplica en límites seguros. No existe un flag de disable safety.

```sh
python3 -B gaia.py autonomy-create --mode DRY_RUN --state-dir state_autonomy
python3 -B gaia.py autonomy-create --mode SHADOW --state-dir state_autonomy
python3 -B gaia.py autonomy-create --mode CONTROLLED_AUTONOMOUS --iterations 3 --experiments 3 --wall-seconds 1800 --compute-seconds 1200 --state-dir state_autonomy
python3 -B gaia.py autonomy-run <campaign-id> --state-dir state_autonomy --authorize-campaign
python3 -B gaia.py autonomy-status <campaign-id> --state-dir state_autonomy
python3 -B gaia.py autonomy-trace <campaign-id> --state-dir state_autonomy
python3 -B gaia.py autonomy-pause <campaign-id> --state-dir state_autonomy
python3 -B gaia.py autonomy-resume <campaign-id> --state-dir state_autonomy
python3 -B gaia.py autonomy-stop <campaign-id> --state-dir state_autonomy
```

## Certificación real definitiva

Tres campañas independientes sobre los mismos bytes funcionales:

| Modo | Campaign ID | Resultado | Tiempo wall (s) |
| --- | --- | --- | ---: |
| DRY_RUN | `ac1263a9a5876e446792e8d1a6` | PASS, materialización sin ejecutar candidato | 17,553 |
| SHADOW | `acbbd7f800969b4e5fa59d9bcc` | PASS, observación/estrategia/review/gate sin candidato | 17,150 |
| CONTROLLED_AUTONOMOUS | `ac1b32b24a444d4391919962f4` | PASS de ciclo acotado; rechazo, learning y parada | 274,780 |

La campaña real empieza desde el objetivo y una observación actual. El gap de
verificación conduce mediante 0.3/0.4 a `UNKNOWN_REQUIRES_EVIDENCE`, componente
core, prioridad **P3**. 0.6 selecciona **CONTROL_EXPERIMENT / VERIFY**, no una
configuración ganadora elegida a mano. Cognition consulta evidencia del plan,
sintetiza clase/mode/riesgo con citas y conserva incertidumbre; después un gate
externo autoriza únicamente la superficie contratada.

### Experimento e00001

Genoma idéntico en valores al baseline, diff `[]`, método
`IDENTICAL_CURRENT_BASELINE`. El genoma canónico tiene hash
`c4443615248cea5c7e5534bb42e3d9782e9f4bd862983b4bc5695ca0430ba3be`
**no usado como un ganador**; la identidad exacta del genoma y del trainer se
conserva en el artefacto MATERIALIZED del bundle. Se genera código sólo con el
renderer existente, y se pasa por G0–G5; todas las puertas resultan PASS.

Screening real: **1,0157 s** de coste frente a referencia aproximadamente
**1,027 s**, accuracy **0,6271**, 2700 batches, bwrap y handshake verificados.
No supera el margen de screening vigente: decisión **REJECTED**, no ACCEPTED
ni INCONCLUSIVE. No se rebajan el min_gain **0,05**, los **cinco** pares de
confirmación configurados ni la tolerancia de memoria **1,25**. Al fallar el
screening no se lanza confirmación adicional. Los controles/gates usan sus propios
trials; no se confunden con otra iteración candidata.

No se observó mejora aceptada. El resultado científico es local y negativo bajo
ese criterio, no una prueba universal de que una región de hiperparámetros falla.

### Aprendizaje y segunda iteración

La evidencia original se proyecta mediante 0.5 y se ingiere persistentemente:
`REJECTED_DIRECTION`, confianza **LOW**, alcance **HISTORICAL_REJECTION_ONLY**.
Se conserva el resultado negativo con su contexto, manifests y ledger refs.
El outcome queda enlazado a la estrategia VERIFY y al coste experimental.

GAIA vuelve a observar, diagnosticar y priorizar, consulta ese learning y produce
otra planificación/review. El control materializado repetiría el mismo punto.
El scheduler lo difiere con el motivo
`BUDGETED_REPEAT_DEFERRED_USING_EXISTING_LEARNING`: **una decisión real cambia por
el aprendizaje**, y se evita un segundo experimento idéntico. No se presenta un
rechazo de screening como una prohibición científica general. El gap no se elimina
artificialmente y no se fuerza un target diferente para consumir el budget.

Parada: **NO_AUTHORIZED_NON_DUPLICATE_EXPERIMENT**. Quedaba presupuesto, pero no
otra alternativa materializable y justificada dentro de esta superficie y contexto.
No hay experimento 2 ejecutado; sí hay segunda iteración y su decisión de no repetir.

### Métricas y niveles

| Métrica | Resultado |
| --- | ---: |
| Iteraciones | 2 |
| Experimentos candidatos | 1 |
| Accepted / rejected / inconclusive | 0 / 1 / 0 |
| Research calls / requests | 0 / 0 |
| Repeticiones evitadas / learning reused | 1 / 1 |
| Experimentos informativos | 1 |
| Tiempo wall total | 274,780 s |
| Coste de Engine.experiment, incluidos gates | 78,792 s |
| Rollbacks | 0 |
| Autorizaciones iniciales | 1 |
| Intervenciones humanas durante campaña | **0** |

| Nivel | Resultado |
| --- | --- |
| PIPELINE_CLOSED_LOOP | PASS |
| AUTONOMOUS_EXECUTION | PASS |
| AUTONOMOUS_LEARNING | PASS |
| AUTONOMOUS_PROMOTION | NOT_EXERCISED |
| AUTONOMOUS_ROLLBACK | NOT_EXERCISED |

Research fue **RESEARCH_NOT_NEEDED**: se requería comparación local, no consejo
web. Promotion no procede ante el rechazo; post-promotion verification y su
matriz quedan NOT_EXERCISED en esta campaña. Rollback conserva la certificación
histórica v0.1 y las pruebas de coordinación, sin inyectar una regresión destructiva.

Los siete comandos CLI se verificaron también con casos adicionales de control:
pause/resume de DRY_RUN, inspección, stop de SHADOW y reejecución terminal
idempotente. No son intervenciones en la campaña autónoma certificada.

No confundir los ensayos de desarrollo detenidos por cambios de fuentes con esta
serie congelada. `development-history.json` conserva IDs, hashes, decisiones
nativas finalizadas y fallos de esos ensayos; los originales permanecen locales.
No se convierten en PASS ni se eliminan outcomes negativos. Una suite de desarrollo
interrumpida antes de cerrar los últimos cambios tampoco se cuenta como validación
final; sus logs quedan identificados separadamente.

## Auditoría y privacidad

`tools/audit_closed_loop.py` verifica offline contratos, transiciones, referencias,
autoridad, materialización reproducida, evidencia de bwrap, hashes, gates G0–G5,
clasificación protegida, learning 0.5 reproducido, decisiones de publicación y
trazas. No ejecuta candidato, modelo, fetch ni promotion. Las trazas cognitivas
se auditan además con el auditor 0.9.

Los originals locales de v0.1 contienen rutas privadas de mounts/hidden paths en
la attestation de sandbox. Primero se auditan íntegramente en su custodia local.
El export portable elimina esas rutas, conserva checks/identidades/métricas y
compromisos de hash originales, y se etiqueta como **privacy projection**, con
hash propio. No se presenta como recomputación del hash de bytes originales que
no se publican. El auditor portable reproduce lógica/claims/evaluación y valida
proyecciones y compromisos, con ese límite de confianza explícito.

No se ocultan rutas privadas en base64 para eludir la revisión. No se publica
modelo, peso, binario, cache, log bruto ni chain-of-thought. Los valores privados
usados para comparar export no se guardan en el resultado del privacy check.

Evidencia portable: [closed_loop_evidence/final/](closed_loop_evidence/final/).
Auditorías completas locales de las tres campañas: **PASS**. Auditoría portable,
incluidas las cuatro trazas cognitivas y su grounding: **PASS** con DNS, sockets
y ejecución de procesos denegados. Una copia alterada se rechaza por hash. La
proyección elimina rutas privadas tanto de los trials como de la copia del resultado
de screening; los originales locales no se modifican. El manifiesto de las campañas
y del historial contiene **cinco documentos / 718.928 bytes**; recibos adicionales
de tests, CLI, regresión, auditoría y privacidad se enlazan desde `verification.json`.

## Tests y regresión

Suite completa final posterior a la campaña: **850 recogidos, 839 ejecutados,
11 skips conocidos, cero fallos, errores, warnings o ResourceWarnings unraisable**,
en **763,421 s**, con `-B -W error::ResourceWarning`.

Desglose de la misma ejecución, sin repetir subconjuntos innecesariamente:

| Subconjunto | Recogidos | Ejecutados | Skips |
| --- | ---: | ---: | ---: |
| Autonomy, nuevos | 67 | 67 | 0 |
| Cognition | 57 | 57 | 0 |
| Local intelligence | 25 | 25 | 0 |
| External research | 69 | 69 | 0 |
| Experiment strategy | 55 | 55 | 0 |
| Learning | 52 | 52 | 0 |
| Prioritization | 39 | 39 | 0 |
| Diagnosis | 46 | 46 | 0 |
| Observation | 34 | 34 | 0 |
| Crítica v0.1 | 171 | 170 | 1 |
| Completa | 850 | 839 | 11 |

En todos: cero fallos/errores/warnings. Los skips son los nueve de Torch ausente
y las exclusiones administrativas de Prueba A y campaña autónoma v0.1 separadas;
no sustituyen ni omiten la campaña 1.0 real. `tests.json` guarda sus IDs/motivos,
hashes de logs externos, source identity y hash de los tests nuevos.

Regresión: **1.932 de 1.937 archivos originales byte-idénticos**. Sólo cambian
dispatch CLI, callback restrictivo opcional del Engine, extensión opt-in de diagnosis
y proyección tipada de review en cognition. AST comparado con la base comprueba
que, quitando esas extensiones, los cuerpos anteriores coinciden. Defaults previos,
evaluator, benchmark, worker, sandbox, publication, rollback y frozen permanecen
byte-idénticos. No se modifica la política 0.6 ni se reentrena el LLM.

Commit funcional: `ecd0d45` — implementación, contratos, adapters, tests y auditor.
La evidencia y este informe se entregan en un commit documental separado.
Committear no cambia los bytes validados; no se relanzan campañas ni suites por
agregar metadata Git o documentación. No se hace merge, push ni tag.

## Limitaciones y certificación

Una campaña de verificación `numpy_mlp` no prueba optimización general, mejora de
inteligencia, evolución del LLM, descubrimiento autónomo de técnicas nuevas,
automodificación arbitraria, AGI, ASI ni self-awareness. Las propuestas permanecen
en una superficie cerrada. Las clases no ejercitadas y los niveles de promoción /
rollback se distinguirán expresamente de los que tengan evidencia real.

PASS significará: «GAIA puede ejecutar un ciclo autónomo cerrado de automejora
dentro de una superficie, presupuesto y autoridad previamente delimitados,
utilizando observación, diagnóstico, priorización, conocimiento, estrategia,
cognición, experimentación, evaluación y aprendizaje».

No se hará push, PR, merge ni tag en esta fase. Si PASS, corresponde cerrar
formalmente GAIA v1.0 antes de definir cualquier fase post-1.0.
