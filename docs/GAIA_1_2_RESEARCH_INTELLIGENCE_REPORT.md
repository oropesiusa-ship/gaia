# GAIA 1.2 — Research Intelligence V1

## Estado

`REAL_WORLD_TESTED` para un ciclo local de tres roles con parada segura.
`GAIA_1_2 = NOT_CERTIFIED`. Este piloto no ejecuta experimentos, no promueve
resultados y no amplía autoridad.

## Arquitectura

- `research_agenda.py`: observación objetiva y baseline congelado.
- `research_dialogue.py`: Investigador → Crítico → Revisor usando una sola
  instancia del backend local por diálogo. Cada salida se parsea y valida antes
  de entrar en la siguiente etapa.
- `research_comparison.py`: siete criterios pre-registrados e independientes;
  el modelo no puede redefinirlos.
- `research_campaign.py`: continuidad acotada, selección de problemas no
  repetidos, presupuestos, persistencia inmutable y reapertura idempotente.
- `research-campaign`: CLI con una autorización de inferencia al inicio; no pide
  prompts humanos entre iteraciones.
- `audit_research_dialogue.py`: replay offline portable.

Los nuevos artefactos `RESEARCH_DIALOGUE`, `RESEARCH_COMPARISON` y
`RESEARCH_CAMPAIGN` usan el almacén cognitivo inmutable. Los prompts y salidas
estructuradas aceptadas se conservan con hashes. Una salida inválida conserva su
hash y motivo de rechazo, pero no texto libre que pudiera contener razonamiento
oculto. El LLM tiene autoridad `NONE` y los experimentos aceptables siguen
marcados `execute: false`.

## Campaña local real definitiva

Entrada común: `GAIA_1_2_MEMORY_QUALITY_V1.json`, SHA-256
`571f9c261e852c592b948607c1d7740a5946e9cb42ef6b2bdab813e846e62388`.

- contexto: 4096;
- problema seleccionado sin prompt humano: `reasoning`;
- llamadas LLM: 3 (Investigador, Crítico, Revisor);
- reserva: 288 tokens; output reportado: 110 tokens;
- latencia total: 15,33 s;
- hipótesis estructuradas: 1;
- críticas estructuradas: 1;
- revisiones: 1;
- experimentos autorizados o ejecutados: 0;
- parada: `DIALOGUE_STOPPED_MORE_EVIDENCE`.

El Investigador atribuyó el fallo a formato JSON y propuso reforzar la
estructura. El Crítico pidió revisión. El Revisor respondió
`MORE_EVIDENCE`, por lo que no se materializó experimento. Es una abstención
segura, no una mejora demostrada.

## Comparación A/B pre-registrada

| Vía | Puntuación | Resultado |
| --- | ---: | --- |
| `DETERMINISTIC_BASELINE_V1` | 6/7 | Ganador |
| `RESEARCH_DIALOGUE_V1` | 2/7 | Parada correcta; propuesta no útil todavía |

El diálogo no obtuvo crédito por relación causal, falsabilidad, utilidad
experimental, referencias de una propuesta aceptada ni novedad. Sí obtuvo
estructura y respeto de autoridad. No se conserva por apariencia: el baseline
sigue siendo la selección útil vigente.

## Evidencia negativa conservada

Siete ejecuciones reales intermedias documentan eco del contexto, JSON inválido,
campos omitidos y rechazos de Investigador, Crítico y Revisor. La reducción del
wire contract permitió completar los tres roles sin relajar citas, autoridad ni
gates. Están resumidas en
`local_intelligence_evidence/GAIA_1_2_RESEARCH_DIALOGUE_DEVELOPMENT_V1.json`.

## Validación

- 25 tests de investigación: PASS.
- 66 tests cognitivos: PASS.
- auditor offline: 13/13 PASS.
- suite global particionada en `.venv-observation`: 80 módulos, 1233 tests PASS,
  9 skips, 0 fallos y 0 errores. La partición evita el timeout monolítico sin
  omitir módulos; precede a los últimos cambios focalizados de diagnóstico.
- procesos de inferencia supervivientes: ninguno observado tras las campañas.

## Límites demostrados

El ciclo inicia, dialoga, valida, compara, persiste y se detiene sin intervención
por etapa. La campaña controlada de dos iteraciones y su reapertura están
probadas con backend simulado. En hardware real sólo se ejecutó una iteración,
que terminó correctamente por evidencia insuficiente. No se demostró mejora del
modelo, ejecución de cambios, campaña real multi-iteración ni superioridad frente
al baseline.

Artefactos portables:

- campaña real: `GAIA_1_2_RESEARCH_DIALOGUE_REAL_V1.json`, SHA-256 de archivo
  `6fb70e6cda47918c2bb15edae81f36fa3d0ce97d3368c85e7698b8b36f3a966f`;
- desarrollo negativo: `GAIA_1_2_RESEARCH_DIALOGUE_DEVELOPMENT_V1.json`, hash
  interno `d87be5a325bae80deb02bd528aa5d9eee06b06bf0052965021679489165f316b`;
