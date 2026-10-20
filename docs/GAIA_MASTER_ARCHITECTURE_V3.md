# Estado actual del proyecto

La versión 3.0 es la autoridad conceptual del proyecto. Las capacidades aspiracionales
del documento no deben confundirse con capacidades ya demostradas.

GAIA v0.1 es infraestructura autónoma de automejora controlada certificada:
- dominio demostrado: CPU `numpy_mlp`;
- generación normal mediante `Strategy.propose()`;
- gates G0–G5, sandbox bwrap y evaluación pareada;
- publicación transaccional, ledger y rollback;
- Prueba A de pipeline y Prueba B autónoma.

Resultado histórico B: mejora observada específica de 46,90 % menos coste hasta
objetivo, aproximadamente 1,88× de aceleración. Alcance: workload CPU concreto.

NO están demostrados todavía: mejora de un LLM real, memoria cognitiva,
razonamiento general, RAG, planificación general, inferencia de modelos de lenguaje,
autodiagnóstico general, selección autónoma del objetivo de mejora,
metaoptimización general ni incremento demostrado de inteligencia general.

Una mejora del trainer CPU no constituye una mejora demostrada de la inteligencia general de GAIA.

GAIA 0.2 observa y caracteriza de forma estructurada su entorno y funcionamiento.
No diagnostica, no selecciona objetivos de mejora y no demuestra un incremento de inteligencia.

---

GAIA — Documento Maestro de Arquitectura, Evolución y Automejora

Versión: 3.0
Estado: Documento maestro consolidado
Naturaleza: Proyecto de IA local, modular, verificable y progresivamente autoevolutiva
Visión a largo plazo: Investigar y desarrollar, de manera gradual y responsable, sistemas de inteligencia artificial cada vez más capaces, con la aspiración de explorar el camino hacia una inteligencia artificial general y, eventualmente, la superinteligencia artificial (ASI).

⸻

1. Visión general

GAIA es un proyecto para construir una inteligencia artificial local que pueda asistir, razonar, recordar, investigar, utilizar herramientas, ejecutar tareas, evaluar sus propios resultados y mejorar progresivamente sus capacidades.

No se concibe como un simple chatbot ni como una interfaz conectada a un único modelo. GAIA es un sistema completo formado por modelos de lenguaje, memoria, herramientas, procesos de razonamiento, infraestructura de inferencia, mecanismos de evaluación, experimentación y control de cambios.

Su objetivo es desarrollar una IA que aproveche de manera eficiente el hardware disponible, mantenga el conocimiento útil entre sesiones, pueda trabajar con autonomía delimitada y sea capaz de investigar mejoras sobre sus propios componentes.

La automejora no debe limitarse a modificar scripts periféricos o ajustar parámetros de un experimento. El propio LLM y toda la infraestructura que permite utilizarlo constituyen superficies centrales de investigación y optimización.

Esto comprende cuatro dimensiones:

1. Mejorar la ejecución del modelo: conseguir una inferencia más rápida, eficiente, estable y adecuada al hardware.
2. Mejorar el sistema cognitivo: optimizar memoria, recuperación de información, planificación, herramientas, verificación y coordinación de modelos.
3. Mejorar los modelos: investigar selección, adaptación, cuantización, ajuste fino, destilación y otras formas de entrenamiento.
4. Mejorar el proceso de automejora: aprender a formular mejores hipótesis, seleccionar experimentos, interpretar resultados y evitar regresiones.

GAIA debe avanzar mediante ciclos verificables de observación, hipótesis, experimentación, evaluación y promoción de cambios. Cada mejora tiene que demostrar su utilidad frente a una referencia y conservar la posibilidad de revertirla.

La visión de largo plazo es ambiciosa, pero no presupone que la acumulación de optimizaciones locales produzca automáticamente inteligencia general o superinteligencia. Estas son metas de investigación, no capacidades que deban darse por conseguidas.

2. Identidad y propósito

GAIA representa una IA personal, local y extensible, diseñada para convertirse progresivamente en un sistema de asistencia e investigación cada vez más competente.

Sus objetivos principales son:

* Comprender solicitudes y mantener el contexto relevante.
* Recordar información útil de manera persistente y controlada.
* Investigar documentación, código, datos y recursos disponibles.
* Utilizar herramientas para ejecutar tareas concretas.
* Descomponer objetivos complejos en subtareas.
* Evaluar resultados antes de considerarlos correctos.
* Aprender de experimentos y errores documentados.
* Optimizar sus propios componentes dentro de límites explícitos.
* Mantener trazabilidad sobre decisiones, cambios y resultados.
* Adaptarse a la evolución del hardware y de los modelos disponibles.

GAIA no debe depender de que cada mejora sea diseñada manualmente. Debe desarrollar una capacidad creciente para identificar problemas, proponer soluciones y comprobarlas.

Sin embargo, autonomía no significa autoridad ilimitada. La capacidad de proponer o probar un cambio es diferente de la autorización para instalarlo permanentemente, acceder a recursos sensibles o alterar las restricciones de seguridad.

3. Principios fundamentales

3.1. Localidad y control

La ejecución local es una prioridad estratégica cuando los recursos disponibles lo permiten.

La localidad aporta control sobre los datos, menor dependencia de servicios externos, mayor capacidad de personalización y libertad para experimentar con modelos e infraestructura.

No implica que todas las tareas deban ejecutarse necesariamente sin conexión. El acceso a Internet puede utilizarse cuando aporte información o capacidades adicionales y esté permitido.

3.2. Modularidad

Cada componente debe tener responsabilidades definidas y una interfaz clara.

