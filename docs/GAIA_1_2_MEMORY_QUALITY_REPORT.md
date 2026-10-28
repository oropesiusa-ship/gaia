# GAIA 1.2 — Memoria útil, contexto adaptativo y calidad conversacional

## Decisión

Este incremento está `REAL_WORLD_TESTED` en el host de referencia.
`GAIA_1_2 = NOT_CERTIFIED`: la mejora de memoria está demostrada, pero la calidad
general no alcanza todavía un umbral de release y conserva fallos objetivos.

## Evaluación reproducible

`tools/benchmark_chat_quality.py` congela ocho comprobaciones objetivas:
español/formato, instrucción exacta, aritmética, coding básico, resistencia a
alucinación, recuerdo dentro de conversación, actualización de un hecho y
recuperación entre conversaciones. Dos muestras abiertas —explicación en español
y ayuda de código— se guardan como `NOT_SCORED`; no se convierten en puntos.

El scoring distingue exactitud semántica de obediencia de formato. Un dato
correcto con prosa adicional puede aprobar recuerdo y fallar `format_pass`.

## Comparación A/B real a 4K

Ejecuciones secuenciales, mismo SmolLM3-3B Q4_K_M, KoboldCpp 1.123.1, Vulkan,
sampling determinista y workload. La única variable es memoria recuperable.

| Métrica | 4K sin memoria | 4K con memoria |
| --- | ---: | ---: |
| Aciertos objetivos | 5/8 | 6/8 |
| Formato estricto | 4/8 | 4/8 |
| Recuperación entre conversaciones | FAIL | PASS |
| Mediana de latencia | 1,033 s | 1,044 s |
| Fallos runtime | 0 | 0 |
| Pico RAM descendientes | 580,9 MB | 581,7 MB |
| Incremento VRAM observado | 2,524 GB | 2,525 GB |

Ganancia objetiva: **+12,5 puntos porcentuales**, con ~1,0% de aumento en la
mediana de latencia y recursos prácticamente iguales. Sin memoria, el modelo
respondió `ORION`; con una memoria recuperada respondió correctamente
`NEBULA_77`. Por ello embeddings/RAG permanecen `NOT_JUSTIFIED`: no existe aún
evidencia de que compensen su complejidad frente al índice léxico determinista.

## Memoria y aislamiento

- Reutiliza `CONVERSATION` y `CHAT_TURN` inmutables; no crea resúmenes inventados.
- Sólo indexa turnos `USER` de otras conversaciones con el mismo `owner_id`.
- Ranking por términos normalizados, determinista, top-3 y máximo 1600 caracteres.
- Cada resultado conserva referencia, términos coincidentes y autoridad `NONE`.
- La conversación actual se excluye; una prueba separada verifica que `alice` no
  recupera memoria de `bob`.
- `owner_id` es aislamiento lógico de una CLI local, no autenticación multiusuario.

## Contexto adaptativo

Perfiles permitidos: 4K, 8K y 16K. 4K sigue siendo default. 8K exige presión de
historial >6000 caracteres y presupuesto de latencia >=30 s; 16K exige >12000 y
>=65 s. Los límites medidos de TTFT y VRAM están en `context_policy.py`. Una carga
fallida de 8K/16K puede bajar una vez a 4K; una generación incierta no se repite.
32K no se intenta.

Prueba real adaptativa: con 8829 caracteres de historial, GAIA eligió 8K, procesó
4277 tokens, incluyó 13 turnos completos, recuperó exactamente `AURORA_808` y
respondió en 15,557 s. Fallback disponible: 4K; no fue necesario.

## Experiencia de chat

`gaia chat` añade selección `auto`, `--latency-budget`, `--no-memory`,
`--inspect-context`, `--list-sessions`, identidad `--user`, `/context` y cambio de
contexto durante una sesión cuando crece el historial. Los errores contractuales
usan códigos comprensibles. Continúan prohibidos tool calls, shell, red y autoridad
de ejecución del modelo.

## Evidencia negativa

- Español: devolvió `blue` en vez de `azul`.
- Aritmética: devolvió `0.7391` en vez de `391`.
- Actualización y memoria fueron semánticamente correctas, pero a veces añadieron
  prosa pese a pedir salida exacta.
- La ayuda de código quedó truncada por el límite de 96 tokens.
- El primer A/B paralelo no sirve para comparar recursos por solapamiento de GPU.
- No se ejercitaron embeddings, RAG, autenticación multiusuario, estrés concurrente
  real, calidad general ni contexto superior a 16K.

## Auditoría y regresión

- Auditor offline: `tools/audit_chat_quality.py`.
- Resultado: PASS, 11/11 checks (schema, tareas, scores, runtimes, mejora,
  atribución de memoria, adaptación 8K y autoridad).
- Suite completa: 1205 tests, 9 skips, PASS.
- Log SHA-256:
  `1329a405c116d0f1e7164e2c75fa6d30243267bd4e1d3c835f63f5f3d2a0718c`.
- Procesos supervivientes: ninguno.

Evidencia compacta:
`local_intelligence_evidence/GAIA_1_2_MEMORY_QUALITY_V1.json`.
