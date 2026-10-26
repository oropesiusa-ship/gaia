# Stage 2 — corrección del gate de ejecución

El `READY_TO_EXECUTE` comunicado para `0867787` fue prematuro. Su contrato de
`.gaia/stage2/ready-20261026T000000/` queda conservado pero **INVALIDADO para ejecución**:
reutilizaba un linaje de Stage 0 y no contenía una orquestación completa.

La corrección no toca fuentes de `gaia/`, evaluadores, benchmarks, thresholds,
policies ni autoridad. Se incorporan un runtime dedicado para S1, ledger agregado
duradero, reservas conservadoras antes de crear campañas, pacing, auditoría,
reconciliación, replay terminal por CLI y contención Linux subreaper/pidfd.

## Revisión independiente

Dos rondas de revisión del ejecutor y una nueva revisión de contención preceden al
launch. La revisión final no encuentra bloqueos adicionales para S1 salvo commit
limpio, contrato nuevo y admisión satisfactoria. Se comprobaron procesos reales de
doble fork/setsid, salida e interrupción, sin terminar el proceso ajeno de control.
Las fixtures son desechables: no son evidencia de campañas de Stage 2.

## Desviaciones declaradas

- Se reservan 1.800 s por campaña; ejecución limitada a 1.740 s, con vigilancia a
  1.770 s para dejar margen de cleanup. La contabilidad cobra el máximo de wall
  supervisado y wall reportado; jamás se devuelve una reserva ambigua.
- Storage se vigila con headroom y stopping/fallo, no mediante una cuota física.
- El runtime sólo autoriza S1: dos campañas NumPy secuenciales y dos slots de una
  hora. No implementa ni inicia S2 automáticamente.
- Una observación correcta de S1 es `S1_OBSERVED`, no PASS de Stage 2.
- Cero hijos efímeros en replay, atribución completa de drift/locks y cobertura
  catálogo→decisión siguen sin probarse. Estos límites bloquean el PASS final,
  no se sustituyen por tests.
- SIGKILL del supervisor, fallo del host o tareas kernel no terminables no permiten
  afirmar cleanup garantizado ni reintentar automáticamente.

Autorización del operador para corregir e iniciar: «Corrígelo entonces e inicia
la campaña no?». El lanzamiento sólo procede tras regresión PASS, commit limpio,
freeze nuevo, backend cualificado, sandbox/reservas y contención disponibles.

## Regresión previa

Suite completa sin reintentos, `-B -W error::ResourceWarning`: **1048 tests, OK,
9 skipped**, 1107.753 s. Log preservado en
`.gaia/stage2/preparation-20261026/full-suite.log`.
