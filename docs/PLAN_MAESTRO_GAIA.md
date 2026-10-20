# GAIA — Plan maestro de evolución autónoma

> **Prioridad vigente — 2026-10-19:** appliance PAUSADO por decisión del propietario.
> Firma NVIDIA lab recibida: `20261019T132311Z-8e0ae907`,
> `SIGNED_ARTIFACTS_VERIFIED`. No continuar preparación física ni pedir otra firma.
> Próxima línea: comparación experimental del Modo B ON/OFF en el laboratorio.
> Estado y condiciones de reanudación:
> [CHECKPOINT_APPLIANCE_PAUSADO_20261019.md](CHECKPOINT_APPLIANCE_PAUSADO_20261019.md).
> Las instrucciones de continuación del appliance inferiores quedan históricas.

Fecha: 15 de octubre de 2026. Estado: acuerdo de diseño y hoja de ruta; no certifica una instalación ni capacidades futuras ya implementadas.

## 1. Propósito y alcance

Construir una IA propia que conozca el sistema donde se aloja, investigue cómo aprovecharlo mejor y conserve únicamente mejoras verificadas. Su primera misión es optimizar su entorno de ejecución; después evolucionará sus componentes de lenguaje hasta desarrollar un LLM propio y capacidades progresivamente más generales.

El hardware es el entorno experimental, no una excusa para detener la investigación. GAIA debe medir sus límites efectivos, buscar alternativas y adaptar sus decisiones. No se presupone que pueda superar límites físicos ni que la automejora conduzca necesariamente a una superinteligencia: esa aspiración orienta la investigación, pero no constituye un criterio de aceptación ni un resultado demostrado.

El orden acordado es:

1. Conocer y medir el host.
2. Optimizar el uso de sus recursos mediante experimentos recuperables.
3. Ampliar el espacio de investigación con pruebas independientes.
4. Desarrollar y optimizar tokenizador, datos, modelo, entrenamiento e inferencia propios.
5. Demostrar transferencia a equipos y tareas nuevos antes de atribuir mejoras generales.

La colaboración entre IAs forma parte del desarrollo: las propuestas de arquitectura y código se incorporan con trazabilidad, revisión y verificación. Su autoría no sustituye la evidencia experimental.

## 2. Qué significa «propio»

| Infraestructura aceptada | Componentes que desarrollará GAIA |
|---|---|
| Linux, firmware, systemd, controladores, herramientas de construcción | Guardián, políticas, integridad, evaluador y mecanismos de evidencia |
| Python, NumPy, PyTorch y runtime CUDA compatible | Benchmarks, motor de experimentos, investigación y estrategia de búsqueda |
| bubblewrap, cgroups, smartmontools, herramientas de diagnóstico | Tokenizador, vocabulario, arquitectura, pesos, entrenamiento y generación |
| Herramientas externas como contraste de mediciones | Formatos propios de datos/checkpoints y ejecución de inferencia |

Se pueden estudiar técnicas de proyectos existentes sin convertirlos en el producto. No se usarán pesos preentrenados, tokenizadores externos ni runtimes de inferencia como llama.cpp como componentes funcionales. Qwen y Gemma fueron referencias del tipo de producto final, no candidatos para integrarse.

Usar herramientas del sistema o bibliotecas tensoriales no obliga a reimplementar kernels, controladores o multiplicación matricial antes de investigar IA.

## 3. Punto de partida y evidencia disponible

El proyecto actual ya contiene un laboratorio de automejora computacional:

- Campaña NumPy/CPU: propuestas restringidas, búsqueda adaptativa, cribado, confirmación pareada, promoción, auditoría y rollback.
- Persistencia: ledger, versiones estables, recuperación de experimentos incompletos e identidad experimental.
- Investigación: observación, diagnóstico, hipótesis, contraste y memoria de resultados.
- Metaoptimización: evaluación de estrategias y pruebas de transferencia separadas.
- GaiaTransformer propio: Transformer causal pequeño, fp32, vocabulario de 256 bytes, corpus sintético y entrenamiento CUDA.
- Laboratorio GPU: aislamiento con bubblewrap, monitorización, presupuestos y puertas G0–G5.

Referencias de implementación: `gaia/engine.py`, `gaia/research.py`, `gaia/meta.py`, `gaia/store.py` y `gaia/gaia_transformer/`. Evidencia histórica: documentos `VALIDACION_*` de este directorio; las validaciones del 15-10-2026 pertenecen a la identidad anterior TinyGPT.

Límites de la evidencia actual:

- Las mejoras sobre MLP sintético no demuestran mejora de un LLM.
- La campaña GPU no ha demostrado todavía una promoción real en sus ensayos históricos documentados.
- La estrategia GPU adoptada se evaluó sobre paisajes cacheados; no demuestra transferencia universal.
- GaiaTransformer activo no es aún un producto de generación de lenguaje natural.
- No existe todavía la appliance arrancable, el Host Lab aquí definido ni su recuperación certificada.

El aislamiento CPU actual por proceso/AST no se considera una frontera contra código hostil. La plataforma nueva necesita aislamiento del sistema operativo.

## 4. Plataforma física y portabilidad

### 4.1 Host inicial observado

| Recurso | Observación del equipo actual |
|---|---|
| CPU | Intel i7-4790, 4 núcleos / 8 hilos, AVX2 |
| RAM | Aproximadamente 14 GiB visibles |
| GPU | NVIDIA GTX 1060, 6 GiB VRAM, Pascal |
| Driver del host actual | Rama 580 observada; compatibilidad de la imagen pendiente de validar |
| Medio experimental | HDD SATA interno dedicado, sin capacidad prefijada |
| Instalación y recuperación | USB independiente |

Estos datos describen el primer host; no son requisitos universales ni constantes del algoritmo. La instalación dedicada volverá a medirlos.

SATA interno es la base inicial por estabilidad y acceso directo. El HDD proporciona restricciones reales de latencia y E/S sin introducir la variabilidad de un adaptador USB. No se busca empeorar artificialmente el sistema: se busca aprender de sus restricciones medibles.

### 4.2 Política por máquina

Cada host tendrá identidad de hardware/software, baseline, calibración, presupuestos y ledger propios. Un cambio relevante de kernel, driver, hardware o benchmark crea una identidad nueva o exige recalibración explícita.

Las conclusiones de otro equipo se transfieren como hipótesis/priores, nunca como evidencia local. Los valores absolutos se conservan para diagnóstico; las comparaciones entre equipos no se usarán para promocionar configuraciones mezclando baselines.

Capacidad, sectores, salud, espacio, rendimiento y características del HDD se detectan dinámicamente. No se codifica una capacidad concreta.

## 5. Sistema arrancable propio

GAIA será una appliance: al arrancar su disco, Linux proporciona el acceso al hardware y GAIA actúa como servicio principal, sin escritorio ni aplicaciones de usuario. No se ejecuta sobre el sistema diario ni necesita un kernel propio.

### 5.1 Base elegida

