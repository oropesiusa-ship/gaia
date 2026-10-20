# Ejecución del plan maestro GAIA

## 2026-10-19 — Firma verificada y pausa explícita del appliance

Leído el informe `20261019T132311Z-8e0ae907/REPORT.md`:
`SIGNED_ARTIFACTS_VERIFIED`, manifiesto GPU lab esperado y dos artefactos íntegros.
No autoriza instalación. El propietario decide guardar checkpoint y priorizar
pruebas emparejadas del Modo B ON/OFF; no se continúa al HDD ni a CUDA física.
F1 sigue incompleta. Se conservan plan, decisiones D1–D4, código y evidencia.
Checkpoint y prompt de siguiente sesión:
[CHECKPOINT_APPLIANCE_PAUSADO_20261019.md](CHECKPOINT_APPLIANCE_PAUSADO_20261019.md),
[PROMPT_EVALUAR_MODO_B.md](PROMPT_EVALUAR_MODO_B.md).
No se ejecutan campañas nuevas en esta sesión de archivo.

## Workspace montado, imagen NVIDIA y matriz VM — firma GPU física pendiente

Montaje humano `111130Z-503c0ab6` contrastado por agente `111229Z-47cd4091`.
Integrados temporales y artefactos externos con comprobación de montaje/UUID/
backing y reportes espejo locales. Imagen `111348Z-95cd9936`, SHA256
`63dc4c7ee9d905edcf2cd61a0f107c7861d03d7bad8c36332e1f0cd5f795b0a4`,
NVIDIA580/kernel6.12.107, initramfs módulos/helper, 34 build-only retirados,
runtime CUDA no root, nodos acotados y sin fallback CPU si falta GPU.

Matriz `112849Z-1a4842c4` interrumpida por timeout global de herramienta3600s;
no quedan procesos activos. Ocho escenarios completos3/3 guardados se conservan;
health-reject/USB ejecutados3/3 en `122929Z-aa6cdca6`. Auditoría `125118Z-1bba0062`
selecciona30 casos únicos/63 boots y verifica hash de fuente. No acepta parciales
ni duplica health-reject. 88 tests appliance OK sin skips (0.970s).

Solicitud firma lab de diagnóstico físico GPU preparada y auditada en
`125118Z-1bba0062`, manifiesto
`2f2401fe2092e3e9bfd5a82780270eb05addb88683966dfede7fce4b0a973c77`.
Parada por firma humana; no privada por agente ni escritura al HDD externo.
No se atribuye CUDA real, instalador físico ni F1 completo. Informe y bloque humano:
[VALIDACION_NVIDIA_WORKSPACE_20261019.md](VALIDACION_NVIDIA_WORKSPACE_20261019.md),
[APPLIANCE_FIRMA_PREFLIGHT_GPU.md](APPLIANCE_FIRMA_PREFLIGHT_GPU.md).

## Contenedor de construcción listo — montaje humano pendiente

Archivo120GiB asignado en SSD autorizado, ext4 UUID
`40b184e0-21a2-43e9-8d02-df296c6d28af`, root_owner1000:1000 y e2fsck0:
`20261019T110456Z-3a1a67b0`, `EXT4_WORKSPACE_FILE_READY_AWAITING_MOUNT`.
Primer intento `110446Z-80e6efb3` abortó sin crear por lsblk sin árbol;
corregido con --tree, segunda ejecución correcta. Sudo exige autenticación
interactiva: se detiene para montaje exacto, sin volver a formatear. Verificador
posterior preparado para montaje/UUID/backing/propiedad/POSIX/sparse/espacio.
No se atribuye resultado a esa verificación aún no ejecutada. Instrucciones e
informe: [WORKSPACE_SSD_CONSTRUCCION_20261019.md](WORKSPACE_SSD_CONSTRUCCION_20261019.md).
Queda integrar salidas voluminosas y temporales en SSD, construir imagen/instalador
y completar la aceptación del plan. No se declara F1 terminada.

## Workspace SSD autorizado — 2026-10-19

El propietario responde «Adelante entonces!» a crear contenedor ext4 dedicado
en SSD Samsung870EVO1TB, volumen UUID661EC3B41EC37C15. Identidad modelo/serie/
capacidad y montaje NTFS3 read/write revalidados. Sudo no interactivo requiere
autenticación humana. Se prepara archivo120GiB con ext4 y e2fsck, sin cambiar
particiones, documentos existentes ni destinos de instalación. El workspace
montado deberá albergar también artefactos grandes; solo TMPDIR no elimina el
gate de espacio del proyecto actual.

## NVIDIA oficial ejecutado — Entradas, módulos, rootfs; bloqueo de workspace

Tras la aprobación y el recordatorio de continuar sin reducir alcance:
fuente oficial firmada NVIDIA580.178.04-1 resuelta sobre Debian13/kernel6.12.107,
descarga autenticada `102204Z-922ea833`; módulos compilados `103018Z-602c9ef1`;
runtime integrado `103937Z-05e8888d`, SHA256
`d347405889851b87266774d408b74b543bdd26590fca5e5dcd6ba6d764444572`.
85 tests appliance OK sin skips; sintaxis shell correcta. Auditoría de identidad
y hashes de los cuatro módulos dentro del rootfs correcta `105034Z-cb1bf2cc`.
Limpieza autorizada `102627Z-16fa1bc7` completada después de comprobar que el
intento interrumpido no seguía ejecutándose; referencias protegidas conservadas.

Parada por presupuesto de imagen insuficiente: 84521353216 bytes requeridos,
36912422912 libres, déficit47608930304. No se lanza ensamblado que agote disco.
No se completan imagen/instalador, GPU real, firma física o S0/S2–S4 por inferencia.
Incidencias de keyring/cache y rootfs importado conservadas, corregidas o alternativa
descartada; ninguna se presenta como validación ni hay bucle activo.
Informe completo y reanudación:
[AVANCE_NVIDIA_OFICIAL_20261019.md](AVANCE_NVIDIA_OFICIAL_20261019.md).

## Ampliación de fuente NVIDIA aprobada — 2026-10-19

El propietario responde «Si seguimos» a incorporar fuente oficial NVIDIA firmada
para el driver propietario/Pascal manteniendo Debian estable y lock Python/Torch.
Se registra y se retoma resolución y construcción, sin cambiar el mínimo560.28.03.

## Transición física 2026-10-19 — Resolución NVIDIA y bloqueo de versión

Implementado `appliance-nvidia --probe` con namespace mmdebstrap, snapshot firmado
Debian fijado y componentes non-free necesarios; conserva policy/metadatos/hashes
y simulación. Probe estable `20261019T101241Z-c22b4fc6`: driver propietario
550.163.01-2, headers6.12.107-1. Probe backports `20261019T101346Z-d5039ca4`:
driver550.163.01-4~bpo13+1 y headers7.2.6-1~bpo13+1. Ambos resuelven correctamente,
pero ninguno satisface el mínimo560.28.03 del contrato CUDA vigente.
Evaluación offline de evidencias con hashes `20261019T101513Z-7a976e76`,
`NVIDIA_PROFILE_BLOCKED_DRIVER_MINIMUM`, salida20 explícita de bloqueo.
Cuatro tests nuevos OK sin skips. No se repitieron matrices ni suite histórica,
no se instaló/compiló driver ni se alteró la imagen CPU o medios físicos.
Parada para refinar fuente del driver: propuesta investigar fuente oficial NVIDIA
firmada/propietaria580 con Pascal, sin rebajar contrato ni cambiar lock Torch.
Informe completo: [PERFIL_FISICO_NVIDIA_20261019.md](PERFIL_FISICO_NVIDIA_20261019.md).
La decisión de usar el HDD diagnosticado ya está registrada y no bloquea.

## Decisión del propietario 2026-10-19 — Mantener el HDD externo diagnosticado

Tras recibir el análisis SMART y la recomendación de sustitución, el propietario
indica expresamente: «No me importa, usamos ese». Se mantiene ST9250315AS externo
como instalador/recuperación autorizado. Se resuelve el bloqueo de sustitución,
conservando diagnóstico y baseline de contadores; no equivale a certificar salud.
No se vuelve a pedir esta decisión. Continúa el perfil NVIDIA/Pascal y el
instalador físico con verificaciones de integridad/readback e identidad vigentes.
La decisión no cambia otros destinos autorizados ni la custodia de claves.

