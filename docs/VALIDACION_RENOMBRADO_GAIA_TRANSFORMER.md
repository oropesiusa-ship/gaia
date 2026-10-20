# Validación nueva del renombrado GaiaTransformer

**Estado final: COMPLETADO, fases 0–6 OK, 2026-10-16.**

Inicio: 2026-10-16. Registro por fases y puertas:
[plan de ejecución](PLAN_RENOMBRADO_GAIA_TRANSFORMER.md).
Referencia previa: [inventario y parámetros](REFERENCIA_RENOMBRADO_GAIA_TRANSFORMER.md).
Las validaciones fechadas 15-10-2026 son evidencia histórica de la identidad
anterior; no representan ejecuciones nuevas ni adopciones bajo GaiaTransformer.

## Fases 0–2

- Inventario por archivo/hash y limpieza delimitada: `evidencia_renombrado/`.
- Corpus del prototipo copiado y comparado byte a byte en
  `../archives/text_prototype/sample_corpus.txt`; SHA-256 del manifiesto confirmado.
- Suite previa: 145 OK sin skips, 16.586 s.
- Suite tras renombrado: 145 OK sin skips, 17.093 s, runtime Torch existente.
- Imports, clase, renderizado, protocolo, perfil, comandos y tests renombrados.
- `evidencia_renombrado/fase2_checks.json` y sus 22 logs contienen comprobaciones
  CLI y suite completa, sin skips. Lockfile byte a byte idéntico al anterior.
- `fase1_identidad_sin_cambios_algoritmicos.json`: inversión del renombrado y hashes
  originales coincidentes para todas las fuentes, tests y configuración.
- Enlaces Markdown locales verificados; excepciones históricas en el plan.

## Reconstrucción experimental

### Fase 3: plataforma, baseline y laboratorio — OK

Venv/config nuevos: huella `df1f7863934daabc`, perfil `gaia-transformer-cuda-pascal`.
Torch 2.14.0+cu126, NumPy 2.3.5, Python 3.14.4, GTX 1060 6GB.
Los cuatro comandos prescritos pasan; instalación nueva verificada con hashes.

| Ejecución | Informe bajo `.gaia/reports/` | Resultado |
|---|---|---|
| bootstrap | `20261016T074444Z-8b56c232/` | CUDA_ENVIRONMENT_READY |
| doctor | `20261016T074619Z-7a73545b/` | CUDA_ENVIRONMENT_READY |
| baseline | `20261016T074630Z-13d974fc/phase1/result.json` | GAIA_TRANSFORMER_BASELINE_READY, tres trials reproducibles |
| lab | `20261016T074658Z-98db08bf/phase2/result.json` | GPU_LAB_READY, 17/17 |

Baseline: semilla 9000 validación 5.5374→0.0722 (dos resultados idénticos),
9001 5.5292→0.1712. Corpus digest
`11d89e90478527ba77648d5a45be459c55133e12bb1b4463adf3901cb5d44285`.
Modelo 9 tests (causalidad CPU/CUDA), lab 13 tests, suite completa 145 tests:
todos OK, **sin skips en runtime nuevo**. Bwrap, telemetría NVML, pérdida privada,
integridad, STOP y fallos deliberados pasan sin rebajar límites.

### Fase 4: benchmark, campaña y recuperación — OK

Estado: `state_gaia_transformer_cuda_df1f7863934daabc/`, independiente del previo.
Benchmark: `.gaia/reports/20261016T074910Z-76ced823/phase3/result.json`, 71 trials,
coste de referencia **4.019073079005466 s**, target CE **0.2596790841227193**.
La CE coincide con la histórica por determinismo; los tiempos son mediciones nuevas.
Hash de fuente nueva: `d0b32da1824bee59bf942d85f707dc8710247f4c0ce52afcdb2dc7a0125cad9a`.

Prepare (26 trials): `20261016T075534Z-9c325f3c/campaign/result.json`.
Run de un experimento/15 minutos (38 trials):
`20261016T075821Z-4c8a0867/campaign/result.json`. G0–G5 correctos, sin skips;
lr 0.003→0.006 rechazado después de cinco pares reales, **cero promociones**.