Los modelos, la memoria, el runtime, las herramientas, el evaluador, el sistema de experimentación y el publicador de versiones deben poder evolucionar sin exigir una reescritura integral de GAIA.

3.3. Medición antes que intuición

Una modificación no se considera una mejora únicamente porque parezca más sofisticada, produzca una respuesta convincente o reduzca el tiempo de ejecución.

Debe compararse con una referencia utilizando métricas apropiadas y pruebas reproducibles.

3.4. Separación entre propuesta, prueba y promoción

El sistema que propone una mejora no debe ser el único que decide si esta funciona.

GAIA debe separar, en la medida de lo posible:

* Generación de propuestas.
* Preparación del entorno de prueba.
* Ejecución de experimentos.
* Evaluación de resultados.
* Verificación de seguridad.
* Promoción a una versión estable.
* Capacidad de reversión.

3.5. Reversibilidad

Las modificaciones deben poder deshacerse. Una nueva versión no debe destruir la última versión conocida como válida.

3.6. Progreso acumulativo

Los resultados deben quedar registrados para evitar repetir indefinidamente experimentos fallidos y para facilitar la comparación entre generaciones de componentes.

3.7. Mejora multidimensional

GAIA debe distinguir entre rendimiento, coste, calidad, fiabilidad, capacidades cognitivas y autonomía.

Una optimización en una dimensión no demuestra automáticamente mejoras en las demás.

4. GAIA como sistema, no como modelo

Un modelo de lenguaje es un componente central, pero no representa por sí solo a GAIA.

La capacidad efectiva del sistema depende de la interacción entre múltiples elementos:

* Modelo de lenguaje.
* Tokenizer y formato de conversación.
* Runtime de inferencia.
* Gestión del contexto.
* Memoria persistente.
* Recuperación de información.
* Planificación y descomposición de tareas.
* Uso de herramientas.
* Coordinación entre modelos.
* Evaluación y verificación.
* Almacenamiento de artefactos.
* Infraestructura de experimentación.
* Gestión de versiones y recuperación ante fallos.

Una limitación aparente del modelo puede deberse a una limitación de cualquiera de estos componentes.

Por ejemplo, una respuesta deficiente puede proceder de una limitación del modelo, una recuperación de memoria inadecuada, un contexto mal construido, un formato de conversación incorrecto, una herramienta mal utilizada o un evaluador insuficiente.

Por tanto, GAIA debe diagnosticar dónde se encuentra el cuello de botella antes de elegir una intervención.

La mejora del sistema completo puede ser más efectiva que sustituir el modelo por otro de mayor tamaño. En otros casos, la limitación será intrínseca al modelo y exigirá cambiarlo o entrenarlo.

5. Automejora del LLM y de toda su pila

Esta sección constituye uno de los ejes centrales de GAIA.

El propio LLM, el mecanismo que lo ejecuta y la infraestructura cognitiva que lo rodea deben tratarse como objetos explícitos de investigación y mejora.

GAIA debe poder estudiar preguntas como:

* ¿Podemos ejecutar el mismo modelo con menor consumo y latencia?
* ¿Estamos aprovechando adecuadamente la CPU, la GPU y la memoria disponible?
* ¿Podemos preparar mejor el contexto para obtener respuestas más útiles?
* ¿Qué modelo ofrece el mejor equilibrio entre calidad, velocidad y recursos?
* ¿Qué cuantización conserva las capacidades necesarias para cada tarea?
* ¿Qué adaptaciones permiten mejorar una capacidad concreta?
* ¿Qué problemas requieren cambios en el sistema y cuáles requieren cambios en los pesos del modelo?
* ¿Cómo podemos determinar si una mejora es real, reproducible y generalizable?
* ¿Cómo puede GAIA mejorar la forma en que descubre y evalúa futuras mejoras?

La automejora de la pila se organiza en cuatro niveles complementarios.

5.1. Nivel A: runtime, inferencia y ejecución

Este nivel comprende todo lo necesario para convertir un modelo en una ejecución funcional.

GAIA debe investigar y optimizar, cuando sea aplicable:

* Configuración del modelo y del runtime.
* Tokenizer y formato de entrada.
* Plantillas de conversación y tokens especiales.
* Preparación y procesamiento de tokens.
* Gestión del contexto y límites de secuencia.
* KV cache y políticas de reutilización de contexto.
* Cuantización de pesos y otros componentes.
* Kernels de ejecución y operaciones numéricas.
* Distribución de cargas entre CPU y GPU.
* Offloading entre memoria principal y memoria gráfica.
* Uso de RAM y VRAM.
* Batching y procesamiento concurrente.
* Decodificación especulativa.
* Estrategias de muestreo y parámetros de generación.
* Gestión de lotes, colas y concurrencia.
* Latencia de primera respuesta y velocidad de generación.
* Consumo energético y estabilidad.
* Compatibilidad entre formatos de modelo y motores de inferencia.

El objetivo no es acumular optimizaciones indiscriminadamente, sino encontrar configuraciones superiores para el hardware y los tipos de tarea que GAIA utiliza realmente.

Cada cambio debe evaluarse en condiciones comparables. Una mejora de velocidad que provoque errores de formato, pérdida de calidad, inestabilidad o consumo excesivo de memoria no puede considerarse una mejora global sin valorar esas consecuencias.

También deben diferenciarse las métricas de generación. La velocidad de procesamiento del prompt, la latencia hasta el primer token y los tokens generados por segundo describen aspectos distintos del rendimiento.

5.2. Nivel B: sistema cognitivo alrededor del LLM

El modelo puede mejorar su rendimiento efectivo sin que cambien sus pesos.

GAIA debe poder optimizar:

* Memoria a corto y largo plazo.
* Selección de recuerdos relevantes.
* Recuperación aumentada por generación (RAG).
* Indexación y búsqueda semántica.
* Reordenación de resultados recuperados.
* Compresión y resumen del contexto.
* Construcción de prompts.
* Descomposición de objetivos.
* Planificación de tareas.
* Selección y ejecución de herramientas.
* Coordinación entre agentes.
* Enrutamiento entre modelos.
* Verificación de resultados.
* Detección de incertidumbre.
* Recuperación ante errores.
* Reintentos y estrategias alternativas.
* Evaluación de resultados parciales.
* Persistencia de aprendizajes útiles.

La memoria debe ayudar a recuperar información relevante, no convertir cada conversación pasada en una carga indiscriminada.

Del mismo modo, un contexto más largo no garantiza un mejor razonamiento. GAIA debe evaluar si el sistema encuentra, conserva y utiliza la información importante, especialmente cuando compite con grandes cantidades de contenido irrelevante.

El sistema cognitivo debe poder decidir cuándo conviene utilizar un modelo rápido, cuándo emplear uno más capaz, cuándo consultar memoria, cuándo usar una herramienta y cuándo reconocer que la información disponible es insuficiente.

5.3. Nivel C: el modelo en sí

Este nivel implica intervenir sobre la elección, configuración, adaptación o entrenamiento del modelo.

Las líneas de investigación incluyen:

* Comparación sistemática de modelos locales.
* Selección de modelos por tarea.
* Conversión entre formatos compatibles.
* Cuantización y evaluación de pérdida de calidad.
* Adaptación de parámetros de generación.
* Ajuste fino supervisado.
* LoRA y QLoRA.
* Entrenamiento adicional sobre datos específicos.
* Destilación entre modelos.
* Preparación y curación de conjuntos de datos.
* Evaluación de capacidades antes y después del entrenamiento.
* Investigación de arquitecturas y métodos de entrenamiento.
* Entrenamiento desde cero, si los datos, el hardware, el presupuesto y la justificación técnica lo permiten.

El modelo no debe considerarse inmutable. GAIA debe poder evaluar cuándo es preferible mejorar la infraestructura que lo ejecuta y cuándo merece la pena intervenir sobre sus pesos.

No obstante, estas operaciones tienen costes y riesgos diferentes.

Cambiar una configuración de inferencia no equivale a cambiar los pesos. Cuantizar un modelo no equivale a entrenarlo. Aplicar LoRA no equivale a entrenar desde cero. Cambiar el tokenizer o la arquitectura puede requerir una adaptación o un entrenamiento considerable y no debe tratarse como una modificación trivial.

El sistema debe conservar la identificación exacta de los artefactos, las configuraciones y los datos utilizados para cada experimento.

5.4. Nivel D: mejorar la capacidad de automejora

El nivel más estratégico consiste en mejorar la propia investigación de GAIA.

El sistema debe aprender a:

* Detectar cuellos de botella.
* Convertir problemas observados en hipótesis comprobables.
* Priorizar experimentos por valor esperado y coste.
* Diseñar pruebas que distingan entre explicaciones alternativas.
* Seleccionar métricas apropiadas.
* Detectar resultados espurios.
* Evitar comparaciones sesgadas.
* Reutilizar resultados anteriores.
* Identificar cuándo un experimento necesita más datos.
* Reconocer cuándo una hipótesis no está respaldada.
* Determinar qué cambios son reversibles.
* Investigar por qué fracasó una propuesta.
* Reducir el número de experimentos innecesarios.
* Mejorar los evaluadores sin hacerlos vulnerables a la optimización de sus propias métricas.

Esta capacidad constituye una forma de metaoptimización: GAIA no solo mejora componentes, sino también el procedimiento utilizado para encontrar mejoras.

El proceso debe permanecer sometido a evaluaciones independientes. Si el propio sistema modifica el evaluador, el benchmark o los criterios de aceptación, no puede utilizarse esa misma modificación como única evidencia de éxito.

6. Memoria y continuidad cognitiva

La memoria persistente es un componente esencial para la continuidad de GAIA.

Su finalidad es conservar información útil más allá de una sesión y permitir que el sistema construya progresivamente una representación de sus proyectos, decisiones, experimentos y aprendizajes.

La memoria debe organizarse por funciones.

6.1. Memoria de trabajo

Contiene la información necesaria para la tarea actual:

* Objetivo inmediato.
* Estado de ejecución.
* Subtareas pendientes.
* Datos relevantes.
* Resultados parciales.
* Decisiones todavía abiertas.

Debe poder actualizarse y descartarse cuando deje de ser útil.

6.2. Memoria episódica

Registra acontecimientos y experiencias concretas:

* Experimentos ejecutados.
* Cambios realizados.
* Resultados obtenidos.
* Fallos observados.
* Decisiones y su justificación.
* Condiciones bajo las que ocurrió un resultado.

6.3. Memoria semántica

Conserva conocimientos estructurados y relativamente estables:

* Documentación técnica.
* Conceptos y relaciones.
* Procedimientos validados.
* Conocimiento de herramientas.
* Resúmenes de investigación.
* Hechos con sus fuentes y nivel de confianza.

6.4. Memoria procedimental

Representa cómo ejecutar una tarea:

* Procedimientos reproducibles.
* Secuencias de herramientas.
* Protocolos de experimentación.
* Procedimientos de recuperación.
* Flujos de trabajo que han demostrado ser útiles.

6.5. Memoria de ingeniería y automejora

Registra la evolución de GAIA:

