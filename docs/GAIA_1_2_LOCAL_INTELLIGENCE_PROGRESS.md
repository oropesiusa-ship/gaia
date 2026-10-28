# GAIA 1.2 — Local Intelligence Maximization

## Estado

Primer incremento sobre la base 1.1 certificada: `INTEGRATION_TESTED`.
No constituye todavía certificación final de GAIA 1.2.

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

- Suite completa: 1205 tests, 9 skips, PASS.
- Auditoría de memoria/calidad: 11/11 checks, PASS.
- Log: `/tmp/opencode/gaia-1.2-memory-quality-final-full-suite.log`.
- SHA-256: `1329a405c116d0f1e7164e2c75fa6d30243267bd4e1d3c835f63f5f3d2a0718c`.
- Procesos supervivientes al cierre: ninguno.