- log de la segunda suite global interrumpida:
  `/tmp/opencode/gaia-1.2-research-full-suite.log`, SHA-256
  `42626bcc191cbf464301f47206f2ee7d9adfc7e72e2f829689acd8a416734ac8`.

## Siguientes objetivos

1. Mejorar la relación semántica entre fallo e hipótesis sin ampliar el límite de
   96 tokens ni alterar el evaluador.
2. Añadir evidencia objetiva diferenciadora para aritmética y español antes de
   permitir que `MORE_EVIDENCE` continúe otra iteración real.
3. Ejecutar la suite completa en una ventana con timeout suficiente y registrar
   su resumen final.

## Transferencia V2 — resultado negativo

Se pre-registraron y ejecutaron tres variantes acotadas con 96 tokens por llamada.
La primera transfirió la objeción completa al Revisor y eliminó el ejemplo que
anclaba `MORE_EVIDENCE`; V2.1 restauró el contrato compacto del Investigador;
V2.2 permitió únicamente un alias de evidencia validado junto a la propuesta.

Las tres campañas reales se detuvieron tras una llamada con
`INVALID_RESEARCHER_SCHEMA` y puntuaron 2/7 frente a 6/7. No hubo red, ejecución,
cambios de evaluador ni promociones. Al no conservarse texto rechazado, no existe
evidencia para ampliar más el parser sin adivinar; esa línea queda rechazada.
La reapertura de V2.2 devolvió exactamente el mismo ID y hash, con un solo diálogo
y una sola comparación, demostrando persistencia e idempotencia tras reinicio.
Evidencia: `GAIA_1_2_RESEARCH_TRANSFER_V2_NEGATIVE.json`, SHA-256
`f12fb7191ec4333d7bf6cde6456e5752dc08d442101446e4fd8178304b941f5f`.

## Vía directa y continuidad real

La alternativa directa pre-registrada se ejecutó en variantes sucesivas, cada
una fijada antes de inferencia. El diagnóstico de forma sin valores reveló salidas
`cause` e `hypothesis` parciales y permitió una reparación de dos llamadas sin
inventar contenido.

- V3.1 obtuvo 7/7 frente a 6/7, pero su intervención de «feedback system» no
  operacionalizaba la causa de representación del operador. Se conserva como
  falso positivo del comparador y no se promueve.
- V4 y V5 produjeron la intervención causal correcta — comparar/reemplazar
  `CONTROL_JSON` por `SYMBOLIC_JSON` — y pasaron la confirmación causal separada,
  pero obtuvieron 6/7 porque el texto generado no incluyó la etiqueta de tarea
  requerida para trazabilidad. No superaron la regla pre-registrada.

Por tanto `RESEARCH_INTELLIGENCE = NOT_PROMOTED`: no existe una candidata que
supere simultáneamente el comparador congelado y la confirmación causal.

La continuidad V3 sí ejecutó una campaña real de dos problemas distintos
(`reasoning` y `spanish`), conservó ambos rechazos y comparaciones, se detuvo por
presupuesto y reabrió con el mismo ID/hash sin nuevas inferencias ni duplicados.
Esto cierra el gate de continuidad H, pero no convierte los rechazos en mejora.
Evidencia: `GAIA_1_2_RESEARCH_CONTINUITY_V3_REAL.json`, SHA-256
`660642f992059119123f10523e5666dd79ce19b177f2685d4118c38a638c7684`.

## Evaluador estructural V2 y holdout V7

El análisis de V3.1–V5 demostró que V1 confundía coincidencia léxica con relación
causal. V1 no fue editado ni usado para revalidar retroactivamente candidatas. Se
pre-registró un evaluador V2 paralelo con ocho criterios, fixtures adversariales,
binding estructural de tarea y reglas causales fijadas antes del nuevo holdout.

V6 falló limpiamente en dos réplicas por JSON inválido. V7 dividió causa e
intervención en dos contratos mínimos de 96 tokens, manteniendo todos los campos
de autoridad, métrica, evidencia y presupuesto bajo binding determinista.

| Ejecución española reservada | V2 score | Llamadas | Tokens reservados | Estado |
| --- | ---: | ---: | ---: | --- |
| V7 run 1 | 8/8 | 2 | 192 | PASS |
| V7 run 2 | 8/8 | 2 | 192 | PASS |

Ambas réplicas produjeron la misma causa e intervención: la interacción entre
instrucción española/casing explica `azul→blue`, y se propone probar el ajuste de
casing preservando el literal español. El auditor offline recomputó 8/8, identidad
de criterios, réplica semántica, presupuestos y ausencia de efectos.

Decisión: `RESEARCH_DIRECT_V7_SPLIT_MINIMAL = ACCEPTED`. Supera el máximo 7/8
del baseline no novedoso bajo V2. Auditoría SHA-256:
`6546dbe2c8f0143b50a390be897724967205b84fb7ec54339ecb368826f26d4c`.
