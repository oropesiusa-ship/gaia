# GAIA 0.8 — Local Intelligence Discovery, Runtime Bake-off & LLM Integration

## Estado y alcance

**PASS de etapa para descubrimiento, cualificación e inferencia local acotada.**
Selección con claim **BEST_BALANCED_TESTED**, sustentada por mediciones finales,
integración real, auditoría portable y suites. Sin merge ni release.
Rama `feat/gaia-0.8-local-intelligence`, desde
`44f80e00d00c2b140d3c03f0fb6c6fc97fb097db` / `gaia-v0.7-external-research`.
Autoridad conceptual: [Documento Maestro v3](GAIA_MASTER_ARCHITECTURE_V3.md).

La capacidad implementada es inferencia cognitiva local acotada y explícita,
con descubrimiento del ecosistema, cualificación y selección basadas en evidencia.
No constituye mejora del LLM, inteligencia general, memoria cognitiva, RAG,
planificación autónoma ni autoridad para ejecutar propuestas del modelo.

## Arquitectura y autoridad

`gaia/local_intelligence/` es un subsistema separado de evolución CPU, evaluadores,
publication, rollback y los componentes GPU/appliance congelados.

| Módulos | Responsabilidad |
| --- | --- |
| `schema`, `store` | Artefactos inmutables, identidades canónicas y autoridad NONE |
| `profile` | Perfil y presupuestos derivados de observation validada |
| `discovery`, `registry` | Research 0.7, catálogo extensible y desconocidos explícitos |
| `qualification` | Elegibilidad estática y transiciones con evidencia |
| `artifacts`, `gguf` | Descarga oficial fijada, extracción pasiva e inspección de cabecera |
| `isolation`, `runtime_worker` | Runtime privado, sin red externa ni respuestas esperadas |
| `backend`, `model_adapter` | API estable y templates de familias cualificadas |
| `benchmark`, `campaign` | Workload protegido, puntuación externa y telemetría |
| `selection`, `controller`, `cli` | Pareto, selección persistida e inferencia explícita |

Flujo: observation → perfil → presupuesto → research → catálogo → evaluación
estática → descarga/instalación → smoke → compatibilidad → benchmark →
cualificación → selección → inferencia de datos.

Los registros ensamblados retrospectivamente lo indican: no se inventa una fecha
anterior para una verificación posterior. Cada descarga original conserva su
recibo; la revalidación posterior de los metadatos se añade como otro artefacto.

## Host observado y límites

Observation 0.2 es la fuente del host; no se usa un detector de hardware paralelo.
Se amplía modularmente `observation/runtime.py` con herramientas de inferencia,
versiones numéricas allowlist y resumen Vulkan acotado.

- Intel i7-4790, cuatro núcleos físicos / ocho lógicos, AVX2 y FMA.
- Aproximadamente 14,99 GiB de RAM; presupuesto de RSS del runtime:
  **6.941.849.600 bytes**, derivado del 70 % de la RAM disponible observada.
- GTX 1060 6GB, compute capability **6.1**, driver **580.178.04**.
- No se observaron compilador/CMake/Ninja/nvcc ni `vulkaninfo` utilizables.
  La ausencia de `vulkaninfo` queda como falta de evidencia inicial; la prueba
  real del runtime es la que establece offload Vulkan.

Presupuesto revisado explícitamente y ligado al perfil: tres paquetes runtime,
tres modelos descargados en total, dos modelos retenidos simultáneamente,
doce stacks, cinco configuraciones por modelo, ocho threads, contexto 1024,
generación máxima 96, tres repeticiones, smoke 120 s y benchmark 900 s.
Artefactos únicos descargados: techo **10.159.433.318 bytes**; disco:
**12.699.291.648 bytes**. Se conserva el presupuesto anterior y la razón de revisión.

Se retiran únicamente el modelo pequeño y el paquete CUDA reproducibles después
de sus fallos; el registro RETENTION conserva hashes, tamaños y motivo. La
evidencia no se elimina. No hay instalación global, root, recompilación de driver,
modificación del kernel ni scripts remotos ejecutados.

## Research real y cobertura

