# Modo B MLP: valor no demostrado; piloto detenido por ruido

## Conclusión y decisión

**El Modo B no ha demostrado valor en esta prueba.** El resultado formal del
protocolo es **INCONCLUYENTE por completitud**: se terminaron tres de las cuatro
parejas previstas y se activó la parada por ruido antes de la cuarta campaña.
Los resultados observados son desfavorables a ON: **OFF ganó de forma verificada
las tres comparaciones finales**. No es un simple interruptor sin actividad:
ON evaluó once candidatos de investigación dentro del presupuesto.

No se reemplaza la cuarta pareja, no se amplía la muestra y no se reinterpreta
la regla como «mejor de tres». Incluso una victoria ON en la pareja restante
no permitiría cumplir las tres victorias ON exigidas. Esto no demuestra que
cualquier Research Engine sea inútil: el alcance es esta implementación,
política temprana, presupuesto y workload.

**Decisión recomendada:** replantear selección/coste/inferencia del Research
Engine antes de ampliar espacio MLP. No hay evidencia que justifique reanudar
el appliance. La réplica GPU tiene runtime disponible y queda para la segunda
sesión, con protocolo y puertas propios; no se presenta como ejecutada.

## Qué se fijó y qué se ejecutó

Prerregistro: `docs/PRERREGISTRO_MODO_B_20261019.md`. Sello anterior al primer
trial: **2026-10-19T13:32:54Z**, SHA-256 del protocolo
`9f5c34374c9814321e1f24a8adce0feda60a97b1af98d08e611fc9aaa398e7f4`.

- Cuatro parejas previstas; semillas 20261019–20261022, orden ON/OFF,
  OFF/ON, ON/OFF, OFF/ON. Tres parejas completas, 72 candidatos en total.
- Doce candidatos por brazo, incluyendo investigación; límite 10 minutos de
  campaña, 20 s/trial, 3000 MiB, un hilo. Meta OFF en ambos.
- Perfil hard, objetivo main 0.6252 congelado del benchmark del host. Baseline
  v0000 y estrategia inicial idénticas, cero historial, priors y desbloqueos.
  Raíces/estado independientes y sin caché de mediciones. Copias iniciales
  verificadas por hash; configuraciones solo difieren en research.enabled.
- Investigación temprana `trigger_after=2`, máximo dos hipótesis/ciclo,
  perfil de 600 batches. **No es la política predeterminada de disparo a 40.**
- G0–G5 nuevas antes de cada brazo iniciado. Ninguna puerta omitida o relajada.
- Auditoría posterior a cada pareja con cinco semillas reservadas 5000–5004,
  baseline/ON/OFF en orden rotado; ninguna usada para seleccionar propuestas.
- Antes de medir se corrigió un fallo real de presupuesto: el contador del
  bucle omitía candidatos research. Ahora consumen el mismo cupo, incluyendo
  el remanente del ciclo. No se modificaron evaluador ni reglas de promoción.

Regla de ventaja: cuatro parejas válidas, al menos tres victorias ON verificadas,
ninguna OFF, ratio geométrico ON/OFF <=0.95, mediana de tiempo total ON/OFF <=1.25
y mediana de promociones únicas ON >= OFF. Regla operativa de piloto, sin
afirmación de potencia o confianza global sobre todas las campañas.

## Resultados individuales

Ganancia = inverso del cociente pareado final/baseline en la auditoría, **no**
producto de promociones ni comparación con tiempos históricos. Tiempo total =
puertas + campaña, incluida toda la investigación; auditoría aparte.

| Pareja / semilla | Brazo | Candidatos B/total | Promociones | Ganancia final | Campaña s | Total con puertas s | CV G2 |
|---|---|---|---|---|---|---|---|
| 1 / 20261019 | ON | 2/12 | 0 | 1.026×* | 88.5 | 149.9 | 1.00% |
| 1 / 20261019 | OFF | 0/12 | 2 | 1.540× | 103.5 | 166.9 | 1.03% |
| 2 / 20261020 | ON | 5/12 | 3 | 2.248× | 113.6 | 175.1 | 2.04% |
| 2 / 20261020 | OFF | 0/12 | 2 | 5.519× | 67.7 | 129.1 | 0.94% |
| 3 / 20261021 | ON | 4/12 | 2 | 1.507× | 125.7 | 187.8 | 1.56% |
| 3 / 20261021 | OFF | 0/12 | 4 | 2.092× | 132.3 | 194.3 | 1.73% |

\* ON1 conservó exactamente la fuente v0000. Su 1.026× puntual es ruido de
medición, **no una mejora**: el contraste con baseline no fue aceptado
(ratio 0.9748, límite superior 1.0096). Los otros cinco finales sí superaron la
baseline en la auditoría bajo las reglas existentes.

