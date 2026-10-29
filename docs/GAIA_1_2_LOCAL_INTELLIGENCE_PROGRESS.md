# GAIA 1.2 — Local Intelligence Maximization

## Estado

Primer incremento sobre la base 1.1 certificada: `INTEGRATION_TESTED`.
GAIA 1.2 quedó `CERTIFIED` para el alcance aprobado el 29-10-2026, sin merge,
tag ni release y sin ampliar autoridad del LLM.

El incremento posterior de contexto y chat está `REAL_WORLD_TESTED`: contexto
interactivo seleccionado de 4096 tokens y conversación local persistente real.
Véase `GAIA_1_2_CONTEXT_AND_CHAT_REPORT.md`.

La memoria determinista y el contexto adaptativo están también
`REAL_WORLD_TESTED`: 5/8 → 6/8 en evaluación objetiva 4K y selección real 8K con
4277 tokens. Véase `GAIA_1_2_MEMORY_QUALITY_REPORT.md`.

Rama: `feat/gaia-1.2-local-intelligence`, alineada sobre el merge de cierre 1.1
`563e51193a992c2f983496e3ec627249690f53ee` y publicada sin PR, merge ni tag 1.2.

## Dirección de desarrollo acordada

La evaluación de inteligencia es el punto de partida de la autonomía, no su
destino final. No se descarta ningún componente actual: chat multiturno, memoria,
contexto adaptativo y evaluaciones serán las entradas de ciclos cognitivos
posteriores.

La progresión prevista queda delimitada así:

1. **GAIA 1.2 — inteligencia local medible:** evaluar, detectar fallos, mejorar
   calidad y mantener memoria útil.
2. **Piloto experimental 1.2.x — primer ciclo cognitivo autónomo:** observar
   resultados, priorizar problemas, formular hipótesis, autocriticarlas y preparar
   una agenda de experimentos.
3. **GAIA 1.3 — investigación y experimentación autónomas:** conectar propuestas
   validadas con herramientas autorizadas y los gates del closed loop existente.
4. **GAIA 1.4 — automejora del modelo:** investigar configuraciones, fine-tuning o
   modificaciones de pesos únicamente cuando la evidencia lo justifique.

Esta dirección no amplía los criterios obligatorios de certificación de 1.2.
`GAIA_1_2` permanece `NOT_CERTIFIED` hasta superar sus requisitos originales.

## Piloto cognitivo 1.2.x — alcance separado

El piloto se construirá como experimento independiente de promoción. Su primera
entrada serán los benchmarks persistidos actuales, incluidos los fallos de
español, aritmética y formato. Sin prompts humanos por ciclo, deberá:

1. cargar resultados objetivos y sus referencias;
2. identificar y priorizar un problema respaldado por evidencia;
3. producir hipótesis estructuradas;
4. someterlas a una crítica separada usando el mismo LLM con otro contexto;
5. proponer un experimento reproducible, predicción, métrica y stop condition;
6. pasar un filtro determinista de evidencia, autoridad y presupuesto;
7. persistir hipótesis aceptadas/rechazadas, aprendizaje y siguiente pregunta;
8. detenerse cuando la evidencia sea insuficiente.

Cada propuesta incluirá problema, referencias, hipótesis causal, cambio
experimental, predicción, verificación, presupuesto, autoridad requerida,
incertidumbres y condiciones de parada. Sólo se persistirán conclusiones
estructuradas; no razonamiento oculto ni cadenas de pensamiento.

El piloto no puede ejecutar shell, herramientas, red, cambios de código o pesos,
modificar evaluadores, autorizar experimentos, ampliar presupuestos ni intervenir
en promoción. Sus salidas tienen autoridad `NONE`. Una ejecución futura deberá
entrar exclusivamente por los gates existentes.

Su utilidad se comparará con un selector determinista sencillo mediante:

- hipótesis válidas y sustentadas por evidencia real;
- precisión de referencias;
- experimentos reproducibles;
- respeto de autoridad, presupuesto y stop conditions;
- capacidad de detenerse sin evidencia suficiente;
- coste en tokens, latencia, RAM y VRAM;
- mejora real de selección frente al baseline determinista.

