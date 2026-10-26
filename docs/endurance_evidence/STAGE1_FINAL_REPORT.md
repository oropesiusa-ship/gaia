# GAIA 1.1 — Cierre consolidado de Stage 1

- **STAGE_1_ENDURANCE = PASS**
- **POST_PROMOTION_RECOVERY_REAL_DRILL = NOT_EXERCISED**
- **Stage 2: no iniciado.**

## Alcance y evidencia

Commit de validación: `c617cfea71dcb873c906fabc8436a192be744440`. Identidad de fuentes: `9e79cda91d6770aeebb73d04406df935dba43cc066d7e1a3b76671ced58c860d`.
Identidad conservada respecto al inicio de la validación: sí.
Resultados completos y hashes: `.gaia/stage1/final-close-20261026T114603/03-final-claims.json`.

## Endurance natural

Ventana observada: 5400.057 s, cinco campañas y diez
experimentos. Tiempo acumulado de campañas: 1281.595 s;
el resto incluye reposo programado y supervisión, no experimentación continua.
Mayor hueco de observación: 10.161 s.
Auditoría: PASS; cobertura temporal: PASS;
replay terminal sin cambios en bytes propios: PASS.
Reauditoría de Stage 0: PASS.

La evidencia original de la ventana conserva su FAIL por la agrupación errónea
de muestras de VRAM. La corrección tool-only audita el sensor global incluyendo
campañas y reposo; no relaja cadencias ni descarta muestras. Se conservan la
auditoría original, la reanálisis identificada y sus hashes de evidencia.

## Recovery separado

Se conservan dos intentos anteriores NOT_EXERCISED y un único intento final
autorizado, con una campaña nueva de hasta dos experimentos, límites fijados,
linaje desechable separado y aprendizaje conservado. Ningún ganador preparado,
criterio relajado, publicación forzada ni repetición automática posterior.
Checkpoint previsto: VERIFYING con matriz nativa viva, al menos 5 s observada y
confirmada por heartbeat; sólo entonces se permitiría un SIGKILL del controlador
identificado por pid/start. **No se alcanzó ni se inyectó el fallo.**
Resultado final: **NOT_EXERCISED**. Auditoría del drill: PASS.

El intento final duró 262,847 s de sesión y evaluó `e00005` y `e00006`,
sin promoción. Presupuestos: PASS; dos evaluaciones distintas para dos intents;
versión nativa conservada en `v0000`, ledger verificado, linaje sin bloquear y
ningún proceso capturado superviviente. Los seis experimentos de los tres
intentos se conservan; no hubo una cuarta campaña.

NOT_EXERCISED no certifica recuperación real ni la sustituye por tests: indica
que no surgió una promoción/checkpoint legítimo dentro del presupuesto. Según
la separación de claims aprobada por el operador, esa ausencia no invalida el
endurance. Cualquier fallo real mantiene el cierre pendiente de revisión.

## Regresión final

Una suite completa, sin reintentos, código de salida 0;
ResourceWarnings detectados: ninguno.

```text
Ran 1011 tests in 1076.186s

OK (skipped=9)
```

## Siguiente fase

No se ha iniciado Stage 2. Su preparación exige runbook, límites y criterios
de ventana explícitos, incluyendo persistencia, reapertura e inferencia local
si se autoriza. Sigue sin afirmarse recuperación post-promoción real cuando
el claim correspondiente sea NOT_EXERCISED. Este cierre no es la release 1.1.

La separación de claims y el presupuesto del último intento fueron aprobados y
pre-registrados antes de ejecutarlo. No se cambia el resultado de ningún
experimento ni se atribuye a los tests una cobertura real no ejercitada.