Recuperación real: `evidencia_renombrado/recuperacion_fase4/result.json`:
SIGKILL de campaña hija tras start de e00002; recuperado aborted, próximo ID3,
campeón v0000 conservado, limpieza de temporal e idempotencia verificadas.
Auditoría `integridad_fase4.json`: 8 eventos, IDs únicos/cerrados, versiones
renderizadas y benchmark/runtime/fuentes verificados; directorio temporal vacío.

### Fase 5: observación, investigación y metaestudio — OK

Observe --steps100: `.gaia/reports/20261016T080610Z-5e8f6c5e/observation/`.
Paridad de hashes/pérdidas/logits entre entrenamientos normales y perfilado;
optimizador dominante, sobrecarga 1.13x, GPU_OBSERVATION_READY.

Research --minutes10: `20261016T080635Z-85f84ea0/research/`.
12 trials de contraste, optimizer_foreach **inconclusive**, clip_foreach **pruned**;
sin desbloqueos ni promoción. Diferencia con histórico: mediciones de tiempo y
cotas locales nuevas; se mantiene resultado sin repetir buscando aceptación.

Meta: `20261016T080758Z-b50b1272/meta/`, **60 trials nuevos**. Separación
periodic_tune/counter_holdout, selección persistida antes de medir holdout;
4 consultas/90 s virtuales por replay, 20 semillas ajuste y 40 reservadas.
Resultado **verified_transfer_on_cached_tasks**, adopción v1
`{ucb_c:1.0,p_global:0.1,small_model_prior:0.3}`.

| Comparación | ΔAUC media | Límite superior | Favorable (<−0.01) |
|---|---:|---:|---|
| Ajuste v1−v0 | −0.06137077 | −0.02785612 | Sí |
| Holdout v1−v0 | −0.05730434 | −0.04651426 | Sí |
| Holdout v1−azar | −0.06412629 | −0.05138532 | Sí |

Conclusión limitada al catálogo y paisajes medidos; no implica acelerar al campeón,
ni transferencia universal. Calidad fallida de lr0.006 en holdout penalizada,
sin reinterpretarla como solución rápida válida.

`integridad_fase5.json`: estrategia recalculada/cargada, completed/selection/ledger
no alterados al verificar rechazo de reutilización. **Holdout nuevo consumido**,
digest `5ea0c743ad926fdf53ac6b33de5d2b94b43d2a76600e2d790fa4742b646c38aa`.
Prepare posterior `20261016T081402Z-47ef5fb8/campaign/`: READY_FOR_CAMPAIGN,
G0–G5 y 26 trials OK con estrategia adoptada. Campeón continúa v0000.

### Fase 6: retirada y validación final — OK

Se retiraron **38 raíces de artefactos delimitadas**:

- `state_tinygpt_cuda/` (README trasladado) y `state_tinygpt_cuda_6661fab15a7e6424/`.
- Venvs anteriores `tinygpt-cuda-pascal-6661fab15a7e6424` y
  `tinygpt-cuda-pascal-8f2f14216f633444`, incluidos marcadores internos.
- Configuraciones `6661fab15a7e6424.json` y `8f2f14216f633444.json`.
- **22 informes exclusivos del workload anterior**, incluidos dos ensayos históricos
  de recuperación. **13 informes CPU/mixtos preservados** tras revisión individual.
- Dos directorios de bytecode del paquete anterior y ocho bytecodes de tests.

Relación exacta por raíz, archivo y hash (salvo bibliotecas instaladas de terceros,
delimitadas por raíz de venv): `evidencia_renombrado/limpieza_fase6_aplicada.json`.
`legacy_v0/`: retirados sus **12 archivos** y directorios, hashes en inventario
de fase 0, decisiones/destinos en `TRANSICION_LEGACY_V0.md`. Corpus de 24120 bytes
preservado y verificado; no existían checkpoints ni historial.
`state/`, estado NumPy, demo_evidence, entorno/config CPU y caché compartida
de bootstrap conservados. **178 archivos preservados comprobados por SHA-256**.

