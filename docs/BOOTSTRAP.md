# Aprovisionamiento automático de GAIA

Para preparar **herramientas del host de construcción de la appliance**, usar
`python3 gaia.py appliance-bootstrap` (o `--preflight` para diagnosticar).
Es un flujo separado de los entornos Python descritos abajo: instala paquetes
del SO mediante sudo con confirmación en terminal. No cambia el bootstrap
NumPy/CUDA ni exige sudo para esos entornos. Véase
[preparación de la appliance](APPLIANCE_BOOTSTRAP.md).

Identidad operativa actual: GaiaTransformer. Las mediciones locales del 15-10-2026
y las validaciones de fases enlazadas son históricas de TinyGPT; reconstrucción
y resultados nuevos en [validación del renombrado](VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md).

## Uso

Con Python disponible, desde la raíz del proyecto:

```bash
python3 gaia.py run
```

GAIA detecta el equipo, elige un perfil compatible, crea/reutiliza su entorno,
instala las dependencias fijadas y se ejecuta dentro de él. `run` calibra el
estado nuevo y exige las puertas G0-G5 antes de experimentar.

Para preparar todo sin iniciar búsqueda:

```bash
python3 gaia.py bootstrap
```

Este comando incluye `selftest` y `prepare`. La calibración inicial puede tardar
varios minutos; los resultados se muestran en directo y se guardan en logs.

Para comprobar requisitos sin descargar, instalar o calibrar:

```bash
python3 gaia.py doctor --preflight
```

Genera un informe `PREFLIGHT_READY` si las comprobaciones previas pasan. Esto
indica que hay una estrategia de aprovisionamiento; la conectividad, las wheels
y la fiabilidad experimental se validan después, cuando se necesitan.

Otros comandos:

```bash
python3 gaia.py bootstrap --no-prepare  # solo entorno y diagnóstico, sin tests ni calibración
python3 gaia.py doctor                 # valida entorno existente, no instala
python3 gaia.py selftest               # suite completa dentro del entorno local
python3 gaia.py status
python3 gaia.py stop                   # funciona incluso sin dependencias ni conexión
```

## Requisitos y perfiles

El catálogo `gaia/bootstrap_profiles.json` define versiones explícitas y las
combinaciones admitidas. Actualmente incluye `cpu-numpy` para Linux
x86_64/aarch64 y Python 3.9–3.14: NumPy 2.0.2 para 3.9–3.10 y NumPy 2.3.5 para
3.11–3.14. Los límites de versión no implican que todas las combinaciones hayan
sido probadas físicamente: cada instalación debe pasar sus probes y puertas.

Se necesitan al menos 1 GiB de RAM del sistema y 1 GiB de disco libre. El límite
inicial del worker es como máximo el 40% de la RAM, con tope de 3000 MiB;
el perfil de benchmark pasa a `easy` en equipos con poca memoria salvo elección
explícita del usuario. Se mantiene un hilo BLAS por defecto. No se suavizan las
reglas de promoción para conseguir que un equipo pase.

Se registran CPU, núcleos, RAM (incluyendo límites cgroup v1/v2), GPU NVIDIA,
driver, VRAM y capacidad CUDA si `nvidia-smi` está disponible. Detectar una GPU
no cambia el workload ni instala Torch. GaiaTransformer tiene comandos específicos
para plataforma, baseline, benchmark, puertas y campaña GPU.
Un workload, SO, arquitectura o Python sin perfil se rechaza con un diagnóstico.

### Perfil de plataforma GaiaTransformer/CUDA (Fase 0.1)

```bash
python3 gaia.py doctor --profile gaia-transformer-cuda-pascal --preflight
python3 gaia.py bootstrap --profile gaia-transformer-cuda-pascal
python3 gaia.py doctor --profile gaia-transformer-cuda-pascal
```

El perfil CUDA requiere Linux x86_64, CPython 3.14 estándar (sin free-threading),
glibc >= 2.28, GPU Pascal con capacidad 6.0/6.1/6.2 y al menos 2048 MiB de VRAM,
driver >= 560.28.03, 6144 MiB de RAM y 20480 MiB de disco libre para entorno/caché.
Solo se elige para el workload `gaia_transformer_cuda` o mediante `--profile` explícito;
el arranque normal del MLP sigue usando `cpu-numpy`.