- Debian estable mínimo construido con `mmdebstrap` desde un snapshot fechado.
- Versiones, repositorios, paquetes, imágenes y dependencias registrados en un manifiesto.
- Kernel y firmware de distribución inicialmente, sin recompilación propia.
- systemd como init y gestión de servicios.
- Un único runtime Python de GAIA, en un venv fijado; Python del sistema solo si la distribución lo necesita. Ningún comando de GAIA dependerá de la resolución accidental del intérprete.
- Dependencias Python instaladas durante la construcción con `pip --require-hashes`; sin instalación de paquetes en ejecución.
- Perfil Torch/CUDA compatible con Pascal, inicialmente CUDA 12.x. No se deduce compatibilidad del número CUDA mostrado por `nvidia-smi`.
- Driver NVIDIA fijado solo después de verificar soporte de Pascal, kernel, módulo propietario y prueba real CUDA/GaiaTransformer en la imagen.

Buildroot queda como posible investigación posterior. No es la base inicial por el coste de integrar y mantener NVIDIA/CUDA.

Reproducibilidad significa primero reconstrucción trazable con entradas fijadas. La identidad binaria bit a bit de imágenes debe probarse antes de declararla conseguida.

### 5.2 Arquitectura de confianza

```text
UEFI
  -> cargador y recuperación
    -> sistema seleccionado A/B
      -> guardián y evaluador protegidos
        -> GAIA evolutiva sin privilegios administrativos
          -> workers aislados y experimentos
        -> DATA persistente
```

La capa evolutiva no recibe root, dispositivos de bloque ni capacidad de modificar el guardián. Este ejecuta operaciones tipadas de un catálogo mediante una interfaz estrecha, con límites y reversión.

Una partición montada en solo lectura no basta para protegerse de root. CORE, el evaluador y sus políticas deben quedar fuera del alcance del agente; se verifican sus hashes y se reduce el privilegio del guardián. Sin Secure Boot no se afirma protección completa frente a manipulación física o un kernel comprometido. La recuperación offline es la raíz externa de confianza de Fase 1.

## 6. Disco, slots y recuperación

### 6.1 Distribución lógica

| Área | Función | Escritura autorizada |
|---|---|---|
| ESP | systemd-boot, UKI y entradas A/B | Herramientas de instalación/actualización autorizadas; metadatos de intentos por el mecanismo de arranque |
| CORE | Guardián, evaluador, política y herramientas verificadas | Actualización humana firmada |
| Slot A / B | SO y componentes de ejecución versionados | Solo candidato mediante transacción autorizada |
| DATA | Corpus, modelos, experimentos, evidencia y temporales con cuotas | GAIA a través de permisos y servicios correspondientes |
| Reserva | Margen de operación y recuperación | Gestionada por política |

Los tamaños se calculan a partir de imágenes construidas, espacio de actualización y capacidad detectada, no de números universales. Si no caben dos slots operativos, CORE, DATA mínima y reserva, se rechaza la instalación. Como orientación inicial se contemplaron ESP/CORE del orden de GiB y slots de varios GiB; Torch/CUDA y sus dependencias deben determinar el tamaño real.

DATA usará inicialmente ext4. No se supone que ext4 aporte snapshots: la reversión del sistema se basa en imágenes A/B y la de archivos/configuraciones en copias y publicación atómica. La recuperación de DATA requiere respaldo, no solo rollback del SO.

### 6.2 Arranque y reversión

- UEFI puro y Secure Boot desactivado como requisito inicial, ambos verificados antes de instalar.
- systemd-boot con conteo de intentos; objetivo inicial: tres intentos para el candidato.
- El slot se bendice únicamente después de validar arranque, CORE/evaluador, acceso a DATA y salud de los recursos exigidos por su perfil.
- La GPU es requisito del perfil CUDA, no de todos los futuros hosts.
- El slot conocido-bueno se conserva durante la prueba del candidato.
- La actualización debe vincular UKI, kernel, módulos, rootfs y manifiesto del mismo slot. El detalle de selección, verificación y privilegios se prueba en VM antes del disco físico.
- Watchdog hardware si está disponible y validado; supervisión software y plazos de experimentos en todo caso.
- El soporte BIOS/GRUB no forma parte de Fase 1. Si no hay UEFI, se detiene y se revisa el diseño.

### 6.3 Recuperación física y claves

- USB de instalación/recuperación con imágenes verificables y clave pública.
- Clave privada en un soporte offline distinto, con copia de seguridad; nunca conectada a GAIA en marcha.
- Firma de imágenes, concesiones de autoridad y autorizaciones externas desde otro equipo o entorno confiable.
- Huella pública guardada por el propietario y verificada desde una herramienta confiable.
- Acceso humano a menú UEFI, teclado y monitor.
- Pérdida de clave: el sistema sigue en su nivel vigente; rotación mediante recuperación física.

**Decisión de custodia confirmada por el propietario (2026-10-16):** clave nueva
exclusiva Ed25519, formato OpenPGP/GnuPG, generada y usada para firmar por el
propietario en su PC personal confiable. USB antes `Ventoy` para privada y USB
antes `KALI LINUX` para backup independiente, ambos LUKS2 cifrados y autorizados
expresamente para borrado. La privada, su contraseña y la revocación permanecen
fuera del repositorio, del HDD instalador/recuperación y de GAIA en ejecución.
En el proyecto y la recuperación solo se publica la clave pública y su huella
completa confirmada externamente. Identidades locales y comandos humanos:
[APPLIANCE_FIRMA_OFFLINE.md](APPLIANCE_FIRMA_OFFLINE.md).

**Estado: ambos USB preparados, pública y firma de prueba Ed25519 verificadas;
pendientes confirmaciones humanas de custodia independiente y registro externo.**
Huella esperada recibida del propietario y registrada en
`keys/gaia-release-signing.fingerprint.txt`:
`6BF5C62DC530889F3D7C644F678D00EC8B5BF748`.
Exportaciones `.pub.asc`/`.pub.gpg` recibidas y comprobadas: mismo material binario,
primaria Ed25519 de firma y huella exacta. Informe:
`.gaia/reports/20261016T133757Z-78fc1d87/REPORT.md`, `OWNER_PUBLIC_KEY_MATCHES_PIN`.
Firma real de esa identidad verificada contra el desafío exacto:
`.gaia/reports/20261016T134648Z-33248432/REPORT.md`, `SIGNED_ARTIFACTS_VERIFIED`,
propósito lab; ambos USB comprobados cerrados después, sin abrirlos por el agente.
Según el procedimiento, la firma se solicita desde el backup con el primario
cerrado; falta confirmación humana explícita de esa independencia y del registro
externo. Esas confirmaciones quedan pendientes mientras se continúa el software S1.
Procedimiento humano:
[APPLIANCE_BACKUP_CLAVE.md](APPLIANCE_BACKUP_CLAVE.md). Una firma lab no autoriza
un release ni demuestra por sí sola la ubicación física de la copia privada.
El verificador no genera claves ni firma. Firma correcta no equivale a S1 OK,
autorización de instalación ni protección automática contra rollback.
El propietario ejecutó `python3 gaia/appliance_key_usb.py`: informe local
`.gaia/signing-usb-preparation.json`, `CUSTODY_USB_PREPARED`, ambos roles completos
y `private_keys_generated=false`. Salida humana acredita LUKS2/Argon2id, ext4 y
e2fsck correcto en ambos. Comprobación posterior del agente, solo metadatos:
identidades correctas, ambos `crypto_LUKS`, sin montajes ni mappers abiertos.
La preparación de los contenedores está completada; no equivale a tener una
clave o un backup de la clave ya verificados. Detalle en el manual.
Primer intento detenido por partición montada omitida en inventario JSON; helper
corregido con `lsblk --tree`, 9 pruebas correctas y nueva comprobación de identidad.
El segundo intento corrigió el montaje y terminó correctamente. No repetir el
formateo. La prueba pública de posesión de clave está verificada; la privada
permanece fuera del proyecto y no se ha usado por el verificador público.

