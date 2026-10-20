# Cómo seguimos — cierre de S1 y preparación de entrega

Fecha: 2026-10-19. **S1 CPU/VM ACEPTADO; entrega física y F1 abiertas.**
Estado vigente y auditoría: [CIERRE_CPU_VM_20261019.md](CIERRE_CPU_VM_20261019.md).
Tres instalaciones/reparaciones firmadas y seis arranques posteriores correctos;
auditoría `S1_CPU_VM_ACCEPTED`. La secuencia inferior conserva el historial.
SMART humano recibido: errores UNC históricos y reasignaciones registrados.
El propietario decide expresamente continuar con ese HDD; bloqueo de sustitución
resuelto, diagnóstico conservado sin declarar salud. Diagnóstico:
[DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md](DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md).
Preparar perfil físico NVIDIA e instalador físico, pues el consumidor actual
exige QEMU/lab.
Resolución NVIDIA realizada: driver550 en snapshot estable y backports, inferior
al mínimo560.28.03 del contrato. Bloqueo de procedencia/versión y propuesta:
[PERFIL_FISICO_NVIDIA_20261019.md](PERFIL_FISICO_NVIDIA_20261019.md).
Actualización vigente: ampliación oficial aprobada y ejecutada, módulos580 y
rootfs NVIDIA construidos/verificados. Bloqueo de driver resuelto; falta
presupuesto de ensamblado (84.52GB requeridos/36.91GB libres), imagen/instalador
y aceptación física. [AVANCE_NVIDIA_OFICIAL_20261019.md](AVANCE_NVIDIA_OFICIAL_20261019.md).

### Reanudación acordada: línea de meta del tramo CPU/VM

Firma recibida: `20261019T091206Z-a19b9124`, `SIGNED_ARTIFACTS_VERIFIED`,
manifiesto `7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26`.
El candidato CPU queda congelado. Primero completar tres instalaciones y tres
reparaciones firmadas con arranque posterior y DATA conservada; después auditar
S1 con evidencia por requisito y conclusión explícita. No repetir pruebas
superadas sin cambio/defecto justificante. Continuar al siguiente paso superado;
parar solo por necesidad humana, bloqueo a refinar o bucle de errores, con informe.
La preparación física y el perfil NVIDIA siguen después; no se confunden con el
cierre del tramo CPU/VM ni se declara F1 completa antes de S0/S2–S4.

**Actualización:** el propietario autoriza limpieza continua de pruebas que no
aportan a la construcción final. Aplicada la propuesta con inventario, hashes,
procesos y dependencias: 147 archivos regenerables retirados, unos 84.8 GB
asignados liberados y 103.5 GB libres después. Evidencia:
`.gaia/reports/20261019T071450Z-23655ad1/REPORT.md`.
El bloqueo de §3 queda resuelto; ese apartado conserva la auditoría previa.
Se retienen referencia firmada actual, último target reparado, rootfs y todos
los logs/manifiestos/código/datos/claves públicas. La política es continua, sin
pedir de nuevo autorización por cada fixture conocido y prescindible.

Paso 2 implementado y probado como candidato CPU: toolchain nativo retirado,
runtime L0 persistente y pruebas repetidas. Nueva puerta de firma del candidato:
[APPLIANCE_FIRMA_CANDIDATO_CPU.md](APPLIANCE_FIRMA_CANDIDATO_CPU.md).
Resultados actuales en [VALIDACION_CANDIDATO_CPU_20261019.md](VALIDACION_CANDIDATO_CPU_20261019.md).
Los pasos de aceptación firmada/física siguen pendientes; no se declara cierre.

## 1. Punto de partida comprobado

- Imagen de laboratorio `216be2f81c1ec29a726859085d6f89d9caadf911489c1090b829a93a05275c6f`.
- Diez escenarios 3/3 de una misma imagen; tres negativas de firma con destino
  intacto; tres instalaciones y tres reparaciones positivas firmadas, seis boots
  posteriores sin el USB y DATA conservada.
- Código actual: 215 tests correctos. Informes y cadena de reanudación en
  [VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md](VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md).
- Es perfil `vm-cpu-l0`, no una imagen física de operación continua. El constructor
  aún instala la unidad de prueba que evalúa y apaga la VM. El siguiente paso no
  es copiar sin más esa imagen al HDD ni anunciar el cierre de F1.

## 2. Secuencia siguiente, una puerta cada vez

1. **Resolver el presupuesto de reconstrucción y la retención de fixtures.**
   Bloqueo actual descrito en §3. No iniciar un ensamblado que agote el filesystem.
