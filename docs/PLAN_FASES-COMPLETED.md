# Plan por fases de GAIA v2

Status: Historical — not current operational guidance

> Registro histórico completado el 15-10-2026 bajo identidad TinyGPT. Conserva
> identificadores, rutas y comandos originales como procedencia histórica;
> para uso actual véanse BOOTSTRAP.md y PLAN_RENOMBRADO_GAIA_TRANSFORMER.md.

## Decisión de autonomía

GAIA puede modificar y seleccionar automáticamente el entrenador TinyGPT que
genera como candidato. El laboratorio experimental permanece protegido:
evaluador, benchmark, reglas de aceptación, aislamiento, puertas G0-G5 y
persistencia de evidencia no se modifican durante una campaña.

La mejora del buscador se permite únicamente por metaoptimización comparada. Un
cambio en el laboratorio protegido requiere una intervención humana explícita,
una nueva identidad experimental y recalibración.

No se comienza una fase hasta cerrar sus dependencias y criterios de cierre.

Las puertas CUDA de Fase 5 son transversales: sus comprobaciones de runtime y
corrección se desarrollan junto a Fases 1–3 y deben estar resueltas antes de una
campaña autónoma de Fase 4. El smoke test de Fase 0.1 no sustituye esas puertas.

## Fase 0: Contrato experimental

- Definir qué puede mutar GAIA y qué archivos quedan protegidos.
- Separar definitivamente el estado histórico MLP/CPU del nuevo workload
  TinyGPT/CUDA.
- Congelar corpus sintético, semillas, métrica, presupuestos y política de
  determinismo.

Cierre: especificación reproducible y estado nuevo para TinyGPT; no se reutiliza
`state/` del workload CPU.

**Estado: CERRADA.** Contrato vigente: `tinygpt_cuda/v1.1` en
`docs/CONTRATO_TINYGPT_CUDA_V1.md`, revisado el 15-10-2026 tras cambiar de equipo.
El estado reservado TinyGPT sigue vacío de campañas; los estados CPU permanecen
independientes. Suite actual: 145 pruebas descubiertas (136 ejecutadas en el perfil
NumPy y 9 de modelo verificadas además en el perfil Torch/CUDA).

## Fase 0.1: Perfil CUDA local resuelto

- Detectar GPU, driver, VRAM, Python, ABI y glibc antes de instalar.
- Aprovisionar un entorno sin sudo con dependencias exactas y hashes.
- Verificar kernels CUDA, forward/backward, flags y repetibilidad numérica entre
  un proceso normal y dos procesos `-I` con entorno mínimo.
- Seleccionar GPU por UUID y derivar límites locales de RSS/VRAM.
- Registrar evidencia sin inicializar baseline, benchmark ni campaña TinyGPT.

Cierre: `CUDA_ENVIRONMENT_READY` en la máquina de destino y suite sin regresiones.

**Estado: CERRADA (15-10-2026).** Perfil `tinygpt-cuda-pascal`: CPython 3.14.4,
PyTorch `2.14.0+cu126`, GTX 1060 6 GiB / capacidad 6.1, driver 580.178.04.
Instalación sin privilegios, kernels y gradientes repetibles, diagnóstico posterior
sin reinstalar paquetes, 67 pruebas superadas. Detalle:
`docs/VALIDACION_CUDA_FASE_0_1.md`.

## Fase 1: TinyGPT base ejecutable

**Estado: CERRADA (15-10-2026).** `python3 gaia.py tinygpt-baseline` ejecuta
TinyGPT fp32 con 120576 parámetros, `D=64, L=2, H=2, T=64, B=32`, corpus
`structured_bytes/v1` y validación privada calculada en el padre. Tres procesos
CUDA: dos repeticiones de semilla 9000 idénticas en pesos, gradientes, logits y
pérdidas; otra semilla 9001 también reduce loss. Se verificó causalidad en CPU y
GPU. Evidencia: `docs/VALIDACION_TINYGPT_FASE_1.md`.

- Implementar TinyGPT byte-level determinista en CUDA.
- Partir de `D=64`, `L=2`, `H=2`, `T=64`, `B=32`, medida en el equipo anterior;
  verificar de nuevo calidad, memoria y tiempos en el equipo local.
- Crear corpus sintético estructurado y separar registros train/validación sin
  compartir ventanas ni entregar targets privados al entrenador (el vocabulario
  de bytes es común).