Los backups de DATA requieren un medio independiente con capacidad suficiente. No se presupone que el USB instalador pueda contener todos los modelos o datos.

## 7. Autonomía y catálogo de acciones

«Libertad total» se concreta como amplitud de investigación y autoridad creciente sobre la plataforma propia. No significa eliminar las condiciones que permiten medir, sobrevivir y recuperarse.

| Nivel | Autoridad | Condición de habilitación |
|---|---|---|
| L0 | Inventario y benchmarks no destructivos; evidencia mediante el servicio del guardián | Estado inicial |
| L1 | Datos y experimentos propios dentro de cuotas; ledger solo por su servicio append-only | Fase 1 superada |
| L2 | Hilos, afinidad, prioridad, cgroups y parámetros de sesión/disco/energía permitidos | Recuperación probada, ensayos del catálogo y autorización firmada |
| L3 | Configuración del slot candidato, parámetros de kernel/módulos e imágenes de paquetes locales firmados | Transacciones y arranques de prueba verificados |
| L4 | Kernel, driver y servicios candidatos | Validación ampliada y autorización humana inicial por clase |
| L5 | Firmware, UEFI, bootloader binario, particiones, CORE, claves, evaluador, política de red y discos ajenos | Exclusivamente humano, fuera de la autonomía evolutiva |

Cada acción especifica precondiciones, estado previo, límites, efecto esperado, comprobación, reversión, plazo y evidencia. Un incidente degrada autoridad y bloquea nuevas modificaciones hasta diagnóstico.

L0 no impide al guardián guardar informes. L1 no permite a la IA reescribir evidencia histórica. Los benchmarks de disco con escritura se limitan a archivos de prueba en DATA y presupuestos explícitos; nunca al dispositivo bruto durante diagnóstico.

Los ajustes L2 se aplican solo si existen en ese hardware. No se fuerza control de clocks, potencia o governor no soportado. Los valores exactos de cuotas, tolerancias y número de ensayos se fijarán en un contrato versionado tras medir el host.

## 8. Red, privacidad e ingesta

- Sin red en operación normal; interfaces desactivadas y firewall con denegación por defecto.
- Workers y evaluador sin red mediante aislamiento de namespaces.
- Ventanas de descarga autorizadas externamente, con alcance, duración monotónica, tamaño y destinos limitados.
- Autorizaciones ligadas a un desafío de arranque y nonce de un solo uso, registradas para impedir reutilización; no se confía solo en la hora del sistema.
- Descarga mediante usuario sin privilegios y namespace separado. La resolución DNS y los redireccionamientos no pueden eludir la política.
- Cuarentena: URL, hashes, tamaño, procedencia, licencia y verificación antes de incorporar datos.
- Si no existe hash esperado confiable, el hash calculado sirve de identidad, no prueba por sí solo autenticidad.
- Sin benchmarks durante ingesta o actividad de red.
- Actualizaciones ejecutables preparadas fuera, firmadas e introducidas como imágenes; ningún texto descargado se ejecuta como instrucción de sistema.
- Operación offline completa con recursos locales.

Solo se accede por defecto a particiones propias y telemetría necesaria de `/proc` y `/sys`, filtrada por rol. Los trabajadores no reciben una vista administrativa completa.

Discos ajenos sin montaje automático ni nodos accesibles al agente. Para inventariarlos, solo el componente de confianza accede a metadatos autorizados. Dispositivos USB de ingesta se identifican y montan en solo lectura, `noexec,nodev,nosuid`; etiqueta/UUID no se consideran autenticación suficiente. Los mecanismos concretos de control deben permitir el USB de recuperación y dispositivos USB autorizados sin bloquearlos accidentalmente.

Serial, MAC y hostname no aparecen en claro en evidencia exportada; las identidades se pseudonimizan con sal por host. La identificación física del disco durante instalación se muestra localmente cuando es necesaria.

## 9. Host Lab: investigación verificable

### 9.1 Observación y pruebas

Inventario: CPU, topología, cachés, SIMD, RAM, almacenamiento, GPU/VRAM, drivers, runtime, sensores, compiladores y capacidades disponibles.

Pruebas propias: cómputo, localidad/ancho de banda de memoria, operaciones de disco secuenciales/aleatorias, latencia de sincronización, GPU, transferencias y cargas representativas de GAIA. Herramientas externas sirven de contraste, no de sustituto del benchmark versionado.

Se separan carga fría/caliente, inicialización/trabajo, datos en caché/E/S efectiva, tiempo instrumentado/tiempo de promoción. Se registra la incertidumbre y se detectan procesos interferentes, calentamiento, deriva y saturación.

Sin swap en HDD como perfil inicial; zram se evalúa con su coste CPU/RAM explícito. Las pruebas E/S directas, cuando se soporten, requieren alineamiento correcto y no sustituyen medir también el comportamiento real con caché. Limpiar cachés no será una acción indiscriminada entre todos los ensayos.

### 9.2 Ciclo de investigación

1. Observar una carga y localizar su cuello de botella.
2. Formular una hipótesis con cambio, alcance, precondiciones, beneficio esperado y falsación.
3. Estimar coste y beneficio máximo plausible, incluida cota de Amdahl cuando aplique.
4. Elegir una acción del catálogo y guardar el estado previo.
5. Ejecutar cribado y comparación pareada/intercalada con baseline equivalente.
6. Evaluar corrección, estabilidad y recursos mediante el evaluador protegido.
7. Promover, conservar como alternativa, rechazar o declarar inconcluso.
8. Restaurar si corresponde y verificar la restauración.
9. Registrar evidencia y actualizar prioridades, sin convertir resultados negativos en prohibiciones universales.

La primera inteligencia puede ser algorítmica y estructurada. No necesita comprender lenguaje natural para investigar, y no se le atribuye razonamiento general por ejecutar este ciclo.

### 9.3 Métricas y promoción

No hay una puntuación universal. Se mantiene una frontera Pareto por host y carga con objetivos de latencia/tiempo hasta calidad, throughput, RAM/VRAM, energía cuando sea medible y estabilidad.

Restricciones: corrección, tasa de errores, ausencia de corrupción, temperatura según límites validados, salud del disco y recuperación funcional. Determinismo bit a bit se exige dentro de perfiles donde esté demostrado; no se presupone entre arquitecturas, kernels o implementaciones numéricas diferentes.

Las comparaciones usan cocientes orientados consistentemente —costes menores son mejores, throughput se transforma o indica con claridad—, intervalos de confianza y una mejora práctica mínima. Promoción del perfil principal: mejora confirmada sin regresiones fuera de tolerancias predeclaradas. Un intercambio velocidad/memoria puede conservarse como alternativa Pareto, sin sustituir silenciosamente al campeón.

