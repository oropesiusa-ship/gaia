# Fase 7: investigación autónoma TinyGPT/CUDA

> Evidencia histórica anterior al renombrado. Los comandos, rutas y mediciones
> originales no son ejecuciones nuevas de GaiaTransformer.
> Evidencia nueva: `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Fecha: 15-10-2026. Resultado: **GPU_RESEARCH_COMPLETE**, con disparo automático
probado dentro de una campaña GPU completa.

## Implementación y uso

```bash
python3 gaia.py tinygpt-research --minutes 10
```

El ciclo verifica el benchmark congelado y campeón actual bajo lock, observa
el campeón con el perfilador de Fase 6, formula hipótesis y las contrasta en el
laboratorio GPU sin instrumentación. No publica versiones ni actualiza CURRENT.

- `gaia/tinygpt/research.py`: hipótesis, memoria, priors, veredictos y desbloqueo.
- `gaia/tinygpt/genome.py`: extensiones foreach cerradas por defecto y propuestas
  condicionadas a evidencia apoyada.
- `gaia/tinygpt/campaign.py`: disparo por estancamiento y consumo de opciones probadas.
- `observation.py` permite reutilizar el perfilado bajo el lock ya adquirido,
  sin introducir un segundo lock incompatible ni alterar el laboratorio.
- `profiling.py` admite la variante conocida de clipping foreach conservando la
  comprobación estructural y paridad de instrumentación.

El render de baseline, su hash y los genomas anteriores se conservan. Las claves
opcionales en modo scalar equivalen al genoma previo; las variantes foreach solo
se exponen al buscador tras evidencia apoyada del mismo campeón.

## Hipótesis completas y reglas

Familias iniciales, técnicas conocidas y no descubrimientos autónomos:

| Familia | Mecanismo | Opción |
|---|---|---|
| optimizer_foreach | Agrupar operaciones del optimizador para reducir lanzamientos/overhead Python | optimizer_impl=foreach |
| clip_foreach | Agrupar operaciones de norma/clipping, sin eliminar clipping | clip_impl=foreach |

Cada hipótesis registra componente, mecanismo, datos de perfil, cota ideal de
ganancia, expectativa si se redujera la fase a la mitad, coste, riesgo, criterio
de falsación, aceptación y conteos previos por familia. Su cota es una proyección
del perfil, no una aceleración medida.

- Cota ideal estimada <5%: `pruned`, sin consumir trials de candidato.
- Cribado con calidad y coste <=1.3x: permite contrastar cinco pares intercalados
  en semillas 1000..1004, mismas reglas y recursos que Modo A.
- `supported`: decisión aceptada por el verificador, calidad 5/5, IC unilateral
  superior 95% del ratio <0.95 y tolerancias RAM/VRAM.
- `refuted`: falla calidad/restricción de memoria o el límite inferior unilateral
  95% es >=0.95, descartando la mejora práctica propuesta bajo ese contraste.
- `inconclusive`: no hay evidencia suficiente para apoyar o refutar. Un cribado
  costoso evita confirmación sin convertir una sola semilla en prueba estadística.

Errores de runtime/infraestructura abortan con informe, no se convierten en
veredictos favorables. Los presupuestos por trial siguen siendo los congelados.

## Memoria y efecto sobre propuestas

La memoria usa hash de fuente de campeón + familia. No repite familias apoyadas,
refutadas o podadas para esa fuente. Una inconclusa admite **dos contrastes como
máximo**, regla fijada antes de la primera ejecución, no reintentos indefinidos
hasta obtener aceptación. Los conteos por familia incluyen resultados anteriores;
un prior suavizado solo ordena trabajo y no altera la regla de aceptación.

Para desbloquear, el buscador no confía solo en `verdict=supported`: recalcula la
decisión desde los cinco pares y verifica hashes de fuente de campeón/candidato.
Sin esa evidencia, foreach no aparece en propuestas ordinarias. Con evidencia,
se prioriza una primera propuesta de la opción recién habilitada. Aun entonces,
la campaña debe volver a comparar para promoverla por su cuenta.

La rama de desbloqueo apoyado y su efecto en propuestas se comprobó con evidencia
sintética en tests. **En las ejecuciones GPU reales de esta fase ninguna opción
alcanzó el requisito de desbloqueo.**

## Resultados reales en GTX 1060

Campeón v0000, objetivo CE <=0.2596790841227193, Torch 2.14.0+cu126, fp32 y
determinismo. Todas las semillas de ambos contrastes de optimizador alcanzaron
calidad. La opción cambia ligeramente redondeos numéricos respecto a scalar;
la exigencia es calidad privada y reproducibilidad del candidato, no igualdad de
sus pesos con otra implementación.

| Contraste optimizer_foreach | Ratio | Límite inferior 95% | Límite superior 95% | Veredicto |
|---|---:|---:|---:|---|
| Bajo demanda | 0.968923 | 0.935748 | 1.003274 | inconclusive |
| Disparo automático | 0.933601 | 0.890730 | 0.978534 | inconclusive |

El segundo tiene mejora puntual de alrededor del 6.64%, pero su límite superior
0.978534 no satisface <0.95. No se declara mejora verificada ni se desbloquea.
Los contrastes son evaluaciones separadas, no un IC agregado de diez pares ni
una afirmación de confianza global sobre la búsqueda.

Clipping: cota máxima estimada **3.6820%**, inferior al 5%; `pruned` sin trials.
La segunda invocación automática no repitió esa familia. Una tercera invocación
bajo demanda encontró la memoria completa y no repitió perfilado ni contrastes.
Sus probes normales de compatibilidad de bootstrap sí se ejecutaron.

## Disparo automático real

```bash
python3 gaia.py tinygpt-run --max-experiments 1 --minutes 15 --research-after 2
```

Se usó el umbral explícito 2 para probar la integración con el historial corto;
**el valor predeterminado permanece en 40**. No se alteró la calibración, calidad,
semillas ni umbrales del verificador. Dos rechazos completos previos activaron
Modo B tras G0-G5; los dos ensayos abortados no contribuyeron al contador.

La campaña ejecutó investigación antes de proponer e00005, conservó las opciones
cerradas al quedar inconclusa y continuó con batch 32→64. Ese candidato ordinario
también fue rechazado: ratio 1.031378, límite superior 1.102835, calidad 5/5.
Campeón final v0000; cero promociones. La campaña completó 50 trials de su
laboratorio principal, además del trial/perfil separados de observación.

El disparo deja `research_trigger` con contador y umbral. Exige otro intervalo
completo antes de dispararse otra vez para el mismo campeón. El flag de configuración
`research.enabled=false` desactiva el disparo; el comando bajo demanda sigue siendo
una petición explícita. La memoria sigue bloqueando repeticiones incluso si se
vuelve a invocar manualmente.

## Persistencia y pruebas

Eventos `research_start` y `research_end` conservan hipótesis, fuente de campeón,
genoma ensayado, pares completos, veredicto y ruta a evidencia. La observación
se registra separadamente. `result.json` resume opciones antes/después y deja
explícito `promotions=0` y campeón intacto. Fallos crean `NEEDS_HUMAN.json`.

Informes locales:

- Bajo demanda: `.gaia/reports/20261015T174247Z-23e3fdeb/research/`.
- Disparo automático y campaña:
  `.gaia/reports/20261015T174504Z-324fa9b6/campaign/`.
- Segundo contraste:
  `campaign/research-before-00005/optimizer_foreach.json` dentro del anterior.
- Memoria sin repetir: `.gaia/reports/20261015T175040Z-8d254db3/research/`.
- Suite final: `.gaia/reports/20261015T175251Z-ad36e496/`.

**135 tests descubiertos: 126 ejecutados sin fallos en NumPy y 9 de modelo
omitidos allí, ejecutados en el entorno Torch/CUDA.** La preparación de la campaña real
ejecutó 31 tests de corrección sin omisiones, incluido entrenamiento/predicción
de las opciones foreach con el runtime Torch.

Después se ejecutaron de nuevo los nueve tests de modelo en el intérprete del
perfil Pascal, sin omisiones. El test de extensiones usa CUDA cuando está
disponible: confirmó dos pasos de entrenamiento y predicción con **optimizador
y clipping foreach simultáneos en la GTX 1060**. Esto valida ejecución, no su
rentabilidad ni un desbloqueo de clipping, que sigue podado por la cota.

Ocho tests nuevos específicos verifican compatibilidad del renderer, opciones
cerradas por defecto, evidencia apoyada vinculada a fuentes, memoria por campeón,
veredictos, contador de meseta, poda/desbloqueo sin promoción y estado correcto del
CLI. El ensayo de variante apoyada en esos tests es sintético, no evidencia de
aceleración en la GTX 1060.

## Cierre y siguiente fase

Se cumple el cierre de Fase 7: un umbral de estancamiento dispara investigación,
deja evidencia y condiciona propuestas; no se repiten familias resueltas y se
mantienen cerradas las ampliaciones no apoyadas. Todavía no se ha demostrado una
mejora GPU promovible ni mejora recursiva del buscador.

Fase 8 debe comparar estrategias de búsqueda con presupuesto equivalente y tareas
no usadas para seleccionarlas, sin confundir el mecanismo implementado con una
mejora transferible demostrada.