* Versiones de los componentes.
* Configuraciones de inferencia.
* Cambios de modelos.
* Hipótesis propuestas.
* Experimentos aceptados y rechazados.
* Métricas antes y después.
* Regresiones.
* Causas conocidas de fallos.
* Reglas de decisión derivadas de resultados reproducibles.

La memoria no debe limitarse a almacenar resultados exitosos. Los experimentos fallidos también son útiles cuando permiten evitar errores futuros.

La persistencia de una conclusión debe depender de su calidad. Una hipótesis provisional no debe convertirse automáticamente en un hecho permanente.

7. Contexto, razonamiento y utilización de información

GAIA debe tratar el contexto como un recurso limitado que necesita administración activa.

Aunque algunos modelos permiten ventanas de contexto extensas, la capacidad efectiva para localizar y utilizar información depende de la arquitectura del modelo, la tarea, la distribución de los datos y la calidad de la preparación del contexto.

Por ello, GAIA debe optimizar:

* Selección de información relevante.
* Recuperación por significado y por coincidencia exacta.
* Orden de los fragmentos recuperados.
* Detección de duplicados.
* Eliminación de contenido obsoleto.
* Compresión que preserve hechos y relaciones importantes.
* Identificación de contradicciones.
* Referencias a las fuentes originales.
* Separación entre instrucciones, datos y contenido externo.
* Construcción del contexto adecuado para cada modelo.

Debe distinguirse entre memoria almacenada, memoria recuperada, información incluida en el prompt y conocimiento que el modelo puede utilizar de manera efectiva.

La mejora de una de estas capas no garantiza la mejora de las demás.

8. Arquitectura neuronal y evolución de capacidades

GAIA debe mantener una arquitectura capaz de incorporar nuevas capacidades sin depender de una única familia de modelos.

La arquitectura puede evolucionar mediante varios enfoques:

* Modelos especializados por tarea.
* Enrutamiento dinámico entre modelos.
* Combinación de modelos pequeños y grandes.
* Sistemas de recuperación externos.
* Herramientas especializadas.
* Adaptadores de entrenamiento.
* Modelos auxiliares para clasificación o verificación.
* Destilación de capacidades.
* Nuevos métodos de planificación.
* Evaluadores especializados.

La decisión de incorporar una arquitectura nueva debe basarse en una necesidad concreta y en resultados medibles.

No toda mejora requiere un modelo más grande. Un modelo pequeño con buen contexto, herramientas adecuadas y un sistema de verificación fiable puede superar a una configuración más costosa en determinadas tareas.

Tampoco debe confundirse la coordinación de muchos componentes con una inteligencia superior por definición. La complejidad adicional puede aumentar los costes, introducir errores y dificultar la evaluación.

GAIA debe mantener una arquitectura experimental que permita comparar alternativas con criterios homogéneos.

9. Recursos computacionales y optimización del hardware

GAIA debe adaptarse a los recursos realmente disponibles.

Antes de seleccionar una intervención, el sistema debe conocer, en la medida de lo posible:

* CPU y capacidades relevantes.
* GPU y memoria gráfica.
* RAM disponible.
* Almacenamiento y velocidad de acceso.
* Ancho de banda entre componentes.
* Consumo energético.
* Temperaturas y estabilidad.
* Carga concurrente del sistema.
* Restricciones de ejecución.

Las optimizaciones deben priorizar los cuellos de botella observados.

Si la limitación principal es la memoria gráfica, podría estudiarse una cuantización distinta, el offloading o un modelo menor. Si la limitación está en el procesamiento de tokens, conviene analizar el runtime, los kernels y la configuración de inferencia. Si el coste principal proviene de recuperar información irrelevante, cambiar de GPU puede no resolver el problema.

El sistema debe distinguir entre:

1. Mejoras de hardware.
2. Mejoras del runtime.
3. Mejoras de configuración.
4. Mejoras de arquitectura del sistema.
5. Mejoras del modelo.
6. Mejoras del procedimiento de trabajo.

Cada categoría requiere pruebas y criterios diferentes.

10. Investigación y uso de Internet

GAIA debe poder investigar fuentes externas cuando disponga de acceso y autorización para ello.

La investigación puede incluir:

* Documentación oficial.
* Repositorios de código.
* Artículos científicos.
* Publicaciones técnicas.
* Benchmarks.
* Informes de errores.
* Experiencias de la comunidad.
* Comparaciones de modelos.
* Nuevas técnicas de entrenamiento e inferencia.
* Herramientas que puedan integrarse en el sistema.

La investigación no debe reducirse a copiar soluciones encontradas en Internet.

GAIA debe identificar el problema que pretende resolver, estudiar la aplicabilidad de cada solución, verificar las dependencias y reproducir los resultados relevantes en un entorno controlado.

El contenido externo debe tratarse como información que necesita evaluación, no como instrucciones con autoridad automática sobre el sistema.

Debe registrar las fuentes, las versiones, las condiciones de las pruebas y las limitaciones conocidas.

11. Motor de experimentación y automejora

El motor de experimentación constituye la infraestructura que convierte las hipótesis en cambios verificables.

Su función es permitir que GAIA proponga, pruebe, evalúe y, cuando corresponda, promueva modificaciones de forma controlada.

11.1. Ciclo de mejora

El ciclo general comprende:

1. Observación: identificar una limitación o una oportunidad.
2. Diagnóstico: determinar el componente probablemente responsable.
3. Hipótesis: formular una explicación y un resultado esperado.
4. Diseño: seleccionar la intervención, las métricas y los criterios de aceptación.
5. Preparación: crear un entorno de prueba aislado.
6. Ejecución: realizar el experimento.
7. Evaluación: comparar los resultados con la referencia.
8. Verificación: comprobar corrección, seguridad y ausencia de regresiones.
9. Decisión: aceptar, rechazar o dejar pendiente el cambio.
10. Promoción: publicar la versión aprobada mediante un mecanismo controlado.
11. Seguimiento: verificar el comportamiento después de la promoción.
12. Aprendizaje: registrar el resultado para orientar futuros experimentos.

