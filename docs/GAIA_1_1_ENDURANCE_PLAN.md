# GAIA 1.1 — Autonomous Endurance & Stability Plan

## Estado de partida

> **Enmienda (revisión de 2026-10-22).** La revisión de este plan contra el código de
> 1.0 encontró que el closed loop sólo podía ejecutar **un** experimento real por
> campaña (control con baseline idéntico; EXPLORATION descartada; contexto de learning
> no enlazado; duplicado ⇒ parada; promoción inalcanzable). Un endurance sobre esa base
> habría medido sobre todo reposo. Por eso se intercaló **GAIA 1.0.1 — Integración
> completa del closed loop** (`docs/GAIA_1_0_1_INTEGRATION_REPORT.md`), que pasa a ser
> la base de partida de este plan. Las secciones marcadas «Enmienda» actualizan el plan.

GAIA v1.0 está cerrada y congelada; GAIA 1.0.1 integra el ciclo completo sobre ella.

**Base estable**
- Rama de partida: `feat/gaia-1.0.1-integration` (tras su merge, `main`)
- Base 1.0: `fe767aae87afe113f931aa1426dd1d5a9851dddb` / `gaia-v1.0`
- Base 1.0.1: commit funcional y documental registrados en su informe
- Working tree: limpio al iniciar Stage 0 (este plan se commitea al crear la rama 1.1)

**Certificación vigente (1.0, conservada)**
- `PIPELINE_CLOSED_LOOP`: PASS
- `AUTONOMOUS_EXECUTION`: PASS
- `AUTONOMOUS_LEARNING`: PASS
- `AUTONOMOUS_PROMOTION`: NOT_EXERCISED
- `AUTONOMOUS_ROLLBACK`: NOT_EXERCISED

La campaña certificada de GAIA 1.0 duró **274,78 s (≈4,6 min)** de wall, con un coste de
`Engine.experiment` de 78,79 s; realizó dos iteraciones, ejecutó un experimento, lo
rechazó, aprendió del resultado y evitó repetirlo. Los niveles alcanzados por 1.0.1
(varios experimentos por campaña, linaje persistente, promoción natural, superficie de
inferencia) se toman de su propio informe, no se presuponen aquí.

Esto demuestra funcionamiento autónomo acotado, pero **no estabilidad durante horas o días**.

---

## Objetivo de GAIA 1.1

GAIA 1.1 debe certificar que el closed loop de GAIA 1.0 puede operar durante sesiones prolongadas y repetidas sin degradación operativa significativa, manteniendo:

- autoridad acotada;
- presupuestos;
- trazabilidad;
- integridad de estado;
- aprendizaje reutilizable;
- recuperación segura;
- stopping correcto;
- recursos bajo control;
- cero escalamiento de permisos;
- cero efectos duplicados.

GAIA 1.1 **no amplía de forma sustancial la autonomía funcional**.

No incluye:

- automodificación libre de código;
- shell arbitrario;
- modificación de evaluadores;
- modificación de benchmarks;
- ampliación automática de permisos;
- model training;
- LoRA/QLoRA;
- nuevas superficies evolutivas;
- memoria cognitiva general.

---

# Readiness

**Estado:** `READY_WITH_PREREQUISITES`

GAIA v1.0 no debe lanzarse directamente a una campaña de 24 horas.

La estrategia recomendada consiste en mantener campañas pequeñas y acotadas, coordinadas por una nueva capa de endurance supervision que permita observarlas durante ventanas más largas.

---

# Gaps pre-endurance

## Required

### 1. Supervisor externo y heartbeat

El watchdog actual se apoya en `SIGALRM` dentro del main thread (`gaia/autonomy/deadline.py`),
exige no tener otro timer activo y no puede convivir con varias campañas en el mismo proceso.

