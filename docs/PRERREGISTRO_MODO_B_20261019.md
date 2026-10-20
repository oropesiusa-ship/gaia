# Prerregistro Modo B — MLP, 19-10-2026

Se fija antes de cualquier campaña ON/OFF nueva. Sesión 1: inspección, corrección
del cómputo de presupuesto, ejecución MLP y decisión. Sesión 2: réplica GPU si sus
puertas lo permiten; sesión 3 solo para resolver una limitación concreta, sin
ampliar retrospectivamente esta muestra. Appliance PAUSADO, reanudación solo por
decisión del propietario desde W2 y según el checkpoint vigente.

## Antecedentes localizados (no resultados de esta prueba)

- `state/readiness.json`: G0–G5 PASS históricos, G2 CV 0.0058 (0.58%,
  próximo al 0.5% referido), control nulo 1.0031. Runtime histórico distinto
  (GTX 1050, NumPy 2.5.4); no se traslada su fiabilidad al host actual.
- `state_numpy_mlp_6446deabc01ec4be/readiness.json`: CV 1.93%, nulo
  0.9975, puertas PASS con el runtime CPU disponible actualmente (NumPy 2.3.5).
- `demo_evidence/REPORT_campaign_demo.md`, ledger y `NEEDS_HUMAN_demo.md`:
  60 experimentos, 8 promociones conocidas, saturación a 0.058 s, baseline
  0.7557 s (~13.0× por esa medición; auditoría main 0.0893× = 11.2×).
  No son 13× verificados por la auditoría. H-fused-bwd refutada en v0005 y
  v0007; lr/batch apoyada en v0005 e inconclusa en v0007. No hay ON/OFF previo.
- Recuperación/IDs/runtime/memoria tienen implementación y tests; no se ha
  localizado aquí un informe original independiente del kill -9 con todos sus
  comandos. No se usa como resultado de esta comparación.

## Semántica y ajuste previo necesario

ON perfila, diagnostica, genera y poda hipótesis, evalúa candidatos en el mismo
`Engine.experiment`, aprende por familia y puede desbloquear shuffled_slices.
OFF elimina el disparo automático; no elimina opciones conocidas ni modifica
umbrales. El comando research bajo demanda ignora ese interruptor: no se usará.
Metaoptimización OFF en ambos brazos para aislar el efecto.

Inspección detectó que `Engine.run` no descontaba experimentos de investigación
de `--max-experiments`. Se corrige ANTES de medir: todo candidato research/search
consume una unidad y se pasa el remanente al ciclo. No se modifica evaluador,
calidad, confirmación ni puertas. Regresión de presupuesto y tests research
deben pasar antes de iniciar. Se conserva snapshot/hash del código ejecutado.

## Diseño cerrado

- **4 parejas**, semillas de búsqueda **20261019, 20261020, 20261021, 20261022**.
  Orden: ON/OFF, OFF/ON, ON/OFF, OFF/ON. Ejecución secuencial, sin campañas
  concurrentes ni selección de semillas por resultados.
- **12 candidatos totales por brazo** (ordinarios + investigación), límite de
  campaña **10 minutos**, mismo límite por trial 20 s, RAM 3000 MiB, un hilo.
  No se iguala retrospectivamente el número alcanzado si hay fallo/tiempo.
- Perfil `hard`; benchmark/objetivos congelados copiados del estado CPU del host,
  sin recalibrar selectivamente. v0000 generado por `G.new_genome`, estrategia
  DEFAULT, cero experimentos/historial/priors/unlocks. Raíz y estado separados
  para cada brazo; sin caché de mediciones. Solo código y especificación comunes.
- Única diferencia entre configuraciones efectivas: research.enabled. Nombres
  de raíz distintos por aislamiento; misma semilla de búsqueda en cada pareja.
  Un adaptador del runner sustituye únicamente RNG tras `_load`, porque el motor
  fija siempre 13 al comenzar desde cero. No cambia la generación de propuestas.
- `trigger_after=2`, `max_hypotheses=2`, `profile_batches=600` en ambos brazos.
  Es una política temprana explícita, NO el valor por defecto (40).
  Semillas de entrenamiento: cribado 0, confirmación 1000–1004 (1005–1009 si
  las reglas existentes amplían). Perfil semilla 0. Mismas en todos los brazos.
