# Prompt para nueva sesión

Status: Historical — not current operational guidance

Trabaja en `/home/mingororo/Projects/GAIA`. Quiero centrar GAIA en comprobar si
mejora su propio proceso de descubrimiento. El appliance queda PAUSADO por decisión
mía. Lee primero `docs/CHECKPOINT_APPLIANCE_PAUSADO_20261019.md` y respeta ese cambio
de prioridad aunque otros documentos históricos indiquen continuar con el HDD.
La firma NVIDIA ya está verificada en
`.gaia/reports/20261019T132311Z-8e0ae907/REPORT.md`; no hay que pedirla de nuevo.
Conserva todo el trabajo del appliance para retomarlo desde W2 si vuelve a tener
sentido. No continúes construcción, preparación de discos ni instalación física.

Tu tarea es diseñar Y EJECUTAR una comparación acotada del Modo B/investigación
activado frente a `research.enabled: false` en el laboratorio existente:

1. Inspecciona CLI, configuraciones, pruebas y resultados previos. Localiza la
   evidencia del CV 0.5 %, control nulo 1.00, saturación MLP (~13×) y la hipótesis
   refutada. Separa antecedentes verificados de afirmaciones sin informe localizado.
2. Comprueba qué hace realmente ON/OFF y si el Modo B llega a intervenir dentro
   de campañas cortas. No confundas un interruptor sin actividad con una prueba
   válida de su valor. Usa las puertas de verificación existentes.
3. Prerregistra por escrito, ANTES de los resultados, varias parejas de campañas
   MLP cortas: mismo punto de partida, configuración, semillas emparejadas y número
   de experimentos; estados independientes, orden alternado y recursos iguales.
   Evita contaminación por campeones, historial o cachés compartidos. Fija número
   de parejas, criterio concreto de consistencia, fallos y saturación; no extiendas
   la muestra después para buscar un resultado favorable.
4. Ejecuta el protocolo y compara mejoras verificadas, ganancia final, tiempo
   total incluyendo investigación, fallos y coste. Conserva comandos, configs,
   semillas, logs y resultados individuales. Distingue exploración de confirmación
   independiente y no cuentes varias veces la misma mejora como descubrimientos.
5. Si ON no supera consistentemente a OFF, concluye que Modo B no ha demostrado
   valor en esta prueba y propón cambios concretos al Research Engine. Si gana,
   amplía después el espacio de búsqueda y workload. Si hay saturación o evidencia
   insuficiente, declara el resultado inconcluyente sin venderlo como ventaja.
6. Haz la comparación equivalente en TinyGPT/CUDA solo si carga y runtime del
   host ya están listos. Si no, registra el bloqueo y termina la prueba MLP.
7. Solo considera aislamiento barato si el CV empeora. No cambies servicios,
   governor ni drivers sin acordarlo; no construyas un SO para esta prueba.

Quiero avanzar en dos o tres sesiones con criterio de parada, sin volver a quedar
atrapado en infraestructura. Empieza inspeccionando y avanza hasta resultados o
un bloqueo real. Al terminar entrega una conclusión honesta sobre el valor
demostrado del Modo B, limitaciones y siguiente decisión basada en los datos.
