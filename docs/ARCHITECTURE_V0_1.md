# Arquitectura real de GAIA v0.1

Status: Current — CPU autonomous MVP; GPU/appliance frozen.

Este documento describe el código existente. No define ni implementa GAIA 0.2.
El comportamiento de referencia es la Prueba B certificada.

## RUNTIME CORE

- `gaia.py` llama primero a `gaia.bootstrap.dispatch()`: provisionamiento,
  selección del entorno/configuración y rutas GPU/appliance. Después, la CLI CPU
  carga `config`, `engine`, `readiness` y `report`. `--no-bootstrap` permite runtime
  manual; no omite requisitos certificables.
- `gaia/config.py` define el workload activo `numpy_mlp`, presupuesto, aceptación,
  stop, meta, research y readiness. `Engine` solo admite ese workload CPU.
- `gaia/engine.py` coordina baseline, campaña, propuestas, screening, confirmación
  y petición de publicación. No confundir inicializar una línea experimental con
  cargar un estado histórico. Un estado nuevo requiere inicialización explícita.
- `gaia/store.py` gestiona artefactos, CURRENT y lock. La existencia de `gaia.lock`
  no indica actividad: la exclusión la proporciona `flock`.

## EVOLUTION

`search.Strategy` usa su historial y RNG para proponer un genoma y operadores;
`genome`, `mutate` y `snippets` definen el espacio existente. `G.render()` produce
el `trainer.py` exacto del genoma. No se amplían operadores ni thresholds durante
la consolidación.

`research.py` y `meta.py` implementan investigación/ajuste internos existentes.
El estudio ON/OFF histórico Modo B no equivale a demostrar ventaja general de
ese mecanismo. Las propuestas de búsqueda normal conservan trazas observacionales
en `proposals/`, sin añadir draws al RNG de búsqueda.

## EVALUATION/SUPERVISION

El padre conserva tarea, benchmark y etiquetas de validación. El candidato recibe
el bundle mínimo necesario, no el estado ni el evaluador privado.
`protected/evaluator.py` utiliza `protected/sandbox.py`: bwrap obligatorio,
namespaces user/PID/net/IPC/UTS, mounts de solo lectura, trabajo y tmp privados,
entorno determinista y RLIMIT. El padre valida un handshake antes de cargar el
entrenador. No hay fallback CPU certificable a worker directo.

`readiness.run_gates()` evalúa:

| Gate | Responsabilidad CPU |
|---|---|
| G0 | Identidad, infraestructura, recovery y sandbox real |
| G1 | Genoma, render exacto, guard AST, corrección y carga del candidato |
| G2 | Salud, calidad, variabilidad, deriva y recursos del campeón CURRENT |
| G3 | Ledger, manifests, artefactos, lineage y publicación/rollback |
| G4 | Controles del evaluador, sin publicar variantes de control |
| G5 | Presupuesto certificado, overrides y capacidad |

Los gates se ejecutan al iniciar campaña y antes de cada experimento concreto.
Un fallo bloquea las etapas posteriores. `--skip-gate` y `--force` son rechazados.
El resultado se guarda en `campaigns/<uuid>/gates.json` y su `evidence.json`.

Screening y confirmación mantienen las semillas, pares intercalados, criterios de
calidad/RAM e intervalos existentes. Evaluar y aceptar no es publicar:
`readiness.pre_promotion()` vuelve a comprobar identidad, integridad, gates,
CURRENT, confirmación y head del ledger antes de solicitar publicación.

## EVIDENCE

### Procedencia y manifests

`provenance.py` crea una copia local inmutable en
`provenance/snapshots/src-000001/`, con fuentes CPU, dependencias declaradas,
configuración experimental y manifiesto SHA-256. El ID es local al estado; los
hashes identifican contenido. Git no participa en la identidad runtime.

`manifest.py` vincula baseline y experimentos con host, runtime, source, config y
política sandbox. La baseline vive en `stable/v0000/manifest.json`; los deltas de
experimento en `experiments/eNNNNN/`. Genoma, trainer, métricas, seeds/orden,
evidencia sandbox y decisión quedan enlazados por hashes. Cambios críticos no se
aceptan mediante refreeze: requieren una nueva línea experimental.

### Ledger, publicación y versiones

`ledger.py` mantiene el JSONL CPU canónico y encadenado, con secuencia, UUID,
previous hash, record hash y referencias a artefactos. La evidencia inmutable
precede al ledger. Es una cadena local no firmada, no un anclaje externo contra
la sustitución coordinada de toda la historia.

`Store.promote(..., context=engine)` aplica la política certificable CPU mediante
`publication.py`. `atomic_publish.py` realiza staging, fsync, validación, rename
sin sobrescritura y sustitución durable de CURRENT. Las versiones estables
contienen trainer, genome, manifest y evidence. CURRENT determina el campeón;
no se usa simplemente el mayor número de versión.

Recovery no adopta versiones por heurística ni borra staging ambiguo para obtener
PASS. Una publicación completa puede justificar recuperar su evento pendiente,
con las comprobaciones y marcas existentes.

### Rollback

`Engine.rollback(destino, motivo)` exige ancestro certificado y razón explícita,
adquiere el lock, valida lineage/entorno/evidencia/ledger y persiste un intent.
Después cambia CURRENT duramente y registra el evento encadenado. No borra ni
reescribe versiones. La recuperación del intent distingue commit/no commit y
bloquea estados ambiguos. El rollback CPU directo de Store está deshabilitado.

### Prueba A y Prueba B

- `certification.py`: A usa un par controlado en un estado independiente y el
  pipeline real. Certifica gates, evaluación, publicación, recarga y rollback;
  declara autonomía **false**. No es un hallazgo de Strategy.
- `autonomous_mvp.py`: B crea un estado independiente, congela presupuesto y llama
  una vez a `Engine.run()` normal. Verifica las trazas de `Strategy.propose()` con
  un RNG separado, sin someter las propuestas reproducidas a evaluación. Solo un
  ganador `search` promovido y verificado certifica autonomía. Después registra
  rollback real y evidencia final.

Los verificadores históricos inspeccionan evidencia guardada; ejecutar nuevamente
las entradas CLI A/B crea trabajo real distinto del hito conservado.
Véanse [evidencia](EVIDENCE_V0_1.md) y [política](CONSOLIDATION_POLICY.md).