- Verificar entrenamiento, descenso de loss, reproducibilidad entre procesos y
  uso de la GPU seleccionada por UUID (actualmente GTX 1060).

Cierre: baseline entrenable y evaluable repetidamente, sin búsqueda todavía.

## Fase 2: Laboratorio de evaluación GPU

**Estado: CERRADA (15-10-2026).** `python3 gaia.py tinygpt-lab` valida el nuevo
laboratorio `gaia/tinygpt/lab/`: protocolo protegido, métricas privadas en el
padre, sincronización CUDA, sandbox bwrap y monitor externo RSS/VRAM/disco/tiempo.
Pasaron 17 escenarios reales en la GTX 1060, incluidos errores, OOM, timeout,
límites de recursos y limpieza. La baseline reproduce los logits de Fase 1.
Evidencia: `docs/VALIDACION_TINYGPT_FASE_2.md`.

- Adaptar worker, evaluador, guard y benchmark a PyTorch/CUDA.
- Mantener los targets de validación solo en el proceso padre.
- Sincronizar CUDA antes y después de cada región medida.
- Registrar inicialización, entrenamiento, evaluación, RSS, VRAM y configuración
  CUDA.

Cierre: un trial GPU aislado produce métricas válidas, detecta errores y no
permite fuga de validación.

## Fase 3: Benchmark y promoción

**Estado: CERRADA (15-10-2026).** `python3 gaia.py tinygpt-benchmark` completó
71 trials GPU: calibración en cinco semillas, fiabilidad 5/5, controles nulo/lento,
cribado y confirmación pareada, auditoría con seis semillas reservadas en dos
splits. Objetivo congelado: CE <= 0.2596790841. CV de coste 1.24%; control lento
2.318x (límite inferior unilateral 95% 2.279x); ningún falso ascenso del control
nulo. Benchmark y baseline guardados en el estado local TinyGPT, con identidad
verificable. Evidencia: `docs/VALIDACION_TINYGPT_FASE_3.md`.

Las reglas de aceptación están implementadas; aún no se ha promovido ningún
candidato real. La escritura de versiones/campeón y búsqueda se integran en
Fase 4, condicionadas a las puertas de campaña de Fase 5.

- Calibrar la baseline con múltiples semillas.
- Fijar el objetivo de calidad con una métrica next-token definida en la Fase 0.
- Mantener cribado barato, confirmación pareada intercalada y auditoría con
  semillas no usadas para selección.
- Definir saturación, deriva térmica, ruido y límite de resolución.

Cierre: baseline pasa fiabilidad y controles; una variante artificialmente lenta
se mide inequívocamente más lenta.

## Fase 4: Modo A, automejora

**Estado: CERRADA (15-10-2026).** `tinygpt-run` propone genomas válidos conocidos,
aprende estadísticas UCB por operador y usa el laboratorio congelado para cribado
y cinco pares de confirmación. Ledger persistente, publicación atómica de versiones,
recuperación de IDs y rollback implementados. Dos candidatos reales rechazados por
estadística; campeón `v0000`. Dos pruebas reales con SIGKILL recuperadas como
`aborted`, sin promoción ni reutilización de IDs; limpieza de temporales verificada.
Evidencia: `docs/VALIDACION_TINYGPT_FASES_4_5.md`. `run` continúa siendo la entrada
del motor MLP; el ciclo GPU tiene su comando explícito.

- Sustituir el genoma MLP por un genoma TinyGPT con combinaciones válidas.
- Espacio inicial: `lr`, `batch`, `weight_decay`, `dropout`, optimizador,
  dimensiones y profundidad compatibles.
- Excluir fp16/bf16 y opciones sin soporte útil en Pascal.
- Ejecutar el ciclo de propuesta, cribado, confirmación, promoción o rechazo y
  aprendizaje estadístico por operador.

Cierre: campaña autónoma corta completa, ledger coherente, recuperación tras
interrupción y una promoción o rechazo estadísticamente verificable.

## Fase 5: Puertas G0-G5 para CUDA

**Estado: CERRADA (15-10-2026), integrada como prerrequisito de Fase 4.**
`python3 gaia.py tinygpt-prepare` devuelve `READY_FOR_CAMPAIGN` en la GTX 1060.
Las seis puertas se vuelven a ejecutar antes de cada campaña GPU: runtime/kernels,
corrección sin tests omitidos, repetibilidad numérica 5/5, integridad, controles
pareados nulo/lento y presupuestos. Se vigilan deriva/saturación por experimento.
El benchmark no se modifica ni recalibra para conseguir un PASS.