11.2. Clases de experimentos

GAIA debe diferenciar entre:

* Experimentos de rendimiento.
* Experimentos de calidad de respuesta.
* Experimentos de memoria y recuperación.
* Experimentos de planificación y herramientas.
* Experimentos de cuantización e inferencia.
* Experimentos de adaptación o entrenamiento.
* Experimentos de arquitectura.
* Experimentos de seguridad y robustez.
* Experimentos sobre el propio proceso de investigación.

Esta clasificación facilita utilizar métricas y protocolos apropiados para cada clase.

11.3. Propuestas y evidencia

Cada propuesta debe identificar:

* Problema que pretende resolver.
* Componente afectado.
* Estado inicial.
* Cambio sugerido.
* Hipótesis.
* Métricas principales.
* Métricas de protección.
* Coste de ejecución.
* Riesgos previsibles.
* Condiciones de aceptación.
* Procedimiento de reversión.

El sistema debe conservar también los experimentos inconclusos y rechazados, junto con sus razones.

11.4. Control de cambios

La ejecución experimental debe estar separada del estado estable.

Las propuestas se prueban en entornos controlados. Los artefactos, los resultados y los registros deben ser verificables. La publicación debe ser transaccional y no debe dejar el sistema en un estado parcialmente actualizado.

Cuando se detecta una regresión, GAIA debe poder regresar a una versión conocida como válida.

12. Evaluación y métricas

La automejora exige medir tanto lo que GAIA gana como aquello que puede perder.

Las métricas deben elegirse en función del objetivo de cada experimento.

12.1. Rendimiento

* Latencia hasta la primera respuesta.
* Tokens generados por segundo.
* Tiempo total por tarea.
* Tiempo de preparación del contexto.
* Tiempo de recuperación de memoria.
* Uso de CPU.
* Uso de GPU.
* RAM y VRAM máximas.
* Consumo energético, cuando sea medible.
* Estabilidad y frecuencia de errores.

12.2. Calidad

* Exactitud.
* Cumplimiento de instrucciones.
* Calidad de las respuestas.
* Consistencia.
* Calidad del uso de herramientas.
* Calidad de la recuperación de información.
* Capacidad de reconocer incertidumbre.
* Tasa de alucinaciones en pruebas apropiadas.
* Robustez frente a entradas difíciles.

12.3. Capacidad de automejora

* Proporción de propuestas que producen mejoras válidas.
* Coste por experimento útil.
* Tiempo hasta identificar una solución.
* Reproducibilidad de los resultados.
* Frecuencia de regresiones.
* Porcentaje de cambios que necesitan intervención manual.
* Capacidad de detectar sus propios errores de evaluación.
* Calidad de las hipótesis y diagnósticos.

12.4. Evaluación multidimensional

Las métricas no deben reducirse a una puntuación única si eso oculta intercambios importantes.

Por ejemplo, una configuración puede generar más rápido, pero responder peor. Otra puede aumentar la calidad y consumir demasiados recursos para el uso habitual.

GAIA debe establecer criterios de aceptación por experimento, incluyendo límites para las métricas que no deben degradarse.

Cuando se utilicen intervalos de confianza, pruebas estadísticas o benchmarks pareados, deben documentarse los métodos, el tamaño de muestra y las limitaciones.

Una mejora observada en un único benchmark debe describirse como tal. No demuestra una mejora general de razonamiento, autonomía o inteligencia.

13. Seguridad, permisos y límites de autonomía

La automejora introduce riesgos específicos porque el sistema puede alterar componentes de los que depende su propio funcionamiento.

Por ello, GAIA debe mantener una separación entre la capacidad de experimentar y la autoridad para modificar el sistema estable.

13.1. Entornos aislados

Las modificaciones deben probarse en entornos con acceso limitado a los recursos necesarios.

Una propuesta de código no debe obtener automáticamente acceso a credenciales, archivos sensibles, red, procesos privilegiados o datos ajenos al experimento.

13.2. Permisos explícitos

Las acciones deben clasificarse por nivel de riesgo.

Las pruebas reversibles y de bajo impacto pueden automatizarse dentro de límites predefinidos. Las operaciones que afecten datos importantes, permisos, seguridad, acceso externo o recursos significativos requieren controles adicionales y, cuando corresponda, autorización humana.

13.3. Evaluación independiente

El componente que propone una modificación no debe poder aprobarla únicamente mediante sus propios criterios.

Los tests de regresión, los benchmarks protegidos y los controles de seguridad deben mantenerse suficientemente independientes del proceso que se está optimizando.

13.4. Registro y trazabilidad

Los cambios deben quedar asociados a sus propuestas, artefactos, métricas y decisiones.

El registro debe permitir reconstruir qué ocurrió, por qué se aceptó una modificación y cómo recuperar una versión anterior.

13.5. Límites de la automejora

GAIA no debe poder eliminar silenciosamente los mecanismos de control, invalidar sus propias restricciones ni ampliar sus permisos como consecuencia de una propuesta experimental.

Una modificación de los mecanismos de seguridad debe someterse a una revisión independiente de la evaluación de rendimiento.

14. Publicación de versiones y rollback

La publicación es una fase distinta de la experimentación.

Un resultado positivo no debe traducirse en una modificación irreversible del sistema estable.

El mecanismo de publicación debe preservar:

