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
| F — calidad final | OPEN | no existe todavía una campaña final única que cubra todos los dominios aprobados |
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

El siguiente trabajo legítimo es pre-registrar la evaluación final amplia del
Hito F y mejorar la transferencia de evidencia del Research Dialogue sin tocar
su evaluador de siete criterios ni elevar el límite de 96 tokens. Después debe
ejecutarse una campaña real dentro de presupuesto para cerrar H. La certificación
debe permanecer `NOT_CERTIFIED` hasta que esos gates pasen.
