# Contrato experimental: GaiaTransformer/CUDA v1.1

Las mediciones y cierres de implementación fechados antes del 16-10-2026 que
aparecen abajo son históricos de TinyGPT, no ejecuciones nuevas con esta identidad.
Los nombres operativos se actualizan; nueva validación en
`VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Este documento define el laboratorio del workload `gaia_transformer_cuda` antes de
implementar el entrenador. Su versión es `gaia_transformer_cuda/v1.1`. Cualquier cambio a
una regla de este documento exige una intervención humana, un estado nuevo y
una recalibración completa.

Revisión humana del 15-10-2026, autorizada al migrar de ordenador: sustituye el
anclaje al entorno y GTX 1050 anteriores por un perfil Pascal resuelto y probado
en la GTX 1060. No existía una campaña de este workload; su primera baseline y calibración
se crearán desde cero. Las métricas, semillas y reglas de promoción se conservan.

## Frontera de autonomía

GAIA puede generar, medir y promover entrenadores candidatos. Puede variar solo
los parámetros y componentes expuestos explícitamente por el genoma GaiaTransformer que
se implementará en la Fase 4.

GAIA no puede modificar durante una campaña el evaluador, benchmark, worker,
guard, protocolo de aislamiento, puertas G0-G5, corpus, criterios de aceptación
ni el libro de evidencia. La metaoptimización puede elegir entre estrategias de
búsqueda previamente implementadas y se adopta solo mediante comparación
pareada en tareas no usadas para selección.

## Identidad y estado

- Workload: `gaia_transformer_cuda`.
- Versión de contrato: `gaia_transformer_cuda/v1.1`.
- Espacio de estado reservado: `state_gaia_transformer_cuda/`; las campañas locales usarán
  `state_gaia_transformer_cuda_<huella>/`, independiente por equipo, perfil y configuración.
- La Fase 0.1 solo escribe entorno, configuración e informes bajo `.gaia/`; no
  crea directorios de campaña, corpus, baseline ni benchmark.
- El estado histórico MLP/CPU permanece en `state/` y no se reutiliza.
- Todas las rutas de estado deben ser un único directorio relativo a la raíz del
  proyecto; no se permite compartir, anidar ni salir del proyecto.

## Datos sintéticos

El vocabulario es el conjunto de bytes `0..255`. El corpus se generará de forma
determinista a partir de una especificación versionada y se guardará su SHA-256
en la identidad experimental antes de calibrar.

- La generación no usa red, reloj, aleatoriedad global ni ficheros externos.
- Train y validación se generan desde semillas y dominios independientes.
- La validación se divide en ejemplos de `context + 1` bytes no solapados.
- El worker recibe los contextos de validación, nunca sus bytes objetivo.
- La generación exacta y su digest están implementados y verificados en Fase 1:
  `gaia/gaia_transformer/data.py` y `gaia/gaia_transformer/corpus_v1.json`. Se especifican en
  `docs/CORPUS_GAIA_TRANSFORMER_V1.md`. Digest conjunto:
  `11d89e90478527ba77648d5a45be459c55133e12bb1b4463adf3901cb5d44285`.
  Estos archivos formarán parte del manifiesto protegido del laboratorio GPU;
  no se permite iniciar una campaña sin comprobarlos.

## Métrica y promoción

La calidad es la pérdida media de entropía cruzada next-token sobre los targets
privados de validación. Menor es mejor. El proceso padre calcula la métrica a
partir de logits producidos por el candidato; el candidato no recibe los
targets.

La calibración fijará el objetivo como la calidad de la baseline más una
tolerancia explícita. Un candidato debe alcanzar el objetivo en todas las
semillas de confirmación. La promoción exige además que el límite superior del
IC unilateral del 95% del cociente de coste pareado sea menor que `0.95`.

El coste será el tiempo de pared sincronizado de inicialización, entrenamiento y
las evaluaciones privadas necesarias para detectar el primer logro sostenido.
No se excluye trabajo de CUDA de la métrica.

## Determinismo y recursos

- El runtime se obtiene del perfil `gaia-transformer-cuda-pascal` del catálogo
  `gaia/bootstrap_profiles.json`, no de una ruta de intérprete histórica. El
  perfil inicial admite Linux x86_64, CPython 3.14 estándar, glibc >= 2.28,
  driver NVIDIA >= 560.28.03 y GPU Pascal (capacidad 6.0, 6.1 o 6.2).
- Se fija PyTorch `2.14.0+cu126` y NumPy `2.3.5` mediante
  `requirements/gaia-transformer-cuda-pascal-py314.lock`: todas las dependencias de runtime
  llevan versión y SHA-256; la wheel Torch procede del índice oficial CUDA 12.6.
  No se utiliza el Torch global. La versión exacta y el hash del binario Python,
  el hash del lock y los paquetes instalados se registran en el informe local.
- Antes de usarlo, el runtime debe ejecutar kernels, forward/backward y una
  actualización numérica en la GPU seleccionada por UUID. Debe reproducir
  salidas y gradientes entre procesos normal/aislados `-I`. La lista de cubins
  debe cubrir la capacidad de GPU (p. ej. `sm_60` es compatible con `sm_61`);
  no basta con `torch.cuda.is_available()`.
- Solo fp32: fp16 y bf16 quedan fuera del espacio de búsqueda en Pascal.
- `torch.use_deterministic_algorithms(True)` es obligatorio.
- `CUBLAS_WORKSPACE_CONFIG=:4096:8` es obligatorio.
- TF32 y autotuning no determinista quedan desactivados.
- Cada trial usa un proceso nuevo, semillas explícitas y una GPU fijada.
- Presupuesto inicial: 20 s por candidato, 3000 MB de RSS, 3000 MB de VRAM,
  500 MB de disco y 60 minutos por campaña. El perfil local puede reducir RAM y
  VRAM según los recursos detectados antes de congelar la identidad; no puede
  elevar automáticamente estos topes. El espacio para instalar el entorno es
  independiente del presupuesto de disco de campaña.
- Toda frontera de medición CUDA debe sincronizarse antes y después.

## Semillas y evidencia

- Cribado: semilla `0`.
- Confirmación: semillas `1000` a `1004`.
- Auditoría: semillas `5000` a `5005`.
- Calibración: semillas `9000` a `9004`.

La identidad congelada incluirá: versión del contrato, digest del corpus,
runtime de padre y worker, GPU y driver, configuración de determinismo,
presupuestos, benchmark, baseline y hashes de todos los archivos protegidos.

## Criterio de la Fase 0

La Fase 0 queda cerrada cuando este contrato está presente, el soporte de estado
por workload está probado y no existía ninguna campaña de este workload inicializada.

## Validación de plataforma (Fase 0.1)

El perfil pasó en la GTX 1060 de 6 GiB con driver 580.178.04 y CPython 3.14.4,
sin sudo ni ensurepip. Evidencia y comandos en
`docs/VALIDACION_CUDA_FASE_0_1.md`. El resultado `CUDA_ENVIRONMENT_READY` habilita
el desarrollo de Fase 1; no equivale a `READY_FOR_CAMPAIGN` ni valida todavía un
entrenador, aislamiento de targets o laboratorio GPU.

## Baseline ejecutable (Fase 1)

`python3 gaia.py gaia-transformer-baseline` comprueba entrenamiento y reproducibilidad
del GaiaTransformer base, con corpus congelado, GPU seleccionada por UUID y procesos
nuevos. El padre calcula entropía cruzada sobre targets que no se serializan en
los inputs del worker. No inicializa `Store`, benchmark, campaña ni promoción.

La baseline conocida usa `D=64`, `L=2`, `H=2`, `T=64`, `B=32`, dropout 0,
AdamW (`lr=0.003`, `weight_decay=0.01`, betas 0.9/0.999, eps 1e-8, sin fused ni
foreach) y clipping de norma 1.0. El entrenamiento verifica 100 pasos por defecto.
No son hiperparámetros seleccionados automáticamente; el objetivo de calidad
experimental sigue pendiente de calibración en Fase 3.

Resultado de cierre actual: `GAIA_TRANSFORMER_BASELINE_READY`. Evidencia histórica:
`docs/VALIDACION_GAIA_TRANSFORMER_FASE_1.md`. El ejecutor de confianza de Fase 1 no
constituye todavía el laboratorio de candidatos ni sus puertas G0-G5.

## Laboratorio GPU (Fase 2)

Implementado en `gaia/gaia_transformer/lab/`. El protocolo de candidatos es
`Candidate(train, seed)`, `train(steps)` y `predict(contexts)`, con un modelo
CUDA/fp32 en `candidate.model`. Los logits de validación deben ser arrays NumPy
float32 finitos `N x 256`. El worker no recibe targets ni objetivo de calidad.

El padre mide inicialización (incluidos arranque/importación/CUDA), entrenamiento,
predicción y cómputo privado de pérdida. Cada operación del worker sincroniza CUDA
antes y después, y solo entonces responde. El coste acumulado incluye las
evaluaciones necesarias para detectar el logro sostenido: no se retrotrae al
primer acierto omitiendo la segunda comprobación.

El laboratorio requiere bwrap por defecto: vista de filesystem mínima, runtime
read-only, directorio privado de trabajo, una GPU por UUID, namespaces de usuario,
PID, red, IPC y UTS, y capacidades descartadas. El generador del corpus, los
informes y el proceso padre no son accesibles dentro de esa vista. El filtro AST
es preventivo y no sustituye este aislamiento del SO.

Un monitor externo comprueba RSS del árbol de procesos, VRAM total por PID vía
NVML, disco y deadline de pared. Las magnitudes `_mb` usan MiB. Muestrea memoria
y disco cada 20 ms (y en cada respuesta); no es una cuota dura de VRAM impuesta
por el kernel. Se conserva además el límite del allocator Torch y límites CPU,
tamaño de archivo y core dumps del SO. La pérdida de telemetría invalida el trial.

Cada trial registra hashes del candidato, corpus y archivos del laboratorio,
comprueba la identidad esperada al comenzar y su continuidad al terminar. Cualquier
error, aborto, OOM o exceso de recursos produce `valid=false` y `cost_s=null`.
Los procesos se terminan/recolectan y los inputs/logits temporales se eliminan.

El laboratorio histórico pasó en este ordenador. Resultado `GPU_LAB_READY`,
sin calibración ni campaña; detalle en `docs/VALIDACION_GAIA_TRANSFORMER_FASE_2.md`.
La identidad persistente de campaña y `READY_FOR_CAMPAIGN` siguen pendientes.

## Benchmark calibrado (Fase 3)

Especificación `gaia_transformer_benchmark/v1` en `gaia/gaia_transformer/lab/calibration.py`:
referencia de 100 pasos, máximo 300, evaluación cada 25 y dos aciertos consecutivos.
El objetivo se fija como la peor pérdida final de las cinco semillas de calibración
más tolerancia absoluta 0.05. No se reajusta tras observar confirmación/auditoría.

Cribado con semilla 0 y rechazo si el coste supera 1.3x la referencia actual;
confirmación con cinco pares intercalados en semillas 1000..1004. Todos los
trials deben ser válidos, alcanzar el objetivo y conservar alineación de semillas.
El IC se calcula sobre log-ratios, t unilateral 95%, df=4. RAM y VRAM medianas
>1.25x derivan a alternativa Pareto, nunca ascenso. Auditoría reservada: seis
semillas 5000..5005 en validation y audit, sin usarlas para ajustar el objetivo.

La fiabilidad exige cinco ejecuciones válidas, CV <= 20%, warmup <= 1.35,
deriva <= 35% y coste >= 0.06 s. El control nulo no debe ser aceptado; el
control lento exige límite inferior unilateral 95% del ratio >1.02. La aplicación
continua de deriva/saturación durante búsqueda se integrará con las puertas.

Benchmark y fuente baseline se guardan en `state_gaia_transformer_cuda_<huella>/` solo
tras superar los controles. La carga verificada comprueba runtime, configuración,
spec, hashes del laboratorio y baseline. Recalibrar requiere otro estado;
el comando no sobrescribe benchmarks existentes. Todavía no hay campeón ni
versiones promovidas, ni `READY_FOR_CAMPAIGN`. Evidencia de 71 trials:
`docs/VALIDACION_GAIA_TRANSFORMER_FASE_3.md`.

## Campaña y puertas CUDA (Fases 4–5)

El ciclo GPU está implementado en `gaia/gaia_transformer/campaign.py`, con genoma conocido
en `genome.py` y versiones/ledger en `campaign_store.py`. Comandos separados:
`gaia-transformer-prepare` verifica G0-G5 y devuelve `READY_FOR_CAMPAIGN`; `gaia-transformer-run`
repite esas puertas antes de realizar propuestas. No usa el motor MLP ni modifica
la calibración para adaptarse a candidatos.

El genoma expone dimensión, capas, heads compatibles, batch, lr, weight decay,
dropout y AdamW/SGD, conservando contexto, vocabulario y fp32. Propuestas inéditas
con hipótesis, UCB por operador a partir de evidencia persistida y recompensa solo
por aceptación pareada. El candidato nunca modifica el verificador.

La publicación exige cinco pares válidos, calidad en todos, ratio superior IC95%
<0.95 y tolerancia de RAM/VRAM. Se verifica correspondencia de fuente/genoma y
hashes de los trials, se escribe versión completa y se actualiza CURRENT
atómicamente. Recuperación tras interrupción no valida ensayos parciales ni
reutiliza IDs. Los temporales propios se recuperan bajo lock.

La identidad incluye benchmark, runtime/configuración, campeón, fuentes de
campaña y tests de corrección. Se controlan deriva/saturación por experimento;
errores detienen la campaña y generan evidencia para intervención humana. No se
han observado promociones GPU reales en los ensayos de cierre, solo rechazos
correctos. Modo B y metaoptimización GPU permanecen pendientes. Evidencia:
`docs/VALIDACION_GAIA_TRANSFORMER_FASES_4_5.md`.

## Observación separada (Fase 6)

`gaia-transformer-observe` valida la identidad y perfila el campeón actual con un observador
de confianza separado del worker/evaluador de promoción. No modifica archivos
protegidos, spec ni objetivo, y no promueve ni genera recompensa de búsqueda.
La salida se registra como evidencia `observation` en el ledger.

Mide fases de entrenamiento mediante AST sobre la estructura conocida de step;
si esa estructura cambia, falla en vez de asignar etiquetas incorrectas. La
instrumentación debe conservar pesos, gradientes, pérdidas y logits respecto a
entrenamientos frescos sin instrumentar. Si coinciden las actualizaciones totales,
exige además igualdad de logits con un trial normal independiente.

Se reportan pared sincronizada, intervalos de stream CUDA, sobrecarga, memoria y
paridad. Las fracciones instrumentadas y sus proyecciones de Amdahl son hipótesis
diagnósticas, nunca costes válidos para aceptar candidatos. El ruido de entrenamiento
caliente se distingue del ruido histórico de trials completos; la escasez de
historial se conserva explícitamente. Evidencia: `docs/VALIDACION_GAIA_TRANSFORMER_FASE_6.md`.

## Investigación GPU (Fase 7)

`gaia/gaia_transformer/research.py` formula hipótesis explícitas de familias conocidas,
con mecanismo, evidencia de perfil, cota ideal estimada, coste, riesgo, regla de
aceptación y falsación. No modifica el laboratorio ni su objetivo de calidad.
Familias iniciales: foreach para optimizador y clipping, registradas en el
renderer como extensiones cerradas al buscador ordinario.

Cribado campeón/candidato en semilla 0 y cinco pares intercalados de confirmación
son obligatorios para apoyar una ampliación. No basta una aceleración aparente:
IC95% superior <0.95, calidad 5/5 y RAM/VRAM <=1.25x. Un límite inferior >=0.95
refuta la mejora práctica; un intervalo no concluyente no permite desbloqueo.
La cota de Amdahl se usa para podar, no para aceptar. El clipping de norma sigue
siendo obligatorio; su opción foreach no elimina la operación.

La memoria se identifica por SHA-256 de fuente del campeón y familia. Apoyadas,
refutadas y podadas no se repiten en esa identidad. Inconclusas admiten como máximo
dos contrastes. Los conteos previos por familia priorizan trabajo, sin alterar
umbrales estadísticos. El desbloqueo recalcula la decisión y comprueba hashes de
fuentes comparadas antes de exponer una opción en el genoma de propuestas.

La campaña dispara investigación tras 40 experimentos completos sin mejora,
salvo umbral explícito de política de búsqueda mediante `--research-after N`.
Modo B registra evidencia y opciones; únicamente Modo A puede promover después
de su propia comparación. Evidencia real: dos contrastes inconclusos, una poda,
cero desbloqueos y cero promociones (`docs/VALIDACION_GAIA_TRANSFORMER_FASE_7.md`).

## Estudio separado de metaestrategias (Fase 8)

Protocolo `gaia_transformer_meta/v1`: catálogo de nueve genomas conocidos, cuatro variantes
de parámetros del selector UCB, 20 semillas de búsqueda de ajuste y 40 reservadas
para prueba. Cada replay dispone de cuatro consultas y 90 s de pared virtual;
una consulta usa las mediciones de tres trials GPU. La puntuación es el AUC por
consulta del log-coste de la mejor opción observada respecto a baseline.

Se materializan tareas `periodic_tune` y `counter_holdout`, con corpus/digests
fijados en `meta_tasks_v1.json`. La segunda cambia la regla de continuación y
solo se mide tras registrar la selección. El evaluador conserva el mismo
bytecode, worker, guard, sandbox, monitor, métrica y coste; un binding de datos
propio, con identidad separada, evita cambiar globals o archivos del laboratorio
congelado de campaña. Sus objetivos se calibran aparte y no sustituyen el objetivo
de producción ni autorizan promociones de modelos.

La adopción exige ventaja práctica AUC >0.01 y límite superior pareado <−0.01:
crítico t=3.0 con 20 semillas de ajuste; t=2.023 con 40 en holdout frente a anterior
y azar (dos comparaciones con corrección Bonferroni al 5% nominal). Estas pruebas
son condicionales a los paisajes medidos, no intervalos sobre todas las tareas o
el ruido de hardware. Selección persistida antes de holdout, reanudación sin
reajuste y bloqueo de reutilización tras consumirse forman parte del protocolo.

Solo se adopta una política, no un entrenador. `search_strategy.load` recalcula
los contrastes desde puntuaciones y comprueba identidad/evidencia antes de que la
campaña use los parámetros. Una política v1 fue adoptada con evidencia limitada
al catálogo y tareas del estudio; la preparación posterior cargó v1 y pasó G0-G5.
El campeón histórico sigue en v0000. Detalle: `docs/VALIDACION_GAIA_TRANSFORMER_FASE_8.md`.