* Identificación de la versión anterior.
* Identificación del candidato.
* Integridad de los artefactos.
* Registro de la decisión.
* Estado de la publicación.
* Posibilidad de recuperación.
* Verificación posterior a la promoción.

La actualización debe ser transaccional: el sistema debe quedar en la versión anterior o en la nueva versión validada, no en una combinación accidental de ambas.

El rollback debe restaurar un estado funcional conocido. También debe conservar los registros necesarios para diagnosticar la causa del fallo.

No basta con que el código de reversión exista. Debe probarse que funciona.

15. Arquitectura lógica propuesta

La arquitectura de GAIA se organiza en componentes con responsabilidades diferenciadas.

15.1. Capa de interacción

Gestiona las solicitudes, las respuestas, las sesiones y la interfaz con el usuario.

15.2. Capa de orquestación

Interpreta objetivos, divide tareas, selecciona modelos y herramientas y coordina su ejecución.

15.3. Capa de modelos

Contiene los modelos de lenguaje y otros modelos auxiliares, junto con sus configuraciones y adaptadores.

15.4. Capa de inferencia

Administra el runtime, los formatos, la cuantización, el procesamiento de tokens, el contexto, la caché y la ejecución en el hardware.

15.5. Capa de memoria

Gestiona memoria de trabajo, episódica, semántica y procedimental, así como los mecanismos de indexación y recuperación.

15.6. Capa de herramientas

Proporciona interfaces controladas para ejecutar acciones, consultar fuentes y manipular recursos autorizados.

15.7. Capa de evaluación

Ejecuta pruebas de calidad, rendimiento, regresión, seguridad y comportamiento.

15.8. Capa de experimentación

Formula, ejecuta y registra los experimentos de automejora.

15.9. Capa de publicación

Gestiona versiones candidatas, promoción transaccional, integridad de artefactos y rollback.

15.10. Capa de auditoría

Conserva registros encadenados, resultados, decisiones y referencias a los artefactos.

Estas capas deben poder evolucionar independientemente, pero compartir contratos explícitos para evitar inconsistencias.

16. Energía, coste y sostenibilidad

El coste computacional es una dimensión central de la estrategia de GAIA.

Una mejora útil no siempre consiste en aumentar la capacidad máxima. También puede consistir en obtener un resultado equivalente con menos recursos, reducir la latencia o permitir que una tarea se ejecute localmente cuando antes no era viable.

GAIA debe considerar:

* Coste por tarea completada.
* Energía consumida por experimento.
* Recursos necesarios para entrenar o adaptar modelos.
* Coste de inferencia en uso habitual.
* Coste de los fallos y reintentos.
* Recursos empleados por agentes auxiliares.
* Tiempo de mantenimiento de componentes complejos.

El sistema debe evitar que una mejora local provoque un coste global mayor.

Por ejemplo, una optimización que acelere una fase pero duplique la cantidad de llamadas al modelo puede empeorar el tiempo y el consumo total de una tarea.

La decisión debe basarse en el flujo completo de trabajo y no únicamente en una operación aislada.

17. Estrategia de desarrollo y prioridades

GAIA debe evolucionar por etapas, consolidando cada capacidad antes de aumentar la complejidad.

Etapa 1. Infraestructura fiable

Prioridades:

* Arquitectura modular.
* Ejecución reproducible.
* Gestión de artefactos.
* Evaluación automatizada.
* Registro de experimentos.
* Publicación transaccional.
* Rollback probado.

Etapa 2. Automejora controlada

Prioridades:

* Generación de propuestas.
* Experimentos aislados.
* Evaluación automática.
* Criterios explícitos de aceptación.
* Registro de resultados.
* Promoción y reversión verificables.

Etapa 3. Automejora de la pila de inferencia

Prioridades:

* Benchmarks de referencia.
* Optimización de la configuración de runtime.
* Evaluación de cuantización.
* Medición de CPU, GPU, RAM y VRAM.
* Gestión eficiente del contexto y la caché.
* Comparación de motores de inferencia.
* Optimización de latencia y consumo.

Etapa 4. Automejora cognitiva

Prioridades:

* Memoria persistente.
* Recuperación de información.
* Compresión de contexto.
* Planificación.
* Uso de herramientas.
* Verificación de resultados.
* Enrutamiento entre modelos.
* Evaluación de tareas completas.

Etapa 5. Adaptación de modelos

Prioridades:

* Comparación de modelos.
* Selección por tarea.
* Cuantización y conversión.
* Ajuste fino y adaptadores.
* Curación de datos.
* Evaluación de mejoras y regresiones.
* Reproducción de resultados.

Etapa 6. Metaoptimización

Prioridades:

* Mejor selección de experimentos.
* Diagnóstico de cuellos de botella.
* Diseño de benchmarks.
* Evaluación independiente.
* Reducción del coste de investigación.
* Identificación de hipótesis prometedoras.
* Detección de métricas engañosas.

Etapa 7. Investigación avanzada

Cuando las etapas anteriores estén suficientemente consolidadas, GAIA podrá investigar técnicas más complejas de entrenamiento, arquitecturas nuevas, sistemas multiagente y métodos de mejora de capacidades.

La transición entre etapas debe depender de evidencia, no únicamente de la finalización de una lista de tareas.

18. Estado del proyecto y criterio de certificación

El progreso de GAIA debe documentarse distinguiendo entre infraestructura implementada, experimentos completados y capacidades efectivamente demostradas.

En particular, deben separarse tres afirmaciones:

1. La infraestructura de automejora funciona: GAIA puede ejecutar el proceso de propuesta, prueba, evaluación y publicación bajo condiciones controladas.
2. Un experimento concreto mejora: una propuesta produce un resultado medible superior en un benchmark específico.
3. GAIA es globalmente más capaz: el sistema demuestra mejoras sostenidas en un conjunto suficientemente amplio de tareas y evaluaciones independientes.

