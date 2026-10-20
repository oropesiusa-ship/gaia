# Estado reservado para GaiaTransformer/CUDA

Este directorio está reservado por `docs/CONTRATO_GAIA_TRANSFORMER_CUDA_V1.md`.

No contiene una campaña inicializada, baseline ni benchmark. Es independiente de
`state/`, que conserva el historial del workload MLP/CPU.

Las campañas locales usan el espacio `state_gaia_transformer_cuda_<huella>/`
con contrato `gaia_transformer_cuda/v1.1`. Bootstrap solo aprovisiona y valida
el entorno CUDA bajo `.gaia/`; no crea una campaña.

`python3 gaia.py gaia-transformer-baseline` entrena y evalúa la baseline
en procesos nuevos y guarda evidencia en `.gaia/reports/`, sin inicializar
este directorio reservado.

`python3 gaia.py gaia-transformer-lab` verifica trials GPU aislados y
manejo de errores, también bajo `.gaia/reports/`. Su resultado `GPU_LAB_READY`
no inicializa este estado ni sustituye la calibración. Ver
`docs/VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Benchmark y baseline nuevos congelados en el estado local
`state_gaia_transformer_cuda_df1f7863934daabc/`, independiente de este reservado.

El estado local tiene campeón `v0000`, un rechazo confirmado y un ensayo
interrumpido recuperado como aborted. `gaia-transformer-prepare` verifica G0-G5
y `gaia-transformer-run` ejecuta la campaña GPU.

`gaia-transformer-observe` escribe perfiles y diagnósticos en los informes
y eventos `observation` en el ledger local. No cambia campeón ni calibración.
Ver `docs/VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

La investigación registra `research_start`, `research_end` y `research_trigger` en el
ledger local. Los contrastes reales quedaron inconclusos/podados y no
desbloquearon opciones; el campeón continúa en `v0000`. Ver
`docs/VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

El metaestudio guardó `strategy_gpu.json` y el registro `meta_gpu_v1/` en el estado
local. Se adoptó una política de búsqueda v1 tras un estudio acotado de transferencia
en paisajes cacheados; el modelo campeón sigue en `v0000`. El holdout consumido no
se reutiliza para nuevas selecciones. Ver `docs/VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.