## SMART recibido 2026-10-19 — Sustitución del medio de recuperación pendiente

El propietario aporta diagnóstico privilegiado del ST9250315AS externo, epoch
1792404416. Resuelto el bloqueo de acceso, pero el medio no supera la revisión:
3 reasignados, Reported_Uncorrect=1576 y log ATA extendido con 1461 errores,
incluido UNC a la hora 6734 frente a 7093 horas actuales. Pendientes/offline
uncorrectable=0, CRC=0, 28 °C, SMART passed; no neutralizan el historial UNC.
Código 64 indica log de errores, no fallo de permisos. Sin autotests registrados.
No se infiere crecimiento actual de una sola muestra ni se igualan errores a
sectores únicos. No hubo operaciones sobre medios ni nuevas pruebas CPU/VM.
Parada por necesidad de elegir soporte de recuperación sustituto; se recomienda
sustituirlo en vez de abrir rondas de pruebas del disco deteriorado. Informe:
[DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md](DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md).
El cierre CPU/VM se conserva; perfil NVIDIA e instalador físico siguen pendientes.

## Cierre 2026-10-19 — S1 CPU/VM aceptado; primera frontera física

Ejecutado el controlador firmado 3/3 sin errores ni reanudaciones:
`.gaia/reports/20261019T091600Z-78c27069/REPORT.md`,
`VM_SIGNED_RECOVERY_VALIDATED`. Tres instalaciones, tres reparaciones, seis boots
operativos sin USB y DATA/ledger 1→2 conservados. Imagen fuente intacta.
Auditoría reproducible `docs/audit_s1_cpu_20261019.py` ejecutada correctamente:
`.gaia/reports/20261019T100144Z-91a97bb3/REPORT.md`, `S1_CPU_VM_ACCEPTED`.
Diez escenarios previos 3/3, negativas 3/3 y depuración/runtime contrastados;
no se repitió la matriz ni la suite previa de 224 tests. 81 boots finales acumulados.

Transición iniciada con inventario físico de solo lectura. Letras cambiadas:
externo ST9250315AS ahora `/dev/sda` y montado; Shared ahora `/dev/sdc`; diario
ahora `/dev/sdb`. `smartctl -x --json /dev/sda` devuelve Permission denied/código 2.
Parada por diagnóstico SMART que requiere intervención humana. El instalador es
QEMU-only/lab y falta implementar el perfil físico NVIDIA: carencias identificadas,
no otro pendiente de auditoría CPU. No se escribieron ni desmontaron medios.
Informe completo y pasos siguientes: [CIERRE_CPU_VM_20261019.md](CIERRE_CPU_VM_20261019.md).

## Reanudación 2026-10-19 — Firma recibida y alcance de cierre congelado

El propietario aporta `20261019T091206Z-a19b9124/REPORT.md`, estado
`SIGNED_ARTIFACTS_VERIFIED`, para el manifiesto
`7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26`.
Se congela la imagen `195cd3661217bd6cc4de8af38e314786a097994940cd61288ed4d1de2a9ed4de`.
Secuencia inmediata: tres instalaciones y reparaciones positivas firmadas,
auditoría explícita de S1, continuación al siguiente paso si se supera. No volver
a ejecutar matrices satisfactorias sin causa nueva. El propietario pide avanzar
uno por uno hasta necesidad humana, bloqueo a refinar o bucle de errores, dejando
informe completo en cualquier parada. No se equipara cierre CPU/VM a F1 física.

## Sesión 2026-10-19 — Candidato depurado/persistente y nueva solicitud de firma

Tras liberar el presupuesto autorizado, se implementa `--delivery-candidate`.
Simulación protegida de retirada APT, inventario antes/después y conservación
de bibliotecas/versiones; se retiraron exactamente **34 paquetes** y se mantienen
174. No autoremove ni modificaciones de paquetes del host. Nuevo selector fijo
de servicios, runtime L0 persistente sin root y probe VM explícito; estado
sincronizado en DATA y comprobaciones reales de imports/ldd/pip/modelo CPU.

Imagen `.gaia/reports/20261019T075104Z-0bda6b85/disk.raw`, SHA-256
`195cd3661217bd6cc4de8af38e314786a097994940cd61288ed4d1de2a9ed4de`.
Tres arranques operativos `CPU_DELIVERY_RUNTIME_VALIDATED`:
`20261019T080658Z-5d9d1767` (UID997, Python3.14.4, pip check correcto).
Diez escenarios 3/3, mismo hash, 63 arranques:
`20261019T081025Z-4e6e623f` y `20261019T083236Z-4b77c01a`.
Negativa de firma 3/3: `20261019T085227Z-678598b8`.
**224 tests OK, 27.284 s sin skips**: `20261019T085227Z-7811da92`.

Incidencias: guard inicial impidió purga transitiva de bibliotecas dependientes
de binutils-common; se conservó el paquete común, nueva simulación/purga exactas.
Validación chroot con binds bloqueada: alternativa retirada, ABI/modelo validado
en VM real, sin cambiar AppArmor. Runner leyó JSON parcial de serie: corregido
para esperar línea completa, con regresión por cada prefijo truncado. Tres boots
posteriores correctos sobre el mismo artefacto construido.

Segunda limpieza continua de staging completado:
`20261019T085951Z-6e28bdb0`, mantiene referencias firmadas/candidato/último target.
No formateos físicos ni lectura/copia de privada por el agente.

**Parada humana:** nueva solicitud
`.gaia/reports/20261019T085624Z-4770def7/install-bundle/install-manifest.json`,
SHA-256 `7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26`.
Es otro hash, por lo que requiere firma del propietario antes de aceptar la
instalación/reparación positiva nueva. Procedimiento exacto en
[APPLIANCE_FIRMA_CANDIDATO_CPU.md](APPLIANCE_FIRMA_CANDIDATO_CPU.md).
Detalle completo: [VALIDACION_CANDIDATO_CPU_20261019.md](VALIDACION_CANDIDATO_CPU_20261019.md).
S1/F1 y pruebas físicas siguen abiertas; perfil CPU no certifica NVIDIA/Pascal.

## Actualización 2026-10-19 — Limpieza continua autorizada y espacio recuperado

El propietario autoriza retirar pruebas sin aporte a la construcción final y
continuar limpiezas según necesidad para no bloquear el espacio. Se registra la
política local `.gaia/artifact-retention.json` y el limpiador auditable
`gaia/appliance_artifacts.py` (plan por defecto, aplicación con `--apply`).

Se comprueba grafo de backing, procedencia por comando productor, propietario,
mtime contra cierre del informe, hashes registrados y ausencia de uso. Se excluyen
referencias actuales por inode, enlaces, archivos ajenos y descendientes no
identificados. Los hijos se retiran antes que las bases; nunca carpetas completas.
Inventario previo `20261019T070828Z-3bb4297f`, aplicación
`.gaia/reports/20261019T071450Z-23655ad1/REPORT.md`,
**DISPOSABLE_ARTIFACTS_CLEANED**: 53 qcow2 dependientes, 2 RAW anteriores,
1 cache bundle y 91 staging FAT, **147 archivos / 84787912704 bytes asignados**.
Espacio libre pasa de 18745077760 a 103532826624 bytes. Cinco tests de retención
correctos, incluidos dependiente protegido, ciclo, origen input/output y aplicación
real sobre fixtures temporales preservando claves/referencias/logs.

Se conservan imagen firmada vigente y sus enlaces/paquete, último target reparado,
rootfs, manifiestos, logs, código y estados/corpus/archivos del proyecto. Los USB
privados no se acceden ni forman parte de esta política. El bloqueo de espacio
queda resuelto y se retoma depuración del candidato; S1/F1 siguen abiertas.
## Auditoría 2026-10-19 — Próximo paso: entrega; bloqueo de workspace

El propietario pregunta cómo seguir. Se revisan constructor y criterios de §13,
confirmando que el próximo trabajo es perfil de entrega/retirada de toolchain,
separación del arranque operativo respecto del probe con apagado, nueva identidad
de artefacto y revalidación antes de preparar el medio físico.

Bloqueo real del presupuesto: 18.7 GB libres aproximadamente, pico conservador
77.7 GB con tar transferido/extraído, ext4, raw ensamblado/copiado y margen.
`.gaia/reports/20261019T063855Z-8cc06d99/REPORT.md`,
**DELIVERY_WORKSPACE_BLOCKED**. Se detiene antes de ensamblar según §13.