La primera no demuestra automáticamente la segunda, y la segunda no demuestra automáticamente la tercera.

Toda certificación debe especificar su alcance, las condiciones del experimento, la referencia de comparación, las métricas utilizadas y las limitaciones.

Cuando una campaña produzca resultados favorables, el documento de progreso debe indicar qué componente mejoró realmente. Una optimización de un trainer de CPU, por ejemplo, no constituye por sí misma una mejora del modelo de lenguaje ni una ampliación demostrada de la inteligencia general de GAIA.

El estado de producción debe permanecer separado del estado experimental. Las versiones certificadas deben poder identificarse y recuperarse, y la certificación debe poder repetirse.

19. Tecnologías y componentes

GAIA debe seleccionar tecnologías según sus necesidades reales, su compatibilidad y su mantenibilidad.

Las categorías tecnológicas relevantes incluyen:

* Runtimes de inferencia para modelos locales.
* Formatos de modelos y herramientas de conversión.
* Bibliotecas de cuantización.
* Frameworks de entrenamiento y ajuste fino.
* Sistemas de indexación y recuperación.
* Bases de datos para memoria persistente.
* Herramientas de evaluación y benchmarks.
* Sistemas de pruebas automatizadas.
* Gestión de artefactos y versiones.
* Registro y monitorización.
* Entornos aislados para experimentos.
* Herramientas de investigación y análisis.

La selección de una tecnología no debe basarse únicamente en popularidad o rendimiento anunciado.

Debe considerarse la compatibilidad con el hardware disponible, la madurez del proyecto, las licencias, la reproducibilidad, el coste de integración, la superficie de ataque y la facilidad de reversión.

GAIA debe evitar dependencias innecesarias y mantener adaptadores que permitan sustituir componentes sin reescribir todo el sistema.

20. Líneas de investigación

Las líneas de investigación deben estar conectadas con hipótesis evaluables.

20.1. Inferencia eficiente

Investigar cómo reducir latencia, memoria y consumo sin degradar las capacidades necesarias.

20.2. Gestión del contexto

Investigar métodos para seleccionar, ordenar y comprimir información manteniendo la utilidad para tareas concretas.

20.3. Memoria de largo plazo

Investigar cómo conservar experiencias y conocimientos relevantes, detectar información obsoleta y recuperar recuerdos con precisión.

20.4. Sistemas de agentes

Investigar cuándo la descomposición de tareas y la coordinación entre agentes mejora realmente los resultados y cuándo introduce costes innecesarios.

20.5. Adaptación de modelos

Investigar qué capacidades pueden mejorar mediante datos, ajuste fino, adaptadores o destilación.

20.6. Evaluación fiable

Investigar métodos para detectar regresiones, resultados espurios, sobreajuste a benchmarks y mejoras que no generalizan.

20.7. Metaoptimización

Investigar cómo elegir experimentos más informativos, reducir el coste de búsqueda y mejorar la calidad de las hipótesis.

20.8. Inteligencia general

Investigar las capacidades necesarias para transferir conocimiento entre dominios, resolver tareas nuevas, planificar a largo plazo, corregir errores y adaptarse a entornos cambiantes.

Los avances en estas líneas deben documentarse con claridad, distinguiendo resultados reproducidos, hipótesis, objetivos pendientes y especulación.

21. Principios permanentes de evolución

Los siguientes principios deben mantenerse incluso cuando GAIA se vuelva más autónoma:

1. Ningún cambio se considera una mejora sin evidencia apropiada.
2. La velocidad no sustituye a la calidad.
3. El tamaño del modelo no equivale por sí solo a mayor inteligencia.
4. Un contexto más largo no garantiza una utilización más eficaz de la información.
5. Una puntuación superior en un benchmark no demuestra una mejora general.
6. El sistema que propone un cambio no debe ser su único evaluador.
7. Toda modificación relevante debe conservar trazabilidad.
8. Los cambios deben probarse antes de publicarse.
9. Las versiones estables deben poder recuperarse.
10. Las restricciones de seguridad no deben desaparecer como efecto colateral de una optimización.
11. Las hipótesis deben distinguirse de los hechos verificados.
12. Los resultados negativos deben conservarse cuando aporten información.
13. La complejidad adicional debe justificarse mediante beneficios medibles.
14. La autonomía debe crecer en función de la fiabilidad demostrada.
15. La mejora del proceso de automejora debe someterse a controles independientes.

22. Objetivo de largo plazo: investigar el camino hacia ASI

La aspiración de largo plazo de GAIA es investigar y desarrollar sistemas de inteligencia artificial con capacidades cada vez más generales, capaces de aprender de la experiencia, utilizar herramientas, resolver problemas nuevos, realizar investigación y mejorar de forma progresiva.

En ese marco, la superinteligencia artificial es un horizonte de investigación, no un resultado garantizado ni una propiedad que pueda deducirse de una mejora de rendimiento.

El desarrollo de GAIA debe contribuir a comprender qué capacidades son necesarias, cuáles pueden obtenerse mediante mejoras de ingeniería y cuáles podrían requerir avances fundamentales en modelos, aprendizaje, memoria, razonamiento o arquitectura.

La ruta de investigación puede incluir:

* Mayor competencia en tareas diversas.
* Transferencia entre dominios.
* Planificación de tareas complejas.
* Uso fiable de herramientas.
* Aprendizaje a partir de resultados.
* Mejora progresiva de modelos y sistemas.
* Investigación autónoma dentro de límites controlados.
* Evaluación robusta de capacidades nuevas.
* Mayor eficiencia en el uso de recursos.
* Métodos de automejora más fiables.

