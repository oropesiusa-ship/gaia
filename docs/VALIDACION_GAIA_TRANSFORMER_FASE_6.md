# Fase 6: observabilidad TinyGPT/CUDA para Modo B

> Evidencia histórica anterior al renombrado. Los comandos, rutas y mediciones
> originales no son ejecuciones nuevas de GaiaTransformer.
> Evidencia nueva: `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Fecha: 15-10-2026. Resultado: **GPU_OBSERVATION_READY** en GTX 1060 6 GiB.

## Uso y componentes

```bash
python3 gaia.py tinygpt-observe
python3 gaia.py tinygpt-observe --steps 100
```

Se observa el campeón actual `v0000` de la campaña GPU real, no una arquitectura
paralela elegida para el perfil. Se valida el benchmark congelado y las versiones
bajo locks de campaña/calibración. No se proponen ni promueven candidatos.

- `gaia/tinygpt/observation.py`: padre, trial normal, sandbox, monitor y persistencia.
- `gaia/tinygpt/observe_worker.py`: entrenamientos frescos y medición CUDA.
- `gaia/tinygpt/profiling.py`: instrumentación AST, paridad y diagnóstico.
- `tests/test_tinygpt_profiling.py`: diez pruebas unitarias específicas.

El observador va fuera de `gaia/tinygpt/lab/`: no modifica los archivos protegidos
ni invalida la calibración del benchmark. Sus propios hashes, fuente del campeón,
runtime y datos de medición quedan identificados en el informe.

## Procedimiento

1. Cargar/verificar benchmark, campeón, genoma y fuente estable.
2. Ejecutar un **trial normal sin instrumentación** con la semilla 0 y el objetivo
   calibrado. Su coste, curva y fases globales se conservan como referencia.
3. Lanzar un observador separado bajo bwrap, con contexto y train pero sin targets.
   Mismo intérprete/Torch/GPU por UUID, fp32, flags deterministas y watchdog externo
   de tiempo, RAM, VRAM NVML y disco. No se heredan secretos del padre.
4. Entrenar tres instancias frescas sin instrumentación, cada una con semilla 0,
   25 pasos de calentamiento y 100 medidos. Son tres réplicas **dentro del mismo
   proceso observador**, no tres procesos independientes de benchmark.
5. Repetir con otra instancia fresca e instrumentación de once fases de step.
6. Exigir paridad exacta de hashes de pesos, gradientes, toda la secuencia de
   pérdidas y logits. Si el total de pasos coincide con el trial normal, comparar
   también sus logits entre procesos. No se comparan checkpoints de pasos distintos.
7. Diagnosticar, verificar que benchmark/campeón siguen intactos y añadir un
   evento `observation` al ledger, sin cambiar estadísticas de recompensa.

La instrumentación verifica la estructura AST conocida antes de introducir
medidores. No adivina fases de un step diferente. No altera el optimizador ni
reimplementa su entrenamiento. Los temporizadores sincronizan CUDA en ambas
fronteras y registran pared e intervalos mediante eventos CUDA.

Los intervalos de eventos CUDA **no son la suma pura de tiempos de kernels**:
pueden incluir esperas del stream mientras el host prepara/enfila operaciones.
Las barreras añadidas perturban el reparto: se mide y publica esa sobrecarga,
sin sustituir los tiempos válidos del laboratorio de promoción.

## Resultado de la ejecución final

Perfil Pascal, Torch 2.14.0+cu126, Python 3.14.4, campeón de 120576 parámetros.
100 pasos medidos + 25 de calentamiento. Mediana normal: **10.219656 ms/paso**.
Sobrecarga de entrenamiento instrumentado: **1.095865x** (aprox. 9.59%).

Fracciones normalizadas sobre la suma de fases de entrenamiento instrumentadas:

| Fase | Fracción |
|---|---:|
| Optimizador | 31.866% |
| Backward | 29.119% |
| Forward y pérdida | 22.278% |
| Clipping | 10.112% |
| Cambio a train | 1.434% |
| Muestreo CPU y transferencia de índices | 1.003% |
| Gather | 0.689% |
| Comprobación de pérdida finita | 1.384% |
| Zero grad | 1.388% |
| Extracción loss.item | 0.505% |
| Contadores y lista de pérdidas | 0.222% |

Se conservan también los tiempos brutos y un residual de instrumentación/bucle
de unos 0.0529 s, no incluido en esas fracciones normalizadas.

### Descomposición del coste normal

En el trial independiente:

- Inicialización/arranque: **59.365%** del coste.
- Entrenamiento: aproximadamente **33.976%**.
- Predicción y métrica privada: **6.660%**.
- Primer cruce del objetivo al paso 100; logro sostenido al paso 125, con
  resolución de evaluación de 25 pasos.

La inicialización incluye intérprete, imports, contexto CUDA y construcción del
candidato. El perfil caliente del observador no elimina ese coste de la métrica
de campaña. Optimizar el mayor segmento de entrenamiento no equivale a acelerar
en esa misma proporción el coste total.

Como orientación, proyectar el reparto instrumentado sobre train del trial sitúa
al optimizador en aproximadamente 10.83% del coste total; su cota ideal estimada
de Amdahl es 1.1214x. Es una **estimación diagnóstica**, no un resultado experimental
de mejora ni prueba de que esa aceleración sea alcanzable.

### Ruido e historial

- CV de tres entrenamientos calientes: **0.3507%**, dentro del mismo observador.
- CV histórico de cinco trials completos de preparación: **4.4247%**. Se etiqueta
  como histórico, con fecha y fuente; es comparable con el mínimo de mejora del 5%.
- Historial: dos experimentos completos y dos abortados deliberadamente; dos
  cambios de hiperparámetro dentro de una región arquitectónica.
- Ambos experimentos completos llegaron a confirmación. Los abortados no se
  cuentan como comparaciones informativas ni como rechazos estadísticos.
- El diagnóstico marca `enough_history=false`: con dos experimentos no se puede
  concluir que haya una meseta ni demostrar que la búsqueda repita regiones en exceso.

## Paridad y recursos

Tres instancias normales y la instrumentada produjeron exactamente:

- Hash de pesos: `00fb494f4c176e701459012b0c405ba8bb3c236c948d372307b3ba46e744c82b`.
- Hash de gradientes: `225f186816795e5f8044d1ddd106c0c845ad56888071fe170d062ae6bd154ab7`.
- Hash de pérdidas: `37957e9564a66d3a16a4f6982a2b73528c9884aeec6864cfd840b3e34e588cce`.
- Hash de logits: `fff6424e140ca2466d678b3fa4e183e1fd3165aa7a00dbc35bb9be4e7acf211e`.

El trial normal también produjo ese hash de logits al paso 125:
`matches_reference_at_same_step=true`. Las ejecuciones previas de validación
produjeron los mismos hashes, con variaciones normales en tiempos.

Observador final: 9.34 s de pared desde el padre, RSS máxima 1452.42 MiB, VRAM
total NVML 238 MiB. Cuota normal de 20 s y topes RAM/VRAM 3000 MiB conservados.
Salida del worker 0 y temporales eliminados; campeón sigue en v0000. No se han
modificado benchmark, fuente estable ni recompensa de operadores.

## Persistencia y pruebas

El ledger registra tipo `observation`, campeón, hash de fuente, ruta a evidencia
y diagnóstico. No registra una aceptación ni un nuevo experimento start/end.
Informes de cada ejecución:

```text
.gaia/reports/<id>/observation/
  REPORT.md
  result.json
  observation.json
  observer_metrics.json
  observer.stderr.log
  reference_trial/result.json
```

La ejecución final está en `.gaia/reports/20261015T173353Z-e5018ae8/`.
Suite final en `.gaia/reports/20261015T173418Z-59d63412/`:
**126 tests descubiertos; 118 ejecutados sin fallos en el perfil NumPy y 8 de
modelo omitidos allí, previamente verificados en CUDA sin cambios de modelo**.

Diez tests nuevos cubren instrumentación de variantes conocidas, rechazo de step
desconocido, paridad, duraciones/conteos inválidos, cobertura del ledger, semántica
diagnóstica de Amdahl, separación de ruido caliente/histórico, paridad con trial
normal e impedimento de reportar READY ante fallo del observador.

## Cierre y siguiente fase

Hay diagnóstico basado en el campeón y ledger de una campaña real, con medidas
internas contrastadas por paridad y referencia normal: se cumple Fase 6.
No se ha ejecutado investigación ni ampliado el espacio de búsqueda.
Fase 7 debe formular hipótesis a partir de esta evidencia, contrastarlas en el
laboratorio sin instrumentación y guardar memoria apoyada/refutada/inconclusa.
