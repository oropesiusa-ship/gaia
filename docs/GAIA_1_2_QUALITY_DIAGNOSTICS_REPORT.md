# GAIA 1.2 — Quality Diagnostics and Prompt Adapter

## Estado

Incremento `REAL_WORLD_TESTED`, aún experimental y no promovido.
`GAIA_1_2 = NOT_CERTIFIED`.

## Diagnóstico de aritmética

Se reutilizó exclusivamente el caso existente `17 × 23 = 391` y se varió una
dimensión por vez. El control español devolvió `0.7391` tanto en JSON como en
formato numérico y con una instrucción de descomposición. En un segundo
diagnóstico, `17 * 23` y `17 times 23` devolvieron `391` correctamente.

Resultado: `LANGUAGE_OR_OPERATOR_REPRESENTATION_SUPPORTED`. El modelo conserva
capacidad para esta multiplicación, pero interpreta mal la forma española
«17 por 23» en este contexto.

## Diagnóstico de español

El control devolvió `blue`; la copia literal devolvió `Azul` con casing
incorrecto; la instrucción inglesa que preservaba el valor español devolvió
`{"color":"azul"}` correctamente.

Resultado V2:
`SPANISH_INSTRUCTION_AND_CASING_INTERACTION_SUPPORTED`. El clasificador V1 no
contemplaba este patrón y se conserva como evidencia negativa sin sobrescribirlo.

## Adaptador experimental

`EXACT_OUTPUT_AND_OPERATOR_V2` realiza sólo dos normalizaciones acotadas:

1. convierte el wrapper español exacto «Responde únicamente con el JSON …» en
   una instrucción inglesa que conserva literalmente el JSON;
2. añade una restatación simbólica para patrones numéricos «N por M».

No cambia expected outputs, scorer, memoria, autoridad ni herramientas.

| Configuración | Objetivo | Formato | Latencia mediana | Fallos |
| --- | ---: | ---: | ---: | ---: |
| Baseline memoria | 6/8 | 4/8 | 1,044 s | 0 |
| Adapter V1 | 7/8 | 5/8 | ≈1,057 s | 0 |
| Adapter V2 | 8/8 | 6/8 | ≈1,035 s | 0 |
| Adapter V2 réplica | 8/8 | 6/8 | ≈1,036 s | 0 |

El auditor offline reproduce puntuaciones, identidad de política, tareas, costes
y ausencia de fallos. La candidata se retiene como
`EXPERIMENTAL_NOT_PROMOTED`: los dos casos mejorados pertenecen al workload de
desarrollo y aún falta una evaluación independiente de generalización.

## Research Dialogue

La evidencia enriquecida hizo que el Investigador reconociera `391` frente a
`0.7391` y produjera una intervención concreta. Tras incorporar el diagnóstico,
el LLM volvió a atribuir incorrectamente el fallo a JSON. El Revisor se abstuvo
en ambos casos y el baseline determinista siguió ganando 6/7 frente a 2/7.

## Regresión

La suite global se particionó por módulos para respetar la ventana del harness:
80 archivos, 1233 tests PASS, 9 skips, 0 fallos y 0 errores. El módulo largo de
certificación se ejecutó separadamente: 8 tests PASS en 287,316 s. Esta ejecución
precedió a los últimos módulos acotados de diagnóstico/adaptador; éstos tienen
sus pruebas focalizadas PASS, por lo que no se usa esta evidencia para certificar
el commit final.

## Siguiente gate

Antes de integrar V2 como política interactiva se requieren casos independientes
pre-registrados de multiplicación española, copia literal y JSON exacto. Si no
generaliza sin regresiones, se rechaza. No se modifica el modelo seleccionado ni
se conectan promociones mientras ese gate permanezca abierto.