Validaciones posteriores a la eliminación:

| Comprobación | Evidencia | Resultado |
|---|---|---|
| Suite final, Torch/CUDA nuevo | `evidencia_renombrado/fase6_check_21.log` | **145 OK, 16.902 s, sin skips** |
| Ayuda/argumentos de ocho comandos | `evidencia_renombrado/fase6_checks.json` | Todos los códigos esperados |
| Doctor perfil nuevo | `.gaia/reports/20261016T082001Z-115f4c7f/` | CUDA_ENVIRONMENT_READY |
| Identidad, baseline, fuentes, versiones, ledger | `evidencia_renombrado/integridad_fase6.json` | STATE_INTEGRITY_OK, 17 eventos |
| Política de búsqueda y holdout | Mismo informe de integridad | Estrategia v1 verificada, reutilización rechazada sin mediciones |
| Preservación CPU/corpus y limpieza delimitada | Mismo informe | 178 hashes coincidentes; raíces antiguas ausentes |

Los comandos experimentales no se repitieron tras limpiar; no se volvió a medir
ni ajustar el holdout. El import antiguo ya no existe; no hay archivos con nombre
antiguo ni referencias antiguas en fuentes/tests activos.

## Incidencias, diferencias y pendientes

- Una aserción de la **utilidad documental de limpieza** detectó que dos informes
  históricos no tenían campo identity. Se detuvo antes de borrar, se inspeccionaron
  runtime/G3 reales y se corrigió la clasificación; la ejecución posterior pasó.
  No se modificaron contratos experimentales para conseguir aceptación.
- ResourceWarning de recursos sin cerrar del evaluador CPU: observados ya en
  la suite previa y también en la final. No producen fallos; registrados como
  comportamiento preexistente, fuera del renombrado mecánico.
- El coste medido nuevo difiere del histórico (4.019073079 s frente a 4.060995411 s);
  no se atribuye mejora causal a renombrar. La CE y el aprendizaje reproducen
  resultados por determinismo; hashes de identidad/renderizado son nuevos.
- La investigación mantiene un resultado inconcluso y otro podado. No se intentó
  forzar un desbloqueo. La adopción de metaestrategia sí tiene evidencia nueva;
  sus contrastes difieren de los históricos porque usan tiempos nuevos.
- **Sin bloqueos pendientes ni intervención humana requerida.** F0 del plan maestro
  cerrada. Lenguaje, checkpoints, tokenización entrenable y generación siguen
  pendientes de F4/F5 con contratos/pruebas en el manifiesto de transición.

## Rutas definitivas y uso

- Paquete/clase: `gaia.gaia_transformer` / `GaiaTransformer`.
- Perfil: `gaia-transformer-cuda-pascal`; workload `gaia_transformer_cuda`;
  contrato `gaia_transformer_cuda/v1.1`.
- Lockfile: `requirements/gaia-transformer-cuda-pascal-py314.lock`.
- Runtime: `.gaia/venvs/gaia-transformer-cuda-pascal-df1f7863934daabc/`.
- Config: `.gaia/configs/df1f7863934daabc.json`.
- Estado: `state_gaia_transformer_cuda_df1f7863934daabc/`.
- Reservado: `state_gaia_transformer_cuda/README.md`.
- Corpus histórico neutral: `archives/text_prototype/sample_corpus.txt`.
- Evidencia nueva experimental: informes del 16-10-2026 citados arriba;
  inventarios, comandos, logs, limpieza y auditorías en `docs/evidencia_renombrado/`.

```bash
python3 gaia.py doctor --profile gaia-transformer-cuda-pascal
python3 gaia.py gaia-transformer-run --max-experiments 1 --minutes 15
python3 gaia.py gaia-transformer-observe --steps 100
```

El metaestudio de esta identidad ya está completado; su holdout está consumido.
Para otra investigación se requieren nuevas tareas/protocolo, sin borrar registros.