Ninguno de estos avances aislados constituye una prueba de ASI.

La evaluación de capacidades generales requerirá tareas diversas, condiciones fuera de muestra, criterios reproducibles y controles contra la optimización excesiva de métricas concretas.

La ambición de GAIA consiste en construir una plataforma que permita investigar estas posibilidades de manera acumulativa, rigurosa y responsable.

23. Definición final de GAIA

GAIA es una plataforma de inteligencia artificial local, modular y progresivamente autoevolutiva, concebida para integrar modelos de lenguaje, memoria persistente, herramientas, planificación, evaluación, experimentación y control de versiones en un sistema coherente.

Su capacidad de mejora abarca tanto el modelo como el runtime de inferencia, el contexto, la memoria, los mecanismos cognitivos, la arquitectura de agentes y los procedimientos utilizados para investigar y validar nuevas soluciones.

GAIA debe ser capaz de identificar limitaciones, formular hipótesis, ejecutar experimentos controlados, medir resultados, conservar aprendizajes y promover únicamente los cambios que satisfagan criterios explícitos de aceptación.

Su evolución debe preservar la trazabilidad, la reversibilidad y la separación entre experimentación y estado estable.

El objetivo no es simplemente construir una IA que responda mejor hoy, sino una plataforma capaz de descubrir, verificar y acumular mejoras útiles a lo largo del tiempo.

La visión de largo plazo es explorar hasta dónde puede llegar esta estrategia y qué avances adicionales serían necesarios para desarrollar inteligencia artificial cada vez más general, sin confundir la ambición con la evidencia ni asumir que la superinteligencia sea una consecuencia automática del progreso técnico.

⸻

Anexo A. Vocabulario operativo

Automejora: proceso por el que GAIA identifica y prueba cambios en sus propios componentes o procedimientos.

Runtime de inferencia: infraestructura que ejecuta el modelo y administra recursos, tokens, contexto y generación.

Sistema cognitivo: componentes que complementan al modelo mediante memoria, planificación, recuperación, herramientas y verificación.

Adaptación del modelo: modificación de los parámetros o del comportamiento aprendido mediante técnicas como ajuste fino, LoRA, QLoRA o destilación.

Benchmark: conjunto de tareas y criterios que permite comparar configuraciones bajo condiciones definidas.

Regresión: deterioro de una capacidad o propiedad previamente alcanzada.

Promoción: incorporación controlada de una versión experimental al estado estable.

Rollback: restauración de una versión conocida como válida.

Metaoptimización: mejora de los métodos utilizados para descubrir y validar futuras mejoras.

ASI: inteligencia artificial superinteligente; objetivo de investigación a largo plazo, no una capacidad que se considere demostrada por la existencia de un mecanismo de automejora.

Anexo B. Plantilla de experimento

Cada experimento de GAIA debería registrar, como mínimo:

* Identificador único.
* Fecha y versión del sistema.
* Componente afectado.
* Problema observado.
* Hipótesis.
* Estado de referencia.
* Cambio propuesto.
* Entorno y recursos utilizados.
* Datos y benchmarks.
* Métricas principales.
* Métricas de protección.
* Resultados.
* Comparación con la referencia.
* Incertidumbres y limitaciones.
* Resultado: aceptado, rechazado o inconcluso.
* Motivo de la decisión.
* Artefactos asociados.
* Procedimiento de reversión.
* Próximos pasos recomendados.

Anexo C. Criterios mínimos de aceptación

Una propuesta no debe promocionarse únicamente porque haya terminado sin errores.

Antes de aceptar un cambio, GAIA debe comprobar, según corresponda:

1. Que el experimento se ejecutó en las condiciones previstas.
2. Que los resultados son comparables con la referencia.
3. Que la mejora alcanza el umbral establecido.
4. Que no existen regresiones inaceptables.
5. Que los artefactos y resultados pueden identificarse.
6. Que se han ejecutado las pruebas de seguridad pertinentes.
7. Que el cambio puede revertirse.
8. Que el alcance de la conclusión está descrito correctamente.

Cuando los resultados sean ambiguos, la decisión correcta es conservar el estado anterior y clasificar el experimento como inconcluso.

Anexo D. Distinción entre tipos de mejora

Tipo de mejora	Ejemplo	Qué demuestra
Rendimiento	Menor latencia de inferencia	Ejecución más rápida bajo las condiciones probadas
Eficiencia	Menor consumo por tarea	Menor coste para esa tarea y configuración
Sistema cognitivo	Mejor recuperación de recuerdos	Mejor acceso a información relevante en las pruebas
Modelo	Ajuste fino con mejores resultados	Mejora en las capacidades evaluadas
Autonomía operativa	Promoción automática de una propuesta válida	Capacidad para ejecutar un flujo de cambio controlado
Metaoptimización	Selección de experimentos más informativos	Mejora del proceso de investigación medido
Capacidad general	Mejor desempeño en tareas diversas y nuevas	Evidencia de generalización dentro del alcance evaluado
ASI	No se deduce de una optimización aislada	Requeriría evidencia mucho más amplia y criterios específicos

Anexo E. Regla central del proyecto

GAIA debe mejorar el modelo, mejorar el sistema que utiliza el modelo y mejorar el método con el que descubre cómo mejorar ambos.

Cada avance debe ser medible, reproducible en la medida apropiada, trazable y reversible. La autonomía debe apoyarse en evidencia, no sustituirla.

El progreso se define por capacidades útiles demostradas, no por el número de componentes añadidos, la complejidad de la arquitectura o la ambición de los objetivos.