Inventariados, sin borrar, unos 72.1 GB candidatos a liberación: cache bundle,
dos revisiones RAW antiguas y 91 staging FAT. Son ahora artefactos de ensayos
válidos, por lo que se pide política de retención. La propuesta conserva imagen
firmada actual, último target reparado, rootfs, claves públicas, logs/manifiestos,
código y datos del proyecto. Los overlays que dependen de una base retirada se
deben identificar/retirar coherentemente, sin afectar dependientes desconocidos.

Informe y secuencia exacta: [CIERRE_S1_ENTREGA.md](CIERRE_S1_ENTREGA.md).
No se ejecutó purga de paquetes, formateo, nueva firma ni limpieza en esta sesión.
F1/S1 sigue abierta. No se solicita nueva autorización general de HDD; se decide
únicamente retención de fixtures de software o un nuevo lugar de construcción.
## Sesión 2026-10-18 — Firma comprobada e instalación/reparación positivas 3/3

El propietario comunica que ejecutó el procedimiento. Se encuentra y contrasta
su firma del manifiesto exacto: informe `20261018T194012Z-42a20cef`,
`SIGNED_ARTIFACTS_VERIFIED`; SHA de manifiesto
`0d0333fc6a7035cb7367b09b1ba160daadc2d1fad99971528a6b62705e25b0a2`, firma
`c49876bcbc035d43f157f1001ce8930c3af13817d98da7a3756c760ffa6edc0e`, huella fijada.

Se descubre que también inició las pruebas. Informe `20261018T194147Z-3dd692af`:
instalación 1/boot correctos, después timeout esperando confirmación de mcopy
sobre un readback Unix ya existente. Corregido con destinos nuevos por llamada,
sin forzar sobrescrituras. Reanudación validando firma/fuente/cache/target.
Informe `20261018T201343Z-e5cd54a4`: reparación 1/boot correctos; instalación 2
acabó readback, pero printk partió el JSON de consola. Parser restringido al
formato conocido de enumeración, salida de kernel más silenciosa. Se aceptó
instalación 2 solo después de comparación de todo el target contra el raw firmado
y un nuevo boot independiente. No se reutilizó exit 0 como prueba de éxito.

**Resultado definitivo:** `.gaia/reports/20261018T203350Z-9e9b020a/REPORT.md`,
**VM_SIGNED_RECOVERY_VALIDATED**, seis resultados únicos: install y repair-system
para repeticiones 1/2/3. Seis boots sin USB posteriores; cada instalación ledger 1,
cada reparación conserva DATA y boot extiende ledger a 2. Imagen firmada no cambió.
Informe completo y cadena de procedencia:
[VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md](VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md).

**215 tests OK, 29.697 s, sin skips**:
`.gaia/reports/20261018T210144Z-2d7effcc/REPORT.md`.
Evidencia resumida: `evidencia_appliance/recuperacion_firmada_20261018.json`.
No se usó privada por el agente ni se instaló sobre discos físicos. Este ensayo
lab queda completado; S1/F1 siguen abiertas: perfil de release/toolchain/aceptación
final y después S0/S2–S4 físicos conforme al plan. Las confirmaciones de custodia
física y registro externo siguen siendo datos del propietario, no inferencias
automáticas de un verificador de firmas.

## Sesión 2026-10-18 — Matriz S1 actual, DATA, salud y recuperación firmada

Se continúa hasta la frontera de firma humana del nuevo paquete de instalación.
**F1/S1 permanece abierta**. Informe completo:
[VALIDACION_APPLIANCE_S1_20261018.md](VALIDACION_APPLIANCE_S1_20261018.md).

### Evidencias actuales

- Imagen `.gaia/reports/20261018T182432Z-f0a96e77/disk.raw`,
  SHA-256 `216be2f81c1ec29a726859085d6f89d9caadf911489c1090b829a93a05275c6f`.
- Diez escenarios, todos 3/3 sobre ese mismo SHA: 63 arranques, 45 evaluaciones
  correctas y 18 fallos inyectados esperados. Informes
  `.gaia/reports/20261018T183217Z-bc850b8c/REPORT.md` y
  `.gaia/reports/20261018T185126Z-be8e6d63/REPORT.md`.
- DATA lógico/ledger corruptos y restaurados desde disco independiente RO;
  rechazo de backup alterado antes de escribir; roles/permisos restaurados y
  continuidad del prefijo confirmado. Publicador real interrumpido con SIGKILL,
  reboot seguro; candidato saludable bendecido y candidato rechazado agotado.
- USB emulado arranca y verifica la firma pública del propietario con el sqv
  nativo de Debian; compatibilidad previa real en
  `.gaia/reports/20261018T180815Z-34059811/REPORT.md`.
- Negativa del instalador **3/3**, firma de otro mensaje rechazada dentro del
  invitado y target completo comparado intacto:
  `.gaia/reports/20261018T192446Z-28cd9ecc/REPORT.md`.
- **213 tests OK, 29.607 s, sin skips**:
  `.gaia/reports/20261018T192446Z-0d538e07/REPORT.md`.

Implementados backup/restore acotado, gate público invitado, ensayo de publicación,
bendición por salud, recuperación/instalación solo QEMU y controlador de fixtures
con firma obligatoria antes de cualquier escritura al target. Unit tests usan
archivos simulados; la instalación positiva no se atribuye a esos tests.

Se corrigieron VirtualSize PE al ampliar cmdline y truncación ESP por count/skip
de qemu-img dd. Se repitió toda la matriz con lectura completa/hash de ESP y UKI.
Se retiraron únicamente dos imágenes fallidas desechables y overlays conocidos,
tras comprobar hashes/estado/no uso/dependencias, para reservar espacio de prueba.
Logs y manifiestos se conservan; informes de retiro
`20261018T182147Z-1407ce83` y `20261018T192115Z-2f5ce62d`.
No se formateó/escribió ningún dispositivo físico directamente ni se accedió a
la custodia privada. Último check de metadatos: ambos USB LUKS cerrados.

### Parada humana concreta

Preparada solicitud `.gaia/reports/20261018T191315Z-018272b8/install-bundle/install-manifest.json`,
SHA-256 `0d0333fc6a7035cb7367b09b1ba160daadc2d1fad99971528a6b62705e25b0a2`.
El paquete vincula la imagen actual y su manifiesto, propósito lab, target virtual
fijo. No existe todavía `.json.asc` para ese mensaje. Reutilizar la firma de
custodia sería criptográficamente incorrecto y el invitado ya lo rechaza.
El propietario debe firmar el manifiesto desde su custodia y cerrar el primario.
Comandos exactos: [APPLIANCE_FIRMA_INSTALACION_VM.md](APPLIANCE_FIRMA_INSTALACION_VM.md).
Se retomará el controlador positivo con tres instalaciones/reparaciones y boot
independiente. No se adelantan S0/S2–S4, perfil físico/NVIDIA ni F2–F8.

## Actualización 2026-10-16 — Firma real del desafío de custodia verificada

El propietario aporta `.gaia/reports/20261016T134648Z-33248432/REPORT.md`,
**SIGNED_ARTIFACTS_VERIFIED**. Se contrasta el informe con el desafío fijado:
huella `6BF5C62DC530889F3D7C644F678D00EC8B5BF748`, propósito lab, SHA-256 del
manifiesto `fadea1478c89e8d891b7f753c094b3b2f080b3ee4379a1a99a468cddd5c81552` y de
la firma `dff6a83028e116591c8c908967b2df37c13a1dd4f1db09c1d0886838b633c059`.
Los tres artefactos públicos coinciden; gpgv terminó con código 0. El verificador
no usó privada. Se verificó que los archivos actuales corresponden al informe.

Comprobación posterior solo de metadatos: los dos USB de custodia están presentes,
son crypto_LUKS y están cerrados/sin montajes ni mappers. No se abrió ni leyó su
contenido. La firma acredita posesión de la clave; el procedimiento prescrito
exigía usar el backup con primario cerrado. La independencia física y la anotación
en el registro externo requieren aún confirmación humana explícita.

Se continúa el trabajo de software S1 con esas confirmaciones registradas como
pendientes, sin declarar completa la fase ni autorizar instalación. El siguiente
escenario pendiente es corrupción DATA y restauración desde respaldo independiente
en discos virtuales, distinto de los USB de custodia de la clave.

## Actualización 2026-10-16 — Exportaciones públicas recibidas y verificadas

