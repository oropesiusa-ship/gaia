# GAIA 1.2 — Certification checkpoint 2026-10-28

## Decisión

`GAIA_1_2 = NOT_CERTIFIED` en `ca473ea`.

No se realizó merge, tag ni release. La autoridad del LLM permanece `NONE` y no
se integró ningún adapter en la proyección interactiva.

## Gates auditados

| Hito | Estado | Evidencia principal |
| --- | --- | --- |
| A — repositorio | PASS | rama 1.2 limpia; base y artefactos verificados |
| B — pre-registro V2 | PASS | `9ab9000`, protocolo sellado antes de inferencia |
| C — generalización V2 | FAIL | 8/18 frente a 14/18; siete regresiones |
| D — integración | NOT_APPLICABLE | candidata rechazada; no se integra |
| E — regresión | PASS | 1247 PASS, 9 skips, 84 archivos |
| F — calidad final | PASS | auditoría pre-registrada: 22/26 objetivos, 20/26 formato, cero errores |
| G — Research Intelligence | FAIL | diálogo 2/7 frente a baseline 6/7 |
| H — continuidad real | PARTIAL | una iteración real; multi-iteración sólo simulada |
| I — certificación | NOT_CERTIFIED | gates F, G y H pendientes |
| J — fases posteriores | NOT_AUTHORIZED | 1.3/1.4 permanecen propuestas; no se amplían capacidades |

## Experimentos de adapter

- V2: rechazado por exactitud, formato, regresiones y latencia. Todas las
  respuestas se conservan en
  `GAIA_1_2_ADAPTER_GENERALIZATION_EVALUATION_V1.json`.
- V3 dirigida: una primera ejecución quedó marcada inválida por contaminación
  entre propietarios y se preservó. La repetición aislada obtuvo 16/18 en ambos
  brazos, sin regresiones ni ganancia, pero no alcanzó el 90 % pre-registrado;
  también fue rechazada.

## Estado recuperable y continuación

El Hito F quedó cerrado por una auditoría offline pre-registrada que separa
métricas objetivas, rendimiento, funcionales y muestras subjetivas. No atribuye
mejora cognitiva. Research Dialogue V2/V2.1/V2.2 produjo evidencia negativa y
permanece en 2/7; H demuestra reapertura real idempotente de una campaña rechazada,
pero no una campaña real multi-iteración aceptada. La certificación debe permanecer
`NOT_CERTIFIED` mientras G y H no superen sus gates.
