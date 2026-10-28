# GAIA 1.2 — Local Intelligence Maximization

## Estado

Primer incremento sobre la base 1.1 certificada: `INTEGRATION_TESTED`.
No constituye todavía certificación final de GAIA 1.2.

Rama: `feat/gaia-1.2-local-intelligence`, creada desde el cierre 1.1
`3875713a4d3a5256febf438a9d3b08f1dc81979e`.

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
este host. Calidad general de memoria, contexto largo >1024, diálogo autónomo
multi-sesión y certificación 1.2 permanecen `NOT_EXERCISED`.

## Regresión

- 62 tests cognition: PASS.
- 25 tests local intelligence: PASS.
- Suite completa: 1198 tests, 9 skips, PASS.
- Log: `/tmp/opencode/gaia-1.2-35eacd2-full-suite.log`.
- SHA-256: `30f845caf0236a027b16bf409ea5f2d2e8e90c9594b8b6909bb6d6053e0c1643`.