| Pareja | Coste ON/OFF | Coste OFF/ON | IC95% unilateral superior OFF/ON | Veredicto final |
|---|---|---|---|---|
| 1 | 1.5010 | 0.6662 | 0.7129 | OFF mejor verificado |
| 2 | 2.4560 | 0.4072 | 0.4617 | OFF mejor verificado |
| 3 | 1.3881 | 0.7204 | 0.8339 | OFF mejor verificado |

Todos esos contrastes tienen calidad 5/5 y cumplen memoria; el límite superior
OFF/ON queda <0.95. Los IC son por comparación, no intervalos simultáneos de todo
el estudio. En las tres parejas completas, media geométrica descriptiva del
coste final ON/OFF **1.7232**: ON acaba aproximadamente un 72.3% más costoso.

### Actividad, mejoras y coste

- ON: 6 ciclos, **11 candidatos research + 25 search = 36**; OFF: **36 search**.
  No hay candidatos extra gratuitos en ON. Todos los brazos completados tienen
  12 starts y 12 ends con IDs únicos; ningún experimento abortado o inválido.
- ON obtuvo **5 promociones** y OFF **8**. Hay 5 fuentes promovidas diferentes
  en ON, 8 en OFF y **11 en la unión**, por dos fuentes compartidas. No son
  trece descubrimientos. Hay cambios `known` y `mixed`; la presencia de una
  mutación generada no acredita novedad ni un mecanismo nuevo.
- Investigación: 3 hipótesis `supported`, 2 `refuted`, 5 `refuted_screen` y
  1 `inconclusive` según las etiquetas actuales del motor. Las tres apoyadas
  fueron float32 (una) y escalado lr/batch (dos), técnicas conocidas. Son
  mejoras locales útiles, pero no dieron una ventaja de búsqueda frente a OFF.
- H-fused-bwd consumió **6 de los 11** candidatos research y ninguno fue
  promovido. Se volvió a probar después de cambiar de campeón. El caso gather
  fue alternativa Pareto por RAM (~1.33×), no promoción ni desbloqueo.
- Campañas completas: ON **327.7 s**, OFF **303.5 s**. Puertas+campañas: ON
  **512.8 s**, OFF **490.3 s**. La mediana pareada de tiempo total ON/OFF es
  **0.9664**: el coste temporal no favorece uniformemente a ninguno. No se
  atribuye toda diferencia temporal al perfilador; dependen también de cuántos
  candidatos llegaron a confirmación.
- Auditorías finales: **71.5 s** adicionales, separadas de la selección.
  Preparación de OFF4: **65.0 s** adicionales. Total de estas mediciones,
  puertas y campañas: aproximadamente **1139.6 s (19.0 min)**, excluidos
  inspección, creación de artefactos, imports iniciales y tests posteriores.
- **620 trials del evaluador**: 393 durante campañas completas, 182 de puertas
  (incluidas OFF4) y 45 de auditoría. Además, 6 observaciones instrumentadas del
  Research Engine; su tiempo sí está incluido en las campañas. No se equiparan
  observaciones ni pares de confirmación a candidatos nuevos.
- Cero errores de candidato registrados en las campañas; cero saturaciones;
  menor mediana final ~0.192 s, por encima del suelo 0.06 s. Energía no disponible
  (`energy_j: null`); no se estima un consumo energético medido.

## Bloqueo y cumplimiento de la parada

OFF4 obtuvo G0–G5 PASS y G2 5/5, pero CV **2.80%**, frente a **2.50%** máximo
adicional prerregistrado para este estudio. Las puertas generales permiten 20%:
no falló el laboratorio general; falló la condición más estricta de esta prueba.
Sus cinco costes fueron 1.1168, 1.0791, 1.0432, 1.0356 y 1.0894 s.

No se inició ningún candidato de OFF4, no se inició ON4 y no se recalibró,
reintentó ni alteró aislamiento. Las tres parejas previas no se borran ni se
excluyen por ser desfavorables. El CV fue 0.94–2.04% en sus seis preparaciones.
Esta parada limita la conclusión formal; tampoco convierte la evidencia
observada en apoyo al Modo B ni demuestra que un SO nuevo sea necesario.

## Siguiente decisión: dos sesiones restantes como máximo

### Sesión 2: diagnóstico barato y réplica GPU acotada

1. Mantener cerrado este estudio MLP. **No ejecutar p4 como si completara el
   prerregistro interrumpido ni repetir semillas buscando aceptación.**
2. Ahora sí hay motivo medido para valorar aislamiento barato: primero guardar
   carga por proceso y topología CPU. Si persiste ruido, comparar diagnóstico
   G2 sin campañas, proceso normal frente a afinidad a un núcleo físico poco
   ocupado, con un hilo y mismo campeón. Fijar previamente tres bloques
   alternados de cinco repeticiones por condición, un máximo de diez minutos;
   aceptar la medida solo si todos sus bloques CV <=2.5% y menor CV mediano.
   Son medidas diagnósticas nuevas, no parejas adicionales del estudio.
   No cambiar servicios, governor o drivers. Si no funciona en ese límite,
   registrar bloqueo y terminar; no infraestructura abierta.