Se fija Torch `2.14.0+cu126`, NumPy `2.3.5` y todas sus dependencias en
`requirements/gaia-transformer-cuda-pascal-py314.lock`, con hashes comprobados por pip.
No se instalan drivers, otro Python ni toolkits del sistema. Si el intérprete
actual no tiene un perfil, se informa de ello; no se descarga un Python alternativo.
La versión exacta y hash del Python instalado se registran en el informe.

Selecciona una GPU compatible por UUID, configura determinismo y comprueba
kernels, gradientes finitos y hashes de salida/gradientes entre tres procesos
(uno normal, dos bajo `-I` y entorno mínimo). El resultado es
`CUDA_ENVIRONMENT_READY`: **no** `READY_FOR_CAMPAIGN`.

Este perfil omite `selftest`/`prepare` de campaña incluso en `bootstrap` normal:
el smoke test CUDA es su validación de plataforma. Solo escribe entorno,
configuración e informes. No crea `state_gaia_transformer_cuda_<huella>/` ni inicia una
baseline. Los intentos de ejecutar el motor MLP con identidad GaiaTransformer se rechazan
tanto en el bootstrap como en el motor, incluido el modo manual.

RSS se limita inicialmente al 40% de RAM con tope de 3000 MiB; VRAM al 60% de la
GPU con tope de 3000 MiB. El probe comprueba RSS y VRAM del allocator de Torch;
el laboratorio de Fase 2 añade supervisión externa de contexto/driver mediante NVML.
Los límites generales de campaña se heredan de `gaia/config.py` y las opciones
del usuario, sin iniciar una campaña en esta fase.

El perfil añade a su huella el hash del lock y del intérprete, y registra el hash
del probe y resultados de cada proceso. Un fallo se conserva en los mismos
reportes por etapa. Véase [evidencia local](VALIDACION_CUDA_FASE_0_1.md).

### Baseline GaiaTransformer (Fase 1)

```bash
python3 gaia.py gaia-transformer-baseline
```

Selecciona el perfil Pascal automáticamente, lo provisiona si hace falta y pasa
su diagnóstico. Ejecuta además los tests de modelo en el entorno Torch/CUDA.
Luego entrena tres procesos aislados nuevos: dos con semilla 9000 y uno con 9001,
100 pasos cada uno. Es una baseline fija, sin propuestas ni promoción.

Opciones: `--steps` (20..10000), `--seed` (0..2**31-2), `--repeats` (2..5).
Siempre se añade una prueba con `seed+1`. Los parámetros de arquitectura y
optimizador no se buscan automáticamente. Se conservan los límites locales;
pedir demasiados pasos puede terminar en timeout, con diagnóstico.

El corpus generado se compara con `gaia/gaia_transformer/corpus_v1.json` antes de entrenar.
Solo se serializan train y contextos; los bytes objetivo de validación permanecen
en el padre. Los resultados incluyen curvas privadas, hashes de pesos, gradientes
y logits y los tiempos/memoria diagnósticos. El resultado de cierre es
`GAIA_TRANSFORMER_BASELINE_READY`, distinto de `READY_FOR_CAMPAIGN`.

Los informes contienen `phase1/result.json`, `phase1/corpus.json`, resultados y
logs por trial. Los archivos temporales de inputs/logits se eliminan al terminar.
No se crea un `Store` ni estado de campaña GaiaTransformer. Detalle histórico:
[validación de Fase 1](VALIDACION_GAIA_TRANSFORMER_FASE_1.md).

### Laboratorio GPU (Fase 2)

```bash
python3 gaia.py gaia-transformer-lab
```

Provisiona/reutiliza el perfil Pascal, valida runtime y ejecuta tests unitarios y
17 escenarios reales de laboratorio. Incluye baseline/repetición, objetivo
privado sostenido, errores de candidato/protocolo, OOM, timeout, RAM, VRAM, disco,
integridad y STOP. Los errores deliberados forman parte de las comprobaciones:
solo se devuelve `GPU_LAB_READY` si coinciden con el resultado esperado.

Requiere `bwrap` funcional y NVML con memoria por PID, además del perfil CUDA.
El comando no instala paquetes del sistema ni usa sudo. Si falta aislamiento o
telemetría, deja informe y falla; no rebaja las condiciones automáticamente.

