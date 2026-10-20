# Referencia funcional anterior al renombrado

Inspección: 2026-10-16. Inventario: `evidencia_renombrado/inventario_fase0.json`:
1785 archivos del proyecto/artefactos (incluidos ignorados), 15247 líneas con nombre
antiguo. Venvs y caché de herramientas se delimitan por raíz administrada, sin
inventariar bibliotecas de terceros como fuentes del proyecto. Lista exacta de
archivos, hashes y referencias por línea; limpieza delimitada en
`evidencia_renombrado/limpieza_delimitada_fase0.json`.

## Comprobaciones previas reales

- Python 3.14.4, GTX 1060 6GB, driver 580.178.04, VRAM usada 333 MiB al inspeccionar.
- `pgrep -af 'gaia.py|gaia.tinygpt|worker.py'`: sin procesos encontrados.
- `.gaia/venvs/tinygpt-cuda-pascal-6661fab15a7e6424/bin/python -m unittest discover -s tests`:
  **145 tests, 16.586 s, OK, sin skips**. ResourceWarning de archivos/subprocesos
  sin cerrar en evaluador CPU preexistente; fallos impresos por fixtures negativos
  esperados, no fallos de suite. Salida registrada por el harness de ejecución.
- Disco: 151 GiB disponibles; cada venv CUDA anterior ocupa aproximadamente 6.4 GiB.
- No hay repositorio Git en el workspace. Se conserva inventario con hashes como
  referencia anterior; no se declara diff respecto a un commit inexistente.

## Configuración y objetivo de reconstrucción

Referencia real `state_tinygpt_cuda_6661fab15a7e6424/`, configuración homónima en
`.gaia/configs/`: fp32, determinismo, cublas `:4096:8`, TF32 desactivado,
cudnn_benchmark=false, un hilo, RAM/VRAM 3000 MiB. Torch 2.14.0+cu126,
NumPy 2.3.5, GPU Pascal 6.1. Segundo entorno/config `8f2f14216f633444` es antiguo;
CPU/NumPy `6446deabc01ec4be` se conserva independiente.

Modelo: dim64, layers2, heads2, context64, dropout0; corpus byte-level sintético
congelado, arquitectura/optimizadores/espacio de búsqueda sin cambios funcionales.
Baseline CLI: 100 pasos, semilla 9000 repetida dos veces +9001. Laboratorio:
17 escenarios de causalidad, CE privada, determinismo, aislamiento bwrap/NVML,
errores, presupuestos, integridad, STOP y limpieza.

Benchmark v1: reference_steps100, max_steps300, eval_every25, hits_needed2,
quality_tolerance0.05; calibración 9000..9004, confirmación1000..1004,
auditoría5000..5005, controles4000..4004, screen_seed0. min_gain0.05,
memory_tolerance1.25, screen_slack1.3, max_cv0.2, max_warmup_ratio1.35,
max_drift0.35, min_resolvable_s0.06, min_slowdown1.02.
Objetivo histórico CE=0.2596790841227193; coste histórico 4.060995411 s;
hash baseline histórica `06d71da887527f3e9d586ccefe4a421d20cd5de85ba8b2735aeb6a4c8995cca4`.
No se copiarán tiempos, identidades ni confirmaciones a evidencia nueva.

G0 runtime/bwrap, G1 correctness sin skips, G2 fiabilidad/determinismo,
G3 integridad, G4 controles nulo/lento pareados, G5 presupuesto: todos OK en
readiness histórico. Campeón **v0000**, sin promoción demostrada; conservar
integridad de versiones/ledger y recuperación. Reconstrucción prevista:
prepare --minutes15; run --max-experiments1 --minutes15 (promoción no exigida).

Observación: --steps100, tres referencias y perfilado numéricamente idénticos.
Investigación: --minutes10, hipótesis foreach optimizador/clipping, cotas Amdahl,
memoria por campeón; no se exige veredicto positivo ni desbloqueo artificial.
Metaestudio v1: periodic_tune y counter_holdout, catálogo baseline+ocho cambios,
3 semillas/modelo/tarea, 60 trials totales, 4 consultas y 90 s virtuales,
20 semillas de ajuste100..119, 40 holdout500..539. Estrategia histórica v1
adoptada (ucb_c1,p_global0.1,small_model_prior0.3), **holdout histórico consumido**
en `meta_gpu_v1/completed.json`. La identidad nueva exige estudio nuevo una vez;
no se exigirá adopción ni se repetirá para obtener resultado favorable.

Documentos de referencia: validaciones CUDA 0.1 y TinyGPT fases 1–8; artefactos
reales benchmark/readiness/strategy/completed y reportes enlazados en ellos.
Activos legacy y capacidades futuras: `TRANSICION_LEGACY_V0.md`.

## Limpieza autorizable solo tras fase 5

Raíces de estado antiguas inventariadas; dos venvs CUDA, configs 6661/8f2f y sus
marcadores internos; informes afectados deben revisarse por workload (lista exacta
en JSON). Reservado `state_tinygpt_cuda/README.md` se trasladará a ruta nueva.
Cachés Python antiguas son regenerables; caché compartida/bootstrap y reportes
CPU/mixtos se conservan salvo clasificación específica. Legacy: retirar solo
tras verificación del manifiesto. No borrar `state/`, `demo_evidence/`, ni NumPy.