Capturas públicas actuales del **21-10-2026** mediante GAIA 0.7, con autorización
de request y opt-in global efímero. Catálogo: **40 proyectos runtime** y **65
modelos**. El presupuesto de investigación es 192 requests, 128 fuentes y
64 MiB decodificados; cada nueva adquisición se restringe al remanente.
Consumo real final: **161 requests**, **100 fuentes**, **2.146.606 bytes**
decodificados. No se requieren nuevos fetches para reproducir la auditoría.

Se investigan GGUF, CPU, CUDA, Vulkan, ONNX, compilados, GPTQ/AWQ/EXL,
low-bit especializado, MoE, serving e híbridos. Semillas: llama.cpp, KoboldCpp,
mistral.rs, MLC, ONNX Runtime GenAI, ExLlamaV2/V3, CTranslate2, BitNet,
ktransformers, vLLM, SGLang, TensorRT-LLM, LocalAI, llamafile y Ollama.
Las búsquedas abiertas descubren proyectos fuera de la lista, incluyendo Strata,
PolyStrata, MemVanta, vlut.cpp y chorus-llm. La lista es extensible, no exhaustiva.

Las búsquedas son endpoints públicos de metadatos con parámetros acotados,
sin claves ni query arbitraria. Continúan las restricciones SSRF, DNS público,
socket fijado, TLS, redirects, robots, bytes y deadlines de 0.7.
Internet conserva autoridad de instrucciones NONE.

El catálogo distingue core runtime, fork, compilado, wrapper, frontend y serving.
KoboldCpp es un fork de ascendencia llama.cpp, no un motor independiente de ésta.
mistral.rs utiliza Candle y sí aporta otra familia de cómputo medida.
Las menciones en README no se convierten en soporte empírico. Licencias,
arquitecturas o capacidades ausentes permanecen UNKNOWN; no se inventa soporte.

### Desambiguación de Strata y descartes

- `Niko1221/Strata`: el bundle por defecto documenta al menos 32 GB combinados
  RAM+VRAM y alrededor de 80 GB de disco. El bundle no cabe en los recursos
  observados; no se afirma incompatibilidad universal del engine ni de modelos
  alternativos no cualificados.
- `ro99/strata`, `VecSzn/PolyStrata`, `robertkarl/UnbiasedStrata` y
  `hongfaqiu/strata-manager` son proyectos distintos; se registran upstream,
  commit y relación de wrapper/fork cuando hay evidencia.
- Resultados no LLM se separan como fuera de alcance, sin contarlos como motores.
- vLLM documenta CUDA CC ≥7.5: la GPU 6.1 incumple ese backend. Esto no prueba
  incompatibilidad de vLLM CPU.
- Los proyectos no medidos quedan sin cualificación empírica, limitados por el
  presupuesto de paquetes, modelos, builds y configuraciones. No son descartes
  universales de calidad o compatibilidad.

## Artefactos realmente utilizados

Runtimes oficiales: **mistral.rs v0.9.5 CPU**, **KoboldCpp v1.123.1 nocuda**
(CPU/Vulkan) y **KoboldCpp v1.123.1 oldpc** (CUDA12). Los metadatos capturados
atestiguan URL, versión, tamaño y SHA-256. El ejecutable extraído de mistral.rs
se comprueba también frente al miembro del archivo oficial, no frente al hash
del archivo comprimido.

| Modelo | Formato / cuantización | Bytes de pesos | SHA-256 |
| --- | --- | ---: | --- |
| Qwen3-0.6B | GGUF Q8_0 | 639.446.688 | `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` |
| SmolLM3-3B | GGUF Q4_K_M | 1.915.305.312 | `8334b850b7bd46238c16b0c550df2138f0889bf433809008cc17a8b05761863e` |
| Gemma4-E4B | GGUF QAT Q4_0 | 5.154.941.280 | `676c35070db6dbe52f93e9c864ee0fba4eddea94b9c875d9cb10daff453fbaee` |

Los modelos se fijan a commits y hashes LFS de los árboles HF capturados.
El tokenizer adicional de SmolLM3 para Candle también tiene commit, hash y
montaje de sólo lectura. Gemma4 se evalúa exclusivamente en texto, sin mmproj.
No se deducen efectos aislados de cuantización de pesos al comparar familias
distintas. Sí se compara KV f16/q8_0 con los mismos pesos SmolLM3.

## Aislamiento, fallos y límites de confianza

