# Cierre del tramo CPU/VM y transición física — 2026-10-19

## Resultado ejecutivo

**Actualización posterior:** SMART humano recibido; bloqueo de permisos resuelto.
El propietario decide continuar usando el HDD pese al historial UNC/reasignaciones;
la sustitución ya no es un bloqueo y no se repite la consulta anterior. Informe del medio:
[DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md](DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md).
El resto de este documento conserva el cierre CPU/VM y su primera parada histórica.
Estado siguiente: [PERFIL_FISICO_NVIDIA_20261019.md](PERFIL_FISICO_NVIDIA_20261019.md),
driver550 del snapshot/backports inferior al mínimo560.28.03 vigente.

**S1 CPU/VM aceptado; F1 y entrega física abiertas.** Se completaron sin errores
las tres instalaciones y tres reparaciones firmadas del candidato congelado.
La auditoría de requisitos VM finalizó con `S1_CPU_VM_ACCEPTED`.
No se reconstruyó el candidato ni se modificaron sus manifiestos firmados.

La parada actual es una necesidad humana del siguiente paso: lectura SMART del
HDD externo denegada por permisos. La preparación física no se ha ejecutado.
Además, la entrega requiere desarrollar un perfil físico y un instalador físico:
el consumidor firmado actual está restringido intencionalmente a QEMU/lab.

## Identidad y evidencias

- Imagen: `.gaia/reports/20261019T075104Z-0bda6b85/disk.raw`.
- SHA-256: `195cd3661217bd6cc4de8af38e314786a097994940cd61288ed4d1de2a9ed4de`.
- Manifiesto firmado: `7ccd1891e65f62160f083488438202f9707f033cefe4eadf4d412cfcc5a7ad26`.
- Firma recibida: `.gaia/reports/20261019T091206Z-a19b9124/REPORT.md`.
- Nuevos ensayos: `.gaia/reports/20261019T091600Z-78c27069/REPORT.md`.
- Auditoría: `.gaia/reports/20261019T100144Z-91a97bb3/REPORT.md`.
- Auditor reproducible: `python3 docs/audit_s1_cpu_20261019.py`.

## Trabajo de esta reanudación

1. Actualizados plan maestro, registro, procedimiento de firma y secuencia de cierre
   con firma recibida, candidato congelado y criterio explícito de finalización.
2. Ejecutado una sola vez el controlador documentado:

   ```bash
   python3 gaia.py appliance-recovery \
     --image-dir .gaia/reports/20261019T075104Z-0bda6b85 \
     --bundle-dir .gaia/reports/20261019T085624Z-4770def7/install-bundle --repeats 3
   ```

3. Resultado `VM_SIGNED_RECOVERY_VALIDATED`: tres instalaciones completas con
   verificación de firma/hash y readback; tres reparaciones después de dañar B,
   verificando las particiones reparadas y DATA intacta antes/después.
4. Seis arranques independientes sin USB de recuperación, todos
   `GAIA_RUNTIME_READY`, slot A, autoridad L0, UID 997, firma pública válida,
   runtime CPU correcto, pip check correcto y persistencia tras readiness.
   Ledger 1 tras cada instalación y 2 tras cada reparación.
5. Auditoría automática de los informes existentes: identidad común, diez
   escenarios exactamente 3/3, aislamiento/offline/catálogo, tres negativas de
   firma con destino intacto, tres arranques persistentes previos y seis nuevos,
   inventario de 34 paquetes retirados y 174 retenidos. No se repitió la matriz.
6. Inicio de transición física mediante inventario de solo lectura y tentativa
   de diagnóstico SMART, que devolvió `Permission denied`, código 2.

Duración del controlador: aproximadamente 44 min 9 s. No hubo errores de pruebas,
reintentos, reanudaciones ni cambios de código de ejecución. La denegación SMART
es del paso físico posterior y no invalida la aceptación CPU/VM.

## Auditoría S1 (§13 del plan)

| Requisito | Evidencia | Conclusión CPU/VM |
|---|---|---|
| Imagen/manifiesto desde entradas fijadas | Manifiesto de imagen, procedencia rootfs, inventarios y firma del paquete exacto | Cumplido; trazabilidad, sin afirmar reproducibilidad bit a bit |
| QEMU/KVM/OVMF y destinos desechables | Comandos y firmware registrados en ambos informes de matriz y recuperación | Cumplido |
| Instalación y recuperación desde USB | Informe `091600Z-78c27069`, 3 instalaciones y 3 reparaciones; USB independiente del target/bundle | Cumplido |
| A/B, B corrupto, agotamiento y fallback | Matriz `081025Z-4e6e623f`, 3/3 por escenario | Cumplido |
| Staging parcial e interrupción de publicación | `interrupted-publication` y `publication-interrupted`, 3/3 | Cumplido; SIGKILL de publicador real, no apagón físico |
| Corrupción DATA y restauración independiente | `data-recovery`, 3/3, backup alterado rechazado, prefijo/roles restaurados | Cumplido para corrupción lógica ensayada |
| Aislamiento y CORE inaccesible al agente | Probe + worker_smoke, `SANDBOX_CPU_OK`; intentos de escritura CORE/app denegados, sin dispositivo bruto | Cumplido para el sandbox ensayado |
| Política offline y catálogo limitado | nft drop, NIC desactivada, namespace de red, catálogo inventory y denegaciones | Cumplido |
| Tres repeticiones por escenario crítico | Auditoría de diez escenarios, negativa 3/3 e instalación/reparación 3/3 | Cumplido |
| Candidato depurado y arranque operativo | 34 paquetes retirados/174 conservados, tres boots previos más seis posteriores | Cumplido |