Se controlan comparaciones múltiples y selección repetida mediante presupuesto de búsqueda y auditoría reservada. Un control nulo y un control de sensibilidad verifican el instrumento. No observar errores no prueba una fiabilidad perfecta.

Los benchmarks protegidos no evolucionan durante una comparación. Nuevas cargas pueden proponerse, pero se revisan, versionan y crean una identidad/calibración separada; el agente no puede facilitar su propio examen.

## 10. Evidencia, memoria y persistencia

Cada experimento registra identidad de host/software/benchmark, baseline, hipótesis, acción, estado previo, presupuestos, orden de ejecución, medidas crudas, incertidumbre, decisión y resultado de reversión.

El ledger tendrá escritura controlada, secuencia y cadena de hashes; publicación atómica y `fsync` donde corresponda. Una cadena detecta ciertas alteraciones, pero no impide por sí sola que alguien con acceso total sustituya toda la historia. Se requieren permisos, anclajes/resúmenes externos y backups.

Tras interrupción se conserva el prefijo confirmado y verificable; una cola incompleta puede descartarse de forma explícita. No se promete conservar operaciones que nunca llegaron a almacenamiento estable. Caché de escritura del HDD y garantías reales de sincronización deben comprobarse.

La compactación afecta vistas derivadas, índices o archivos archivados verificables, no reescribe silenciosamente el historial. La memoria global conserva condiciones de aplicabilidad y separa observaciones de inferencias.

## 11. Datos y evolución hacia lenguaje propio

El primer corpus será especializado en el objetivo: implementaciones propias, perfiles, métricas, hipótesis, resultados y fundamentos técnicos relevantes. Se evita introducir conversación general sin una necesidad medida.

Fuentes previstas:

- Datos sintéticos propios para probar el pipeline.
- Evidencia empírica propia para aprender qué funciona bajo qué condiciones.
- Documentación y textos técnicos con licencia clara, seleccionados y trazables.

Restringir el dominio reduce dispersión, pero no garantiza ausencia de sesgos ni conocimiento correcto. Un modelo no aprende a optimizar solo por leer su ledger; su utilidad se compara con estrategias simples y controles aleatorios.

Entrenamiento, validación y auditoría se separan por origen y contenido, evitando duplicados. La auditoría nunca guía selección; si se usa para ajustar decisiones, se declara consumida y se prepara otra. La telemetría viva se consulta como memoria estructurada, no se obliga al modelo a memorizar el estado cambiante del PC.

Evolución prevista, después de la base de host:

1. Generación autoregresiva propia sobre el modelo byte-level: parada, semillas, muestreo, checkpoints y recarga.
2. Tokenizador entrenable propio, inicialmente BPE, comparado con bytes en coste y efecto sobre aprendizaje; no solo tokens/s.
3. Pipeline de texto real especializado, corpus versionado y evaluación retenida.
4. Modelos pequeños propios con capacidad elegida tras medir coste, memoria y aprendizaje.
5. Búsqueda de arquitectura y entrenamiento: dimensiones, capas, atención, normalización, optimizador y organización de datos.
6. Inferencia propia: prefill, decodificación, KV cache, cuantización y formatos, con pruebas de paridad o tolerancias explícitas.
7. Ampliación de capacidades lingüísticas y tareas únicamente si mejora y transfiere.

La Fase 0 de transición definida a continuación documentará las capacidades y
activos útiles del prototipo `legacy_v0` como entradas concretas para esta evolución.
Su retirada no significa que entrenamiento sobre texto, checkpoints o generación
estén ya implementados en la base activa. F4/F5 deberán cerrar esas capacidades
con pruebas propias y trazabilidad a la especificación de transición.

No se fijan fechas de entrenamiento a partir de TFLOPS nominales. Se extrapola desde ensayos end-to-end medidos, incluyendo datos, validación, checkpoints y memoria.

## 12. Hoja de ruta completa

La numeración siguiente corresponde a la appliance y su evolución. No renumera las fases históricas TinyGPT documentadas en el repositorio ni las fases del [plan de renombrado](PLAN_RENOMBRADO_GAIA_TRANSFORMER.md).

| Fase | Entregable | Criterio de salida |
|---|---|---|
| F0 — Transición y consolidación de la base | GaiaTransformer renombrado y validado; inventario, especificación funcional y destino de activos de `legacy_v0`; retirada del prototipo duplicado | Plan de renombrado cerrado y traspaso legacy verificable, sin activos útiles sin destino ni capacidades futuras presentadas como implementadas |
| F1 — Instrumento de host | Imagen mínima, instalación identificada, recuperación A/B, inventario y benchmarks | Validación detallada de la sección 13 |
| F2 — Investigación de recursos L2 | Catálogo reversible, búsqueda, memoria y comparaciones | Ciclos completos de rechazo/promoción/inconcluso y restauración comprobada; para afirmar mejora, ganancia confirmada y auditada |
| F3 — Evolución del entorno L3/L4 | Construcción de slots candidatos y pruebas de arranque | Candidato verificable, promoción y fallback demostrados; ningún cambio al núcleo de confianza |
| F4 — Datos y tokenización propios | Pipeline, particiones de datos, BPE y generación mínima byte-level | Entrenamiento/recarga/generación end-to-end, equivalencia de tokenización y coste/beneficio medido |
| F5 — Modelo de lenguaje propio | Modelo pequeño entrenado desde cero, checkpoints y evaluación | Aprendizaje fuera de entrenamiento, generación verificable, exportación/recarga y consumo medidos |
| F6 — Inferencia y entrenamiento eficientes | Caché KV, cuantización y variantes propias | Mejora de rendimiento a calidad comparable, sin esconder regresiones |
| F7 — Investigación ampliable | Nuevas familias de operadores y metaestrategias | Mayor eficacia que baselines a presupuesto igual en tareas reservadas; expansión del catálogo revisada |
| F8 — Portabilidad y capacidades más generales | Validación en otros hosts y tareas, interacción local | Recalibración autónoma, transferencia demostrada y límites documentados |

La caracterización de recursos continúa en todas las fases; no se espera «optimizar todo» de forma definitiva antes de avanzar. Un máximo global no puede certificarse por agotar unas variantes. Se avanza con cobertura y presupuestos explícitos, conservando investigación abierta.

### 12.1 Fase 0 — Transición y consolidación de la base

**Estado: OK (2026-10-16).** Renombrado y reconstrucción fases 0–6 cerrados con
evidencia nueva en `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`; traspaso en
`TRANSICION_LEGACY_V0.md`. Prototipo retirado, muestra preservada y verificada.
Las capacidades de texto/checkpoints/generación permanecen pendientes F4/F5.
Esta fase prepara la base para F1; no adelanta el producto
de lenguaje de F4/F5. Se ejecuta coordinada con las fases 0–6 del plan de
renombrado, sin duplicar experimentos. Cada paso requiere resultados verificados
antes de pasar al siguiente.

#### A. Inventario y especificación antes de retirar el prototipo

- Revisar todos los archivos de `legacy_v0`, incluidas rutas ignoradas o generadas:
  corpus, checkpoints, configuración, historial, scripts y dependencias. Registrar
  existencia o ausencia real; no deducir que no hay datos por no estar versionados.