Si el ciclo LLM no supera al selector determinista, no se conservará por su
apariencia de inteligencia. Este piloto puede validarse separadamente, pero no
certifica GAIA 1.2 ni modifica sus requisitos originales.

### Primer incremento del piloto: contrato y baseline determinista

Se implementó el contrato `gaia_research_agenda_v1` y el selector de referencia
`DETERMINISTIC_BASELINE_V1`. Este incremento todavía no es el ciclo LLM y no se
presenta como autonomía validada. Sus límites son deliberados:

- proyecta exclusivamente campos objetivos ya puntuados, sin reinterpretar la
  respuesta generada ni la evidencia negativa;
- referencia cada observación mediante nombre del artefacto, SHA-256 y JSON
  Pointer exacto;
- produce agenda, hipótesis causal marcada como no verificada, crítica,
  predicción, métrica, presupuesto y stop conditions;
- toda salida y propuesta conserva autoridad `NONE`; el experimento requiere un
  gate futuro `LOCAL_COMPUTE`, pero lleva `execute: false` y cero red, cambios de
  fuente, cambios de evaluador o promoción;
- detiene el ciclo con `INSUFFICIENT_FAILURE_EVIDENCE` si no existen fallos
  objetivos o de formato.

Aplicado a `GAIA_1_2_MEMORY_QUALITY_V1.json`, el baseline selecciona primero
`reasoning` (dos fallos objetivos), seguido por `spanish`, y conserva también los
fallos de formato de memoria. La salida reproducible está en
`local_intelligence_evidence/GAIA_1_2_RESEARCH_AGENDA_BASELINE_V1.json`.
Constituye el control contra el que deberá medirse el ciclo LLM; no autoriza ni
ejecuta el experimento propuesto.

### Research Dialogue V1

El primer ciclo real de Investigador, Crítico y Revisor está
`REAL_WORLD_TESTED`. Completó tres llamadas autónomas, conservó autoridad `NONE`
y se detuvo en `MORE_EVIDENCE`. El comparador pre-registrado mantuvo al baseline
determinista como ganador (6/7 frente a 2/7); por tanto no se atribuye utilidad
adicional al LLM. Véanse `GAIA_1_2_RESEARCH_INTELLIGENCE_REPORT.md` y
`local_intelligence_evidence/GAIA_1_2_RESEARCH_DIALOGUE_REAL_V1.json`.

### Diagnóstico de calidad y adaptador experimental

La aritmética fallida se aisló a la representación española de multiplicación:
el control devolvió `0.7391`, mientras `17 * 23` y `17 times 23` devolvieron
`391`. En español, una instrucción inglesa preservó correctamente `azul` donde
el control lo traducía a `blue`. El adaptador V2 obtuvo y replicó 8/8 objetivos y
6/8 de formato, pero permanece `EXPERIMENTAL_NOT_PROMOTED` hasta superar casos
independientes. Véase `GAIA_1_2_QUALITY_DIAGNOSTICS_REPORT.md`.

## Persistencia conversacional

Se añadió custodia persistente y acotada en `gaia/cognition/conversation.py`:

- conversaciones y turnos como artefactos canónicos inmutables;
- secuencia enlazada por hash y referencia al turno anterior;
- reapertura tras reinicio sin reconstrucción mutable;
- lock por conversación y rechazo fail-closed de forks, cadenas desconectadas,
  secuencias ambiguas, symlinks y tampering;
- roles limitados a `USER` y `ASSISTANT`;
- autoridad del contenido y del modelo `NONE`, cero tool calls y sin razonamiento
  oculto almacenado;
- proyección newest-first de turnos completos con tokenizer exacto, reserva de
  output y exclusiones visibles, sin resumen inventado;
- CLI: `cognitive-conversation`, `cognitive-chat-append` y
  `cognitive-chat-history`.

## Baseline local real

La auditoría portable 0.8 vuelve a dar `PASS`: 968 archivos, 100 fuentes,
726 artefactos locales, ocho benchmarks finales y selección
`lia02f893b5c87c4b4880e8fc0` con claim `BEST_BALANCED_TESTED`.