El propietario comunica «pública exportada». Se comprueban exclusivamente los
archivos públicos del proyecto: formato de paquetes público (sin secreto/subclaves),
ASCII y binario con bytes decodificados idénticos, primaria Ed25519 con firma y
huella `6BF5C62DC530889F3D7C644F678D00EC8B5BF748`, exactamente la fijada previamente.
GPG se ejecuta con homedir público aislado, sin abrir USB ni usar privada.

Informe `.gaia/reports/20261016T133757Z-78fc1d87/REPORT.md`,
**OWNER_PUBLIC_KEY_MATCHES_PIN**. SHA-256:

- `.pub.asc` (409 bytes): `b615950bc31e716939fb61b34abdb5bd6d4dd8d24d4105fa9e6ecff32de907fe`.
- `.pub.gpg` (242 bytes): `a358214217109bc06bd0c7d684962ca87b8555099f063175b068654f250f138f`.
- `.fingerprint.txt` (41 bytes): `70449f4493cf01c4809c32e0e729af5c3b11b99dff10e5d6e87ef33d998bb42a`.

Preparado `keys/gaia-custody-backup-check.json`, manifiesto público `purpose=lab`
que vincula esos tres archivos a un desafío de esta sesión. Pendiente de firma
humana desde el backup; no representa un release ni prueba aún posesión de privada.
Comandos exclusivamente humanos en [APPLIANCE_BACKUP_CLAVE.md](APPLIANCE_BACKUP_CLAVE.md):
copiar custodia con agente GPG detenido, cerrar primario, reabrir solo backup,
firmar el manifiesto, cerrar backup y ejecutar verificador público. Sin recrear
clave ni contenedores, sin sobrescribir un backup existente.

Comprobados los hashes de los tres artefactos del desafío y la sintaxis Bash de
los dos bloques humanos, sin ejecutarlos. SHA-256 del manifiesto pendiente de firma:
`fadea1478c89e8d891b7f753c094b3b2f080b3ee4379a1a99a468cddd5c81552`.
Evidencia: `evidencia_appliance/publica_gaia_20261016.json`.

Parada humana: realizar esa copia/prueba y confirmar el registro externo. Todavía
no hay firma GAIA/backup probado ni confirmación explícita del registro externo.
F1/S1 sigue abierta. La privada, revocación y contraseñas no se han solicitado,
abierto o leído por el agente.

## Actualización 2026-10-16 — Huella de firma recibida del propietario

El propietario comunica terminada la generación y aporta la huella:
`6BF5C62DC530889F3D7C644F678D00EC8B5BF748`.
Se registra como **identidad esperada** en
`keys/gaia-release-signing.fingerprint.txt`, sin generar/importar privada ni abrir
la custodia. No había archivos de pública en `keys/` al comprobar el proyecto.

Pendientes: exportación pública por el propietario desde su primario, contraste
de formato/algoritmo/huella, confirmación explícita del registro externo, copia
y firma real desde el backup con el primario cerrado. No se afirma todavía una
firma GAIA verificada ni se cierra S1. Se conserva intacto el informe histórico
del formateo (`private_keys_generated=false` describe aquel helper, anterior a
la generación humana posterior).

Siguiente acción exclusivamente pública del proyecto tras la exportación:
verificar los archivos recibidos contra la huella fijada. La privada/contraseñas
siguen fuera del proyecto y no son datos que el agente necesite recibir.

## Actualización 2026-10-16 — Dos USB de custodia preparados correctamente

El propietario ejecutó el helper corregido en su terminal. Resultado local
`.gaia/signing-usb-preparation.json`: **CUSTODY_USB_PREPARED**,
`prepared=["primary","backup"]`, `private_keys_generated=false`.

Su transcripción acredita, para cada USB autorizado: retirada de firma DOS,
creación LUKS2/Argon2id con contraseña introducida por él, apertura, creación ext4,
cinco pasadas e2fsck correctas, asignación de permisos y cierre del volumen.
Etiquetas ext4: GAIA-KEY-PRIMARY y GAIA-KEY-BACKUP. Las contraseñas no se recibieron
ni se registraron por el agente.

Comprobación posterior del agente **solo de metadatos**, sin abrir los LUKS:
serie/modelo/capacidad/by-id coincidentes; ambos USB de 31457280000 bytes con tipo
`crypto_LUKS`; sin montajes en sus descendientes y sin los mappers de custodia.
El filesystem interior se acredita por salida del propietario/helper, no por una
lectura descifrada del agente. Evidencia resumida:
`evidencia_appliance/custodia_usb_preparada_20261016.json`.

**Paso de preparación de contenedores completado.** No se genera ni se considera
verificada aún la clave Ed25519 o su backup. Siguiente intervención humana:
abrir el primario ya preparado, generar la clave exclusiva, exportar pública y
huella, copiar y probar la custodia del backup según el manual. No repetir
wipefs/luksFormat/mkfs. La privada y sus contraseñas siguen fuera del proyecto;
F1/S1 permanece abierta hasta cumplir el resto de sus criterios.

## Corrección 2026-10-16 — USB ocupado por partición montada omitida

El propietario ejecutó el preparador y `wipefs` terminó con código 1,
`probing initialization failed: Device or resource busy`, sobre el primario.
El programa se detuvo antes de `luksFormat`; no se declara preparado ningún USB.

Diagnóstico real solo de lectura con lsblk/findmnt: la partición del primario
seguía montada como Ventoy y la del backup como KALI LINUX. El inventario pedía
JSON con PATH pero sin NAME ni `--tree`. En util-linux esto produce una lista
plana: `descendants()` no encontraba las particiones y omitía su desmontaje.
Era un fallo del preparador, no una contraseña o identidad incorrecta del usuario.

Corregido `inventory()` con `lsblk --json --tree ...`. Una nueva prueba reprodujo
el fallo con la versión anterior (wipefs alcanzado con partición aún montada) y
pasó después de la corrección. Otra prueba exige que el fallo de umount impida
llegar a wipefs/luksFormat. **9 tests del preparador OK** y check-only real de
ambas identidades correcto. No se usa force, lazy-unmount ni cierre de procesos.

Evidencia: `.gaia/reports/20261016T132211Z-8e1293e9/REPORT.md`,
`USB_PARTITION_DETECTION_FIXED`. Solo se ejecutaron diagnósticos y tests con
comandos privilegiados simulados; ningún formateo desde el agente.

Reanudación humana en terminal, mismo comando:
`python3 gaia/appliance_key_usb.py`. Ahora detectará y desmontará las particiones
del USB verificado antes de intentar borrar sus firmas. Si umount informa ocupado,
se detiene y se revisará el proceso que lo mantiene abierto; no se fuerza.
Sigue pendiente acreditar LUKS/ext4 de ambos USB y generar/probar la clave por el
propietario. F1/S1 permanece abierta.

## Actualización 2026-10-16 — Solicitud de formateo de los USB de firma

El propietario solicita formatear los dos USB ya autorizados. Se reidentifican
en vivo: USB ProductCode de 31457280000 bytes, primario serie terminada E424 y
backup BED3, con rutas by-id distintas. La identificación completa queda solo
en `.gaia/signing-usb-targets.json`, ignorado por el repositorio. El HDD externo
de 250 GB y los SATA no son destinos del preparador.

**Bloqueo humano real:** `sudo -n true` exige autenticación interactiva y la
sesión del agente no tiene TTY. Cryptsetup ahora está disponible. No se ha
formateado, montado ni abierto ningún USB en esta actualización.

Preparado `gaia/appliance_key_usb.py`, ejecutable por el usuario normal desde
terminal: `python3 gaia/appliance_key_usb.py`. Solo herramientas acotadas reciben
sudo; sudo/cryptsetup heredan la terminal y piden contraseñas directamente. El
script verifica identidad/uso, rechaza cifrado existente, inicializa LUKS2/ext4,
comprueba el filesystem y permisos, desmonta/cierra; no genera claves GPG.
Si falla un desmontaje no borra recursivamente el contenido montado ni intenta
cerrar un mapper todavía en uso. Bloqueo de exclusión mutua entre preparaciones.

Verificación: **7 tests del helper correctos**, con comandos privilegiados
simulados, y `--check-only` real correcto para ambos USB, sin sudo ni escritura.
Evidencia `.gaia/reports/20261016T125951Z-364f6a4e/REPORT.md`,
`NEEDS_LOCAL_TERMINAL_FOR_USB_FORMAT`. No equivale a formateo completado.
El resultado real se guardará en `.gaia/signing-usb-preparation.json` cuando el
propietario ejecute el comando con terminal. No compartir contraseñas.