`bwrap` obligatorio: namespaces user/pid/net/ipc/uts, capacidades eliminadas,
root/runtime/model RO, home/workspace no montados, trabajo privado y sólo los
devices GPU necesarios en configuraciones aceleradas. Handshake real compara
namespaces con el padre y verifica montajes RO y ausencia de `/home`.
El worker sólo ve pesos, runtime, soporte de tokenizer y prompts; no el scorer,
respuestas esperadas, estado GAIA, evaluadores ni credenciales.

Límites AS/CPU/core/file size y deadline padre, monitor RSS de descendientes y
disco privado muestreado. Los monitores son límites supervisados, no cuotas
atómicas de cgroup ni garantías contra kernel/driver comprometidos. El cómputo
de CPU-seconds considera los threads; no se confunde tiempo CPU multihilo con
deadline wall-clock. Todo fallo conserva evidencia y no bloquea otros candidatos.

El paquete CUDA inicia, pero sus logs reportan fallo de inicialización CUDA.
El fallback CPU no se cuenta como aceleración CUDA verificada. Vulkan exige
device `Vulkan0` y capas offloaded no cero. El modelo pequeño falla el guard
de calidad y no puede ganar por ser rápido.

## Benchmark y comparabilidad

Nueve tareas verificables: instrucciones, JSON, razonamiento, comprensión de
código, precisión técnica, incertidumbre, resumen fundamentado, intención de
herramienta y frontera de fuente. Tres retrievals de contexto (64/256/640 unidades
de padding) y throughput. Cada configuración completa ejecuta **39 requests**,
**36 puntuados**, tres repeticiones. Guard: calidad ≥0,75, JSON ≥0,90 y cero
requests fallidos. JSON se compara con tipos estrictos: `true` no equivale a `1`.

La calidad se puntúa fuera del sandbox. Se recalculan workload completo, scorer
y estadísticas al seleccionar; duplicar o suprimir tareas no produce un ganador.
La estabilidad se calcula entre repeticiones del mismo workload de rendimiento,
no mezclando latencias de tareas distintas. STABLE requiere tres muestras y CV
≤0,10. NOISY y MISSING_EVIDENCE se conservan.

Comparabilidad **aproximada**, incluso con el mismo GGUF, prompts, contexto y
greedy: Candle CPU rechaza seed explícita y usa seed null; implementaciones KV,
telemetría y tokenizadores pueden diferir. La elección de KV es observada en logs.
TTFT es un upper bound al primer evento de contenido; SSE bufferizado no mide
el primer token exacto. Throughput nativo se distingue de proxies del stream.
No se inventan tok/s o token counts ausentes en mistral.rs. RAM es RSS sumada
de descendientes, con páginas compartidas; VRAM incremental es muestreo del
device completo respecto al baseline, no atribución perfecta por proceso.
La latencia de las tablas es con el modelo cargado; los recibos separan carga
nativa, carga total del adapter (incluyendo hashes) y duración cold-call de la
API. El controller actual carga y descarga por llamada; throughput warm no es
la latencia total percibida en esa llamada fría.

## Resultados finales y selección

La serie definitiva comprende **ocho configuraciones cualificadas**, cada una
con su propio smoke y 39 requests completos. Hay dos familias de cómputo reales
(Candle y ggml/llama.cpp-derived), dos modelos finalistas y doce configuraciones
únicas contando el modelo pequeño y el intento CUDA anteriores. Se ejecutan
serialmente, antes de la suite completa. El manifiesto identifica esa serie;
no se mezclan intentos antiguos ni se elige la repetición más rápida.

Todos los finalistas puntúan **33/36 (91,67 %)** y completan los 39 requests sin
errores. Las métricas son descriptivas de los casos probados, no intervalos de
confianza sobre tareas generales.

