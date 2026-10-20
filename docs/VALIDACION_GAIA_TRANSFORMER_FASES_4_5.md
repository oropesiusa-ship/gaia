# Fases 4–5: campaña autónoma TinyGPT y puertas CUDA

> Evidencia histórica anterior al renombrado. Los comandos, rutas y mediciones
> originales no son ejecuciones nuevas de GaiaTransformer.
> Evidencia nueva: `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Fecha: 15-10-2026. Resultados reales: **GPU_CAMPAIGN_COMPLETE** y
**READY_FOR_CAMPAIGN** en GTX 1060 6 GiB, perfil `tinygpt-cuda-pascal`.

## Uso

```bash
python3 gaia.py tinygpt-prepare --minutes 15
python3 gaia.py tinygpt-run --max-experiments 1 --minutes 15
```

Requiere el benchmark local congelado de Fase 3. No lo recalibra ni modifica.
Cada ejecución vuelve a verificar las puertas; no confía en un READY anterior.
El tiempo de puertas está incluido en el presupuesto: en este PC cuestan varios
minutos. Límites CLI: 1..60 minutos, 1..1000 experimentos nuevos; por defecto
15 minutos y un experimento. No se promete agotar todos los experimentos si falta
presupuesto: se detiene antes de empezar otro trial que no quepa.

`python3 gaia.py stop` crea STOP global; `resume` lo elimina. La campaña lo
comprueba antes de proponer, antes de cada trial y durante la supervisión externa.
Errores de runtime, integridad o infraestructura detienen el ciclo con evidencia;
no se reinterpretan como mejoras. No se ha implementado Modo B ni metaoptimización GPU.

## Componentes nuevos

- `gaia/tinygpt/genome.py`: validación, render, hashes y propuestas reproducibles.
- `gaia/tinygpt/campaign.py`: puertas, presupuestos, ciclo y comparación.
- `gaia/tinygpt/campaign_store.py`: ledger, versiones completas y recuperación.
- `tests/test_tinygpt_campaign.py`: integridad, promoción, rollback y recuperación.
- `tests/gpu_campaign_recovery_check.py`: prueba manual de SIGKILL sobre procesos propios.

El espacio inicial contiene alternativas **conocidas**, no descubrimientos nuevos:

| Componente | Valores |
|---|---|
| dimensión | 32, 64, 96 |
| capas | 1, 2, 3 |
| heads | 1, 2, 4, con divisibilidad validada |
| batch | 16, 32, 64 |
| lr | 0.001, 0.003, 0.006 |
| weight decay | 0, 0.01, 0.1 |
| dropout | 0, 0.1 |
| optimizador | AdamW o SGD |

Contexto 64, vocabulario 256 y fp32 permanecen fijos. No se exponen fp16, bf16,
Flash Attention ni opciones de compilación incompatibles con el perfil Pascal.
Los operadores aprenden intentos/recompensas del ledger con UCB; solo una aceptación
verificada proporciona recompensa positiva. Se evitan genomas ya propuestos,
incluidos los ensayos interrumpidos, y cada propuesta lleva hipótesis y procedencia.

## Puertas ejecutadas antes de experimentar

| Puerta | Verificación |
|---|---|
| G0 | Trial CUDA real válido, huella padre/worker y sandbox con red/procesos/archivos separados |
| G1 | Tests reales de modelo, causalidad CPU/GPU, gradientes, datos y laboratorio; ninguna omisión permitida |
| G2 | Calidad 5/5, curvas y hashes de logits idénticos, CV/warmup/deriva/resolución y referencia baseline |
| G3 | Corpus/benchmark/laboratorio y fuente baseline congelados; fuentes/versiones de campeón verificadas |
| G4 | Cinco pares nulos rechazados y cinco pares lentos con límite inferior 95% >1.02 |
| G5 | Límites positivos finitos, reloj total, cuota por trial, RAM/VRAM/disco e IDs/experimentos acotados |

El último `tinygpt-prepare` completó 26 trials GPU y G1 ejecutó 30 tests sin
omisiones. Resultado de G2: mediana 4.260889 s, CV 4.4247%, repetibilidad numérica
verdadera, deriva frente a calibración 4.9223% (<35%). Control nulo rechazado;
control lento ratio 2.263717, límite inferior 95% 2.133812.

La preparación guarda `readiness_gpu.json` e identidad en el estado y el informe.
Durante preparación se marca PREPARING; si falla queda NOT_READY. Una identidad
distinta no se acepta reutilizando las puertas antiguas. El ciclo comprueba
integridad antes de cada experimento y de publicar una versión. La deriva del
campeón actual y la saturación se revisan en su trial de cribado; la referencia
baseline se mantiene separada para no confundir una aceleración con deriva del PC.

## Ciclo, aceptación y persistencia

Cada experimento registra `start`, propone/renderiza un candidato, mide al campeón
y candidato en semilla 0 y, si pasa cribado, ejecuta cinco pares intercalados de
confirmación en semillas 1000..1004. Calidad en todas, IC unilateral superior
95% del ratio <0.95 y RAM/VRAM medianas <=1.25x son obligatorios para promover.
La auditoría reservada de Fase 3 no interviene en las propuestas ni en la aceptación.

Una publicación prepara directorio temporal con genoma, fuente y evidencia;
publica el directorio completo y actualiza CURRENT atómicamente. La fuente debe
coincidir con el render y los hashes de todos los trials comparados. La decisión
se recalcula desde pares, no se confía únicamente en una etiqueta `accepted`.
Rollback está disponible en la API del store; todavía no hay comando GPU dedicado.
No se afirma durabilidad ante corte eléctrico: las pruebas cubren interrupciones
de procesos y publicación atómica visible.

Estado local:

```text
state_tinygpt_cuda_6661fab15a7e6424/
  benchmark.json          # calibración intacta
  baseline.json
  ledger.jsonl            # append-only
  readiness_gpu.json
  stable/CURRENT
  stable/v0000/{genome.json,trainer.py,evidence.json}
  tmp/                    # temporales propios recuperables