Se cargó el backend seleccionado real, sin red ni tool authority, y se ejecutaron
tres casos de recuperación de la clave `ORBIT_731`:

| Turnos fuente | Incluidos | Excluidos | Tokens input | Latencia | Resultado |
| ---: | ---: | ---: | ---: | ---: | --- |
| 3 | 3 | 0 | 259 | 2,652 s | PASS |
| 9 | 9 | 0 | 793 | 3,391 s | PASS |
| 21 | 10 | 11 | 882 | 2,940 s | PASS |

En el tercer caso la ventana descartó once turnos antiguos completos y conservó
el requerimiento reciente. Evidencia compacta:
`local_intelligence_evidence/GAIA_1_2_CONTEXT_BASELINE.json`.

Clasificación honesta: almacenamiento conversacional `UNIT_TESTED` e
`INTEGRATION_TESTED`; proyección y recall de tres casos `REAL_WORLD_TESTED` en
este host. Contexto >1024 y diálogo generado entre reinicios están ahora
`REAL_WORLD_TESTED`: 16K es el máximo funcional observado y 4K el óptimo
interactivo. Calidad general, RAG, memoria semántica y certificación final
permanecen `NOT_EXERCISED`.

## Regresión vigente

### HEAD `ca473ea` (28-10-2026)

- 84 archivos enumerados; hash de la lista
  `9f25c2b883d92db90e60e44384101c24357c9b543c90ba520eb72c911a9bb5f3`.
- Suite focalizada cognitiva: 101 PASS en 3,467 s.
- Suite global: 1247 PASS, 9 skips, 0 fallos, 0 errores en 1131,315 s.
- Log global: SHA-256
  `e86d2fbab66972a1760c1cbb615860b1869bf965c5aaa9c3fb7740db0e43b939`.
- Evidencia portable:
  `local_intelligence_evidence/GAIA_1_2_FINAL_REGRESSION_CA473EA.json`.

Esta regresión funcional no cambia por sí sola `GAIA_1_2 = NOT_CERTIFIED`: los
adapters V2 y V3 fueron rechazados por sus protocolos reservados y Research
Dialogue sigue por debajo del baseline determinista.

### HEAD funcional `e0d0ae9` (28-10-2026)

- 85 archivos; 1250 PASS, 9 skips, 0 fallos y 0 errores.
- Tiempo: 1144,348 s; `ResourceWarning` tratado como error.
- Log SHA-256:
  `1fff191b2ec3da7d58cdb200d0cc3168a76bdba61db1a019ba132848aec8b7c4`.
- Evidencia portable:
  `local_intelligence_evidence/GAIA_1_2_FINAL_HEAD_REGRESSION_E0D0AE9.json`.

### Evidencia histórica

### Certificación final V2 (`da118a3`)

- Research Direct V7: 8/8 en dos réplicas españolas reservadas.
- Auditor Research V2: PASS; réplica semántica y cero efectos.
- Regresión particionada exhaustiva y addendum: 88 archivos, 1265 PASS, 9 skips.
- Auditor de certificación: `CERTIFIED`, 7/7 checks PASS.
- No se promovieron adapters V2/V3; la política interactiva permanece ORIGINAL.
- Autoridad del LLM: `NONE`; merge/tag/release no autorizados.

### HEAD funcional `b2af752` (29-10-2026)

- 85 archivos; 1257 PASS, 9 skips, 0 fallos y 0 errores.
- Tiempo: 1134,007 s; `ResourceWarning` tratado como error.
- Log SHA-256:
  `82b5f8e08ccc78df0269f8c062230c3d92685fae30d50874cc87bdef21324fbc`.
- Incluye continuidad real multi-problema, diagnóstico de forma sin valores,
  rutas directas y confirmación causal independiente.

- Suite completa: 1205 tests, 9 skips, PASS.
- Auditoría de memoria/calidad: 11/11 checks, PASS.
- Log: `/tmp/opencode/gaia-1.2-memory-quality-final-full-suite.log`.
- SHA-256: `1329a405c116d0f1e7164e2c75fa6d30243267bd4e1d3c835f63f5f3d2a0718c`.
- Procesos supervivientes al cierre: ninguno.
