# S1 — Validación actual de DATA, publicación, salud y USB virtual

Fecha: 2026-10-18. **F1/S1 EN DESARROLLO. No se declara el objetivo completo.**

**Actualización posterior:** la firma solicitada fue recibida y las instalaciones
y reparaciones positivas se completaron 3/3, informe
`20261018T203350Z-9e9b020a`. Este documento conserva el estado parcial anterior;
resultado actual en
[VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md](VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md).

## 1. Punto de salida y bloqueo humano

Se continúa el plan tras recibir la firma real del desafío de custodia del
propietario. Se implementan y ejecutan diez escenarios de la misma imagen actual,
tres repeticiones cada uno, y la negativa de instalación con firma incorrecta.

**Parada necesaria:** el siguiente paso positivo escribe el destino virtual solo
tras verificar una nueva firma sobre la imagen concreta de instalación. El agente
no tiene ni usa la privada offline y no puede sustituir esa autorización por la
firma del desafío anterior. Solicitud preparada, manifiesto y hashes revisables:
[APPLIANCE_FIRMA_INSTALACION_VM.md](APPLIANCE_FIRMA_INSTALACION_VM.md).

Esto no oculta los pendientes: instalación/reparación positiva en VM, criterios de
release y eliminación de toolchain siguen pendientes; S0 y S2–S4 físicos no se han
ejecutado, F2–F8 no han comenzado. Las confirmaciones humanas del registro externo
y de la independencia física de la custodia también están pendientes.

## 2. Identidad única de las pruebas actuales

- Imagen `.gaia/reports/20261018T182432Z-f0a96e77/disk.raw`.
- 22577938432 bytes, SHA-256
  `216be2f81c1ec29a726859085d6f89d9caadf911489c1090b829a93a05275c6f`.
- CORE manifiesto SHA-256
  `88a784fc927a5ddcda6166bc83c10482b68f968df4ca89e7fc86c820b2362dd3`.
- Perfil **vm-cpu-l0**, kernel/initrd/runtime de las entradas fijadas anteriores.
- Root A/B y DATA de base conservados byte a byte al revisar CORE. Fuentes y
  payload públicos capturados en el directorio del build; ningún secreto de firma.
- `release_image=false`, `signed=false`: el artefacto no es todavía una release
  de producción. La firma solicitada es externa al binario y de propósito lab.

No se mezclan los resultados de distintos CORE para declarar el cierre de la
imagen actual. Los informes anteriores siguen siendo evidencia histórica.

## 3. Firma y raíz pública

Firma del propietario realmente verificada:
`.gaia/reports/20261016T134648Z-33248432/REPORT.md`,
`SIGNED_ARTIFACTS_VERIFIED`, huella
`6BF5C62DC530889F3D7C644F678D00EC8B5BF748`, desafío exacto y tres hashes públicos.
La firma acredita posesión de clave; la ubicación física del backup requiere la
confirmación humana del procedimiento, no se infiere solo de la criptografía.

Se ha incorporado al CORE **solo pública, huella/configuración y prueba firmada**.
El host usa gpg/gpgv y verifica identidad/algoritmo antes de incorporar esas
entradas. Debian mínimo ya incluye `sqv` para APT: se utiliza ese verificador
público nativo en el invitado, sin añadir runtime privado de firma. Compatibilidad
real con la firma del propietario probada en Debian firmado del mismo snapshot:
`.gaia/reports/20261018T180815Z-34059811/REPORT.md`.
Cada arranque normal exige de nuevo esa firma pública antes de sus comprobaciones.
No hay keyservers, ni lectura de GNUPGHOME privado, ni privada copiada a la imagen.

## 4. Matriz ejecutada con la imagen actual

Informes:

- `.gaia/reports/20261018T183217Z-bc850b8c/REPORT.md`.
- `.gaia/reports/20261018T185126Z-be8e6d63/REPORT.md`.

Ambos **VM_BOOT_SELECTION_VALIDATED**, mismo SHA-256 de imagen, tres repeticiones
por cada ámbito siguiente:

| Escenario | Repeticiones OK | Arranques | Evidencia exigida |
|---|---:|---:|---|
| normal-A | 3 | 3 | A, integridad, offline, catálogo y worker no root |
| normal-B | 3 | 3 | B y las mismas puertas |
| attempt-exhaustion | 3 | 12 | B→B→B→A, contador persistente |
| interrupted-publication | 3 | 3 | Staging `.tmp` no seleccionable; A intacta |
| corrupted-B | 3 | 12 | Superb. B destruido; tres fallos previstos y vuelta A |
| data-recovery | 3 | 3 | Contenido/ledger restaurados desde disco independiente |
| publication-interrupted | 3 | 6 | SIGKILL real del escritor; reboot A sin seleccionar parcial |
| health-bless | 3 | 6 | B se bendice tras salud, permanece B en reboot |
| health-reject | 3 | 12 | Fallo inyectado de salud impide bendecir; agota y vuelve A |
| usb-smoke | 3 | 3 | Root montado desde USB emulado, firma pública válida |

Total **63 arranques** de esta matriz: 45 evaluaciones correctas y 18 fallos
inyectados/esperados. Hay además un smoke USB preliminar de desarrollo que no
se suma a estas repeticiones. No se atribuye GPU/watchdog físico a estas pruebas.

### DATA

`data_backup.py` implementa snapshot/restore v1 acotado: árboles agent/evidence,
archivos y directorios regulares, dueños/grupos por rol, permisos, contenido y
timestamps; sin symlinks/hardlinks/dispositivos ni escapes de ruta. Comprueba todo
el tar/manifiesto antes de modificar el destino. El hash esperado del manifiesto
proviene del evaluador confiable, separado del contenido recibido, no se confía
en un hash autoafirmado por el backup. Es un contrato de laboratorio (32 MiB y
1024 entradas), no el dimensionamiento universal de futuros modelos.

En VM se añade un disco virtual independiente de 512 MiB, se pausa el único
escritor guardián tras completar el worker, se crea snapshot y se rechaza un backup
alterado antes de tocar DATA. Después el respaldo se monta RO, se corrompen un
archivo binario y el ledger, se detectan ambas corrupciones y se restauran.
Se preservan los inodes raíz de los roles y sus permisos; el guardián reanudado
extiende el prefijo confirmado de secuencia 1 a 2. No se confunde rollback A/B con
restauración de datos. Es corrupción **lógica**, no recuperación de un ext4 entero
destruido ni prueba de pérdida brusca de alimentación (S4).

### Publicación y salud

`boot_transaction.py` es un componente privilegiado de prueba, inaccesible por
el catálogo del agente. Un proceso hijo real copia 256 KiB de la UKI candidata a
un `.tmp`, hace fsync y anuncia un checkpoint; el padre lo mata con SIGKILL y
comprueba las UKI activas. El siguiente arranque confirma A y el parcial no
seleccionable. No es un apagón físico ni se certifica durabilidad del HDD real.

La bendición de B se solicita después de integridad CORE/root, offline, catálogo,
DATA/evidencia y smoke causal no root. Retira el contador del candidato y sincroniza
FAT; el siguiente boot mantiene B. La inyección de un fallo de salud antes de la
bendición deja el contador activo y demuestra fallback. Son precondiciones del
perfil CPU VM; el perfil CUDA deberá añadir sus requisitos reales antes de bendecir.

## 5. Recuperación firmada: implementada, positiva aún pendiente

- `recovery_install.py`: consumidor de imagen firmada **solo QEMU**, identidad
  de target fija de laboratorio, firma/contexto/hashes antes de escritura,
  rechazo de target montado/ambiguo, readback de instalación y reparación del
  sistema preservando DATA cuando GPT coincide con la geometría firmada.
- `appliance-recovery`: solicitud de firma, fixtures separados de medio USB,
  bundle RO y destino virtual, reinstalación de sistema y boot posterior sin USB.
  El controlador conserva logs/hashes y descarta solo targets temporales exitosos
  entre repeticiones para limitar el consumo de disco.
- Unit tests simulan dispositivos con archivos temporales, no discos reales.
  La prueba positiva integrada **no se ha ejecutado**, falta la firma del paquete.