- G0: runtime padre/worker, GPU, kernels reales y determinismo.
- G1: causalidad, formas, gradientes finitos, ausencia de fuga y
  reproducibilidad.
- G2: fiabilidad del campeón en ejecuciones repetidas.
- G3: integridad de workload, corpus, renderer, benchmark y baseline.
- G4: control nulo y control lento en GPU.
- G5: límites de tiempo, RAM, VRAM, disco y experimentos.

Cierre: `tinygpt-prepare` devuelve `READY_FOR_CAMPAIGN` para TinyGPT;
`prepare` conserva su significado CPU para evitar mezclar workloads.

## Fase 6: Observabilidad para Modo B

**Estado: CERRADA (15-10-2026).** `python3 gaia.py tinygpt-observe` observa el
campeón de la campaña real en un proceso CUDA separado bajo bwrap/NVML. Mide
once fases, inicialización/evaluación, repetibilidad, sobrecarga y memoria, y
diagnostica coste, resolución, ruido y cobertura del ledger. La instrumentación
conservó pesos, gradientes, pérdidas y logits; los logits coinciden con un trial
normal independiente al mismo número de pasos. Benchmark/campeón intactos,
evento `observation` persistido sin recompensa ni promoción. Evidencia:
`docs/VALIDACION_TINYGPT_FASE_6.md`.

- Crear un perfilador específico para TinyGPT.
- Medir muestreo, forward/backward, optimizador, evaluación, inicialización y
  memoria.
- Diagnosticar cuellos de botella, resolución del benchmark, repetición de
  regiones, candidatos informativos y ruido.

Cierre: diagnóstico basado en datos medidos de una campaña real.

## Fase 7: Modo B, investigación autónoma

**Estado: CERRADA (15-10-2026).** `tinygpt-research` observa, formula hipótesis
con cota de Amdahl, contrasta en el laboratorio y conserva memoria por fuente de
campeón/familia. Una ampliación solo se propone tras evidencia apoyada verificable;
Modo B nunca promueve. Disparo automático validado con `--research-after 2`
(predeterminado 40), tras pasar G0-G5. Dos contrastes GPU de optimizer_foreach
inconclusos, clipping podado por cota <5%, ninguna opción desbloqueada. Una tercera
invocación no repitió las familias. Evidencia: `docs/VALIDACION_TINYGPT_FASE_7.md`.

- Formular hipótesis con mecanismo, cota esperada, coste, riesgo y criterio de
  falsación.
- Contrastarlas usando exactamente el laboratorio de Modo A.
- Registrar evidencia apoyada, refutada o inconclusa.
- No repetir hipótesis refutadas para el mismo campeón.
- Ampliar el espacio de búsqueda solo cuando una hipótesis esté apoyada.

Cierre: una meseta dispara investigación, deja evidencia y condiciona las
propuestas posteriores.

## Fase 8: Automejora del buscador

**Estado: CERRADA (15-10-2026), con evidencia acotada a paisajes cacheados.**
`tinygpt-meta` materializó 60 trials GPU en dos tareas con reglas de continuación
distintas y comparó cuatro estrategias con presupuestos equivalentes. Selección
registrada antes de medir holdout; 20 semillas de ajuste y 40 reservadas de búsqueda.
La estrategia v1 superó a v0 y azar en holdout según AUC de log-coste y se adoptó
como política parametrizada. `tinygpt-prepare` cargó v1 y pasó G0-G5 después.
No se promovió un modelo: campeón v0000. Evidencia y límites de inferencia:
`docs/VALIDACION_TINYGPT_FASE_8.md`.

Esto no demuestra mejora recursiva general: el adaptador de estrategias se prueba
en un catálogo finito de nueve genomas y dos tareas sintéticas, condicionado a
los costes medidos. La eficacia en el espacio abierto de campañas requiere más
evidencia; no se extrapola este resultado a LLM ni tareas arbitrarias.

- Comparar estrategias contra la estrategia anterior y contra azar en tareas no
  usadas para selección.
- Ajustar parámetros de estrategia mediante comparación pareada, sin modificar
  el verificador.
- Promover una estrategia solo si su mejora es verificable y transferible.

Cierre: informe que distinga mejora real, resultado inconcluso y sobreajuste al
benchmark.