- Crear `docs/TRANSICION_LEGACY_V0.md` con inventario, hashes de activos,
  procedencia, formatos, parámetros, decisiones y destinos concretos.
- Documentar el pipeline original con suficiente detalle para no depender de
  recordar el código: lectura UTF-8 como bytes, ventanas de contexto, muestreo,
  entrenamiento, separación de datos, arquitectura, pesos ligados, guardado,
  recarga, continuación y generación. Incluir valores por defecto y limitaciones.
- Crear una matriz por capacidad: origen, componente actual equivalente (si lo
  hay), destino futuro, contrato esperado, prueba de aceptación y estado. Lo que
  se posponga a F4/F5 queda registrado como pendiente, no como migrado.

#### B. Destino de datos y conocimiento útil

| Elemento | Tratamiento |
|---|---|
| Corpus `data/train.txt` y otros textos | Revisar contenido, procedencia y utilidad. Preservar datos útiles con hash y manifiesto en una ubicación neutral documentada; el texto de muestra no se convierte automáticamente en corpus de entrenamiento válido |
| Checkpoints, si existen | Preservar los bytes originales y metadatos de arquitectura, runtime y formato fuera del estado activo; registrar si su lectura se ha verificado. No afirmar compatibilidad con GaiaTransformer ni convertir pesos sin pruebas |
| Historial y resultados, si existen | Conservar evidencia única útil como histórica, con hashes y alcance; no transferir sus decisiones como promociones del evaluador nuevo |
| Algoritmos y utilidades aprovechables | Documentar comportamiento y referencias; extraer fixtures o ejemplos mínimos independientes cuando aporten valor, sin conservar un segundo motor ejecutable |
| Reglas de aceptación antiguas | Documentar para interpretar el historial; sustituirlas en el futuro por contratos actuales con evaluación independiente, sin importar el umbral legacy como regla general |
| Duplicados y temporales | Retirar tras registrar por qué no aportan datos o funcionalidad únicos |

Para cada activo debe constar «preservado y verificado en ruta concreta»,
«sustituido por equivalente probado» o «descartado con justificación». Un archivo
no se borra solo por llevar un nombre antiguo. Si hay dudas sobre contenido único,
se preserva hasta resolverlas. El archivo histórico de datos no será un paquete
ejecutable mantenido ni una dependencia del runtime. Sus nombres de almacenamiento
serán neutrales; los metadatos de procedencia y los bytes originales conservarán
la identidad histórica necesaria para interpretarlos.

#### C. Requisitos mínimos transferidos a F4/F5

- Corpus externo local, versionado y verificable; particiones train/validación/
  auditoría por origen y contenido, con controles de duplicación y sin fuga.
- Representación byte-level propia con encode/decode UTF-8, tratamiento explícito
  de secuencias inválidas y pruebas de ida/vuelta para texto válido.
- Entrenamiento desde cero con presupuestos, semillas, parada y registro de
  métricas; continuación desde checkpoint con semántica declarada para pesos,
  optimizador y RNG. El prototipo solo conservaba pesos: no atribuirle reanudación
  exacta del optimizador ni del RNG.
- Formato de checkpoint con identidad de modelo, datos, configuración y runtime;
  publicación atómica, comprobación de integridad, recarga y rechazo de
  incompatibilidades. La recuperación exacta, si se promete, debe demostrarse.
- Generación autoregresiva con prompt, contexto acotado, semilla, temperatura,
  límite de salida y parada; prueba end-to-end entrenamiento → guardado →
  recarga → generación sobre el modelo causal propio.
- Evaluación retenida y controles independientes conforme al contrato nuevo,
  separados del benchmark sintético CUDA, cuya identidad se conserva.

Estas capacidades se implementarán sobre GaiaTransformer y las abstracciones
comunes que realmente compartan los workloads. No se introduce una abstracción
universal solo para alojar el código antiguo. La arquitectura legacy basada en
`TransformerEncoder` y sus checkpoints no se consideran intercambiables con la
atención causal explícita actual.

#### D. Retirada y puerta de salida

Retirar `legacy_v0/` durante la fase 6 del plan de renombrado **solo después** de
completar A/B/C y verificar los destinos de los activos conservados. Actualizar
README y referencias para que no anuncien scripts eliminados.

F0 queda OK cuando el renombrado está validado, el prototipo duplicado se ha
retirado y `docs/TRANSICION_LEGACY_V0.md` permite localizar cada activo útil y cada
requisito futuro con su prueba prevista. No exige implementar lenguaje antes del
Host Lab; sí exige que F4/F5 tengan entradas concretas sin depender de archivos
que se vayan a borrar. No se declara ausencia total de deuda técnica: quedan
pendientes explícitos y trazables, sin una implementación paralela abandonada.

## 13. Fase 1 ejecutable: Instrumento de host

**Estado de ejecución (2026-10-19): tramo S1 CPU/VM ACEPTADO; entrega física de
S1 y F1 ABIERTAS.** Tres instalaciones y tres reparaciones del candidato firmado,
seis arranques operativos posteriores y DATA conservada: `091600Z-78c27069`.
Auditoría `100144Z-91a97bb3`, `S1_CPU_VM_ACCEPTED`. Informe de cierre y transición:
[CIERRE_CPU_VM_20261019.md](CIERRE_CPU_VM_20261019.md).
Actualización 2026-10-19: candidato CPU depurado construido, 34 paquetes de
compilación/cabeceras retirados y 174 retenidos sin cambios de versión. Nuevo
arranque L0 persistente separado del probe VM; tres arranques operativos correctos,
pip/ABI/modelo no root comprobados. Diez escenarios y negativa de firma repetidos
3/3 sobre el nuevo hash `195cd3661217bd6cc4de8af38e314786a097994940cd61288ed4d1de2a9ed4de`.
Firma humana recibida y verificada: `20261019T091206Z-a19b9124`,
`SIGNED_ARTIFACTS_VERIFIED`, manifiesto
`7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26`.
Instalación/reparación positivas de **ese** candidato completadas 3/3;
los éxitos firmados de la revisión anterior no se trasladan automáticamente.
224 tests actuales OK. Informe:
[VALIDACION_CANDIDATO_CPU_20261019.md](VALIDACION_CANDIDATO_CPU_20261019.md).
Solicitud y comandos humanos:
[APPLIANCE_FIRMA_CANDIDATO_CPU.md](APPLIANCE_FIRMA_CANDIDATO_CPU.md).
Auditoría 2026-10-19: el bloqueo de workspace se resolvió mediante limpieza
autorizada por el propietario: 147 fixtures regenerables, unos 84.8 GB recuperados,
103.5 GB libres después. Política continua autorizada para retirar pruebas que
no contribuyan a la construcción final, verificando referencias/uso/procedencia
y conservando datos, código, logs/manifiestos, claves y referencia firmada vigente.
No se requiere repetir aprobación para cada fixture elegible. Secuencia y detalle:
[CIERRE_S1_ENTREGA.md](CIERRE_S1_ENTREGA.md).
El usuario instaló las herramientas mediante el bootstrap.
El probe genérico unshare era demasiado restrictivo: mmdebstrap tiene un perfil
AppArmor que permite su helper real. Bootstrap corregido y APPLIANCE_HOST_READY.
Base Debian construida y verificada en
`.gaia/reports/20261016T100352Z-e5710bf9/rootfs-manifest.json`.
El usuario ejecutó `appliance-rootfs --with-runtime` y terminó con
`DEBIAN_RUNTIME_ROOTFS_BUILT`; la selección automática de `/var/tmp` resolvió los
fallos de temporales. Artefacto verificado contra su hash e inventario real:
`.gaia/reports/20261016T102648Z-70fc2c5a/rootfs-manifest.json`.
Python 3.14.4, Torch 2.14.0+cu126 y NumPy 2.3.5; smoke GaiaTransformer en CPU
correcto con UID 997. Se construyó imagen GPT UEFI de laboratorio con CORE/guardián
L0, política offline y A/B. La revisión actual incorpora la raíz pública del
propietario y verifica su firma de prueba en el invitado con sqv de Debian.
Imagen `.gaia/reports/20261018T182432Z-f0a96e77/disk.raw`, SHA-256
`216be2f81c1ec29a726859085d6f89d9caadf911489c1090b829a93a05275c6f`.
Pasaron 3/3 cada uno: A, B, intentos/fallback, B corrupto, staging parcial,
corrupción lógica DATA/restauración desde otro disco, SIGKILL del publicador y
reboot, bendición saludable, rechazo de salud y arranque desde USB emulado.
63 arranques de esa matriz; además rechazo de firma incorrecta en recuperación
con destino intacto 3/3. Suite actual 215 tests OK, sin skips.