El sandbox monta solo runtime, bibliotecas y GPU necesarios, oculta fuentes de
datos/informes del host y separa red/procesos. Targets y objetivo de calidad
permanecen en el padre. Tiempo, RSS, disco y VRAM total por PID se supervisan
desde fuera del worker. El monitor muestrea a 20 ms y registra sus picos.

Los informes quedan en `.gaia/reports/<id>/phase2/`. Cada trial incluye estado,
error, fase, curvas privadas, tiempos, picos, huellas y limpieza. Se puede usar
la API `gaia.gaia_transformer.lab.evaluator.run_trial` para un candidato concreto; su
especificación no calibra ni promueve modelos. El modo process-only existe en
esa API mediante opción explícita y queda identificado como tal; el comando de
validación exige bwrap. Detalle histórico: [evidencia Fase 2](VALIDACION_GAIA_TRANSFORMER_FASE_2.md).

### Benchmark GPU (Fase 3)

`python3 gaia.py gaia-transformer-benchmark` calibra y valida un estado GPU nuevo: cinco
semillas, fiabilidad, controles pareados nulo/lento, confirmación y auditoría.
Requiere el mismo perfil, bwrap y NVML que `gaia-transformer-lab`. Puede tardar varios
minutos; guarda cada trial y su stderr bajo `.gaia/reports/<id>/phase3/`.

Solo al superar todos los controles escribe `benchmark.json` y `baseline.json`
en el estado local GaiaTransformer. No sobrescribe benchmarks existentes ni inicia
búsqueda. La carga verificada exige misma configuración, runtime, spec y hashes.
Resultado: `GPU_BENCHMARK_READY`, no autorización de campaña. Detalle:
[validación histórica Fase 3](VALIDACION_GAIA_TRANSFORMER_FASE_3.md).

### Campaña GPU y puertas (Fases 4–5)

```bash
python3 gaia.py gaia-transformer-prepare --minutes 15
python3 gaia.py gaia-transformer-run --max-experiments 1 --minutes 15
```

Ambos requieren un benchmark congelado de `gaia-transformer-benchmark` y vuelven a ejecutar
G0-G5. `gaia-transformer-prepare` no propone candidatos; `gaia-transformer-run` añade propuestas,
cribado, cinco pares de confirmación y publicación de versiones solo si gana.
Los presupuestos incluyen preparación. El estado y ledger GPU permanecen
independientes del motor CPU, cuyo comando sigue siendo `run`.

La campaña siempre vuelve a preparar; un JSON READY guardado no omite pruebas.
Errores detienen la ejecución con logs, `result.json` y `NEEDS_HUMAN.json` en el
informe de campaña. STOP y presupuesto producen `STOPPED` en ese informe.
Los ensayos sin cierre por interrupción se recuperan como aborted, salvo un
commit de versión completo con evidencia aceptada. Los IDs no se reutilizan.
Detalle histórico: [validación Fases 4–5](VALIDACION_GAIA_TRANSFORMER_FASES_4_5.md).

### Observación GPU (Fase 6)

```bash
python3 gaia.py gaia-transformer-observe --steps 100
```

Requiere benchmark calibrado y campeón existente (`gaia-transformer-prepare` lo inicializa).
No repite todas las puertas ni propone candidatos: valida la identidad congelada,
mide un trial normal y perfila el mismo campeón en otro sandbox, con NVML y límites
locales. Los steps medidos admiten 10..300, además de 25 de calentamiento; valores
altos pueden agotar el límite normal de 20 s y fallar con reporte, sin elevarlo.

El observador compara tres entrenamientos frescos normales y uno instrumentado,
exigiendo igualdad de pesos, gradientes, pérdidas y logits. Mide once fases con
pared sincronizada y eventos CUDA, inicialización/evaluación y memoria externa.
Registra la sobrecarga para no atribuirla al coste del campeón.

Resultado: `GPU_OBSERVATION_READY`. Informe legible y JSON en
`.gaia/reports/<id>/observation/`, con `observation.json`, `observer_metrics.json`,
`reference_trial/` y `result.json`. El ledger añade un evento de observación;
campeón, benchmark y recompensas de búsqueda no cambian. Los diagnósticos y cotas
de Amdahl orientan investigación, no demuestran mejoras. Detalle:
[validación histórica Fase 6](VALIDACION_GAIA_TRANSFORMER_FASE_6.md).

