# Evidencia de Fase 1: TinyGPT base en CUDA

> Evidencia histórica del 15-10-2026, anterior al renombrado. Nombres, comandos,
> rutas y mediciones del cuerpo son los originales; no son nuevas ejecuciones de
> GaiaTransformer. Evidencia nueva: `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Fecha: 15-10-2026. Resultado: **TINYGPT_BASELINE_READY**.

## Implementación

- `gaia/tinygpt/data.py`, `corpus_v1.json`: corpus determinista versionado.
- `gaia/tinygpt/model.py`: embeddings de bytes/posición, dos bloques pre-LN,
  atención multihead causal explícita, MLP GELU y head ligado al embedding.
- `gaia/tinygpt/trainer.py`: muestreador privado, AdamW fijo y predicción sin targets.
- `gaia/tinygpt/baseline_worker.py`: entrenamiento de confianza en un proceso CUDA nuevo.
- `gaia/tinygpt/phase1.py`: orquestación, targets privados, métricas y repetibilidad.

Baseline fp32/eager, sin Flash Attention ni compilación: **120576 parámetros**,
`D=64, L=2, H=2, T=64, B=32`, dropout 0, AdamW lr 0.003, weight decay 0.01,
betas 0.9/0.999, eps 1e-8, clipping 1.0, foreach/fused desactivados. Se mantienen
los flags deterministas, CUBLAS workspace y GPU por UUID del perfil Pascal.

## Ejecución reproducible

```bash
python3 gaia.py tinygpt-baseline
```

El comando aprovisiona/reutiliza el entorno CUDA, valida la plataforma, ejecuta
los tests de modelo y lanza tres procesos nuevos bajo `-I` con entorno mínimo:
dos con semilla 9000, uno con 9001. Cada trial entrena 100 pasos y produce logits
privados al paso 0, 25, 50, 75 y 100. La pérdida se calcula solo en el padre.

Se rechaza el cierre si el corpus difiere del manifiesto, cambia el runtime,
se excede un presupuesto, aparecen no finitos, no baja la pérdida train y privada,
o la repetición cambia pesos, gradientes, logits o cualquier pérdida registrada.
Otra semilla debe producir pesos distintos y también reducir ambas pérdidas.

## Resultados en GTX 1060 6 GiB

Torch 2.14.0+cu126, Python 3.14.4, driver 580.178.04, entorno local de Fase 0.1.
Corpus `structured_bytes/v1`, digest conjunto
`11d89e90478527ba77648d5a45be459c55133e12bb1b4463adf3901cb5d44285`.

| Trial | Semilla | Train media primeros/últimos 10 pasos | Validación inicial/final | Wall del worker |
|---|---:|---|---|---:|
| 0 | 9000 | 4.351239 → 0.473495 | 5.537448 → 0.072185 | 3.511 s |
| 1 | 9000 | 4.351239 → 0.473495 | 5.537448 → 0.072185 | 3.500 s |
| 2 | 9001 | 4.350847 → 0.647214 | 5.529156 → 0.171169 | 3.585 s |

Las métricas de wall son diagnósticas, no el coste de promoción de un benchmark.
Incluyen importación/inicialización, entrenamiento y evaluaciones del worker;
el informe desglosa las fases sincronizadas. El límite de 20 s se cumplió en
los tres procesos. Pico RSS máximo: 1447.52 MiB. Pico reservado por el allocator
Torch: 100 MiB (no incluye toda la VRAM de contexto/driver).

Dos repeticiones de semilla 9000 idénticas bit a bit:

- Estado final: `22abc08ccebecc8d1684529377fedcce8b8f086612ab268afc455e37d934aec4`.
- Gradiente final: `88477f9a9fd5b42c007e220ca0b8614a34892586bb88f20772477b545c12b2bb`.
- Logits privados del paso 100:
  `faa2ea4e25f7372d8d4bf914545b3d0afc2c89c1030248dc48580ac17c4f4027`.

Los pesos de semilla 9001 son distintos:
`72369d764efd14875bb49a854ce31888fedd5810a156641dc26aab336f6836ee`.

## Tests y regresiones

- Suite NumPy: **84 tests descubiertos**, 77 ejecutados sin fallos y 7 omitidos
  porque ese entorno no instala Torch.
- Esos **7 tests de modelo pasaron en el perfil Torch/CUDA**, incluido el caso de
  causalidad GPU: cambiar tokens futuros no altera los logits de su prefijo.
- También se verificaron formas, gradientes finitos, pesos ligados, independencia
  de logits respecto a targets, separación de registros, serialización sin la
  columna privada, CE estable y rechazo de resultados inválidos.
- El digest del corpus coincide en un proceso aislado `-I -S` sin paquetes externos.
- Se corrigió una fuga de alcance de `GAIA_LOCAL_CONFIG`: ahora se usa únicamente
  para la raíz del proyecto propietaria de `.gaia/configs/`. Una configuración
  local no se propaga a otros proyectos o raíces temporales. Hay prueba de regresión.

## Evidencia local

- `.gaia/reports/20261015T160041Z-8491cb10/REPORT.md`: ejecución final completa.
- En su subdirectorio `phase1/`: `corpus.json`, `result.json`, resultados de cada
  trial y logs stdout/stderr. El resultado agregado incluye hashes del código,
  runtime, configuración, curvas, pesos, gradientes y logits.
- `.gaia/reports/20261015T160508Z-ddf5f913/REPORT.md`: suite completa final.

Los inputs y logits temporales se eliminan al terminar cada trial. Los targets
de validación permanecen en memoria del padre, no en archivos del worker.

## Alcance del cierre

Hay una baseline entrenable, evaluable y reproducible. No hay búsqueda, promoción,
benchmark calibrado ni campaña TinyGPT; `Store` sigue reservado al motor MLP.
El siguiente paso es Fase 2: protocolo/evaluador de candidatos GPU, guard,
aislamiento y supervisión completa de recursos. Las puertas G0-G5 de ese workload
y la calibración multisemilla todavía no están cerradas. El corpus es deliberadamente
sencillo; estas pérdidas no demuestran mejoras sobre lenguaje natural ni LLM.