Firma del paquete recibida y contrastada con la solicitud exacta.
Instalación/reparación **positivas 3/3** y seis boots independientes sin USB,
readback de imagen/sistema y DATA conservada con ledger 1→2. Informe definitivo
`.gaia/reports/20261018T203350Z-9e9b020a/REPORT.md`, `VM_SIGNED_RECOVERY_VALIDATED`.
Se reanudaron resultados comprobados tras corregir prompts Unix de mcopy y
transporte intercalado de consola; sin cambiar la imagen firmada.
Pendientes criterios de release, retirada del toolchain y aceptación final; no
equivale a instalación física autorizada. Informe detallado:
[VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md](VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md).
La privada sigue en custodia externa, no se usa por el agente. Confirmaciones
humanas de independencia del backup y registro externo aún pendientes.
Informe vigente: [VALIDACION_APPLIANCE_S1_20261018.md](VALIDACION_APPLIANCE_S1_20261018.md).
El [informe VM anterior](VALIDACION_APPLIANCE_S1_VM.md) se conserva como histórico.
Las autorizaciones y el cambio de secuencia siguen confirmados; no se requieren
nuevas autorizaciones generales de borrado. El diagnóstico anterior permanece en
`evidencia_appliance/preflight_s1_20261016T094641Z.json` como evidencia histórica.
El aprovisionamiento de herramientas ya está implementado como
`python3 gaia.py appliance-bootstrap`: muestra dependencias, pide confirmación,
delega la contraseña al sudo del terminal y verifica otra vez. Diagnóstico sin
instalar: `--preflight`. Uso y resultados en [APPLIANCE_BOOTSTRAP.md](APPLIANCE_BOOTSTRAP.md).
Su implementación no declara lista la imagen ni superada la puerta de S1.
Constructor de base: `python3 gaia.py appliance-rootfs`; runtime de construcción:
`python3 gaia.py appliance-rootfs --with-runtime` (selector temporal automático
con presupuesto de 16 GiB; `--tmpdir` permite fijarlo explícitamente).
Constructor/pruebas UEFI: `python3 gaia.py appliance-image --rootfs-manifest PATH`;
reutilización sin rebuild: `--image-dir PATH`, escenarios: `--boot-scenarios`.
Las imágenes actuales declaran `release_image=false`, `signed=false`; las pruebas
VM no habilitan instalación física ni cierran la puerta de S1.
`appliance-recovery --image-dir PATH` prepara solicitud de firma; con
`--bundle-dir PATH` ejecutará instalación/reparación firmadas en VM tras validarlas.
`--negative-check --repeats 3` exige rechazo de firma y destino virtual intacto.
F0 conserva su cierre OK; F2–F8 no se han iniciado. El usuario ha confirmado las
autorizaciones y la secuencia siguientes. No se vuelven a solicitar los mismos
permisos generales; se conserva la comprobación de identidad física de S0.

| Medio | Identificación observada | Función y autorización |
|---|---|---|
| HDD interno `Shared` | SATA, ST1000DM003-1ER162, 1000204886016 bytes; actualmente `/dev/sdb`, partición `/dev/sdb1` | Disco completo autorizado para borrado e instalación de la appliance, slots A/B y DATA |
| HDD externo por adaptador Ugreen USB 3/SATA | ST9250315AS, 250059350016 bytes (232.9 GiB); actualmente `/dev/sdd`; WWN local comprobado en la sesión de identificación | Disco completo autorizado para borrado y preparación como instalador/recuperación, con espacio de backup inicial sujeto al tamaño real de DATA |

Los nombres `/dev/sdX`, las etiquetas y los identificadores del puente USB no
sustituyen modelo/serie/capacidad del disco. Se reidentificarán antes de escribir;
la identidad completa se muestra localmente, no en evidencia exportada. Ningún
otro disco está autorizado para borrado. El sistema diario está actualmente en
`/dev/sda2`; otro SATA ajeno sigue conectado.

### Secuencia F1 acordada y confirmada

**Transición tras cierre CPU/VM:** el siguiente inventario reidentifica el HDD
externo ST9250315AS (250059350016 bytes) ahora como `/dev/sda`, montado. SMART
humano recibido: 3 sectores reasignados, Reported_Uncorrect=1576, log ATA con
1461 errores y UNC explícitos; pendientes/no corregibles offline actuales=0.
El estado global passed no acredita salud suficiente. **Decisión expresa del
propietario posterior al diagnóstico: «No me importa, usamos ese». Se conserva
el ST9250315AS como medio autorizado de instalación/recuperación con su historial
SMART registrado; queda resuelto el bloqueo de sustitución.** No se declara sano
ni se borra la evidencia. Se mantienen verificación de integridad/readback y parada
ante errores de E/S o deterioro nuevo durante las operaciones. Detalle:
[DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md](DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md).
Las letras de la tabla anterior son históricas. Antes de escribir el medio debe
existir instalador físico (el actual solo admite QEMU/lab) y perfil NVIDIA con
kernel/módulos coherentes; la imagen CPU queda como referencia cerrada. Detalle,
evidencias y secuencia concreta en el informe de cierre anterior. S0/S2–S4 siguen
pendientes; no se solicita otra firma del paquete CPU ya aceptado.

**Siguiente bloqueo comprobado:** resolución NVIDIA del snapshot fijado y sus
backports realizada en mmdebstrap. Estable ofrece `550.163.01-2`; backports,
`550.163.01-4~bpo13+1`. Ambos quedan por debajo del mínimo `560.28.03` de
`gaia-transformer-cuda-pascal` (Torch cu126/CUDA12.6). No se rebaja el contrato.
Evaluación `20261019T101513Z-7a976e76`, `NVIDIA_PROFILE_BLOCKED_DRIVER_MINIMUM`.
Pendiente refinar procedencia del driver; recomendación investigar fuente oficial
NVIDIA firmada/rama propietaria 580 con Pascal, versiones/hashes fijados y kernel
Debian coherente. No se construye una revisión incompatible ni se copia el driver
del host. Informe y secuencia:
[PERFIL_FISICO_NVIDIA_20261019.md](PERFIL_FISICO_NVIDIA_20261019.md).