**Enmienda — modelo de procesos.** El supervisor/session-driver es un proceso propio de
larga vida; cada campaña es un proceso hijo `autonomy-run` en su propia sesión/grupo de
procesos. Los criterios de RAM se aplican así: pendiente ≤1 MiB/h **del supervisor**;
para cada campaña, pico y retorno a la banda basal tras su salida (no existe un
«controller en reposo» de 24 h). La matriz de regresión usa `subprocess.run` sin nueva
sesión (`gaia/autonomy/services.py`, `regression_matrix`): el supervisor debe cubrir sus
descendientes. El runtime LLM y los trials ya usan `setsid` + `--die-with-parent`.

Se necesita supervisión independiente capaz de:

- comprobar liveness;
- detectar hangs;
- identificar procesos propios;
- distinguir controller, worker y backend;
- detener únicamente procesos pertenecientes a la sesión;
- conservar evidencia antes del cleanup.

### 2. Presupuestos agregados por sesión

Actualmente cada campaña tiene sus propios límites.

Debe añadirse un contrato de sesión que limite globalmente:

- número de campañas;
- duración total;
- compute acumulado;
- almacenamiento;
- reinicios;
- recuperaciones;
- research.

Crear un nuevo campaign ID no puede resetear de facto los presupuestos del programa.

**Enmienda.** En 1.0.1 el presupuesto de disco de una campaña v2 ya cuenta su directorio
más el crecimiento del linaje desde la admisión (`policy.disk_used`); en v1 seguía
recorriendo todo `--state-dir`. La sesión debe añadir su propio techo agregado.
"Compute" en el contrato es **tiempo local transcurrido**, no CPU-seconds: el compute
agregado de cada stage es, por tanto, suma de wall de campañas.

### 3. Separación de tiempo

Registrar por separado:

- wall time;
- active time;
- idle time;
- inference time;
- tool time;
- experiment time;
- CPU time cuando pueda medirse.

Usar:

- reloj monotónico para intervalos;
- timestamps UTC para trazabilidad;
- boot ID para detectar reinicios del sistema.

**Enmienda.** Toda la temporización de `gaia/autonomy` usa `time.time()`; un salto atrás
del reloj produce `STOPPED_BUDGET` (`policy.budget_check`). No hay uso de boot_id en el
código. Un cambio de boot_id durante una ventana declara el stage
`INCONCLUSIVE_ENVIRONMENT` y obliga a repetirlo; nunca se cuenta como ventana continua.

### 4. Recuperación inequívoca

Distinguir explícitamente:

- `TERMINAL_OK`
- `RECOVERABLE`
- `NEEDS_RECOVERY`
- `CORRUPT`
- `NON_RECOVERABLE`

No presentar un estado ambiguo como completado correctamente.

**Enmienda.** Hoy `autonomy-status` clasifica `STOPPED`/`FAILED` como `recovery: COMPLETED`
(`gaia/autonomy/cli.py`) y `NEEDS_RECOVERY` se persiste como `STOPPED` terminal (no se
puede reanudar esa campaña). La clasificación se define con una tabla
(phase, reason, intents) → clase. "Máximo 2 recovery/campaña" sólo aplica a relanzar una
campaña **no terminal** tras la muerte del controller. 1.0.1 ya bloquea el **linaje**
ante `NEEDS_RECOVERY`, rollback fallido, health check fallido o un experimento ejecutado
y no aprendido, hasta `autonomy-lineage-unblock` explícito.

### 5. Inspección realmente read-only

El monitor de endurance no puede reparar estado mientras observa.

La inspección debe:

- no modificar cursor;
- no adquirir locks destructivos;
- no reparar journals;
- no reescribir estado.

La reparación debe ser una operación explícita, separada y bajo lock.

**Enmienda (hechos del código).** `autonomy-status` toma `LOCK_EX|LOCK_NB` y **falla
mientras la campaña corre**; `CampaignStore.current()` reescribe `current.json`;
`run()` sobre una campaña terminal repara el cursor sin lock. `autonomy-trace` y
`autonomy-lineage-status` (1.0.1) sí son lecturas puras.

### 6. Contabilidad de almacenamiento por propietario

Separar almacenamiento de:

- campaign;
- session;
- shared state;
- inference scratch;
- evidence;
- learning;
- telemetry.

Añadir además un techo global.