3. CUDA **está disponible**: Torch 2.14.0+cu126 ejecutó una suma real en GTX 1060,
   runtime y hashes coinciden con el benchmark congelado existente, bwrap está
   presente. Evidencia guardada en `cuda_readiness.stdout.log`. No se han
   ejecutado G0–G5 GPU nuevas ni una comparación ON/OFF GPU en esta sesión;
   la réplica queda en la segunda sesión tras la parada del estudio MLP.
4. Antes de esa réplica: prerregistrar cuatro parejas GPU con raíces, semillas,
   estado y presupuesto total independientes; comprobar G0–G5 y NVML. Revisar
   cómputo de presupuesto: en GPU research contrasta hipótesis sin promover,
   y `--max-experiments` tampoco descuenta por sí mismo esos contrastes.
   Descontarlos de un cupo común antes de medir. No usar historial/meta v1
   consumido para favorecer un brazo ni relajar la identidad del benchmark al
   clonar configuraciones. Si aparece un fallo real, conservarlo y parar.

### Sesión 3: Research Engine, solo con objetivo concreto

Esta prueba ya justifica diseñar una revisión, no ampliar ciegamente campañas:

- **Ranking por beneficio esperado neto y coste de oportunidad**, no cota ideal
  de Amdahl como sustituto de ganancia esperada. El ranking actual privilegió
  seis veces fused sin éxito y desplazó exploración ordinaria.
- **Memoria transferible con contexto y descuento** entre campeones: exigir
  evidencia de que cambió la fase relevante antes de reabrir la misma familia;
  no basta con que cambie el número de versión. Mantener incertidumbre explícita.
- **Separar cribado fallido, falta de evidencia y refutación**: `refuted_screen`
  no refuta el mecanismo causal; un IC superior que no cruza aceptación tampoco
  basta por sí solo para refutar. Adoptar criterio de inferior/superior coherente
  con el motor GPU y conservar resultados de calidad/memoria aparte.
- **Intervenciones de un factor realmente aislado**: `_with(..., slots=...)`
  borra `drops` y `lits`, por lo que H-float32 en ON2 también restauró `loss`.
  Su promoción es real, pero no identifica el efecto puro del dtype. Corregir
  esa atribución antes de vender hipótesis apoyadas como explicación causal.
- **Controlar RAM antes de priorizar gather**, con estimación explícita del
  coste de la copia contigua y su compatibilidad con tolerancia 1.25×.

Elegir una revisión pequeña verificable y prerregistrar su estudio independiente
solo después; no cambiar el motor en mitad de estos resultados. Si no existe
una hipótesis nueva contrastable, parar la ampliación. El appliance sigue
PAUSADO, conservado para retomarlo desde W2 según decisión del propietario.

## Artefactos y verificación

Todo bajo `.gaia/reports/modo_b_mlp_20261019/`:

- `PREREGISTRATION.md`, `preregistration_seal.json`, `source/`: protocolo,
  fecha, hashes y snapshot ejecutado.
- `commands.json`; `pN_on/off/effective_config.json`, `initial_hashes.json`,
  `run.log`, `trials.jsonl`, `result.json`, `process.json`, `state/`: comandos,
  configuraciones, fuentes estables, ledger, puertas y resultados completos.
- `audit_p1.json`–`audit_p3.json`: datos finales independientes completos.
- `summary.json`: decisión automática **inconclusive** y bloqueo OFF4.
- `analysis.json`: métricas descriptivas y controles de consistencia; todos los
  controles de hashes, estados, configs, semillas e IDs comprobados pasan.
  Que esos controles pasen no convierte tres parejas en cuatro.
- `verification.json`, `tests.*.log`, `cuda_readiness.*.log`, `nvidia_smi.*.log`:
  comandos y salidas de verificación posterior. **41 tests correctos, sin skips**
  (core + research + regresión de presupuesto). Antes de campañas, 17 tests
  research/presupuesto correctos. Ningún test posterior se ejecutó en paralelo
  a las mediciones de campaña.
- Log del controlador: `.gaia/reports/modo_b_mlp_20261019.controller.log`.

Reproducir el análisis existente, sin campañas:

```bash
.gaia/venvs/cpu-numpy-6446deabc01ec4be/bin/python tools/summarize_mode_b.py
```

El runner `tools/evaluate_mode_b.py` se niega a reutilizar el directorio existente.
No volver a lanzarlo para «completar» o reemplazar estos resultados. El análisis
no realiza tests, propuestas, investigación ni nuevas medidas del workload.