### Investigación GPU (Fase 7)

```bash
python3 gaia.py gaia-transformer-research --minutes 10
python3 gaia.py gaia-transformer-run --max-experiments 1 --minutes 15 --research-after 2
```

El segundo comando usa un umbral reducido explícito para pruebas. El valor normal
es 40 experimentos completos sin mejora; abortados y errores no cuentan. Después
de un disparo se exige otro intervalo completo antes de repetirlo para el mismo
campeón. `research.enabled=false` en configuración desactiva el disparo automático.

Cada ciclo observa de nuevo, estima cotas y contrasta familias implementadas.
Actualmente: operaciones foreach de optimizador y clipping. La calidad y coste
se contrastan en el laboratorio normal, no en el perfilado. Si una opción no cabe
en la cota mínima estimada del 5%, se poda sin medir candidatos. Solo `supported`
con pares verificables desbloquea la opción en propuestas del mismo campeón.

Familias apoyadas, refutadas o podadas no se repiten para la misma fuente de
campeón. Una inconclusa admite como máximo dos contrastes, política fijada antes
de ejecutarse. La memoria y conteos previos por familia proceden del ledger;
ningún veredicto relaja la aceptación ni publica un campeón desde Modo B.

Los informes quedan bajo `.gaia/reports/<id>/research/`, o dentro de `campaign/`
si el disparo fue automático. Incluyen hipótesis completas, observación, pares,
veredicto y opciones antes/después. Fallos de runtime/infraestructura detienen
el ciclo con diagnóstico y no se interpretan como mejora. Una invocación sin
familias pendientes termina correctamente sin repetir perfilado ni contrastes;
los probes habituales del bootstrap siguen ejecutándose.

Detalle histórico: [validación Fase 7](VALIDACION_GAIA_TRANSFORMER_FASE_7.md).

### Metaestrategia GPU (Fase 8)

```bash
python3 gaia.py gaia-transformer-meta
```

Es un estudio separado con protocolo fijado, no una campaña de promoción de
entrenadores. Materializa dos paisajes GPU de nueve genomas y tres semillas por
genoma/tarea, más referencias de calidad. El ajuste usa solo la primera tarea;
la selección se guarda antes de medir una segunda tarea con otra regla de
continuación. Los replays tienen los mismos topes de consultas y pared virtual.

El estudio conserva caché e identidad verificadas. Si se interrumpe tras registrar
la selección, reanuda la prueba reservada sin volver a elegir estrategia. Tras
completarse, el holdout v1 no se reutiliza: otra ronda requiere protocolo/tareas
nuevos, no borrar registros para conseguir aceptación.

Solo si supera la estrategia anterior y azar en holdout, además del criterio de
ajuste, se guarda `strategy_gpu.json`. La campaña carga esa política verificando
la evidencia; el campeón y benchmark de modelos no cambian. En este equipo el
resultado fue `GPU_META_COMPLETE`, estrategia v1 adoptada y preparación posterior
correcta. Los datos crudos, selección y comparaciones están en los informes.
Detalle histórico: [validación Fase 8](VALIDACION_GAIA_TRANSFORMER_FASE_8.md).

## Creación sin privilegios

Antes de tocar el entorno de destino se prueban los módulos `venv`, `ensurepip`,
`ssl`, `zlib`, `ctypes` y `resource` con el Python de arranque bajo `-I`.

1. Con `venv` y `ensurepip`, se usa el creador estándar.
2. Si falta alguno, se descargan wheels de virtualenv y sus dependencias a una
   caché del proyecto. Sus URLs, versiones y SHA-256 están fijados en
   `gaia/bootstrap_tools.json`.
3. Se verifican **todas** las descargas antes de crear el entorno. Las herramientas
   se ejecutan desde un directorio temporal privado, sin instalarlas globalmente.
4. Virtualenv usa su pip incluido, sin actualizaciones periódicas ni descargas
   adicionales para sembrarlo. Los datos auxiliares también quedan en el proyecto.
5. NumPy se instala con el pip del entorno, desde PyPI y solo mediante wheels.
6. Se comprueba el cálculo NumPy y la igualdad del runtime normal/aislado `-I`.