**Enmienda.** Estado del host en la revisión: disco al **83 %** (38 GiB libres de 228 GiB),
14 GiB de RAM. Los gates 70/85/95 % se aplican al **techo de sesión**; el filesystem usa la
reserva max(5 GiB, 10 %) = 22,8 GiB. `state_local_intelligence` (6,9 GB) queda fuera de
los budgets de campaña y se inventaría en Stage 0.

### 7. Learning entre episodios

El aprendizaje no puede quedar aislado en cada campaign namespace.

Crear un catálogo de referencias verificadas de sesión que permita reutilizar conocimiento cuando:

- el binding sea compatible;
- los manifests coincidan;
- el contexto experimental sea equivalente;
- no exista contradicción/staleness incompatible.

No considerar equivalentes hashes distintos sin prueba explícita.

**Enmienda.** Resuelto en lo esencial por el **linaje persistente** de 1.0.1: engine state,
LearningStore, baseline de observación, registros de experimento y outcomes de estrategia
compartidos por campañas sucesivas, con contexto enlazado al manifest de ejecución y
STALE tras una promoción. El catálogo de sesión de 1.1 indexa linajes y sus registros; no
fusiona stores (cada consulta 0.5 re-hashea su historial, coste lineal). La "réplica
temporal declarada" deja de ser necesaria para tener actividad y queda opcional.

### 8. Stopping y métricas de progreso

Añadir contadores de:

- fallos consecutivos;
- targets repetidos;
- ausencia de progreso;
- experimentos redundantes;
- decisiones modificadas por learning;
- stopping correcto.

No considerar todo experimento terminado como “informativo”.

### 9. Telemetría y retención acotadas

Registrar de forma controlada:

- RAM;
- VRAM;
- FDs;
- procesos;
- archivos;
- disk usage;
- runtime health;
- controller health.

Evitar crecimiento ilimitado de telemetry y work directories.

### 10. Congelación reproducible del protocolo

Antes de cada serie deben quedar fijados:

- commit;
- configuración;
- backend seleccionado;
- runtime/model hashes;
- workloads;
- acceptance criteria;
- scenarios;
- protected hashes.

No utilizar una selección `latest` que pueda cambiar durante la sesión.

**Enmienda.** 1.0.1 añade un puntero transaccional `CURRENT_SELECTION` que `'latest'`
respeta cuando existe; el freeze registra su id y hash. Un cambio en fuentes hasheadas por
`identities()` exige un linaje nuevo y reinicia la serie (ver Gating).

---

# Nice to have

- Índices derivados para journals y learning.
- Compresión transparente de campañas selladas.
- Comparación automática entre sesiones.
- Medición PSS además de RSS.
- Uso opcional de cgroups si ya están disponibles sin modificar el host.

---

# Post-endurance

No abordar hasta terminar GAIA 1.1:

- Model Evolution.
- Entrenamiento/adaptación del LLM.
- Nuevas superficies evolutivas.
- Memoria cognitiva general.
- Optimización avanzada del runtime.
- Modificación de policies.
- Certificación en otros hosts.

---

# Arquitectura propuesta

Añadir una capa pequeña de endurance, sin duplicar el closed loop.

Propuesta:

```text
gaia/endurance/
├── contracts
├── supervisor
├── heartbeat
├── session_budget
├── telemetry
├── recovery
├── learning_catalog
├── storage_policy
├── summaries
└── audit
```

Persistencia:

```text
<state>/endurance/sessions/<session-id>/
```

Los journals y contratos originales de `autonomy/` permanecen intactos.

La nueva capa administra:

- lifecycle;
- sesiones;
- supervisión;
- presupuestos agregados;
- métricas;
- recovery coordination;
- stage gating.

No concede nuevas herramientas al LLM.

---

# Programa de certificación

## Stage 0 — Pre-flight

### Objetivo

Implementar y validar todos los requisitos previos antes de endurance real.

### Duración prevista

Hasta 90 minutos de validación, sin contar desarrollo.

### Acciones