Procedimiento actualizado para abrir los contenedores tras el helper sin repetir
los bloques destructivos: [APPLIANCE_FIRMA_OFFLINE.md](APPLIANCE_FIRMA_OFFLINE.md).
Se mantiene pendiente la generación humana y custodia probada de la clave; F1/S1
no se cierra ni se adelantan las fases físicas.

## Actualización 2026-10-16 — Custodia confirmada y procedimiento de firma registrado

El propietario confirma clave nueva Ed25519 exclusiva de GAIA, PC personal como
entorno confiable y dos USB cifrados independientes: antiguo `Ventoy` para privada
y antiguo `KALI LINUX` para backup. Autoriza su formateo, pero pide explícitamente
**generar él mismo la privada**, sin entregarla ni sus contraseñas al agente.
El HDD de instalación/recuperación queda excluido de cualquier custodia secreta.

Decisiones incorporadas a §6.3 y estado S1 del plan. Procedimiento completo:
[APPLIANCE_FIRMA_OFFLINE.md](APPLIANCE_FIRMA_OFFLINE.md), con identificación por
by-id/serie completa local, LUKS2/Argon2id, pinentry, exportación exclusivamente
pública, parada de agentes antes de backup, reapertura y firma de comprobación
desde el backup con primario cerrado, cierre y desconexión de ambos USB.
No se conservan series completas en este registro exportable.

Implementado `gaia/appliance_verify.py`, comando `appliance-verify` antes de
cargar el runtime, y pruebas públicas en `tests/test_appliance_verify.py`.
Protocolo `gaia-signed-artifacts-v1`: manifiesto firmado que vincula propósito,
huella fijada, nombres, tamaños y SHA-256; verificación con gpgv y un homedir
aislado que solo contiene material público. No hay generación privada ni función
de firma en GAIA. Se rechazan material secreto/subclaves, identidad distinta,
firmas inválidas/múltiples/caducadas/revocadas, ambigüedad JSON, rutas inseguras y
artefactos alterados. La integración del instalador y sus puertas sigue pendiente.

Comprobación real de formato con la **pública de Debian trixie** instalada en
el host (no una identidad GAIA): algoritmo 22/Ed25519 y parsing de huella correctos.
`.gaia/reports/20261016T124001Z-7663ed50/REPORT.md`,
`KNOWN_PUBLIC_FORMAT_VALIDATED`. No se importó esa clave como confianza GAIA.
Las pruebas de estados criptográficos del módulo usan dobles de gpg/gpgv;
**no acreditan todavía una firma real del propietario**.

Comprobaciones locales: no existen archivos `keys/*` de GAIA y falta el binario
cryptsetup. Solo se han leído rutas de proyecto y disponibilidad de herramientas;
no se abrieron USB de custodia ni se creó, exportó o leyó material privado.
No se ha ejecutado formateo, montaje ni instalación de paquetes del host.

**Parada humana actual:** ejecutar el procedimiento y devolver únicamente pública,
huella confirmada, SHA-256 públicos y confirmación de LUKS/backup probado/cierre.
F1/S1 sigue abierta; S0/S2–S4 y F2–F8 no avanzan ni cambian sus criterios.
Verificación de cierre: **191 tests OK, 17.121 s, sin skips**, informe
`.gaia/reports/20261016T124320Z-b4935330/REPORT.md`. Ayuda CLI sin site-packages OK.
Además de los dobles de tests unitarios se realizó comprobación criptográfica
real pública: firma Ed25519 Debian sobre su Release aceptada y Release alterado
rechazado con BADSIG, sin generar claves ni adoptar confianza Debian para GAIA.
`.gaia/reports/20261016T124245Z-b08e3dd6/REPORT.md`,
`PUBLIC_CRYPTO_CHECKS_PASSED`. La firma del propietario sigue pendiente.
Evidencia resumida: `evidencia_appliance/firma_offline_20261016.json`.

## Sesión 2026-10-16, 10:49–12:15 UTC — UEFI y ensayos VM; punto humano de firma

El usuario pide continuar secuencialmente y parar solo por necesidad humana,
bloqueo de diseño o bucle de errores, con informe al detenerse.

**Resultado: imagen UEFI construida y validación parcial VM correcta. F1/S1
permanece abierta.** Se detiene antes de preparar la recuperación firmada para
fijar con el propietario la clave pública y la huella de release, el entorno de
firma externo y el soporte offline de la privada, conforme a §6.3. No se ha
creado una privada en el proyecto ni declarado confianza de release en imágenes
de laboratorio. No se han escrito/formateado discos físicos.

Informe completo de cambios, incidencias, comandos, pruebas y pendientes:
[VALIDACION_APPLIANCE_S1_VM.md](VALIDACION_APPLIANCE_S1_VM.md).
Evidencia resumida: `evidencia_appliance/s1_vm_20261016.json`.

- Imagen: `.gaia/reports/20261016T113055Z-a9d2a6f2/image-manifest.json`,
  hash `70e179153afb5ab30df4848547fbbce20c7dfdf6589b701b6c88048add5d0fa6`.
- Fundación 3/3: `.gaia/reports/20261016T113805Z-8b0ffd12/REPORT.md`.
- A 3/3, B 3/3, intentos agotados/fallback 3/3 y staging parcial 3/3:
  `.gaia/reports/20261016T115050Z-d3c87053/REPORT.md`.
- B con superbloque destruido: 3/3, tres fallos previstos y retorno A en cada
  repetición: `.gaia/reports/20261016T120518Z-56fab0d3/REPORT.md`.
- 36 arranques en ejecuciones finales correctas: 27 evaluaciones correctas y
  9 fallos de corrupción inyectados y esperados. No son aún todos los escenarios S1.
- 183 tests OK, 26.669 s sin skips:
  `.gaia/reports/20261016T121413Z-d376a187/REPORT.md`.
- Host preflight actualizado APPLIANCE_HOST_READY:
  `.gaia/reports/20261016T121537Z-beaec2e4/REPORT.md`.

Reanudación tras aportar la información de confianza: implementar medio de
recuperación y su instalación en VM, restauración DATA, publicación transaccional
y promoción saludable, completar CORE/política de release y la firma externa.
No se vuelve a pedir autorización general de borrado ni una nueva compilación
manual del runtime al usuario. Se mantienen los requisitos físicos posteriores.

## Actualización 2026-10-16 — Runtime construido y artefacto verificado

El usuario reanudó la construcción con el comando sin configuración manual de
temporales:

```bash
python3 gaia.py appliance-rootfs --with-runtime
```

Resultado real **DEBIAN_RUNTIME_ROOTFS_BUILT**:
`.gaia/reports/20261016T102648Z-70fc2c5a/REPORT.md`.
mmdebstrap terminó con código 0 en 413.34 s. El selector descartó `/tmp` por
capacidad (7.4 GiB) y eligió `/var/tmp` automáticamente. La pausa anterior queda
resuelta; las secciones anteriores se conservan como historial fechado.

### Comprobación posterior del artefacto

Se recalculó el SHA-256 completo y se volvió a inspeccionar el tar mediante
`gaia.appliance_rootfs.inspect_rootfs`, sin extraerlo ni ejecutar su contenido.
Se contrastaron todos los campos devueltos (inventario, kernel, initramfs, EFI y
runtime) con `rootfs-manifest.json`, y el hash también con `report.json`:

- `rootfs.tar`: **7817448960 bytes** (aproximadamente 7.28 GiB).
- SHA-256: `c9d9a64c740454fa431828ac905992e094429f926e3afdd199b6bb33b00375e1`.
- 208 paquetes Debian instalados; kernel e initramfs 6.12.107+deb13-amd64.
- Python **3.14.4**, venv propio `/opt/gaia/venv`.
- Torch **2.14.0+cu126**, runtime CUDA **12.6**, NumPy **2.3.5**.
- `pip check`: `No broken requirements found.` en el log de construcción.
- Smoke real guardado dentro del tar: **GAIA_RUNTIME_CPU_SMOKE_OK**, UID **997**,
  logits `[2, 16, 256]`, salida y pérdida finitas exigidas por el script.
- `s1_complete=false` y `bootable_media=false`, comprobados.