No se ejecuta `sudo`, no se instalan paquetes del SO ni drivers. En Debian/Ubuntu
`python3-venv` es una alternativa opcional, no un requisito del arranque automático.
Si al Python le faltan SSL, zlib, ctypes o resource, se indica que hace falta un
intérprete completo; el bootstrap no puede reparar esas bibliotecas del sistema.

## Entornos, configuración y campañas

- `.gaia/venvs/<perfil>-<huella>/`: entorno local.
- `.gaia/configs/<huella>.json`: configuración local derivada de `gaia.json`.
- `.gaia/bootstrap-cache/`: herramientas verificadas y datos de virtualenv.
- `state_numpy_mlp_<huella>/`: campaña local independiente.
- `.gaia/reports/<fecha>-<id>/`: informe y logs de cada ejecución.

La huella incluye hardware, identidad de host seudonimizada, versión de Python,
perfil, catálogo y configuración del usuario. Otro equipo o una configuración
distinta seleccionan un estado nuevo. El arranque automático sustituye únicamente
la ruta de estado de `gaia.json` por la ruta local derivada; nunca borra `state/`
ni reutiliza la calibración histórica. Las puertas protegen la identidad después
de la preparación y no se llama automáticamente a `prepare --refreeze`.

`GAIA_LOCAL_CONFIG` solo se aplica si pertenece a `.gaia/configs/` de la raíz
que se está cargando. Otras raíces y los proyectos temporales de tests cargan
su propio `gaia.json` o los valores por defecto.

Los entornos creados parcialmente se pueden completar al reintentar. No se borran
campañas ni carpetas desconocidas. Un bloqueo de kernel evita aprovisionamientos
simultáneos y se libera también si el proceso muere. Los subprocesos que exceden
su timeout se terminan junto con su grupo de procesos.

El modo manual sigue disponible con `python3 gaia.py --no-bootstrap <comando>`:
usa el intérprete actual y el estado de la configuración manual. Es útil para
reproducir un entorno específico; requiere gestionar sus dependencias.

## Fallos y recuperación

`report.json` y `REPORT.md` contienen detección, preflight, perfil y motivo de
selección, configuración, versiones instaladas, descargas, comandos, duración,
códigos de salida, causa y siguiente acción. Cada etapa tiene stdout/stderr
completos en archivos separados. No se vuelcan las variables de entorno.

Si no hay red o falla un certificado/hash, se detiene la provisión y se conserva
la evidencia; no se omite la verificación ni se usa el pip global. Las herramientas
ya verificadas se reutilizan sin red. Para precargarlas se pueden copiar los wheels
exactos del catálogo a `.gaia/bootstrap-cache/wheels/`; esto solo cubre las
herramientas de creación, no la instalación inicial de NumPy desde PyPI.
Un entorno ya instalado puede usarse sin conexión.

El código `40` indica fallo del bootstrap. `30` indica puertas/identidad inválidas
en el CLI. Los códigos normales de campaña se conservan: `10` ayuda humana,
`20` presupuesto agotado y `130` parada manual. En `bootstrap`, un fallo del
subproceso de preparación se comunica como `40`, con el código original en el
informe. Ante un fallo experimental se revisan los logs y `readiness_failed.json`;
no se cambian automáticamente los criterios de aceptación.

## Validación en el ordenador de migración

El 15-10-2026 se verificó el flujo con Intel i7-4790, unos 15 GiB de RAM,
GTX 1060 de 6 GiB y Python 3.14.4 **sin ensurepip**:

- Recuperación del entorno parcial del intento anterior mediante virtualenv 20.35.4.
- Instalación de NumPy 2.3.5 sin privilegios y probes normal/aislado correctos.
- Suite completa: 56 pruebas, incluidas descargas corruptas, falta de red,
  timeout, perfiles incompatibles y exclusión mutua.
- G0-G5: todas PASS; `READY_FOR_CAMPAIGN` en un estado local nuevo.
- Ensayo de campaña de un experimento: candidato rechazado y salida normal por
  presupuesto (`20`).

Los informes reales quedaron en `.gaia/reports/`. Esta validación corresponde al
workload NumPy/CPU, no a GaiaTransformer/CUDA ni a otros sistemas operativos.