| Runtime / modelo | Backend / offload / KV | JSON | Latencia perf. mediana (s) | Media tarea calidad (s) | Decode tok/s | RSS pico (GiB) | VRAM incr. (GiB) | Latencia |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| KoboldCpp / SmolLM3 | Vulkan 37/37, f16 | 100 % | 2,171 | 0,749 | 40,26 | 0,54 | 2,14 | STABLE |
| KoboldCpp / SmolLM3 | Vulkan 37/37, q8_0 | 100 % | 2,270 | 0,778 | 38,55 | 0,54 | 2,11 | STABLE |
| KoboldCpp / SmolLM3 | Vulkan 18/37, f16 | 100 % | 11,558 | 1,800 | 7,23 | 1,42 | 1,27 | STABLE |
| KoboldCpp / Gemma4 | Vulkan todas, f16 | 100 % | 2,694 | 0,836 | 32,13 | 3,12 | 3,27 | STABLE |
| KoboldCpp / Gemma4 | Vulkan 21 capas, f16 | 100 % | 14,883 | 2,442 | 5,54 | 4,32 | 2,04 | STABLE |
| KoboldCpp / SmolLM3 | CPU, f16 | 100 % | 19,560 | 4,729 | 4,66 | 2,08 | 0 | STABLE |
| mistral.rs / SmolLM3 | CPU, KV no verificado | 90,91 % | 18,676 | 5,515 | MISSING_EVIDENCE | 6,30 | 0 | STABLE |
| KoboldCpp / Gemma4 | CPU, f16 | 100 % | 25,660 | 6,273 | 3,48 | 5,66 | 0 | NOISY |

**Primary:** KoboldCpp **v1.123.1 nocuda**, **SmolLM3-3B Q4_K_M**, Vulkan
con todas las capas offloadables, KV f16, contexto 1024 y ocho threads.
Selección persistida: `lia02f893b5c87c4b4880e8fc0`;
benchmark primary: `li756122ac074a7b07b10cccec`.

**Secondary CPU:** el mismo modelo/runtime en CPU, sin devices GPU montados.
**Secondary low-VRAM:** el mismo modelo/runtime con 18 capas Vulkan.
Son alternativas registradas; el controller no degrada silenciosamente el backend.

Frontera epsilon-Pareto: `stack-a424bbb1c10e43df`, `stack-6d06e7be6d3d867a`,
`stack-113ae9aa21f705e8` y `stack-1c3a9e80ca6cbedf`. Refleja trade-offs
descriptivos de los finalistas; no prueba dominancia estadística universal.
Las dimensiones NOISY permanecen visibles y no habilitan un primary.

Política visible: calidad/reliability/JSON/intención antes que latencia, memoria
y complejidad; primary exige latencia STABLE. Frontera epsilon-Pareto con banda
relativa 5 % y tolerancia de calidad 0,005. Diferencias de velocidad dentro de
la banda no prueban superioridad; entre equivalentes se prefiere KV f16.
El techo de claim es **BEST_BALANCED_TESTED**, nunca BEST_AVAILABLE.

## API y CLI

`LocalIntelligenceBackend`: load/unload, generate, structured_generate,
tokenize/count cuando el runtime lo soporta, health, capabilities y metrics.
Las funciones cognitivas permitidas son ANSWER, EVIDENCE_SUMMARY,
DIAGNOSIS_EXPLANATION y STRUCTURED_TRANSFORM. Las evidencias externas y diagnosis
se validan y delimitan como datos; una explicación generada no cambia el diagnóstico
determinista ni establece causalidad.

Integración real verificada después del bake-off: health READY, tokenización
de prueba de cinco tokens, tres funciones cognitivas estructuradas y la CLI
operativa. Las salidas fueron `{"ready":true}`,
`{"instruction_authority":"NONE","execute":false}` y
`{"causality":"NOT_ESTABLISHED"}`; la CLI reprodujo `{"ready":true}`.
Un quinto recibo conserva el rechazo real `INPUT_CONTEXT_BUDGET` al exceder el
contexto. Hay cuatro inferencias OK y una FAILED esperada, cero tool calls,
cero cambios de policy y cero trials de evolución. Los tests adversariales
comprueban también que JSON con una supuesta llamada shell sigue siendo dato
y que el JSON malformado falla sin ejecutar acciones.

```sh
.venv-observation/bin/python -B gaia.py intelligence-observe --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-research --url <public-url> --authorize-network --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-catalog --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-qualify <candidate-id> --backend CPU --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-download <manifest.json> --candidate <eligible-id> --authorize-install --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-install <download-id> --candidate <eligible-runtime-id> --adapter koboldcpp --authorize-install --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-benchmark <stack.json> --authorize-inference --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-select --benchmark <benchmark-id> --coverage <coverage-id> --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-generate --selection latest --prompt 'Return only JSON {"ready":true}.' --structured --authorize-inference --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-results --kind SELECTION --state-dir state_local_intelligence
.venv-observation/bin/python -B gaia.py intelligence-show <id> --state-dir state_local_intelligence
```