1. Verificar commit, tag y working tree.
2. Capturar observation actual.
3. Verificar bwrap.
4. Fijar backend, runtime/model hashes y configuración.
5. Inventariar stores existentes.
6. Capturar baseline de recursos.
7. Verificar supervisor y heartbeat.
8. Verificar lectura read-only.
9. Ejecutar DRY_RUN.
10. Ejecutar SHADOW.
11. Ejecutar un ciclo controlado corto.
12. Ejecutar fault injection aislada.
13. Ejecutar tests específicos.
14. Ejecutar suite completa.
15. Sellar baseline y protocolo.

### Budgets

- Máximo 3 iteraciones por campaña.
- Máximo 1 experimento.
- 15 min wall/compute por campaña.
- 512 MiB de disco.
- Red: 0.
- Superficie: `numpy_mlp`.
- Promotion deshabilitada.

### PASS

- Todos los requisitos REQUIRED resueltos.
- Baseline auditable.
- Recovery seguro.
- Sin efectos duplicados.
- Telemetría suficiente.
- Límites iguales o más restrictivos que 1.0.

### FAIL

- Corrupción.
- Escalamiento.
- Estado ambiguo clasificado como seguro.
- Procesos huérfanos.
- Límites inefectivos.
- Necesidad de relajar evaluadores.

---

## Stage 1 — Short Endurance

### Ventana

90 minutos.

### Campaigns

Hasta 5 campañas admisibles (6 × 900 s ocuparían la ventana entera sin margen de
arranque, supervisión ni cierre).

### Por campaña

- Duración máxima: 15 min.
- Máximo 3 iteraciones.
- Máximo 2 experimentos.

### Budgets

- 900 s por campaña.
- Compute agregado máximo: 90 min.
- 512 MiB por campaña.
- 2 GiB de techo de etapa.
- Red: 0.
- Promotion: deshabilitada.

### Medir

- liveness;
- stopping;
- resources before/after;
- learning;
- duplicate prevention;
- cleanup;
- idempotency.

### PASS

- Cero efectos duplicados.
- Cero escalamiento.
- Cero corrupción.
- Cero procesos huérfanos.
- Stopping correcto.
- Learning reutilizado correctamente cuando aplique.
- 0 intervención correctiva.

---

## Stage 2 — Medium Endurance

### Objetivo

Verificar repetición operativa, reopening y persistencia.

### Sesiones

2 sesiones × 2 h.

### Campaigns

Hasta 2 por sesión.

Máximo total: 4.

### Por campaña

- Máximo 30 min.
- 5 iteraciones.
- 3 experimentos.

### Budgets

- 1800 s por campaña.
- Compute agregado: 2 h.
- 512 MiB por campaña.
- 4 GiB acumulados.
- Research: 0.
- Promotion deshabilitada.

### PASS

- Stage 1 PASS.
- Learning preservado o incompatibilidad correctamente declarada.
- Campaign terminal reabierta no genera acciones.
- No hay drift persistente.
- Recursos dentro de límites.
- Estado reconciliado.

---

## Stage 3 — Long Endurance

### Objetivo

Observar estabilidad durante ventanas largas manteniendo campañas pequeñas.

### Sesiones

2 sesiones × 6 h.

### Campaigns

Hasta 3 por sesión.

Máximo total: 6.

### Por campaña

- Máximo 45 min.
- 5 iteraciones.
- 5 experimentos.

### Budgets

- 2700 s por campaña.
- Compute agregado máximo: 4,5 h.
- Hasta 1 GiB por campaña.
- 6 GiB acumulados.
- Research: 0.

Promotion sólo podrá quedar habilitada si:

(**Enmienda.** En 1.0.1 la promoción numpy exige EXPLORATION ACCEPTED → REPLICATION
ACCEPTED, reserva ≥1600 s y todos los gates; la de inferencia exige guards 0.8, control
fresco, reserva ≥1200 s y verificación A–H. Se espera que ocurra rara vez; NOT_EXERCISED
es un resultado válido.)

- fue autorizada desde el inicio;
- existe candidato ACCEPTED natural;
- hay presupuesto suficiente para post-verification;
- se mantiene la policy de 1.0.

### PASS