```

## Resultados de campaña reales

| ID | Cambio | Decisión | Ratio coste / límite superior 95% |
|---|---|---|---|
| e00001 | lr 0.003 → 0.006 | rechazado | 1.060629 / 1.113769 |
| e00002 | heads 2 → 4 | aborted por SIGKILL deliberado | sin resultado válido |
| e00003 | prueba interrumpida deliberadamente | aborted por SIGKILL | sin resultado válido |
| e00004 | weight_decay 0.01 → 0 | rechazado | 0.980472 / 1.012796 |

Cada campaña completa realizó 26 trials de puertas y 12 de cribado/confirmación.
Ambos candidatos completos alcanzaron la calidad en todas las semillas pero
ninguno cumplió la mejora mínima verificada del 5%. **Cero promociones reales**;
el campeón sigue en `v0000`. No se considera esto una mejora ni un fallo del
verificador: satisface el criterio de cierre mediante rechazo verificable.

## Recuperación real y corrección encontrada

El harness lanzó una campaña hija, esperó un `start` persistido y la terminó
con SIGKILL. En la prueba final `e00003` quedó cerrado como `aborted`, el siguiente
ID fue 4 y `CURRENT` siguió en v0000. La campaña posterior usó efectivamente
e00004. La recuperación repetida no añadió otro cierre.

El primer ensayo detectó que matar el evaluador dejaba un temporal en /tmp.
Se corrigió redirigiendo los temporales del laboratorio a `state.../tmp/`:
la recuperación elimina solo subdirectorios `gaia-gpu-*` propios, bajo lock.
La segunda prueba eliminó un directorio parcial y dejó vacía la carpeta de
temporales tras reanudar. El fixture del primer ensayo se limpió verificando su
PID muerto y el informe propietario; no se barrió el /tmp global.

Los workers murieron junto con su supervisor; NVML no mostró procesos de trial
remanentes. Los procesos ajenos de escritorio/navegador no fueron afectados.
Una interrupción después de publicar CURRENT pero antes de cerrar el ledger se
recupera como accepted solo si existe versión completa con evidencia verificada;
esta rama y rollback se probaron con evidencia sintética en tests, no con una
promoción real GPU.

## Pruebas e informes

- Suite: **116 descubiertos, 108 ejecutados sin fallos en NumPy, 8 de modelo
  omitidos allí y ejecutados en el perfil CUDA durante G1**.
- Diez tests de campaña cubren variantes renderizables, aprendizaje/hashes,
  genomas inválidos, promoción/rechazo, evidencia vinculada a fuente, rollback,
  IDs, commit interrumpido y limpieza selectiva.
- El test adicional de modelo ejecuta un candidato renderizado con otra
  arquitectura y SGD, verificando entrenamiento/predicción.

Informes locales:

- Primera campaña completa: `.gaia/reports/20261015T170143Z-701ea05f/`.
- Recuperación final: `.gaia/reports/phase4-recovery-final/result.json`.
- Campaña reanudada: `.gaia/reports/20261015T171450Z-4414914c/`.
- Preparación final: `.gaia/reports/20261015T171955Z-55a77313/`.
- Suite general: `.gaia/reports/20261015T171854Z-82d9e75b/`.

Fases 4 y 5 cumplen sus cierres en este equipo. El siguiente paso es Fase 6:
perfilado interno TinyGPT para diagnosticar cuellos de botella y sustentar Modo B.
