# Informe de GAIA

**Línea base** (v0000): coste hasta objetivo **0.6489 s** (calidad objetivo 0.7126; variabilidad entre repeticiones CV=2.9%).

**Experimentos:** 121 · rejected: 102, deferred: 13, accepted: 6

**Coste total de búsqueda:** 210 s (3.5 min).

## Mejoras verificadas (versiones estables)

- **v0001** · coste 0.801x del anterior (IC95% sup. 0.911, 9 pares) · RAM 0.999x · procedencia **known** · sgd/relu/float64/fused/randint h64x2 b64 lr0.08292 · cambios vs anterior:  · tras 6 experimentos
- **v0002** · coste 0.344x del anterior (IC95% sup. 0.366, 4 pares) · RAM 1.096x · procedencia **known** · momentum/tanh/float64/fused/randint h96x2 b64 lr0.01504 · cambios vs anterior:  · tras 10 experimentos
- **v0003** · coste 0.634x del anterior (IC95% sup. 0.926, 5 pares) · RAM 1.0x · procedencia **generated** · momentum/tanh/float64/fused/randint h96x2 b64 lr0.01504 lits=1 · cambios vs anterior:  · tras 3 experimentos
- **v0004** · coste 0.868x del anterior (IC95% sup. 0.933, 10 pares) · RAM 1.0x · procedencia **generated** · momentum/tanh/float64/fused/randint h96x2 b64 lr0.01504 lits=1 drop=loss,wd · cambios vs anterior:  · tras 11 experimentos
- **v0005** · coste 0.681x del anterior (IC95% sup. 0.917, 10 pares) · RAM 0.952x · procedencia **generated** · momentum/tanh/float32/fused/permutation h96x2 b128 lr0.01474 drop=clip · cambios vs anterior:  · tras 30 experimentos
- **v0006** · coste 0.477x del anterior (IC95% sup. 0.589, 5 pares) · RAM 0.834x · procedencia **known** · momentum/tanh/float64/fused/permutation h32x1 b64 lr0.01504 · cambios vs anterior:  · tras 37 experimentos

> Procedencia `known`: técnica conocida elegida por la búsqueda; NO es un descubrimiento autónomo. Solo `generated` (mutaciones de código propias) podría serlo, y únicamente si la auditoría la confirma.

## Auditoría independiente (semillas nunca usadas para seleccionar)

- tarea `main`: línea base 0.5266 s → v0006 0.0332 s · cociente 0.0609 · decisión **accepted** (coste 0.061x del campeón (límite sup. IC95% 0.091 < 0.95))
- tarea `audit`: línea base 0.4428 s → v0006 0.0311 s · cociente 0.0775 · decisión **accepted** (coste 0.077x del campeón (límite sup. IC95% 0.094 < 0.95))

## Frontera de Pareto (tiempo hasta objetivo, RAM máx.), cribado

- 0.03 s · 46.1 MB

## Qué operadores funcionan (aprendizaje del historial)

| operador | intentos | alcanzan objetivo | llegan a confirmación o mejor |
|---|---|---|---|
| random_global | 45 | 2 | 2 |
| crossover | 15 | 7 | 4 |
| hidden | 9 | 5 | 2 |
| init_scale | 9 | 5 | 1 |
| lit | 9 | 5 | 3 |
| drop | 9 | 8 | 5 |
| lr | 8 | 4 | 2 |
| dtype | 8 | 6 | 1 |
| wd | 7 | 6 | 2 |
| depth | 6 | 1 | 1 |
| backward | 6 | 5 | 1 |
| optimizer | 6 | 0 | 0 |
| warm | 6 | 4 | 1 |
| act | 6 | 0 | 0 |
| momentum | 6 | 2 | 0 |
| beta2 | 6 | 2 | 0 |
| horizon | 6 | 4 | 2 |
| sched | 5 | 0 | 0 |
| sampler | 5 | 4 | 2 |
| beta1 | 5 | 3 | 0 |
| batch | 4 | 2 | 0 |
| clip | 3 | 1 | 1 |
| undrop | 2 | 0 | 0 |
| reset_lit | 2 | 1 | 1 |

## Metaoptimización (Nivel 4)

Estrategia actual: v2 · 6 variantes evaluadas, 2 adoptadas.

## Verificación de la mejora recursiva (Nivel 5)

- actual_vs_v0: Δ AUC log-coste 0.0199 IC90% [-0.2644, 0.3078] → **SIN DIFERENCIA CONCLUYENTE** (evals hasta -20%: 3.3 → 3.1; 10 semillas)
- v0_adaptativa_vs_aleatoria: Δ AUC log-coste 0.1542 IC90% [-0.2303, 0.5551] → **SIN DIFERENCIA CONCLUYENTE** (evals hasta -20%: 3.7 → 3.3; 10 semillas)
- v0_adaptativa_vs_mutacion_uniforme: Δ AUC log-coste 0.0342 IC90% [-0.095, 0.1777] → **SIN DIFERENCIA CONCLUYENTE** (evals hasta -20%: 3 → 3.3; 10 semillas)

## Límites conocidos

- Tarea sintética en CPU (NumPy); no demuestra nada sobre LLM ni GPU.
- El aislamiento es por proceso y límites de recursos, no un sandbox de seguridad.
- Energía solo si el sistema expone RAPL; si no, no se mide.
- El paisaje de metaoptimización congela mediciones de tiempo (con ruido); por eso la verificación usa una tarea distinta.