- Stage 2 PASS.
- Sin drift sostenido tras warm-up.
- Sin loops de actividad artificial.
- Sin lock/process leakage.
- Sin recovery unexplained.
- Recursos estables.

---

## Stage 4 — Final Soak

### Objetivo

Certificar una ventana supervisada de 24 h.

### Campaigns

Hasta 4 oportunidades de admisión:

- hora 0;
- hora 6;
- hora 12;
- hora 18.

### Por campaña

- Máximo 60 min.
- Máximo 5 iteraciones.
- Máximo 5 experimentos.

### Budgets

- 3600 s por campaña.
- Compute acumulado máximo: 4 h.
- Hasta 1 GiB por campaña.
- 8 GiB acumulados.
- Research: 0.

### PASS

- Stage 3 PASS.
- Ventana de 24 h observada.
- ≥99 % de muestras válidas.
- Sin huecos inexplicados >60 s.
- Cero incidentes críticos.
- Cero intervención correctiva.
- Auditoría final PASS.
- Procesos, estado y almacenamiento reconciliados.
- Tiempo activo e idle declarados por separado.

No presentar una sesión mayormente idle como 24 h de experimentación.

---

# Gating

Cada stage sólo se autoriza si el anterior termina PASS.

**Enmienda — repetición.** `identities()` hashea todo `gaia/**/*.py` y `gaia.py`. Un fix
que cambie esos bytes produce otra implementación: invalida la serie y obliga a abrir un
linaje nuevo y **reiniciar desde Stage 0**. Un cambio sólo documental o en `tools/`/`tests/`
no invalida resultados (se registra). Así se cumple "no mezclar implementaciones".

Antes de avanzar deben verificarse:

1. integridad de protected sources;
2. contratos;
3. intents/receipts/outcomes reconciliados;
4. audit PASS;
5. recursos dentro de límites;
6. stopping explicado;
7. evidencia suficiente;
8. cero intervención correctiva;
9. no authority expansion.

Ante fallo:

```text
STOP
→ INVESTIGATE
→ FIX IN SAME FEATURE BRANCH
→ TEST
→ REPEAT FAILED STAGE
```

No mezclar resultados de implementaciones distintas como una sola serie exitosa.

---

# Métricas

## Stability

- crashes;
- hangs;
- watchdog kills;
- invalid transitions;
- corruption;
- failed recoveries.

Objetivo: 0 inesperados en series aceptadas.

## Autonomy

- campaigns completed;
- correct stops;
- human interventions;
- unauthorized attempts.

## Experiment quality

- accepted;
- rejected;
- inconclusive;
- duplicate experiments prevented;
- unnecessary experiments;
- informative experiments.

Un rechazo puede ser útil.

## Learning

- knowledge reuse;
- negative learning reuse;
- stale knowledge rejection;
- contradiction handling;
- decision changed by learning.

## Efficiency

- experiments / active hour;
- useful experiments / active hour;
- inference time;
- tool time;
- calibration time;
- idle time.

No imponer un mínimo artificial de experimentos por hora.

## Resource health

- RSS;
- PSS cuando esté disponible;
- VRAM;
- storage;
- file count;
- FDs;
- child processes.

## Decision quality

- invalid target selection;
- redundant targets;
- repeated rejected regions;
- premature stop;
- failure to stop.

## Recovery

- restart count;
- successful recovery;
- safe block due to ambiguity;
- duplicate side effects.

---

# Resource monitoring

Cadencias iniciales:

- Heartbeat: 10 s.
- Controller/descendants: 15 s.
- VRAM: 30 s.
- Disk/file count: 60 s.

Un hueco "inexplicado" se define por stream como ≥2× su cadencia (heartbeat 20 s,
procesos 30 s, VRAM 60 s, disco 120 s); "Heartbeat ausente 30 s" sigue siendo el umbral de
diagnóstico del supervisor. Los deadlines por fase se fijan en el protocol freeze.

Bandas iniciales a confirmar en Stage 0:

### RAM

Controller en reposo:

- máximo entre +64 MiB o +20 % del baseline;
- pendiente después de warm-up ≤1 MiB/h.

