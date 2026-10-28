# GAIA 1.2 — Contexto ampliado y chat local

## Resultado

Incremento `REAL_WORLD_TESTED` en este host. GAIA mantiene una conversación
local persistente real con un contexto operativo de **4096 tokens**, cuatro veces
el límite cualificado de 0.8. No es todavía una certificación integral de 1.2.

## Origen del límite anterior

El límite 1024 no procedía del modelo. El GGUF declara 65.536 tokens y
KoboldCpp acepta `--contextsize`; 0.8 había fijado conservadoramente
`max_context=1024` en el presupuesto de cualificación y en la pila seleccionada.
La selección 0.8 permanece intacta. 1.2 crea una variante explícita con los mismos
hashes de runtime/modelo, backend, aislamiento y límites de autoridad.

## Barrido controlado

| Contexto | Input ejercitado | Recuperación | TTFT aproximado | Decisión |
| ---: | ---: | --- | ---: | --- |
| 1024 | 756 | PASS | 3,62 s | baseline |
| 2048 | 1614 | PASS | 6,89 s | funcional |
| 4096 | 3286 | PASS | 12,02 s | funcional |
| 8192 | 6652 | PASS | 24,19 s | funcional, lento |
| 16384 | 13028 | PASS | 54,65 s | máximo funcional observado |
| 32768 | 26146 | TIMEOUT | sin primer token | no funcional bajo timeout actual |

La prueba de calidad temprana/media/reciente y corrección de un dato se repitió
dos veces por escalón: 2K, 4K y 8K obtuvieron 2/2 PASS. Medianas TTFT: 5,39 s,
10,38 s y 22,23 s respectivamente. Se selecciona **4096** como óptimo inicial:
cuadruplica contexto manteniendo calidad completa y evita la duplicación de espera
de 8K. El mayor contexto no se declara automáticamente mejor.

## `gaia chat`

Se añadió un chat interactivo y un modo `--message` reproducible. Cada turno:

1. persiste primero el input de usuario;
2. proyecta turnos completos con conteo exacto y reserva de output;
3. genera dentro del runtime aislado;
4. persiste la respuesta o un `CHAT_FAILURE` inmutable;
5. mantiene autoridad `NONE`, cero tool calls y red aislada.

Prueba real mediante cuatro procesos CLI separados sobre la conversación
`cgc81c5d806f017f9d15d79c5e`:

- se registra `LUCERO_42`;
- tras reinicio se recupera exactamente `LUCERO_42`;
- se corrige el alias a `SOLAR_88`;
- tras otro reinicio se recupera exactamente `SOLAR_88`.

El input exacto creció 121 → 190 → 245 → 319 tokens y la latencia API fue
2,07–2,81 s. No quedaron procesos runtime supervivientes.

## Evidencia negativa y límites

- El primer arnés de viabilidad llamó a un método inexistente y no sustenta
  claims de calidad; se conserva como intento fallido.
- El primer diálogo real recordó el alias pero repitió una respuesta anterior;
  motivó separar explícitamente historial y mensaje más reciente. No se reclasifica.
- 32K es `NOT_FUNCTIONAL_UNDER_CURRENT_TIMEOUT`, no PASS.
- 16K es máximo funcional observado, no contexto interactivo recomendado.
- Calidad conversacional general, sesiones largas cerca de 4K, concurrencia real,
  RAG, memoria semántica y contexto >16K permanecen `NOT_EXERCISED`.

Resumen compacto: `local_intelligence_evidence/GAIA_1_2_CONTEXT_CHAT_V1.json`.

## Regresión

- Suite completa: 1201 tests, 9 skips, PASS.
- Log: `/tmp/opencode/gaia-1.2-context-chat-full-suite.log`.
- SHA-256: `994195c0ec9d42c47a0e9b95d86e4b1f61da7d3b550296fb596ba929efb942c7`.
- Procesos runtime/GAIA supervivientes: ninguno.