Los defaults deshabilitan red, instalación e inferencia implícitas. Los flags son
opt-ins explícitos por operación; no conceden al modelo autoridad sobre tools,
research, configuración, código, seguridad, evaluación o publicación. Los fallos
de inferencia producen artefacto FAILED y exit 2. No existe fallback sin sandbox.

## Evidencia, auditoría y regresión

Export portable: [local_intelligence_evidence/](local_intelligence_evidence/).
`tools/audit_local_intelligence.py` no hace DNS, descargas o inferencia: verifica
hashes, observación, fuentes, versiones, descargas, límites, scorer, estadísticas,
aislamiento final y selección/Pareto reproducidos.

Auditoría portable **PASS**: 968 documentos / 6.425.542 bytes, 726 artefactos
locales, 100 fuentes y ocho benchmarks finales. El replay también pasa con
DNS, socket connect y ejecución de procesos denegados. Una copia alterada del
export se rechaza por hash; los bytes originales permanecen intactos.
Privacy check de los 968 documentos: sin username/hostname/home/ruta privada
del proyecto. Los valores privados usados para comprobarlo no se exportan.

Regresión byte a byte: **568 de 576 archivos originales idénticos**. Los ocho
cambios originales son dispatch/defaults, ampliación observation y extensión
modular research. Evaluadores/evolución/frozen, defaults anteriores y
`experimental_config` permanecen idénticos. Recibos: `audit.json`,
`offline-checks.json`, `privacy.json` y `regression.json`.

Suite completa con `-B -W error::ResourceWarning`: **726 recogidos, 715
ejecutados, 11 skips conocidos, cero fallos, errores, warnings o ResourceWarnings
unraisable**, en **744,189 s**. Se mantienen las dos exclusiones administrativas
históricas (Prueba A real y campaña autónoma) y los nueve skips Torch ausente,
sin nuevas campañas de evolución.

Desglose de esa misma ejecución completa, sin repetir suites innecesariamente:

| Subconjunto | Recogidos | Ejecutados | Skips | Fallos / errores / warnings |
| --- | ---: | ---: | ---: | --- |
| Local intelligence, nuevos | 25 | 25 | 0 | 0 / 0 / 0 |
| External research | 69 | 69 | 0 | 0 / 0 / 0 |
| Observation | 34 | 34 | 0 | 0 / 0 / 0 |
| Diagnosis | 46 | 46 | 0 | 0 / 0 / 0 |
| Prioritization | 39 | 39 | 0 | 0 / 0 / 0 |
| Learning | 52 | 52 | 0 | 0 / 0 / 0 |
| Experiment strategy | 55 | 55 | 0 | 0 / 0 / 0 |
| Crítico v0.1 | 171 | 170 | 1 | 0 / 0 / 0 |
| Completa | 726 | 715 | 11 | 0 / 0 / 0 |

`tests.json` conserva el recibo completo, exclusiones exactas, desglose por módulo,
hashes de logs y hash de los tests nuevos. `verification.json` enlaza manifiesto,
auditorías, regresión, privacidad, tests, informe y fuentes finales. Los logs
completos son custodia administrativa externa, no runtime portable ni nuevos
certificados de automejora CPU.

## Limitaciones

Survey dirigido y finalistas presupuestados, no ranking exhaustivo del ecosistema.
Un benchmark pequeño no demuestra razonamiento general ni seguridad semántica
de todos los outputs. Las funciones producen datos no fiables; JSON válido no
garantiza verdad. No hay tool execution, investigación autorizada por el modelo,
training, distillation, LoRA aplicada, modificación de pesos, publicación ni
medición de aumento de inteligencia general. Los resultados pertenecen al host,
versiones, contexto y configuraciones fijados en los recibos.

En particular, SmolLM3/KoboldCpp devuelve `{"total":10}` en el problema de cuentas
cuyo resultado correcto es 17; Gemma4 devuelve `{"value":10}` en el ejercicio de
Python cuyo resultado es 6. Ambos errores se repiten y permanecen puntuados como
fallos. Un 33/36 global no significa que ambos modelos resuelvan los mismos casos
ni que se haya demostrado capacidad matemática o de programación general.