- Cada brazo debe superar **G0–G5 nuevas**, con valores predeterminados; no se
  omiten ni relajan puertas. Identidad comprobada antes de campaña.
- Intervención real: cada ON debe registrar research_diagnosis y al menos un
  `end origin=research`; OFF ninguno. Si no ocurre, no hay prueba válida del valor
  del mecanismo para esa pareja; no se fuerza después con llamadas manuales.

## Medición independiente y reglas de decisión

Tras finalizar ambos brazos de cada pareja, auditoría final NO usada por búsqueda:
baseline, final ON y final OFF en semillas **5000–5004**, tarea main, rotando
orden baseline/ON/OFF por semilla y pareja. Guardar resultados completos. Son
semillas ya reservadas por el laboratorio: no datos nuevos de generalización
universal. No se reoptimiza a partir de ellas. `stats.decide` compara finales
ON/OFF y cada final/baseline. Si ambos finales son idénticos, se mide igualmente.

Métricas: promociones verificadas (eventos y fuentes únicas por brazo y unión;
una misma fuente repetida no es varios descubrimientos), ganancia final
baseline/final por cocientes pareados, IC95%, calidad, errores, candidatos por
origen, tiempo campaña completo con investigación, tiempo puertas y tiempo total
puertas+campaña. Auditoría posterior se informa por separado. Temporización
externa; `search_seconds` NO es el tiempo completo. Coste = segundos y trials;
energía solo si existe telemetría, nunca estimada como medición.

**Ventaja consistente ON**, fijada ahora: las cuatro parejas válidas, ON con
ventaja práctica verificada frente a OFF por `stats.decide` (IC95% superior
<0.95 y calidad/memoria) en **al menos 3/4**, ninguna victoria verificada OFF,
media geométrica de ratios finales ON/OFF <=0.95, mediana de tiempo total
ON/OFF <=1.25 y mediana de promociones únicas ON >= OFF. Es una regla operativa
de piloto pequeño, no una prueba global con potencia estadística garantizada.
Más promociones sin mejor campeón final no basta. Técnicas conocidas no se
etiquetan descubrimientos autónomos.

- Si la prueba es válida pero no cumple esa regla: **Modo B no ha demostrado
  valor en esta prueba**, revisar Research Engine antes de ampliar infraestructura.
- Si hay puertas fallidas, intervención ausente, auditoría sin calidad, o menos
  de cuatro parejas completas: **inconcluyente**, además de no haber demostrado
  valor; conservar lo medido sin reemplazar ni ampliar muestra.
- Saturación: parada existente por coste <0.06 s o dispersión >25%; también
  marcar si la mediana final queda bajo 0.06 s. Pareja saturada = censurada,
  no victoria; resultado global inconcluyente. No endurecer benchmark a mitad.
- Errores de candidato consumen presupuesto y se cuentan; error de infra,
  deriva, límite temporal o STOP conserva parciales, invalida completitud y
  no se reintenta para favorecer un brazo. Fallo G0 detiene la prueba; otro fallo
  de puertas deja evidencia y detiene antes de campañas adicionales.
- Si G2 CV >2.5% (ruido de escala comparable a ganancia del 5%), detener antes
  de la campaña y valorar aislamiento barato en otra sesión; ningún cambio
  automático de servicios, afinidad, governor o drivers. Se informa también el
  CV de todas las puertas aunque pasen su umbral original del 20%.
- No añadir parejas ni reintentos tras ver resultados. Si la regla gana,
  siguiente estudio independiente con espacio/workload ampliados, no reusar
  confirmación como exploración favorable.

## CUDA y parada entre sesiones

Inspección actual: nvidia-smi funcional, GTX 1060 6GB, driver 580.178.04;
runtime GPU existente Torch 2.14.0+cu126, tensor CUDA ejecutado correctamente.
Código GaiaTransformer/TinyGPT presente. Antes de réplica GPU hay que verificar
laboratorio/benchmark y puertas en el host; no instalar ni preparar appliance.
Se fija su protocolo específico antes de sus resultados, respetando el mismo
presupuesto total y contabilizando los contrastes research (la semántica GPU
no es idéntica a MLP). La sesión 1 termina con resultados MLP o bloqueo real.

Artefactos: `.gaia/reports/modo_b_mlp_20261019/`; runner en
`tools/evaluate_mode_b.py`. Protocolo copiado con hash antes del primer trial.