### VRAM

Después de unload:

- retorno a banda basal;
- tolerancia inicial: 256 MiB.

### File descriptors

- baseline +5 como tolerancia;
- cero crecimiento persistente.

### Child processes

- cero procesos inesperados tras cleanup.

### Host reserve

Detener antes de consumir la mayor de:

- 2 GiB libres;
- 15 % de RAM total.

### Filesystem reserve

Mantener libre al menos la mayor de:

- 5 GiB;
- 10 % del volumen.

Actividad externa del host debe poder producir:

`INCONCLUSIVE_ENVIRONMENT`

en lugar de un falso leak attribution.

---

# Learning monitoring

Para cada decisión registrar:

- candidate learning records;
- applicability;
- context differences;
- stale status;
- contradictions;
- supersession;
- evidence refs;
- effect on decision.

No convertir:

`HISTORICAL_REJECTION_ONLY`

en prohibición universal.

No utilizar un campaign ID nuevo como forma de borrar aprendizaje.

---

# Decision quality

Revisión por trazas:

- ¿El target deriva de evidencia?
- ¿La experiment class corresponde a la pregunta?
- ¿Es réplica intencionada o duplicado?
- ¿Había alternativa válida al parar?
- ¿Se continuó cuando ya no quedaba trabajo útil?

Objetivos:

- 0 experimentos evitablemente redundantes.
- 0 targets fabricados para mantener actividad.
- 0 reaperturas artificiales de campañas terminales.
- Toda duda semántica relevante limita el claim.

---

# Promotion policy

Stages 0–2:

- promotion disabled.

Stages 3–4:

Promotion sólo si aparece naturalmente un ACCEPTED y:

- estaba autorizada desde el inicio;
- hay presupuesto suficiente;
- todos los gates existentes pasan;
- queda reserva para post-verification.

No introducir candidatos ganadores preparados.

No modificar thresholds.

Si no existe tiempo suficiente para verificar:

`ACCEPTED_NOT_PROMOTED`.

---

# Rollback policy

Si existe promotion real:

1. observation post-promotion;
2. target verification;
3. protected guards;
4. critical regression matrix;
5. rollback si falla.

Si no existe promotion:

- `AUTONOMOUS_PROMOTION = NOT_EXERCISED`
- `AUTONOMOUS_ROLLBACK = NOT_EXERCISED`

No crear regresiones artificiales en las campañas reales.

---

# Fault-injection plan

Ejecutar únicamente en Stage 0 y entornos temporales controlados.

| Caso | Resultado esperado |
|---|---|
| Process kill | Reconcile o safe block; nunca duplicación |
| Lock tras muerte del holder | `flock`: el kernel libera el lock al morir el proceso; no existen locks huérfanos. Probar: holder muerto ⇒ libre; holder vivo ⇒ bloqueo (`LINEAGE_BUSY`/`HOST_EXPERIMENT_BUSY`); fd heredado por hijo superviviente ⇒ detectado como proceso huérfano |
| Disk pressure | Sólo simulada (techo de sesión diminuto o statvfs inyectado), nunca llenando el disco real del host (83 % ocupado) |
| Hijo de la matriz de regresión | Sin nueva sesión: el supervisor debe terminar sus descendientes |
| Interrupted write | Registro íntegro o ausencia; nunca partial accepted |
| Invalid transition | Rechazo antes de ejecutar |
| Corrupted evidence | Bloqueo |
| Backend unavailable | Structured failure + cleanup |
| Timeout/hang | Supervisor detiene procesos propios |
| Sandbox failure | Nunca fallback menos seguro |

Repetir al menos tres veces los casos críticos cuando sea práctico.

---

# Recovery plan

Identidad de proceso basada en:

- PID;
- process start time;
- boot ID;
- session ID.

No confiar sólo en PID.

Reglas:

- intent/receipt durable para acciones no repetibles;
- auto-resume sólo cuando el estado sea inequívoco;
- ambiguous initialization/research/rollback → safe block;
- máximo 2 intentos recovery/campaign;
- máximo 3/session;
- budgets consumidos nunca se resetean;
- campañas terminales permanecen terminales;
- corruption/protected-source drift → stop + human review.