**Ampliación aprobada por el propietario (2026-10-19): «Si seguimos».** Se autoriza
investigar e incorporar la fuente oficial NVIDIA firmada para el driver
propietario compatible con Pascal, manteniendo Debian estable, kernel fijado y
lock Python/Torch. Se continúa resolución/verificación de paquetes y módulos sin
volver a solicitar esta ampliación de procedencia.

**Resultado actual de esa ampliación:** NVIDIA oficial propietario580.178.04
autenticado y descargado (`102204Z-922ea833`), cuatro módulos compilados para
6.12.107+deb13-amd64 (`103018Z-602c9ef1`), rootfs NVIDIA integrado
(`103937Z-05e8888d`, SHA256
`d347405889851b87266774d408b74b543bdd26590fca5e5dcd6ba6d764444572`).
Readback de los módulos correcto; 85 tests appliance OK sin skips. GPU real aún
no probada. Bloqueo actual `105034Z-cb1bf2cc`, `NVIDIA_IMAGE_WORKSPACE_BLOCKED`:
presupuesto84.52GB, libres36.91GB, déficit47.61GB tras limpieza autorizada.
Pendiente refinar workspace/retención antes de imagen CUDA/instalador; después
VM/firma física/preparación/S0/S2–S4. No se declara F1 cerrada. Informe completo:
[AVANCE_NVIDIA_OFICIAL_20261019.md](AVANCE_NVIDIA_OFICIAL_20261019.md).

**Workspace adicional autorizado (2026-10-19):** el propietario aprueba crear un
archivo contenedor ext4 de construcción en el SSD Samsung870EVO1TB, volumen UUID
`661EC3B41EC37C15`, montado en `/run/media/mingororo/661EC3B41EC37C15`.
Se reserva archivo dedicado de120GiB, sin reparticionar/formatear el SSD ni
modificar sus archivos anteriores. Montaje previsto `/mnt/gaia-build`, con
temporales y artefactos voluminosos en ext4. Sudo requiere autenticación humana;
se prepara/verifica el archivo y después se solicita únicamente su montaje.
Estado local en `.gaia/build-workspace.json`; no equivale aún a imagen construida.
Archivo120GiB creado/asignado y e2fsck correcto: `110456Z-3a1a67b0`,
`EXT4_WORKSPACE_FILE_READY_AWAITING_MOUNT`. Pendiente exclusivamente montar con
sudo humano y validar; bloque exacto y siguientes pasos:
[WORKSPACE_SSD_CONSTRUCCION_20261019.md](WORKSPACE_SSD_CONSTRUCCION_20261019.md).
Después integrar TMPDIR **y salidas grandes** en SSD para resolver ambos gates
de espacio del constructor; no volver a crear/formatear el contenedor.

**Workspace y nueva imagen ya ejecutados:** montaje verificado por propietario
`111130Z-503c0ab6` y agente `111229Z-47cd4091`. Builder y fixtures VM usan SSD;
informes locales espejan los externos. Imagen NVIDIA `111348Z-95cd9936`, SHA256
`63dc4c7ee9d905edcf2cd61a0f107c7861d03d7bad8c36332e1f0cd5f795b0a4`,
34 paquetes build-only retirados; servicio CUDA obligatorio y allowlist GPU.
Diez escenarios3/3 (63 boots seleccionados), auditoría `125118Z-1bba0062`, 88 tests
appliance OK sin skips. Timeout global del primer runner documentado; se aceptan
solo casos completos únicos y los restantes se ejecutaron en `122929Z-aa6cdca6`.
Pendiente humano: firma lab para primer diagnóstico GPU físico, manifiesto
`2f2401fe2092e3e9bfd5a82780270eb05addb88683966dfede7fce4b0a973c77`.
No equivale a instalador interno ni aceptación CUDA/F1; hardware aún no probado.
[VALIDACION_NVIDIA_WORKSPACE_20261019.md](VALIDACION_NVIDIA_WORKSPACE_20261019.md),
[APPLIANCE_FIRMA_PREFLIGHT_GPU.md](APPLIANCE_FIRMA_PREFLIGHT_GPU.md).

**Acuerdo de ejecución 2026-10-19:** congelar el candidato CPU anterior; completar
en orden tres instalaciones y tres reparaciones firmadas con arranque posterior
y conservación de DATA, y auditar S1 requisito por requisito. No repetir matrices
ya superadas sin cambios o defectos que lo justifiquen. La auditoría debe producir
cierre o carencias concretas, no un pendiente genérico. S1 CPU/VM y F1 física son
hitos distintos; NVIDIA/kernel/driver y S0/S2–S4 conservan su alcance.
Continuar uno por uno y pasar al siguiente paso si se supera el anterior. Parar
solo por intervención humana necesaria, bloqueo que requiera refinar el plan o
error repetitivo sin avance. En toda parada entregar informe de acciones,
evidencias, resultados y pendientes; si se completa todo, informe completo final.

1. **Construcción y validación S1 primero desde el host de desarrollo actual**:
   imágenes/manifiestos y pruebas QEMU/OVMF con discos virtuales desechables,
   sin acceso a discos físicos. La desconexión del disco diario no es requisito
   de esta preparación de software.
2. Preparar el HDD externo como instalador/recuperación, tras superar los ensayos
   pertinentes de S1, comprobar su identidad/salud y calcular capacidad necesaria.
3. Realizar **S0 físico** arrancando desde ese HDD externo USB verificado, con
   discos diarios/ajenos desconectados. Superar S0 y S1 antes de instalar (S2).
4. Completar S2, S3 y S4 y su evidencia antes de iniciar F2.

Este acuerdo resuelve la dependencia circular del orden original S0→S1. S0 no se
considera superado por autorizar el borrado ni por aprobar pruebas en VM. Los
pasos de desconexión se aplican a la instalación y ensayos físicos, no al host de
construcción. El medio externo USB no cambia la decisión de usar SATA directo
como disco experimental principal.

La capacidad mínima del medio de recuperación **se calculará a partir de las
imágenes construidas**, las copias retenidas y el margen previsto. Las cifras
64/128 GB comentadas antes fueron recomendaciones de aprovisionamiento, no un
mínimo validado por el plan. El HDD externo de 250 GB está disponible; su cabida
real sigue pendiente de construcción. Un backup inicial en él es independiente
de Shared, pero no sustituye los otros requisitos de recuperación: la clave
privada debe permanecer offline en otro soporte y un backup creciente de DATA
necesitará capacidad suficiente independiente.

Comandos, evidencia, requisitos pendientes y acuerdos confirmados en
[registro de ejecución](EJECUCION_PLAN_MAESTRO_GAIA.md).

### S0 — Preflight físico y diagnóstico sin escritura

