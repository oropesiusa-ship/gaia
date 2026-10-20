# Fase 8: metaestrategia y prueba de transferencia acotada

> Evidencia histórica TinyGPT anterior al renombrado. Los comandos, rutas y
> mediciones originales no son ejecuciones nuevas de GaiaTransformer.
> Evidencia nueva: `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Fecha: 15-10-2026. Resultado: **GPU_META_COMPLETE**;
`verified_transfer_on_cached_tasks`, estrategia de búsqueda **v1 adoptada**.

Este resultado demuestra una ventaja de ordenación de búsqueda en los dos
paisajes medidos y el catálogo fijado. No demuestra mejora recursiva general,
ni una aceleración del modelo campeón, ni eficacia garantizada en el espacio
completo de genomas. El campeón permanece en **v0000**.

## Protocolo fijado antes de medir

`tinygpt_meta/v1`, digest:
`39d24b324cd70c25641621fdd92b59aa45b16302e3c70573b9c4c71bf747edc4`.

Componentes:

- `metastudy.py`: protocolo, caché, replay, selección y holdout.
- `meta_tasks.py`, `meta_tasks_v1.json`: tareas/digests y binding de laboratorio.
- `search_strategy.py`: selector UCB parametrizado y carga verificada.
- `genome.py`: utiliza el selector compartido en las propuestas de campaña.
- `tests/test_tinygpt_metastudy.py`: diez pruebas de datos, separación, presupuestos,
  decisiones, reanudación e integración CLI.

El catálogo contiene baseline y ocho cambios individuales conocidos: lr 0.001,
lr 0.006, batch 16, batch 64, dimensión 32, una capa, cuatro heads y weight_decay 0.
No incluye variantes foreach: la investigación previa no las desbloqueó.

Se comparan cuatro ajustes de `ucb_c`, `p_global` y `small_model_prior`, todos
definidos antes del experimento. El último parámetro prioriza explorar las
familias dimensión/capas; en la campaña completa no fuerza por sí solo una
dimensión menor. Las políticas son heurísticas conocidas, no algoritmos nuevos
descubiertos por generación abierta de código.

## Tareas distintas y protección de producción

| Tarea | Regla | Semillas de modelo |
|---|---|---|
| periodic_tune | Patrones arbitrarios repetidos de períodos 2/4/8 | 11000..11002 |
| counter_holdout | Progresión modular sobre 16 símbolos, incremento 1/3/5/7 | 21000..21002 |

La segunda tarea no es un simple cambio de semilla del mismo generador. Cada
registro tiene prefijo de dominio/índice y 55 símbolos de cuerpo. En holdout, el
inicio y el incremento se derivan de SHA-256 de
`counter_bytes/v1|<split>|<seed>|<index>`, con semillas 5101 train y 6203 validation,
dominios M/N, 4096 registros train y 256 de validación. El vocabulario y contexto
del modelo siguen siendo 256 bytes y 64 posiciones.

Manifestaciones congeladas:

- Ajuste: `bbab09a6815715b1f08ae59fce88f204968761f7e176017f93ceb3fa853f9d4f`.
- Holdout: `8c42b5dee0ad43f44f653f23cf514f0abba56a6c190e2ddef691262c7ee559a7`.

Para no invalidar la calibración de producción se crea una función con el
**mismo objeto de bytecode de `run_trial`** y un diccionario de globals propio
cuyo binding de datos/identidad pertenece a la tarea del estudio. No se parchean
los globals del evaluador original ni se modifican sus archivos. Worker, guard,
sandbox bwrap, NVML, coste y CE privada se reutilizan sin cambios. La identidad
experimental añade tareas, protocolo y fuentes del estudio; no se presenta como
la identidad de la campaña original. Los targets siguen solo en el padre.

## Materialización GPU: 60 trials

Cada tarea consume tres referencias baseline de 100 pasos y nueve genomas por
tres semillas con máximo 300 pasos, evaluación cada 25 y dos logros sostenidos.
Total: **30 trials por tarea, 60 en la GTX 1060**, con sus datos crudos y fallos
de calidad conservados. Se alterna el orden del catálogo entre semillas.

Objetivos de estudio, fijados como peor referencia +0.05 antes de evaluar variantes:

- periodic_tune: CE <= **0.2302009383**.
- counter_holdout: CE <= **0.6124518824**.

El objetivo de producción **0.2596790841** se conserva. Estas calibraciones de
estudio usan tres semillas y no constituyen confirmaciones de promoción de modelos.

La fitness de un genoma es la mediana de sus tres costes solo si alcanza calidad
en todos. De lo contrario recibe penalización 20 s. El modelo lr 0.006 no alcanzó
calidad en ninguna de las tres semillas de holdout y fue penalizado; no se trató
como una alternativa rápida válida. Las otras variantes alcanzaron calidad.

Medianas ilustrativas:

| Variante | Ajuste | Holdout |
|---|---:|---:|
| Baseline | 4.074800 s | 4.102315 s |
| Una capa | 3.623725 s | 3.857504 s |
| Dimensión 32 | 5.270783 s | 5.106127 s |

Estos valores son fitness de paisaje, **no una promoción**: no hay cinco pares
intercalados con aceptación del candidato de campaña en esta medición.

## Presupuesto y puntuación de estrategias

Cada replay conoce la baseline, pero solo revela fitness de las consultas que
elige. Todas las estrategias tienen **cuatro consultas** y tope de **90 s de pared
virtual**. Cada consulta consume la suma de las paredes reales de sus tres trials,
incluida preparación/limpieza registrada. Si no cabe, no revela su fitness ni
mejora el incumbente. Los costes de materializar los paisajes son comunes y se
reportan aparte; los replays no vuelven a gastar GPU.

La puntuación es la media, sobre las cuatro consultas, de
`log(mejor_coste_observado / coste_baseline)`; menor es mejor. Se combina la calidad
de la solución encontrada con cuán pronto se encuentra. **No es AUC respecto al
tiempo continuo ni porcentaje de aceleración de entrenamiento**. El proxy de
feedback del replay recompensa mejoras observadas de fitness; no sustituye el
verificador pareado de promociones reales.

Se usa el mismo selector UCB de campaña, adaptado a las alternativas disponibles
del catálogo finito. En el espacio completo hay más valores y combinaciones;
esa distribución más amplia no está demostrada por el replay de nueve genomas.

## Ajuste, compromiso y prueba reservada

1. Materializar solo periodic_tune.
2. Comparar cuatro estrategias contra v0 con **20 semillas de búsqueda 100..119**.
3. Elegir por menor AUC media y registrar estrategia/identidad en `selection.json`.
4. Solo entonces generar las mediciones GPU/calibración de counter_holdout.
5. Comparar la seleccionada con anterior y azar con **40 semillas nuevas 500..539**.

Semillas de búsqueda no son semillas de inicialización del modelo. Los intervalos
son diferencias pareadas por semilla de búsqueda, **condicionados a la caché
medida**, no una estimación de incertidumbre sobre todos los tiempos GPU.

Regla práctica preregistrada: límite superior de diferencia AUC < **−0.01**.
En ajuste se usa crítico t=3.0 con df=19, conservador para cuatro variantes. En
holdout, t=2.023 con df=39: dos comparaciones unilaterales, corrección Bonferroni
al 5% nominal. Son contrastes paramétricos sobre replays, no pruebas universales.

Estrategia seleccionada y adoptada:

```json
{"version": 1, "ucb_c": 1.0, "p_global": 0.1, "small_model_prior": 0.3}
```

| Comparación | Media ΔAUC | Límite superior | Resultado |
|---|---:|---:|---|
| Ajuste: v1 − v0 | −0.051327 | −0.023594 | cumple <−0.01 |
| Holdout: v1 − v0 | −0.032304 | −0.026221 | cumple <−0.01 |
| Holdout: v1 − azar | −0.036150 | −0.028967 | cumple <−0.01 |

Se obtuvo `verified_transfer_on_cached_tasks`, no mero ajuste sin evidencia de
transferencia. El sistema también representa `adjustment_without_verified_transfer`
y `no_verified_search_improvement`; solo el resultado favorable completo autoriza
adopción. La aceptación no se fuerza si el resultado es inconcluso.

## Estado y protección frente a repetir el holdout

En `state_tinygpt_cuda_6661fab15a7e6424/`:

- `meta_gpu_v1/selection.json`: compromiso previo a holdout con estrategia elegida.
- `meta_gpu_v1/completed.json`: holdout consumido, ruta a evidencia y adopción.
- `strategy_gpu.json`: política v1 y enlace a resultados verificables.

Si se interrumpe después del compromiso, se reutiliza la selección y caché de
esa identidad, sin volver a ajustar tras ver parte del holdout. Al completarse,
el comando bloquea nuevas rondas sobre el holdout v1. Otra investigación requiere
protocolo y tareas reservadas nuevos, no borrar registros ni reintentar hasta ganar.

La campaña carga la política recalculando los contrastes desde las puntuaciones;
no confía solo en `adopted=true`. Verifica parámetros, benchmark e identidad del
protocolo. Cambiar código de este estudio/renderer/selector invalida la evidencia
para su carga: no se actualizan sus hashes a posteriori para aparentar equivalencia.

La preparación posterior cargó v1 y pasó G0-G5 (`READY_FOR_CAMPAIGN`, 26 trials).
No ejecutó nuevos candidatos ni promociones. Modelo campeón: **v0000**. La mejora
de una estrategia no se contabiliza como mejora demostrada del entrenador.

## Pruebas e informes

- Estudio real:
  `.gaia/reports/20261015T180611Z-f8463345/meta/result.json`.
- En `tuning/` y `transfer/`: manifiestos, 60 resultados de trial, stderr y paisajes.
- Preparación posterior con v1:
  `.gaia/reports/20261015T181434Z-4117c17f/campaign/result.json`.
- Suite final: `.gaia/reports/20261015T181419Z-775c8c37/REPORT.md`.

**145 tests descubiertos: 136 pasaron en NumPy y 9 se omiten allí por requerir
Torch, ejecutados sin omisiones en G1 del perfil CUDA**. Diez tests nuevos cubren
ley/digest de tareas, labels privados, no mutación del evaluador, igualdad de
presupuestos, no revelación tras deadline, pares completos, selección antes del
holdout, reanudación sin reajuste y carga verificable de la política.

Un fixture de reanudación aisló/restauró la raíz global de tempfile del proceso
de prueba; no se modificó el protocolo tras ver resultados ni se repitió holdout.

## Alcance del cierre

Se cumple Fase 8: mecanismo de ajuste, comparación contra v0/azar y prueba en
una tarea no usada para seleccionar, con resultado favorable **dentro del estudio
acotado** y adopción verificable. No se demuestra superioridad del buscador en
tareas arbitrarias, múltiples ciclos recursivos, LLM ni el espacio completo de
campañas. Repeticiones independientes con nuevos catálogos/tareas reservados
y campañas abiertas son evidencia futura, no resultados de esta ejecución.