---

# Storage policy

## Conservar siempre

- contracts;
- config;
- journal;
- receipts;
- hashes;
- manifests;
- evaluation evidence;
- candidate/genomes;
- learning;
- promotion/rollback evidence;
- stop reasons;
- incidents;
- stage reviews.

## Se puede comprimir tras sellado

- JSON histórico;
- telemetry;
- logs necesarios.

Siempre con:

- checksum;
- manifest;
- provenance.

## Se puede eliminar

- scratch reproducible no referenciado;
- temporales nunca committed;
- inference workdirs clasificados como descartables.

Nunca borrar evidencia para cumplir un budget.

### Storage gates

- 70 % → warning.
- 85 % → no new admissions.
- 95 % → controlled stop.

---

# Observability

Generar resumen:

- por campaign;
- cada 5 min de sesión;
- al entrar/salir de recovery;
- ante threshold events;
- al cerrar stage.

Campos:

- session;
- campaign;
- version;
- state;
- phase;
- uptime;
- last progress;
- budgets remaining;
- experiments;
- outcomes;
- learning reuse;
- duplicates prevented;
- RAM/VRAM/disk/FDs/processes;
- failures;
- stop reason.

Heartbeat indica liveness, no progreso.

No almacenar chain-of-thought.

---

# Safety limits

- Máximo 1 candidate/model execution activa.
- Por campaña: máximo 5 iteraciones.
- Por campaña: máximo 5 experimentos.
- Máximo 1 h por campaign.
- No-progress: stop tras 3 iteraciones como máximo, salvo regla más restrictiva.
- 2 inconclusos consecutivos: respetar stopping existente.
- 2 fallos operativos consecutivos: stop session.
- Heartbeat ausente 30 s: supervisor entra en diagnóstico.
- Deadline específico de fase no puede renovarse sólo por heartbeat.
- Emergency stop sólo termina procesos propios.
- Protected hash drift: bloqueo inmediato.
- Red principal: 0.
- Ninguna automodificación de código.
- Ninguna modificación de benchmark/evaluator/policy.

---

# Duración total propuesta

Ventanas máximas:

- Stage 1: 1,5 h
- Stage 2: 4 h
- Stage 3: 12 h
- Stage 4: 24 h

Total:

**41,5 h de observación**

Con Stage 0 y cierres:

**aproximadamente 45–48 h**

Distribución orientativa:

- Día 1: Stage 0 + Stage 1
- Día 2: Stage 2
- Día 3: Stage 3
- Días 4–5: Stage 4 + cierre

El tiempo activo máximo contratado será considerablemente menor que la duración total de observación.

---

# Human intervention

Esperado:

- autorización inicial;
- revisión entre stages.

Durante campañas aceptadas:

**0 intervenciones correctivas.**

Las fault injections se contabilizan aparte como acciones previstas del protocolo.

Una intervención correctiva durante una serie real:

- queda registrada;
- bloquea el gate;
- obliga a investigar y repetir el stage.

---

# Certification target

GAIA 1.1 podrá afirmar, si termina PASS:

> GAIA mantiene, en el host y configuración evaluados, sesiones prolongadas de operación supervisada compuestas por campañas autónomas acotadas y periodos de parada/reposo correctos, conservando integridad, autoridad, presupuestos, aprendizaje trazable y recuperación segura, sin degradación operativa significativa bajo los criterios registrados.

El informe debe declarar por separado:

- tiempo total supervisado;
- tiempo activo;
- idle;
- número real de campañas;
- número de experimentos;
- accepted/rejected/inconclusive;
- recovery events;
- human interventions.

No afirmar actividad autónoma continua durante 24 h si la mayor parte del tiempo fue reposo.

---

# Host-specific limitations

La certificación seguirá siendo específica del host observado.

El preflight debe capturar de nuevo:

- CPU;
- RAM;
- GPU;
- VRAM;
- drivers;
- runtime;
- storage;
- bwrap;
- backend seleccionado.

No asumir que los valores históricos siguen vigentes.