Las ejecuciones finales del candidato acumulan **81 arranques**: 63 de la matriz,
3 negativos, 3 operativos iniciales y 12 de instalación/reparación y arranque
posterior. Los fallos inyectados esperados no son fallos nuevos del controlador.
Los 224 tests previos siguen siendo la referencia; no se ha vuelto a ejecutar esa
suite ni se le atribuyen tests nuevos. El auditor sí se ejecutó y pasó.

## Alcance cerrado y metadatos históricos

El tramo CPU/VM ya no tiene pendiente genérico de «auditoría» ni de «firma».
`release_image=false`, `signed=false` y pendientes dentro del manifiesto original
son metadatos del instante de construcción. La firma detached y esta aceptación
se registran externamente para no alterar el mensaje firmado. No se interpreta
que esta firma lab autorice una instalación física.

No se cierra la puerta de entrega de S1 ni F1: el perfil objetivo incluye NVIDIA,
instalación/recuperación físicas y S0/S2–S4. El cierre CPU/VM conserva su evidencia
como referencia; un futuro perfil físico tendrá identidad propia y solo las
validaciones pertinentes a sus cambios.

## Siguiente paso y bloqueo humano comprobado

Inventario actual `lsblk --json --tree --bytes ...`:

- HDD externo previsto: **ST9250315AS, 250059350016 bytes, USB**, ahora `/dev/sda`;
  una partición montada en la sesión del propietario.
- HDD experimental previsto: **ST1000DM003-1ER162, 1000204886016 bytes, SATA**,
  ahora `/dev/sdc`, Shared montado.
- Disco diario: ahora `/dev/sdb`, `/` y `/boot/efi`; otro SSD ajeno conectado.
- Los USB de custodia figuran sin montajes en el inventario.

Las letras anteriores del plan son históricas y no pueden reutilizarse. El
inventario completo con series se comprobó localmente. No se desmontó ni escribió
ningún medio. La lectura `smartctl -x --json /dev/sda` falló al abrir el dispositivo
por permisos, sin llegar a producir diagnóstico de salud. Un usuario con sudo
debe obtenerlo usando el by-id del ST9250315AS comprobado localmente y devolver la
salida. No requiere abrir los USB de claves ni firmar de nuevo.

Se intentó también la misma lectura por by-id con `sudo -n`: devuelve
`sudo: interactive authentication is required`. No hay credencial sudo reutilizable
por el agente; el bloqueo requiere realmente el terminal del propietario.
Desde ese terminal, obtener `sudo smartctl -x --json` sobre el by-id ATA del
ST9250315AS mostrado localmente y aportar su salida. Este comando solo consulta;
no inicia autotests, no cambia configuración SMART y no escribe particiones.

## Trabajo software de transición, identificado de forma concreta

La revisión de código demuestra dos carencias previas a preparar un instalador
de entrega funcional:

1. `gaia/appliance_vm_payload/recovery_install.py:47–70` exige proveedor QEMU,
   `gaia.lab=1`, tipo `gaia-vm-install-bundle-v1`, propósito lab y serie virtual.
   `main` exige además medios virtuales separados. Copiarlo a un USB no crea un
   instalador físico; hay que implementar el perfil físico con identificación,
   salud, exclusión de montajes/discos ajenos y confirmación humana según S0.
2. `gaia/appliance_rootfs.py` construye solo componentes main; el candidato no
   incluye el perfil propietario NVIDIA/kernel/módulos. El servicio CPU usa
   PrivateDevices y no expone GPU. Hay que preparar el perfil NVIDIA explícito,
   con entradas fijadas y prueba real en la imagen; el driver del Ubuntu anfitrión
   no lo valida.

Secuencia de transición: obtener diagnóstico del medio; definir/construir el
perfil físico NVIDIA y el instalador real conservando esta referencia CPU cerrada;
validar sus cambios en VM; solicitar firma del paquete físico cuando esté listo;
preparar medio identificado/saludable; intervención humana S0; S2, S3 y S4.
No se prepara un supuesto instalador final copiando el bundle QEMU ni se abre
otra revisión CPU cosmética. El SMART es requisito del medio, no solución de las
carencias de software enumeradas.

## Estado de parada

**Necesidad humana: acceso de lectura SMART al HDD externo.** No hay bucle de
errores. Aceptación CPU/VM terminada sin dudas en su alcance; entrega física y F1
pendientes expresamente. No se ha usado clave privada, formateado, instalado en
disco físico ni habilitado autoridad superior a L0.