Evidencia resumida: `evidencia_appliance/runtime_rootfs_20261016T102648Z.json`.
La comprobación posterior valida el resultado registrado del smoke; no se ha
repetido la compilación ni ejecutado otra inferencia. CUDA en GPU sigue pendiente
de hardware físico. El tar conserva herramientas de construcción y no es todavía
la imagen de release ni una medida de capacidad mínima del USB de recuperación.

### Estado y siguiente dependencia de S1

F0 OK; F1/S1 en desarrollo, **base y runtime construidos**; F2–F8 sin iniciar.
No hay bloqueo humano de temporales ni necesidad de repetir este comando.

Los componentes actuales implementan bootstrap y rootfs; el siguiente trabajo
de software es construir las imágenes UEFI A/B y el entorno protegido
CORE/guardián con política offline, reutilizando el tar verificado como entrada.
Después se requiere automatizar los escenarios QEMU/OVMF de S1 (al menos tres
repeticiones por escenario crítico), incluyendo recuperación y restauración DATA.
La automatización debe verificar el hash de entrada y detenerse al fallar una
etapa, conservando logs; todavía no existe un comando integrado para ese tramo.
La preparación de los medios físicos continúa después de las puertas ya
acordadas. No se ha escrito ni formateado ningún disco físico en esta validación.

## Sesión 2026-10-16, 10:01–10:18 UTC — Namespace resuelto, base construida, runtime pausado

### Estado de salida

- F0 OK; F1/S1 en desarrollo, **pausa por fallos reiterados de temporales**.
- Herramientas instaladas y helper real rootless operativo, sin nuevos cambios
  de privilegios, AppArmor, sysctl o permisos del home.
- Base Debian construida con manifestación verificable.
- Runtime completo, imágenes A/B, guardián y escenarios VM todavía pendientes.
- F2–F8 sin iniciar. No se ha escrito ni formateado ningún disco físico.

### Diagnóstico y corrección del bootstrap

Revisado el informe aportado por el usuario:
`.gaia/reports/20261016T095945Z-aa703100/REPORT.md`. apt update/install terminaron
correctamente; la única barrera posterior era el probe genérico unshare.

Comprobaciones reales: `/etc/subuid` y `/etc/subgid` contienen un rango 65536
para el usuario; `apparmor_restrict_unprivileged_userns=1`; existe
`/etc/apparmor.d/mmdebstrap` con permiso userns. No se han modificado esos archivos.

`mmdebstrap --unshare-helper /usr/bin/unshare --mount /usr/bin/true` pasó, y su
`id` muestra UID0 **dentro del namespace**, no root del host. El bootstrap ahora
utiliza esta prueba del constructor real y conserva el resultado genérico como
diagnóstico. Resultado nuevo:
`.gaia/reports/20261016T100156Z-3f92e268/REPORT.md`, **APPLIANCE_HOST_READY**.
No hace falta reinstalar herramientas ni desactivar restricciones globales.

### Implementación y construcción reales

Añadidos `gaia/appliance_rootfs.py`, `gaia/appliance_runtime_build.sh` y
`tests/test_appliance_rootfs.py`; despacho CLI, ayudas y documentación actualizados.

`python3 gaia.py appliance-rootfs` terminó correctamente:

- `.gaia/reports/20261016T100352Z-e5710bf9/REPORT.md`:
  **DEBIAN_BASE_ROOTFS_BUILT**, 52.1757 s de mmdebstrap.
- Snapshot `https://snapshot.debian.org/archive/debian/20261015T000000Z/`,
  suite trixie, amd64, minbase; metadatos firmados mediante keyring Debian.
- Tar `rootfs.tar`, **382922240 bytes**, SHA-256
  `d9678d5d7ac4d2c23dd24f64510e71aa1b7699de9e70f77d800b0d15c6d7516a`.
  Hash recalculado al terminar esta sesión y coincidente.
- `rootfs-manifest.json`: versiones reales de todos los paquetes, kernel Debian
  6.12.107-1, initramfs y binarios EFI; versiones de herramientas/keyring/fuentes.
- Python de sistema Debian 3.13, no confundido con el runtime GAIA 3.14 pendiente.
- Manifiesto declara explícitamente `s1_complete=false`, `bootable_media=false`.

La opción `--with-runtime` prepara fuente Python 3.14.4 fijada por URL/hash publicado
en Python.org, compila en Debian, crea venv nuevo, instala el lock Torch/CUDA con
hashes y exige smoke CPU no root. Su implementación existe, pero **no cuenta aún
con una ejecución completa satisfactoria**. No se atribuye validación CUDA a un
chroot ni se ha modificado el benchmark activo.

### Incidencias y decisión de parada

| Informe bajo `.gaia/reports/` | Resultado real |
|---|---|
| `20261016T100718Z-c4e99f7c/` | Python se compiló e instaló; pip del runtime falló `No space left on device`. `/tmp` es tmpfs de 7.5 GiB; no era falta de espacio en el disco del proyecto |
| `20261016T101235Z-eb9dd08d/` | Mover TMPDIR al workspace privado falló por permisos de usuarios mapeados en `/home`; cleanup de mmdebstrap también informó permisos. Se conserva su temporal residual dentro de ese informe, sin presentarlo como artefacto válido |
| `20261016T101532Z-12cda2c0/` | Alternativa experimental de bind mount por descriptor falló antes de construir |
| `20261016T101557Z-25d5aadd/` | Prueba corregida de esa alternativa devolvió `Invalid argument`; alternativa retirada, sin cambios de montajes del host |

Se detuvieron las construcciones para evitar un bucle, conforme a la instrucción
del usuario. El código final **no conserva** el wrapper de bind mounts ni cambios
de API para pasar descriptores. Vuelve al mmdebstrap unshare que construyó la base.
Se añadieron comprobaciones de temporal y selección explícita/automática:

- 2 GiB para base y 16 GiB para runtime, además de presupuesto en workspace.
- Rechazo anticipado de directorios con padres privados inaccesibles a `_apt`.
- Si `/tmp` no sirve, evaluación de `/var/tmp`, sin cambiar permisos del home.
- En este host, diagnóstico final selecciona `/var/tmp` con **168387424256 bytes
  libres**, frente a presupuesto 17179869184; `/tmp` descartado con 7.4 GiB.
  Es una comprobación de espacio/permisos, no prueba de build.
- La elección de `/var/tmp` queda **pendiente de ejecución real del runtime**;
  no se ha reiniciado otra compilación tras la parada.

### Verificación final

**173 tests OK, 17.714 s, sin skips**, runtime Torch del proyecto:
`.gaia/reports/20261016T101816Z-fd57660f/REPORT.md` y logs selftest.
19 tests del bootstrap appliance y 9 del constructor (28 específicos en total).
Cobertura añadida: helper permitido/generic denegado, inventario del tar sin
extracción, paquetes/kernel/initrd/EFI ausentes, duplicados, comando firmado y
fechado, host bloqueado, hash del artefacto, tmpfs insuficiente, padres privados,
fallback a temporal de disco y respeto a selección explícita.
Persisten ResourceWarning CPU ya conocidos; sin fallos de suite.
Ayuda real sin site-packages: `python3 -S gaia.py appliance-rootfs --help`, OK.

### Reanudación

```bash
python3 gaia.py appliance-rootfs --with-runtime --tmpdir /var/tmp
```

No requiere sudo ni reinstala paquetes del host; descarga/compila/instala dentro
del rootfs temporal. El mismo comando sin `--tmpdir` ya selecciona automáticamente
un candidato válido. Antes de repetir, queda registrado el motivo de parada y el
cambio concreto que se probará: temporal público con espacio de disco. Después
se necesitará completar el resto de S1, no saltar directamente al HDD físico.

## Implementado: aprovisionamiento interactivo del host appliance — 2026-10-16

El usuario solicita automatizar la preparación para que el flujo inicial no
dependa de instalar paquetes a mano. Implementación completada y verificada;
**F1/S1 sigue pendiente de instalación real de herramientas y de construcción/VM**.

### Uso y comportamiento implementado

```bash
python3 gaia.py appliance-bootstrap
python3 gaia.py appliance-bootstrap --preflight
```

- Despacho antes de cargar NumPy/Torch o seleccionar un entorno de campaña.
- Diagnóstico de Debian/Ubuntu x86_64, versiones de paquetes, ejecutables, firmware
  OVMF, espacio, KVM, UEFI y metadatos de medios sin serial/WWN.