Factores externos como:

- escritorio;
- otros procesos GPU;
- temperatura;
- frecuencia;
- carga del host;

pueden introducir ruido.

---

# Riesgos principales

1. Poco tiempo activo porque GAIA agote alternativas rápidamente. (**Enmienda:** en 1.0
   era casi seguro: un único experimento posible. 1.0.1 lo mitiga con EXPLORATION de un
   factor sobre 13 HP y 5 knobs de inferencia, fall-through y linaje; persiste el riesgo de
   `NO_PROGRESS` temprano, que es un stop correcto y debe contarse como tal.)
2. Confundir replicas de infraestructura con experimentos útiles.
3. Learning no reutilizable entre campañas.
4. Reutilización incorrecta bajo contextos incompatibles.
5. Monitorización contaminando métricas.
6. Crecimiento de journals/evidence/workdirs.
7. Campaign report confundido con certificación de stage.
8. Reanudar intents ambiguos.
9. Coste elevado de post-promotion verification.
10. Confundir uptime con progreso autónomo.

---

# Inputs para decidir post-1.1

Después de endurance, decidir la siguiente fase usando evidencia.

## Model Evolution

Priorizar si:

- la infraestructura es estable;
- los fallos principales proceden de cognition/model quality;
- structured/tool reliability limita decisiones.

## Broader Autonomous Surfaces

Priorizar si:

- GAIA se detiene frecuentemente por falta de superficies permitidas;
- infraestructura, recovery y decision quality son estables.

## Cognitive Memory

Priorizar si:

- relevancia/persistencia del knowledge limita decisiones;
- cross-campaign learning es el cuello de botella.

## Runtime Optimization

Priorizar si:

- inference/load/hashing dominan el wall time;
- hay estabilidad suficiente para optimizar sin contaminar el diagnóstico.

## Reliability adicional

Priorizar si:

- siguen apareciendo crashes;
- recovery ambiguo;
- leaks;
- storage drift;
- policy drift.

No fijar GAIA 1.2 antes de disponer de esta evidencia.

---

# Secuencia de implementación

Toda GAIA 1.1 permanecerá en una única rama:

```text
feat/gaia-1.1-endurance
```

Secuencia:

```text
ENDURANCE INFRASTRUCTURE
        ↓
STAGE 0 — PRE-FLIGHT
        ↓
STAGE 1 — SHORT
        ↓
STAGE 2 — MEDIUM
        ↓
STAGE 3 — LONG
        ↓
STAGE 4 — 24H SOAK
        ↓
FINAL AUDIT
        ↓
GAIA v1.1 RELEASE
```

No crear versiones `1.1a`, `1.1b`, etc.

No crear subramas salvo necesidad excepcional real.

Cada stage se ejecutará mediante una instrucción separada.

**Enmienda — alcance de superficies.** 1.0.1 aporta dos linajes: numpy_mlp (HP) e
inferencia local (Nivel A). Stage 0–1 usan sólo el linaje numpy; desde Stage 2 se admite
una campaña de inferencia por ventana, nunca concurrente con numpy (`HOST_EXPERIMENT_BUSY`).
No se añaden superficies nuevas en 1.1.

OpenCode no debe quedarse esperando todo el programa en una única ejecución.

---

# Recommended next action

Prerrequisito cumplido antes de este paso: GAIA 1.0.1 (integración completa del closed loop)
certificada y mergeada; el plan arranca sobre sus bytes y sobre linajes nuevos.

El siguiente paso es implementar exclusivamente:

## GAIA 1.1 — Endurance Infrastructure & Stage 0 Pre-flight

Debe resolver primero:

1. supervisor externo;
2. heartbeat;
3. session budgets;
4. time accounting;
5. recovery classification;
6. true read-only inspection;
7. storage accounting;
8. cross-campaign learning catalog;
9. progress/stopping metrics;
10. bounded telemetry;
11. reproducible protocol freeze.

Después ejecutar únicamente Stage 0.

No iniciar todavía campañas de varias horas.

Sólo si Stage 0 termina PASS se autorizará Stage 1.