1. Tras la preparación S1 en el host de desarrollo, desconectar los discos diarios/ajenos antes de arrancar el instalador; mantenerlos desconectados durante S0, S2–S4 y la operación física de GAIA.
2. Arrancar el HDD externo USB de instalación/recuperación verificado; confirmar UEFI y Secure Boot desactivado.
3. Enumerar dispositivos con herramientas como `lsblk`, `smartctl -x` y consulta de identidad ATA, cuando proceda.
4. Identificar exactamente un disco interno candidato por modelo, serie y capacidad. Ninguna partición del objetivo montada; excluir el medio de arranque y cualquier dispositivo ambiguo.
5. Examinar salud SMART y lectura no destructiva. No medir escritura sobre el disco bruto.
6. Comprobar clave pública/imagen y capacidad suficiente según el manifiesto construido.
7. Solicitar confirmación manual visible de identidad y borrado. Los últimos caracteres de serie ayudan, pero no sustituyen la identificación completa ni la exclusión de otros discos.

Salida: objetivo inequívoco y saludable, requisitos de arranque satisfechos y confirmación registrada. Si aparecen varios discos internos o hay ambigüedad, se detiene sin ofrecer un forzado automático.

SMART correcto no garantiza un disco sano. Sectores pendientes/no corregibles o señales preocupantes requieren revisión antes de instalar. Los valores históricos se registran y los cambios durante pruebas detienen la experimentación.

### S1 — Construcción y recuperación en VM

- Construir imagen/manifiesto desde entradas fijadas.
- Probar en QEMU/KVM con OVMF, almacenamiento desechable y sin acceso al disco físico objetivo.
- Probar instalación, slots, slot B corrupto, agotamiento de intentos, retorno a A, interrupción de publicación y recuperación desde USB.
- Probar corrupción de DATA y restauración de un backup; A/B no debe presentarse como reparación de datos.
- Verificar aislamiento, política offline, acceso al catálogo y prohibición de modificar CORE.

Salida: al menos tres repeticiones satisfactorias por escenario crítico definido, con logs e identidades. La VM no certifica GPU ni watchdog físico.

### S2 — Instalación y arranque dedicado

- Solo tras S0/S1, particionar e instalar el HDD confirmado.
- Validar inventario, rootfs/CORE, runtime único y compatibilidad GPU real.
- Probar arranques normales, candidato y fallback; objetivo inicial de robustez: veinte arranques en frío satisfactorios, documentando qué se ensayó.
- Detectar watchdog hardware y probarlo si existe; si no existe, registrar la limitación y conservar supervisión software/recuperación física.

Salida: plataforma estable y recuperable, sin acceso a discos ajenos.

### S3 — Benchmark propio v0

- Adaptar G0–G5: runtime, corrección, fiabilidad, integridad, controles y presupuesto.
- Caracterizar CPU, RAM, HDD y GPU, más cargas representativas NumPy/GaiaTransformer.
- Separar muestras de calentamiento, medición y auditoría; registrar duración, energía disponible y evolución térmica.
- Probar estabilidad térmica con duración inicial de diez minutos, ampliable si no alcanza régimen estable.
- Objetivos iniciales de precisión: CV hasta 3 % CPU/RAM, 10 % HDD aleatorio y 2 % GPU. Son metas del instrumento, no garantías ni motivos para alterar umbrales después de ver un candidato.
- Repetibilidad GaiaTransformer: objetivo 10/10 bit a bit dentro del mismo perfil congelado. Si falla, diagnosticar antes de usarlo como referencia.

Salida: baseline e incertidumbre conocidas, controles nulo/sensibilidad correctos, benchmarks versionados y presupuestos compatibles con salud/temperatura.

### S4 — Ensayo de recuperación física

- Primero simular fallos en VM; después probar apagado/interrupción controlada y recuperación en disco con backup ya comprobado.
- Probar slot candidato dañado y recuperación manual desde USB.
- Solo al final, si se decide probar pérdida brusca de alimentación, hacerlo como ensayo físico separado, documentado y recuperable.
- Objetivo inicial: cinco recuperaciones satisfactorias del prefijo confirmado del ledger, sin atribuir persistencia a escrituras no confirmadas.

Salida: recuperación automática y manual demostradas, datos restaurables y manifiesto de F1 firmado/archivado fuera del disco experimental.

### Parada y degradación

Detener y diagnosticar ante:

- Cualquier escritura intentada sobre un dispositivo no autorizado.
- Violación de integridad o incapacidad de restaurar una acción.
- Nuevos sectores pendientes, no corregibles o reasignados.
- Temperatura fuera de límites fijados por dispositivo; 55 °C sostenidos en HDD es un umbral provisional de revisión, sujeto a especificación.
- Errores GPU Xid: registrar y evaluar desde el primero; recurrencia o pérdida de corrección bloquean la campaña.
- Mediciones persistentemente no reproducibles tras repetir con condiciones controladas.
- Espacio insuficiente, cuota agotada o presupuesto térmico/temporal excedido.

Una parada produce evidencia y conserva la recuperación. No se reinterpreta como mejora ni se solventa relajando el evaluador durante la campaña.

## 14. Riesgos y tratamiento

| Riesgo | Tratamiento |
|---|---|
| Formatear otro disco | Desconexión física, exclusión del arranque, identificación completa y rechazo de ambigüedad |
| HDD antiguo o datos perdidos | SMART más pruebas, presupuestos de E/S, backup independiente y restauración ensayada |
| Incompatibilidad NVIDIA/Pascal | Perfil fijado y prueba real antes de congelar; kernel/módulos/driver coherentes por slot |
| Espacio insuficiente por CUDA | Dimensionar según imágenes reales y rechazar instalación si faltan márgenes |
| Arranque roto | A/B, intentos limitados, slot bueno preservado y USB offline |
| Falsa mejora o sobreajuste | Pares intercalados, controles, tolerancias previas, auditoría y tareas reservadas |
| Privilegios que anulan CORE | Agente sin root/disco bruto, catálogo estrecho y verificación externa |
| Corrupción del ledger | Prefijo confirmado, escrituras durables, recuperación y anclajes externos |
| Datos externos maliciosos o confundidos con instrucciones | Cuarentena, parsers limitados y separación entre contenido, propuesta y autoridad |
| Modelo entrenado sin utilidad real | Comparación con reglas/búsqueda aleatoria y criterios de transferencia |
| Expectativas de escalado no demostradas | Ensayos end-to-end medidos y capacidad creciente solo con evidencia |

## 15. Decisiones cerradas y verificaciones pendientes

Cerrado: misión host-first, IA propia sin modelos/runtime externos, infraestructura Linux aceptada, Debian mínimo, HDD SATA sin capacidad fija, aislamiento del sistema diario, arranque A/B, recuperación offline, autoridad por catálogo, evidencia por host y progresión posterior a lenguaje.

Pendiente de comprobación física o implementación: HDD conectado e identidad/salud; UEFI/Secure Boot; disponibilidad de soportes offline y equipo para firma; watchdog; perfil exacto Debian/kernel/NVIDIA/Torch; tamaño real de imágenes; presupuestos y parámetros del catálogo; garantías de persistencia y precisión de medidas.

Este plan registra acuerdos, razones y criterios de prueba. No constituye permiso para formatear un dispositivo no identificado ni evidencia de que F1 haya sido superada.

Al completar y verificar los criterios de Fase 1, GAIA podrá empezar la Fase 2: investigar y optimizar sus recursos mediante el catálogo L2, con evidencia y rollback.