2. **Preparar un candidato de entrega**, separado del fixture VM:
   - Eliminar herramientas APT de construcción de CPython dentro del nuevo rootfs.
     No ejecutar purgas en el Ubuntu del propietario ni sobre la imagen firmada.
   - Conservar las bibliotecas de ejecución de Python/Torch/CUDA y las herramientas
     de diagnóstico/recuperación. No usar autoremove ciego ni borrar compiladores
     internos de bibliotecas que puedan ser dependencias de ejecución.
   - Registrar paquetes retirados y conservados, comprobar enlaces dinámicos,
     pip check, intérprete único y smoke real no root después de depurar.
   - Separar el modo de prueba con apagado automático del arranque operativo y
     del entorno de diagnóstico/recuperación humano. Normalizar hostname y evitar
     heredar información del PC de construcción en la entrega.
   - Mantener CORE/guardián/evaluador protegidos, política offline y permisos de
     DATA; incluir solo la raíz pública de firma.
3. **Congelar la nueva identidad y revalidar S1 sobre ella.** Depurar/cambiar
   unidades cambia el hash: los resultados de la imagen anterior son referencia,
   no aceptación automática de la nueva. Repetir los escenarios críticos 3/3;
   firmar el manifiesto del candidato desde la custodia humana cuando esté listo.
4. **Auditar §13/S1 con cada requisito y sus evidencias actuales**, y cerrar S1
   solo si la imagen que se entregará satisface su puerta. La VM no certifica
   compatibilidad NVIDIA real, watchdog o robustez del HDD físico.
5. **Preparar el HDD externo de recuperación** después de sus ensayos pertinentes,
   reidentificación y salud. Dimensionar por imágenes/copia retenida/backup/margen;
   no imponer un mínimo universal ni usar los USB de claves para este fin.
6. **Intervención humana física S0**: desconectar discos diarios/ajenos, arrancar
   el medio verificado, identificar HDD, UEFI/Secure Boot y SMART, confirmación
   visible. Después S2 (incluida GPU real), S3 y S4. F1 no se cierra antes de ellos.

El perfil NVIDIA de la appliance debe respetar §5.1: no se considera verificado
por el driver 580 del Ubuntu actual ni por el runtime CUDA de la VM CPU. Se prepara
como candidato coherente con kernel/módulos, y su compatibilidad real se prueba
antes de congelarlo como perfil físico aceptado. No se cambia ese requisito.

## 3. Bloqueo de espacio real

Auditoría actual, solo metadatos:
`.gaia/reports/20261019T063855Z-8cc06d99/REPORT.md`,
**DELIVERY_WORKSPACE_BLOCKED**.

- Aproximadamente **18.7 GB decimales / 17.5 GiB libres**.
- Pico conservador estimado del ensamblado actual: **77.7 GB / 72.4 GiB**.
  Cuenta tar transferido y extraído, filesystem de construcción, disco ensamblado,
  copia de salida, ESP/CORE/DATA, base auxiliar y margen. No es tamaño final de
  la appliance ni mínimo del USB.
- No se lanzó el ensamblado ni se borraron artefactos en esta auditoría.

### Política de limpieza autorizada por el propietario

Conservar:

- Imagen firmada actual y sus enlaces/paquete/firma/manifiestos.
- Último destino reparado de VM.
- Rootfs tar de runtime y procedencia, claves públicas y pruebas firmadas.
- Código, logs, informes, manifiestos, evidencia histórica, archivos `state_*`,
  corpus/checkpoints/archivos del proyecto y todos los USB de custodia.

Posibles retiradas de artefactos regenerables de pruebas:

| Objeto | Espacio asignado aproximado |
|---|---:|
| `20261018T194147Z-3dd692af/bundle.ext4` (cache de cuatro archivos públicos conservados) | 16.2 GB |
| `20261016T113055Z-a9d2a6f2/disk.raw` (revisión anterior) | 16.0 GB |
| `20261016T140112Z-44b6c062/disk.raw` (revisión anterior) | 16.1 GB |
| 91 archivos `.fat` intermedios de staging ESP | 23.8 GB |

Total de esos candidatos: unos **72.1 GB**. Deben comprobarse propietario,
integridad frente a manifiestos, modificaciones posteriores, ausencia de procesos
y grafo de backing antes de retirar. No borrar bases RAW dejando overlays que las
referencien: retirar también fixtures dependientes ya completados si la política
lo autoriza, o conservar la base si algún dependiente es trabajo nuevo/no confirmado.
No se propone borrar carpetas de informes completas ni usar una eliminación global.

Esta vez se trata de revisiones con ensayos válidos, no solo de los dos fixtures
fallidos ya retirados anteriormente. Se solicita decidir su retención antes de
eliminarlas. Alternativa: proporcionar un filesystem Linux de construcción con
presupuesto suficiente para mantener también esos artefactos históricos.

Tras autorizar una política, generar inventario de retiradas con hashes/motivo,
ejecutarla solo sobre fixtures identificados y comprobar espacio real de nuevo.
Entonces se retoma el candidato de entrega, no los pasos físicos.

## 4. Custodia

Siguen anotadas las confirmaciones explícitas del registro externo de huella y
del uso independiente del backup. La pública y ambas firmas se han comprobado
criptográficamente; el agente no inspecciona la privada para suplir una declaración
del propietario. No bloquea esta auditoría ni exige recrear las claves.
