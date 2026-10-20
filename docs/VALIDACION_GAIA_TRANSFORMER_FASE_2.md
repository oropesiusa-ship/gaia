# Evidencia de Fase 2: laboratorio de evaluación GPU

> Evidencia histórica TinyGPT anterior al renombrado. Los comandos, rutas y
> mediciones originales no son ejecuciones nuevas de GaiaTransformer.
> Evidencia nueva: `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Fecha: 15-10-2026. Resultado: **GPU_LAB_READY**.

## Componentes

Directorio `gaia/tinygpt/lab/`:

| Archivo | Función |
|---|---|
| `benchmark.py` | Spec de trial, corpus verificado, datos privados e identidad del laboratorio |
| `candidate.py` | Baseline conocida como fuente autónoma; todavía sin búsqueda/genoma |
| `guard.py` | Filtro AST de imports, introspección, I/O y cambios de objetos externos |
| `worker.py` | Servidor protegido CUDA `READY/INIT/TRAIN/PREDICT/QUIT` |
| `evaluator.py` | Padre: tiempos, pérdida privada, validación y resultados |
| `sandbox.py` | Aislamiento bwrap, entorno mínimo y acceso a GPU seleccionada |
| `monitor.py` | NVML vía ctypes, RSS, disco, deadline y terminación |
| `validation.py` | Matriz de integración con errores deliberados |

El evaluador CPU y sus archivos protegidos no se han modificado. El laboratorio
GPU conserva una identidad propia: hashes antes/después de cada trial y una
identidad esperada común a toda la matriz. Su congelación en estado de campaña
pertenece a las fases de benchmark/puertas.

## Protocolo y privacidad

El candidato exporta `Candidate(train, seed)`, con métodos `train(steps)` y
`predict(contexts)` y un `model` nn.Module CUDA/fp32. La baseline se renderiza a
fuente autónoma a partir del modelo y entrenador de Fase 1; no importa el corpus.

El padre genera train y validación. Solo se guardan `train` y `contexts` en el
NPZ del worker; los targets quedan en memoria del padre. `target_loss` y el
criterio de parada tampoco se envían. El worker produce arrays float32 `N x 256`
y el padre calcula la entropía cruzada privada. Se rechazan formas, tipos,
objetos y valores no finitos incorrectos.

Los mensajes JSON tienen tamaño limitado y acuses asociados al comando. La
salida `print` del candidato se descarta, separada del canal protegido. Tras cada
operación se verifican flags deterministas, GPU, dtype y parámetros finitos, y
se sincroniza CUDA antes de responder.

### Aislamiento comprobado en este PC

Bwrap funciona sin sudo. El worker ve:

- Runtime y bibliotecas read-only; worker/runtime protegidos en `/lab`.
- Datos, candidato y temporales propios en `/work`; nada del corpus generador ni
  de `.gaia/reports/` del host.
- `/proc` de su namespace PID: no aparece el padre con sus targets en memoria.
- Namespace de red independiente, IPC/UTS/usuario separados y capacidades eliminadas.
- Nodos de dispositivo de la GPU elegida, control y UVM; no se monta todo `/dev`.
- Entorno mínimo: sin variables API/secretos heredadas.

El handshake verificó `host_files_hidden=true`, `parent_hidden=true` y
`network_isolated=true`. El guard es un filtro adicional, no una frontera de
seguridad por sí mismo. El comando de validación exige bwrap; si no existe o el
kernel lo bloquea, se detiene con `SANDBOX_UNAVAILABLE`. No se instala mediante sudo
ni se degrada silenciosamente.

## Medición y presupuestos

El padre mide pared alrededor de cada petición/respuesta sincronizada. El coste
es `t_init_s + t_train_s + t_eval_s + t_metric_s`, incluido el arranque/importación
del worker y todas las evaluaciones requeridas hasta la segunda consecución del
objetivo. El tiempo de preparación del laboratorio/datos y limpieza se refleja
adicionalmente en `wall_s`, sin confundirse con el trabajo del candidato.

Límites normales: 20 s de pared, 3000 MiB RSS, 3000 MiB VRAM y 500 MiB de disco.
El watchdog recorre el árbol de procesos real del host, aunque el worker vea un
PID diferente dentro del namespace. NVML atribuye memoria exclusivamente a esos
PIDs; no suma ni termina procesos ajenos que usan la misma GPU.

RSS usa `/proc`, VRAM total usa NVML y disco incluye todos los temporales propios.
Se muestrean cada 20 ms y en cada respuesta. Los picos muestreados no equivalen a
contabilidad instantánea de cada asignación; se combina el monitor con la cuota
del allocator Torch y límites del SO. No se aplica RLIMIT_AS, que impediría
importar Torch/CUDA por sus reservas de espacio virtual.

## Matriz real: 17 escenarios pasaron

```bash
python3 gaia.py tinygpt-lab
```

Equipo: GTX 1060 6 GiB, driver 580.178.04, CPython 3.14.4, Torch 2.14.0+cu126.

| Caso | Resultado esperado y observado |
|---|---|
| baseline, 100 pasos | `ok`, pérdida 5.537448 → 0.072185 |
| repetición | `ok`, idénticas curvas y hashes de logits |
| objetivo privado de diagnóstico 3.0 | `ok`, dos logros sucesivos; parada al paso 50 |
| import de OS | `invalid`, no se inicia candidato |
| logits con forma incorrecta | `worker_error` |
| logits NaN | `worker_error` |
| excepción en entrenamiento | `worker_error` |
| asignación de 4 GiB fuera de cuota | `cuda_oom`, asignación rechazada |
| determinismo desactivado | `worker_error` |
| entrenamiento bloqueado | `timeout`, interrumpido por el padre en TRAIN |
| print que imita protocolo | `ok`, no altera el canal |
| RSS excesiva | `resource_limit`, `ram_mb` |
| VRAM excesiva | `resource_limit`, `vram_mb` |
| disco excesivo | `resource_limit`, `disk_mb` |
| huella Torch falsa | `protocol_error` |
| identidad protegida distinta | `error`, antes de iniciar candidato |
| STOP | `stopped` |

Los tests de límites utilizan cuotas deliberadamente pequeñas; no modifican los
presupuestos normales. El objetivo 3.0 solo prueba el protocolo y no está calibrado
para seleccionar modelos. Ningún fallo produce un resultado válido ni coste
aceptable: `valid=false`, `cost_s=null`. Todos los temporales se eliminaron y
los workers fueron recolectados.

### Métricas de baseline del ensayo final

| Medida | Valor |
|---|---:|
| Inicialización/arranque | 2.320560 s |
| Entrenamiento | 1.112834 s |
| Predicción sincronizada | 0.226666 s |
| Métrica privada del padre | 0.007031 s |
| Coste acumulado | 3.667091 s |
| Pared total del evaluador | 4.503760 s |
| RSS máxima del árbol | 1472.66 MiB |
| VRAM máxima NVML por proceso | 238 MiB |
| Pico reservado por allocator Torch | 100 MiB |
| Pico disco temporal | 0.5523 MiB |

El hash final de logits coincide con Fase 1:
`faa2ea4e25f7372d8d4bf914545b3d0afc2c89c1030248dc48580ac17c4f4027`.
Fuente de candidato SHA-256:
`06d71da887527f3e9d586ccefe4a421d20cd5de85ba8b2735aeb6a4c8995cca4`.

## Regresiones y evidencia

- **13 tests unitarios nuevos** del laboratorio, ejecutados sin fallos en CPU y
  en el entorno CUDA: guard, protocolo, datos privados, telemetría, cuotas,
  rechazo por integridad y estado del CLI.
- Suite general: **97 descubiertos; 90 ejecutados sin fallos y 7 de modelo omitidos
  en el perfil NumPy**, ya verificados en Torch/CUDA en Fase 1. No se cambió el modelo.
- Informe de integración final:
  `.gaia/reports/20261015T162752Z-180b832f/REPORT.md`.
- Resultados detallados: su subdirectorio `phase2/`, con agregado `result.json`
  y `result.json`/stderr por caso.
- Suite general final:
  `.gaia/reports/20261015T162906Z-314e8a07/REPORT.md`.

## Cierre y siguiente fase

`GPU_LAB_READY` confirma trials aislados y manejo de errores en este equipo.
No equivale a `READY_FOR_CAMPAIGN`. No se han inicializado Store, calibración,
campeón ni promociones TinyGPT. Fase 3 debe fijar el benchmark y objetivo multisemilla,
comparaciones pareadas, controles de ruido/deriva y auditoría. Las puertas de
campaña y la búsqueda se integrarán sobre este laboratorio.