Negativa integrada **3/3**, informe
`.gaia/reports/20261018T192446Z-28cd9ecc/REPORT.md`,
`VM_INVALID_INSTALL_SIGNATURE_REJECTED`:
arranque del recuperador desde USB virtual, contexto QEMU/CORE comprobado,
firma de otro mensaje rechazada por sqv y comparación de todo el target contra
su estado cero inicial. No basta exit 0: se exige el rechazo explícito y que el
destino no cambie. Tres arranques adicionales; **66 arranques en las ejecuciones
finales aceptadas**, incluyendo esta negativa, sin sumar intentos de desarrollo.

Solicitud actual `.gaia/reports/20261018T191315Z-018272b8/REPORT.md`:
**AWAITING_OWNER_VM_INSTALL_SIGNATURE**. SHA-256 del manifiesto:
`0d0333fc6a7035cb7367b09b1ba160daadc2d1fad99971528a6b62705e25b0a2`.
No se reutiliza la firma de custodia para autorizar una imagen diferente.

## 6. Incidencias encontradas y resueltas

1. Primer escenario DATA no se activó: `objcopy --update-section` retuvo el
   VirtualSize PE viejo al ampliar cmdline. Se elimina/reinserta la sección a su
   VMA segura y se comprueba el contenido visible desde la cabecera antes de boot.
   Evidencia de fallo `.gaia/reports/20261016T140112Z-44b6c062/REPORT.md`.
2. Revalidación B detectó initramfs incompleto: extracción ESP mediante qemu-img
   dd produjo 1 MiB menos por semántica de count/skip. La fuente estaba íntegra;
   lectura estática reprodujo la truncación. Se cubre el final absoluto, se acota
   el tamaño y se compara la ESP inicial con el hash de partición. Se verifica
   también cada UKI después del staging. Regresión cubre ambas semánticas de dd.
   Evidencia `.gaia/reports/20261016T141941Z-c69a7086/REPORT.md` y diagnósticos
   `20261016T142548Z-18cd187e`, `20261016T142702Z-2dd67e57`.
3. Primer diagnóstico sqv leyó el canal de mmdebstrap, que redirige stdout del
   hook a stderr. Verificador devolvía éxito; se separaron canales dentro del
   chroot y se confirmó salida exacta de la huella. Informe definitivo
   `20261018T180815Z-34059811`.

No queda un bucle de esos errores: la matriz actual y la negativa firmada se
ejecutaron después de las correcciones. Se conservan fallos como historial.

## 7. Código, almacenamiento y límites de cierre

- **213 tests OK, 29.607 s, sin skips** con el runtime Torch del proyecto:
  `.gaia/reports/20261018T192446Z-0d538e07/REPORT.md`.
- Seis tests nuevos DATA, seis de recuperación y regresión dd; los casos positivos
  de bajo nivel de instalación/repair usan archivos temporales. No se presentan
  como la instalación VM positiva pendiente de firma.
- No se abrieron ni leyeron USB privados desde el agente ni se escribieron discos
  físicos directamente. Al comprobar su estado, primario y backup figuraban LUKS
  cerrados; la firma privada siempre queda como acción humana externa.
- Para reservar espacio se retiraron **solo** los discos virtuales y sus overlays
  de dos intentos fallidos conocidos, tras comprobar hashes, antigüedad sin
  modificaciones, ausencia de procesos y dependencias de backing. Logs/manifiestos
  y material público permanecen como evidencia. Informes:
  `20261018T182147Z-1407ce83` y `20261018T192115Z-2f5ce62d`.
- Quedan >56 GB libres al cerrar esta comprobación; presupuesto lógico de la
  prueba positiva aproximadamente 53.7 GB, incluido margen. No es capacidad mínima
  del HDD/USB físico ni una reserva garantizada si se añaden archivos entretanto.

**No se cierra S1:** falta instalar y reparar usando la nueva firma real, completar
el perfil/paquete de release, retirar build-only toolchain y comprobar los demás
criterios de aceptación final. No se cierra F1 sin S0/S2–S4, baseline, GPU real,
arranques y recuperación física con el manifiesto final archivado fuera del HDD.
