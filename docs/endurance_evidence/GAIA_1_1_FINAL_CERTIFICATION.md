# GAIA 1.1 — Certificación final abreviada

## Decisión

`GAIA_1_1 = RELEASE_READY`

Decisión host-specific conforme al protocolo pre-registrado
`GAIA_1_1_ABBREVIATED_CERTIFICATION_V1.md`. No equivale a una prueba de endurance
de 24 horas ni publica una release.

Commit ejecutado y certificado: `3facdf3e79e9b0ae63056a3179935d6ca9dc36a0`
(`feat/gaia-1.1-endurance`).

## Evidencia aceptada

- Stage 0 histórico: `PASS`.
- Stage 1 histórico: `PASS`; 5 campañas, 10 experimentos y 5400,057 s.
- Stage 2 final: `.gaia/stage2/final-abbrev-3facdf3`.
- Contrato Stage 2:
  `ad324faebc7610027844f08e2dbc50e7ebcaf20aae363f40357aa6e7d6961fa4`.
- Sesión S1 `asb3457d8ad73342e7937df2ba`: dos campañas terminales.
- Sesión S2 `asb1f61b7575ae46e38b449c46`: dos campañas terminales.
- Campañas: `ac5e142e6456ac4ed1ae12532a`, `acf914a00eb1e042acbcb2ab06`,
  `ac8d7cdf2ec6554fb795fc4831`, `ace3858d1cb8ff4cb08bfe8a1f`.
- Compute agregado: 1737,227622403996 s de 7200 s reservados; `overrun=false`.
- Boundary y cierre: cuatro replays reales `TERMINAL_NOOP`, sin writes,
  creación de procesos ni supervivientes.
- Auditoría offline completa: `PASS`, 15/15 checks requeridos, sin faltantes:
  sesiones, ventanas, presupuesto, atribución S1/S2, catálogo, decisiones,
  protocolo congelado, bytes terminales, drift, scratch y cadena administrativa.
- Regresión previa: 1193 tests, 9 skips, `PASS`; log
  `/tmp/opencode/gaia-1.1-3facdf3-full-suite.log`, SHA-256
  `acfa7a73584ecccc7d48274b9abc9d04273237b6cfecc718597465776d39b821`.
- Regresión posterior: 1193 tests, 9 skips, `PASS`; log
  `/tmp/opencode/gaia-1.1-3facdf3-post-stage2-full-suite.log`, SHA-256
  `9a6a017f0a85e109e694f161fdd751814c8cf2c6f112afd471ce75b3b8d25cd8`.
- Procesos GAIA/backend supervivientes al cierre: ninguno.

## Evidencia negativa conservada

Los intentos anteriores permanecen sin reclasificación. Incluyen bloqueos de entorno,
la recuperación C3 con downtime contado como wall y carreras de atribución corregidas.
Ninguno se usa como PASS ni forma parte de la serie final.

## Límites de la declaración

- `24_HOUR_ENDURANCE = NOT_EXERCISED`.
- `POST_PROMOTION_ROLLBACK = NOT_EXERCISED`.
- `RELEASE_PUBLISHED = NOT_PUBLISHED`.
- Merge, tag, push y publicación: no realizados.
- La certificación cubre la serie abreviada de dos sesiones y cuatro campañas descrita
  arriba, además de la evidencia Stage 0/1 conservada; no afirma más duración.
