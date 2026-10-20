# Evidencia de Fase 3: benchmark, comparación y auditoría GPU

> Evidencia histórica TinyGPT anterior al renombrado. Los comandos, rutas y
> mediciones originales no son ejecuciones nuevas de GaiaTransformer.
> Evidencia nueva: `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Fecha: 15-10-2026. Resultado: **GPU_BENCHMARK_READY**, 71 trials GPU válidos.

## Comando y archivos

```bash
python3 gaia.py tinygpt-benchmark
```

Reutiliza el perfil Pascal y el laboratorio bwrap/NVML. No sobrescribe un benchmark
existente: una nueva calibración requiere nueva identidad/configuración y estado.
En este equipo ya se ha ejecutado correctamente.

- Calibración y reglas: `gaia/tinygpt/lab/calibration.py`.
- Carga verificada: `gaia/tinygpt/benchmark_state.py`.
- Estado: `state_tinygpt_cuda_6661fab15a7e6424/benchmark.json` y `baseline.json`.
- Evidencia completa:
  `.gaia/reports/20261015T164914Z-db097e0f/phase3/result.json`.
- Logs y resultados individuales: `trial-0001/` a `trial-0071/` junto al agregado.
- Suite final: `.gaia/reports/20261015T165624Z-762f0588/REPORT.md`.

## Especificación fijada antes de medir

`tinygpt_benchmark/v1`: baseline conocida de Fase 1, 100 pasos de referencia,
máximo 300 pasos en trials con objetivo, evaluación cada 25 pasos y dos aciertos
sucesivos para alcanzar calidad. El coste incluye arranque, CUDA, entrenamiento,
predicción y cómputo privado del padre hasta la segunda comprobación requerida.

El objetivo es **máxima pérdida final de las cinco referencias + 0.05**. Esta
regla se fijó en el código antes de ejecutar trials. No se rebajó ni adaptó tras
ver controles o auditoría. Las mismas reglas se conservarán al comparar candidatos.

| Semilla de calibración | CE al paso 100 |
|---:|---:|
| 9000 | 0.0721847568 |
| 9001 | 0.1711693045 |
| 9002 | 0.0811060217 |
| 9003 | 0.1410838273 |
| 9004 | 0.2096790841 |

Objetivo congelado: **CE <= 0.2596790841227193**.
Las cinco semillas lo alcanzaron de forma sostenida al reevaluarse.

## Fiabilidad y controles

Cinco repeticiones con semilla 0:

| Medida | Observado | Umbral fijado |
|---|---:|---:|
| Alcance de calidad | 5/5 | 5/5 |
| Coste mediano | 4.060995 s | >= 0.06 s |
| CV | 1.2392% | <= 20% |
| Warmup / mediana | 1.00939 | <= 1.35 |
| Deriva entre mitades | 0.2354% | <= 35% |

Controles con semillas separadas 4000..4004, cinco pares alternando orden:

- Nulo, baseline vs sí misma: ratio 0.999872; límite superior 95% 1.014397.
  **Rechazado**, no hay mejora verificada.
- Lento: añade 20 predicciones redundantes de contextos train por paso, sin
  actualizar pesos adicionales ni modificar los logits privados de baseline.
  Ratio **2.318047**, límite inferior unilateral 95% **2.278669** (>1.02).
  Se mide inequívocamente más lento y no se acepta.

El control lento no se selecciona como candidato ni modifica la baseline estable.
Los controles pasan por el mismo guard, sandbox, recursos y métrica que cualquier trial.

## Cribado y confirmación

`compare_candidate` evalúa primero campeón/candidato con semilla 0. Rechaza si no
hay calidad válida o el coste candidato supera 1.3x el campeón actual. Si pasa,
ejecuta cinco pares intercalados con semillas 1000..1004.

`decide` exige cinco pares completos, todas las semillas con calidad, costes
positivos finitos y métricas de RAM/VRAM disponibles. Log-ratio medio y t unilateral
95% (df=4) determinan aceptación únicamente si el límite superior es <0.95.
Si RAM o VRAM medianas superan 1.25x se devuelve `pareto_alternative`, no aceptación.
Una mejora aparente sin evidencia suficiente se devuelve como `deferred`.

Se ejecutó cribado y confirmación con baseline vs sí misma: ratio 1.011630,
límite superior 1.050682, **rechazado**. Las pruebas unitarias verifican además
una mejora sintética clara, fallos de calidad, semillas desalineadas, pares
incompletos, regresión VRAM y ruido/deriva/saturación. No se ha aceptado ni
promovido un candidato real diferente de baseline en esta fase.

## Auditoría

Seis semillas reservadas 5000..5005; doce pares baseline/baseline en total:
seis en validation y seis en audit, alternando el orden. **Todas las ejecuciones
alcanzaron el objetivo**. El objetivo ya estaba fijado y no se modificó.

Audit usa registros y dominio independientes del corpus congelado; comparte la
misma gramática sintética. Esta evidencia no demuestra transferencia a otra
tarea ni lenguaje natural. La rutina devuelve ratios y cumplimiento por split,
no fabrica una afirmación de mejora a partir de baseline vs baseline.

## Persistencia e integridad

Tras superar todas las comprobaciones se escribieron fuente/hash baseline y
benchmark con spec, objetivo, runtime, configuración, referencia temporal, hashes
del laboratorio y ruta a evidencia. La carga real del estado mediante
`benchmark_state.load` pasó después de congelar.

Cambiar configuración, runtime, spec, archivos protegidos o fuente baseline
invalida la carga. Los tests cubren las discrepancias y evitan reutilización
silenciosa. Un fallo durante calibración conserva resultados individuales y
reporte agregado `FAILED`, pero no escribe un benchmark aprobado.

Suite final: **105 tests descubiertos; 98 ejecutados sin fallos y 7 de modelo
omitidos en el entorno NumPy**, verificados previamente en el entorno CUDA.
Ocho tests nuevos cubren decisiones, fiabilidad, semillas, control lento y carga
del estado congelado.

## Alcance del cierre

Se cumple el cierre de Fase 3: benchmark local fiable, objetivo congelado y
control lento inequívoco, con reglas de aceptación y evidencia de confirmación y
auditoría. `GPU_BENCHMARK_READY` no equivale a `READY_FOR_CAMPAIGN`.

Fase 4 debe integrar genoma, propuestas, persistencia de versiones y promoción
atómica usando estas decisiones; Fase 5 debe cerrar las puertas CUDA y la
supervisión continua de deriva/saturación. No hay búsqueda ni `stable/CURRENT`
GPU todavía, y `run` continúa usando el motor MLP.