- Lista fija de dependencias del host, mostrando motivos y comandos antes de
  una confirmación `[s/N]`. Enter/no, EOF y Ctrl+C quedan registrados.
- Solo apt-get recibe privilegios a través de sudo. La contraseña y salida de
  apt/sudo van directamente a la terminal heredada, sin captura por GAIA.
- Verificación posterior real y probes de versiones. Reejecución sin reinstalar
  si ya está listo; fallos e instalaciones parciales no se aceptan como éxito.
- Namespace denegado sigue siendo un bloqueo explícito, aunque estén los paquetes.
- Informes JSON/Markdown y exclusión mutua compartida con el bootstrap existente.

Archivos: `gaia/appliance_bootstrap.py`, despacho en `gaia/bootstrap.py`, ayuda en
`gaia.py`, `tests/test_appliance_bootstrap.py`, README, BOOTSTRAP, este registro,
plan maestro y [manual del comando](APPLIANCE_BOOTSTRAP.md).

### Comprobaciones reales

| Comprobación | Resultado y evidencia |
|---|---|
| Suite específica inicial | 15 tests OK (antes de ampliar cobertura de fallos/locks); apt/sudo simulados |
| Suite final completa en venv Torch/CUDA | **163 tests OK, 26.769 s, sin skips**; `.gaia/reports/20261016T095742Z-a9f5e8f6/`, logs selftest |
| Cobertura nueva final | **18 tests**: CLI sin dependencias, despacho con GAIA_MANAGED, confirmación/cancelación/EOF, terminal requerida, comandos acotados, stdio heredado, fallos/interrupción, idempotencia, estado de campaña preservado, firmware incompleto, namespace denegado, consulta parcial dpkg, probes y lock |
| Ayuda real sin site-packages | `python3 -S gaia.py appliance-bootstrap --help` correcto |
| Preflight real sin site-packages | `.gaia/reports/20261016T095742Z-761d9c1b/REPORT.md`: APPLIANCE_HOST_PACKAGES_MISSING, código 10 |
| Comando real sin TTY | `.gaia/reports/20261016T095558Z-04e5497c/REPORT.md`: NEEDS_INTERACTIVE_TERMINAL, código 10, sin instalar |

La suite conserva ResourceWarning CPU preexistentes, sin fallos de tests.
El preflight nuevo confirma KVM accesible, UEFI presente y 157.2 GiB libres;
faltan siete paquetes (dosfstools ya instalado) y el probe unshare sigue denegado.
La instalación privilegiada se ha probado con dobles de proceso, **no ejecutado
con sudo real en esta sesión**, que no tiene terminal para la contraseña.

### Cómo seguimos

El siguiente paso del usuario es ejecutar **solo** `python3 gaia.py
appliance-bootstrap` en una terminal local desde el proyecto, revisar la lista,
confirmar y autenticar sudo cuando lo pida. Ya no hace falta pegar el comando
manual apt de la sección histórica siguiente. Si devuelve 10 por namespace,
se revisará el nuevo informe y se definirá el modo de construcción; no debe
desactivarse la política del host sin diagnosticarla.

Después se retomará la implementación del constructor y ensayos S1. El bootstrap
actual no promete reanudar un constructor que todavía no existe. Cero imágenes
construidas, cero escenarios VM y ningún medio formateado por este trabajo.

## Resultado de la preparación S1 — Bloqueo del entorno de construcción

Sesión iniciada 2026-10-16 a las 09:46 UTC. **Autorizaciones y secuencia ya
incorporadas al plan; F1/S1 bloqueada por herramientas/privilegios del host.**
F0 sigue OK; F2–F8 no iniciadas.

Evidencia estructurada:
`evidencia_appliance/preflight_s1_20261016T094641Z.json`.

### Diagnóstico ejecutado

- Host Ubuntu 26.04.1 LTS, x86_64, Python 3.14.4; 158 GiB libres según df.
- `/dev/kvm` existe y el usuario actual tiene lectura/escritura: la VM puede usar
  aceleración KVM cuando esté instalado QEMU. La lista de grupos por sí sola
  no determinaba este acceso; se comprobó el acceso efectivo.
- Consulta de ejecutables con `shutil.which` y paquetes con `dpkg-query`:
  faltan mmdebstrap, qemu-system-x86, qemu-utils, ovmf, uidmap y smartmontools.
  Mtools tampoco está instalado. Dosfstools sí: 4.2-1.2build1.
- `sudo -n -l`: autenticación interactiva requerida; no se puede instalar como
  administrador de forma autónoma en esta sesión.
- `unshare --user --map-root-user --mount true`: error
  `write failed /proc/self/uid_map: Operation not permitted`. La vía rootless
  probada no funciona; no se ha cambiado ninguna política del host para forzarla.
- `apt-cache policy` confirma candidatos de los paquetes en los repositorios
  configurados. Sus versiones observadas están en el JSON; no son un lock de la
  appliance Debian, cuyo snapshot/paquetes deben fijarse durante su construcción.

### Acción humana necesaria para continuar

