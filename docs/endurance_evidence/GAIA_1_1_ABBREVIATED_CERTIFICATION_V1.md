# GAIA 1.1 — Protocolo de certificación abreviada v1

**Pre-registrado antes de la nueva ejecución real.**

## Alcance

Este protocolo sustituye las ventanas rígidas de Stage 3 y Stage 4 para la decisión de
release 1.1. No altera evaluadores, benchmarks, umbrales, autoridad ni fuentes
protegidas. Conserva Stage 0 y Stage 1 ya cerrados y exige un Stage 2 nuevo y completo
sobre estado nuevo después de corregir los defectos administrativos observados.

No certifica endurance de 12 o 24 horas. Certifica operación representativa acotada,
dos sesiones, cuatro campañas, persistencia, reapertura, learning, presupuestos,
idempotencia, aislamiento, contención y recovery seguro dentro del alcance observado.

## Evidencia histórica conservada

- Stage 0: PASS.
- Stage 1: PASS, ventana real de 90 minutos, cinco campañas y diez experimentos.
- Reanudación real de verificación post-promoción: PASS.
- Rollback post-promoción: NOT_EXERCISED.
- Intento Stage 2 `master-attempt3`: INCONCLUSIVE_ENVIRONMENT.
- Continuación C3: FAIL por incluir downtime no supervisado en `wall_s`; permanece
  evidencia negativa y no se reutiliza como PASS.

## Nueva serie

La nueva serie debe usar un intento, estado, linajes, sesiones y campañas nuevos. No
reabre ni repara el intento fallido. Usa la implementación comprometida y árbol limpio.

Límites máximos:

- dos sesiones Stage 2;
- dos campañas por sesión, cuatro total;
- 1.800 s reservados por campaña y 7.200 s agregados;
- 4 GiB de almacenamiento;
- una ejecución candidate/model activa;
- red, research y promotion deshabilitados;
- cero ampliación de autoridad;
- cero intervención correctiva durante cada ventana aceptada.

El downtime entre procesos o sesiones se declara por separado y nunca se presenta como
compute. Dentro de una campaña ininterrumpida se conserva la contabilidad contractual
existente. Una interrupción invalida esa ventana; no se continúa para obtener un PASS.

## Gates previos

1. Working tree limpio y commit identificado.
2. Identidad de `gaia/` y fuentes protegidas sin cambios respecto a Stage 1.
3. Suite Stage 2 focalizada PASS.
4. Suite completa PASS sin reintentos.
5. Sandbox, reservas del host, filesystem y backend cualificado PASS.
6. Ausencia de campañas/backend GAIA concurrentes.
7. Contrato y hashes administrativos congelados antes de ejecución.

## PASS

Requiere:

- S1 y S2 reales observadas;
- las cuatro campañas terminales y reconciliadas;
- presupuestos y almacenamiento dentro de límites;
- cero duplicados, corrupción, escalamiento o procesos supervivientes;
- terminal replay idempotente;
- learning y catálogo preservados entre campañas y sesiones;
- binding incompatible rechazado y binding compatible interpretado correctamente;
- telemetría, atribución de procesos/locks y auditoría completa PASS;
- regresión final PASS;
- ningún defecto crítico abierto.

## FAIL / INCONCLUSIVE

- Un límite excedido, journal ambiguo, evidencia alterada, duplicado, huérfano,
  escalamiento o fallo de auditoría es FAIL.
- Actividad externa demostrada antes de una campaña es BLOCKED_PREEXECUTION.
- Actividad externa que invalida una ventana iniciada es INCONCLUSIVE_ENVIRONMENT.
- No se repite una ventana sólo para buscar un resultado favorable. Una repetición sólo
  procede después de identificar y corregir un defecto real de implementación.

## Claims finales permitidos

Si todos los gates pasan puede declararse `GAIA_1_1 = RELEASE_READY`, especificando que
la certificación es abreviada y host-specific. Deben permanecer explícitos:

- `24_HOUR_ENDURANCE = NOT_EXERCISED`;
- `POST_PROMOTION_ROLLBACK = NOT_EXERCISED`;
- release publicada/merge/tag = NOT_PUBLISHED hasta acción humana posterior.