Instalar las herramientas iniciales en una terminal local con autenticación sudo:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends mmdebstrap qemu-system-x86 qemu-utils ovmf uidmap smartmontools mtools
```

Estos paquetes son herramientas del host de desarrollo. No instalan la appliance
en Shared ni escriben una imagen al HDD externo. Los binarios de arranque y
paquetes de la futura imagen Debian se fijarán desde su snapshot propio; no se
instala un cargador en el disco de arranque del host.

Tras la instalación se debe volver a comprobar mmdebstrap, QEMU/OVMF y el modo
de creación de rootfs. Instalar uidmap no demuestra que la política de namespaces
quede resuelta: si sigue denegada, se necesitará una ejecución privilegiada
del constructor delimitada o un entorno de construcción adecuado. No se solicita
contraseña en el chat ni sudo global sin contraseña.

### Alcance y resultados de esta sesión

- Modificados `PLAN_MAESTRO_GAIA.md` y este registro para guardar los acuerdos,
  la asignación de ambos medios y la secuencia S1→preparación externa→S0→S2–S4.
- Añadido el informe JSON de requisitos y resultados reales.
- **Cero imágenes construidas, cero ensayos VM ejecutados; S1 no está OK.**
- Sin instalaciones, cambios al código activo, formateos, modificaciones de
  montajes o arranque, ni nuevas mediciones GPU/consumo del holdout.
- No se repitió la suite: los cambios son documentales y el fallo es de
  prerrequisitos, no de runtime GAIA. No hay bucle de reintentos.
- Próximo paso: instalar herramientas y reanudar construcción/verificación S1.

## Actualización 2026-10-16, 09:46 UTC — Autorizaciones confirmadas; inicio S1

El usuario confirma explícitamente los dos puntos solicitados:

1. Borrado completo del HDD externo USB identificado, ST9250315AS, 232.9 GiB,
   para instalador/recuperación y backup inicial. Su WWN se comprobó localmente en
   la conversación; no se reproduce en este registro exportable.
2. Construir y validar primero la imagen/recuperación en VM desde el sistema
   actual; preparar después el HDD externo y superar S0 físico antes de S2.

La autorización previa del SATA Shared sigue vigente. No hay que repetir ninguna
de estas autorizaciones generales. El plan maestro incorpora el acuerdo y delimita
la preparación software frente a los ensayos físicos. La identidad se revalidará
antes de las escrituras porque los nombres de dispositivo pueden cambiar.

Comprobaciones nuevas a las `2026-10-16T09:46:41Z`:

- `lsblk --nodeps --bytes --output PATH,MODEL,SIZE,TRAN /dev/sdb /dev/sdd`:
  Shared ST1000DM003-1ER162, 1000204886016 bytes SATA, y externo ST9250315AS,
  250059350016 bytes USB. Ambos coinciden con los medios identificados.
- `id`: UID 1000; pertenencia al grupo sudo, sin grupo kvm en la salida.
- `uname -m`: x86_64; `python3 --version`: Python 3.14.4.
- `df -h /home/mingororo/Projects/GAIA`: 158 GiB libres en el sistema de desarrollo.
- `sudo -n -l`: falla con `interactive authentication is required`. Pertenecer a
  sudo no permite ejecutar administración no interactiva en esta sesión.

F1/S1 iniciada. Pendiente de comprobar herramientas y vía de construcción
disponible antes de construir o declarar una imagen. No se ha formateado ningún
disco. La cifra definitiva de capacidad de recuperación se obtendrá de la imagen
real; 64/128 GB fueron recomendaciones anteriores, no una medición de mínimos.

## Actualización 2026-10-16, 09:29 UTC — Disco autorizado

El usuario indica que el disco montado como `Shared` puede dedicarse a GAIA,
incluido formateo y pruebas. Se ha resuelto la selección por intención del usuario;
no se requiere repetir esa autorización general.

Comprobaciones nuevas:

- `findmnt -n -o SOURCE,FSTYPE,TARGET --target /run/media/mingororo/Shared`:
  `/dev/sdb1 ntfs3 /run/media/mingororo/Shared`.
- `lsblk --nodeps --bytes --output PATH,MODEL,SIZE,TRAN /dev/sdb`:
  disco SATA, modelo **ST1000DM003-1ER162**, **1000204886016 bytes**.
- `findmnt -n -o SOURCE,FSTYPE,TARGET /`: `/dev/sda2 ext4 /`.
- Inventario `lsblk` repetido: el disco autorizado sigue montado; el disco de
  arranque y otro disco SATA permanecen conectados. El USB reporta 0B.

El alcance autorizado es el disco que actualmente contiene `Shared`, no el
directorio padre `/run/media/mingororo/` ni los otros discos. `/dev/sdb` no es
una identidad persistente: al arrancar otro entorno se debe volver a identificar
por modelo, serie y capacidad antes de cualquier operación destructiva.

**F1 continúa bloqueada en los restantes requisitos de S0.** La autorización de
borrado no acredita desconexión física, arranque desde USB verificado, salud SMART,
imagen/clave ni ensayos de recuperación en VM. No se han ejecutado desmontajes,
formateos ni cambios en el disco. Sigue pendiente resolver la secuencia de
preparación de la imagen: desarrollar y validar primero el software en VM desde
este host, dejando S0 físico como puerta obligatoria anterior a S2, o aportar un
medio inicial verificado para seguir S0 antes de S1. Esta modificación de secuencia
requiere un acuerdo explícito por las condiciones del plan.

Cambios de esta actualización: autorización y mapeo registrados en este informe
y estado del plan actualizado; sin cambios de código o experimentos nuevos.

## Sesión 2026-10-16 — F1/S0 bloqueada

Diagnóstico iniciado a las 09:19 UTC. Referencia:
[plan maestro](PLAN_MAESTRO_GAIA.md#13-fase-1-ejecutable-instrumento-de-host).

### Estado por fase

| Fase | Estado real |
|---|---|
| F0 | OK previamente; cierre documental revisado y hash del corpus preservado comprobado de nuevo |
| F1 | Bloqueada en S0: prerrequisitos físicos y secuencia de construcción pendientes |
| F2–F8 | Pendientes, sin iniciar |

### Trabajo realizado

1. Revisado el cierre previo en `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`,
   el manifiesto `TRANSICION_LEGACY_V0.md` y la evidencia
   `evidencia_renombrado/integridad_fase6.json`. Los 145 tests y las pruebas CUDA
   de esos documentos son resultados de la ejecución anterior; no se han repetido
   ni se presentan como pruebas nuevas del sistema arrancable.
2. Comprobado que el prototipo retirado no aparece en la raíz del proyecto.
3. Verificado de nuevo el SHA-256 de
   `archives/text_prototype/sample_corpus.txt`:
   `3d8922516deb38620bc1edd5f5bd4c3194dc42b255d80dea890a9d85a8f8b4e7`.
4. Consultados metadatos de arranque, montajes y dispositivos mediante comandos
   de diagnóstico. No se han leído contenidos de los discos ajenos.
5. Revisada disponibilidad de herramientas e imágenes dentro del proyecto.
6. Registrado el bloqueo sin dar por superada ninguna puerta de F1.

### Comandos y observaciones reales

| Comprobación | Resultado |
|---|---|
| `date -u +%Y-%m-%dT%H:%M:%SZ` | `2026-10-16T09:19:03Z` |
| `findmnt -n -o SOURCE,FSTYPE,TARGET /` | `/dev/sda2 ext4 /` |
| `findmnt -n -o SOURCE,FSTYPE,TARGET --target /home/mingororo/Projects/GAIA` | `/dev/sda2 ext4 /` |
| `id -u` | `1000`, sesión sin privilegios root |
| `command -v lsblk smartctl mmdebstrap qemu-system-x86_64 mokutil bootctl` | Localizados `/usr/bin/lsblk` y `/usr/bin/mokutil`; los otros cuatro nombres no se resolvieron en el PATH |
| Lectura de directorio `/sys/firmware` | Existe `efi/` |
| `mokutil --sb-state` | `SecureBoot disabled`; `Platform is in Setup Mode` |
| `sha256sum archives/text_prototype/sample_corpus.txt` | Hash coincidente con el manifiesto |
| Glob del proyecto `**/*.{iso,img,qcow2,raw,efi,sig,pub}` | Sin archivos coincidentes; no demuestra ausencia fuera del proyecto ni verifica medios externos |

`lsblk --json --output NAME,TYPE,TRAN,RM,SIZE,FSTYPE,MOUNTPOINTS,RO`
mostró los siguientes discos (se omiten identificadores de volúmenes y nombres
de montajes externos en este resumen exportable):

| Nombre observado | Transporte | Tamaño mostrado | Situación |
|---|---|---|---|
| `sda` | SATA | 232.9G | `sda1` vfat montada en `/boot/efi`; `sda2` ext4 montada en `/`, contiene el workspace |
| `sdb` | SATA | 931.5G | `sdb1` NTFS montada bajo `/run/media/…` |
| `sdc` | SATA | 931.5G | Cuatro particiones; `sdc3` NTFS montada bajo `/run/media/…` |
| `sdd` | USB, removible | 0B | Sin capacidad utilizable reportada; no permite acreditar un USB instalador válido |

También aparecieron dispositivos loop de aplicaciones snap, ajenos a los candidatos
de instalación. Los nombres `/dev/sdX` son observaciones de esta sesión, no
identidades persistentes ni selecciones autorizadas de disco.

### Puerta de S0: no superada

- El sistema y el workspace están en un disco SATA actualmente montado. No está
  acreditada la desconexión física del disco diario ni el arranque desde USB.
- Existen varios discos internos y todos tienen alguna partición montada. El plan
  exige detenerse ante ambigüedad: **no se selecciona ninguno como destino**.
- UEFI y Secure Boot desactivado sí se observan en esta sesión; no certifican el
  futuro arranque del instalador.
- Identidad física del HDD dedicado, salud SMART, imagen/manifiesto verificados,
  clave pública y confirmación manual de borrado siguen pendientes.
- La falta de imagen local introduce una dependencia de secuencia: S0 pide
  arrancar un USB verificado y comprobar imagen/clave, mientras S1 incluye la
  construcción de imagen/manifiesto. Antes de ejecutar el plan estrictamente en
  orden hace falta fijar cómo se prepara ese medio de arranque inicial.

### Intervención/refinamiento necesario

Se propone resolver la dependencia dentro de F1: **autorizar primero la preparación
del software de construcción y los ensayos S1 en VM desde el entorno de desarrollo**,
manteniendo S0 físico obligatorio antes de instalar sobre el HDD y sin iniciar F2.
Este cambio de secuencia no está aplicado; requiere acuerdo con el usuario.
Alternativamente, el usuario puede aportar un medio inicial y su manifiesto/clave
verificados para ejecutar S0 como está escrito.

El usuario debe identificar físicamente cuál será el HDD dedicado y su disponibilidad
para borrado, así como el USB de instalación/recuperación y los medios de firma/backup.
No se solicita una confirmación de borrado a ciegas: la confirmación definitiva de
S0 se hará con la identidad real comprobada en el entorno de instalación.

### Cambios y alcance de esta sesión

- Añadido este informe y actualizado el registro de estado del plan maestro.
- Diagnóstico no destructivo: ninguna instalación de paquetes, cambio de montaje,
  particionado, formateo, modificación de arranque o desconexión de red.
- Sin cambios al código activo, estados experimentales ni holdout consumido.
- No corresponde repetir suite o experimentos para este cambio documental.
- Sin bucles ni fallos nuevos del runtime: la parada es por prerrequisitos reales
  y decisión de secuencia pendiente. **No se declara F1 implementada ni validada.**
