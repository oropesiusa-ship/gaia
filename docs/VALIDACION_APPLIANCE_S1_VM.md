# Appliance — Construcción UEFI y validación parcial S1

Fecha: 2026-10-16. **F1/S1 sigue EN DESARROLLO.** Este informe registra resultados
reales; no certifica el instalador, la recuperación completa ni el cierre de F1.

## 1. Resultado y motivo de parada

Se continuó desde el rootfs con runtime verificado, se construyó una imagen GPT
UEFI y se ejecutaron los escenarios descritos abajo. La última ejecución de cada
escenario terminó correctamente. No hay un bucle de errores activo.

**Intervención humana necesaria antes de la recuperación firmada:** establecer
la raíz externa de firma de §6.3 del plan maestro. El constructor no tiene una
clave pública de release configurada ni una huella confirmada por el propietario;
las imágenes de laboratorio declaran `signed=false`, `release_image=false`.
Se necesita la clave pública y su huella, además de confirmar el entorno confiable
de firma y el soporte offline de la privada, distinto del medio de recuperación.
La privada y su contraseña no se entregan al agente ni se guardan en el proyecto.
Si ya existe una identidad de firma, primero se comunica su formato y clave
pública; no se sustituye silenciosamente por una nueva.

Esto no convierte las pruebas restantes en superadas: instalación desde USB,
restauración de DATA, promoción saludable y política CORE de release siguen
pendientes de implementación/validación. Tras fijar la confianza se retomará ese
trabajo dentro de S1. **S0/S2–S4 y F2–F8 no se han ejecutado.**

## 2. Entradas y artefactos

### Rootfs reutilizado

- Informe: `.gaia/reports/20261016T102648Z-70fc2c5a/REPORT.md`.
- SHA-256 tar: `c9d9a64c740454fa431828ac905992e094429f926e3afdd199b6bb33b00375e1`.
- Debian trixie/amd64, snapshot `20261015T000000Z` firmado por Debian.
- Python 3.14.4, NumPy 2.3.5, Torch 2.14.0+cu126, CUDA runtime 12.6.
- No se recompiló Python ni se reinstaló Torch para cada prueba.

### Imagen de laboratorio validada

- Directorio: `.gaia/reports/20261016T113055Z-a9d2a6f2/`.
- `disk.raw`, **22577938432 bytes** lógicos, aproximadamente 21.03 GiB.
- SHA-256: `70e179153afb5ab30df4848547fbbce20c7dfdf6589b701b6c88048add5d0fa6`.
- `image-manifest.json`: GPT, PARTUUID, hash de cada partición, CORE y UKI.
- ESP 250 MiB; CORE 32 MiB; A y B 10 GiB cada uno; DATA 512 MiB y reserva.
  Estos son tamaños de la VM de laboratorio, **no dimensionamiento físico final**.
- CORE SHA-256 de su lista de ficheros:
  `02a456b834078a865924f16516c0ee53ad2335200591b32154401ef63cfea1ee`.
- Origen de la revisión:
  `.gaia/reports/20261016T111311Z-4751285f/image-manifest.json`.
  La revisión preservó byte a byte ambas particiones de sistema y DATA, y modificó
  CORE y sus referencias UKI en una copia nueva. La imagen anterior se conserva.
- Imagen de laboratorio sin firma de release; no se ha escrito en medios físicos.

## 3. Componentes implementados

- `gaia/appliance_image.py`: CLI `appliance-image`, entrada rootfs verificada,
  presupuesto de espacio, revisión incremental CORE, overlays, timeout y reportes.
- `gaia/appliance_image_build.py`: ensamblador interno en namespace de usuario;
  crea archivos regulares ext4/FAT y GPT sin loop devices ni montajes del host.
  Comprueba ext4, GPT y la identidad de cada partición tras copiarla al disco.
- UKI con kernel, initramfs y cmdline del mismo build; PARTUUID vincula el slot y
  la cmdline contiene la identidad CORE. systemd-boot con entradas A/B.
- `gaia/appliance_vm_payload/`: servicios systemd, guardián **L0 de laboratorio**,
  política nftables y evaluador/worker protegidos.
- Guardián sin root, socket Unix con comprobación de UID del cliente; única acción
  `inventory` sin parámetros arbitrarios; rechazo de shell y campos adicionales.
  Evidencia append-only para el agente, con secuencia, hashes encadenados, `fsync`
  y presupuestos de laboratorio. No es aún el catálogo de autorizaciones L2.
- Worker como `gaia` mediante bubblewrap: árbol visible por lista explícita,
  sin dispositivos de bloque, sin privilegios efectivos ni red, CORE/runtime RO,
  escritura limitada al área propia de DATA.
- `gaia/appliance_vm_scenarios.py`: escenarios acotados, cada repetición con
  overlay/firmware independientes, contador persistente entre los arranques de
  una misma repetición y comprobación final del hash de la imagen base.
- Bootstrap del host ampliado a binutils, e2fsprogs y fdisk, además de comprobar
  las herramientas mtools/qemu-utils utilizadas. Preflight real final:
  `.gaia/reports/20261016T121537Z-beaec2e4/REPORT.md`, **APPLIANCE_HOST_READY**.
  No se instalaron nuevos paquetes del host durante esta sesión.

## 4. Resultados ejecutados

### Fundación VM: 3/3

`.gaia/reports/20261016T113805Z-8b0ffd12/REPORT.md`:
**VM_FOUNDATION_VALIDATED**, tres arranques independientes del slot A, QEMU/KVM
q35, 2 vCPU y 3072 MiB, firmware OVMF con Secure Boot desactivado.
Duraciones de QEMU: 18.01, 18.35 y 18.10 segundos.

Cada arranque exigió:

- Rootfs/CORE RO y DATA RW, hashes de CORE correctos y vínculo con cmdline.
- NIC virtual presente pero desactivada; cadenas input/forward/output DROP.
- Catálogo L0 permitido; shell y solicitud de ruta arbitraria denegadas.
- Agente incapaz de abrir el ledger del guardián para escritura.
- Worker UID 997, capacidades efectivas cero y `NoNewPrivs=1`, namespace de red
  separado, sin `/dev/vda`, sin acceso de escritura a CORE/runtime/evidencia.
- Inferencia GaiaTransformer en CPU, logits `[2,16,256]` y pérdida finitos.
- Evidencia con secuencia/hash verificados y apagado ordenado.

### Selección y agotamiento de intentos: 3 repeticiones por escenario

Informe `.gaia/reports/20261016T115050Z-d3c87053/REPORT.md`:
**VM_BOOT_SELECTION_VALIDATED**.

| Escenario | Repeticiones OK | Arranques incluidos | Resultado |
|---|---:|---:|---|
| Normal A | 3 | 3 | Evaluación correcta en A |
| Normal B | 3 | 3 | Evaluación correcta en B |
| Candidato no bendecido, agota intentos | 3 | 12 | B → B → B → A; nombres de contador 2-1, 1-2, 0-3 comprobados |
| Publicación parcial en staging | 3 | 3 | Ficheros `.tmp` no seleccionados; UKI A intacta y arranque A correcto |

El escenario de publicación parcial **no sustituye** la futura prueba de matar
un publicador real durante una transacción/`fsync`. La bendición automática está
enmascarada en esta imagen de pruebas; aún no se valida promoción saludable.
Las UKI se sitúan en `EFI/GAIA` en los escenarios para evitar entradas Type-2
sin contador duplicadas; las nuevas construcciones adoptan esa ubicación.

### Corrupción real de B: 3/3

`.gaia/reports/20261016T120518Z-56fab0d3/REPORT.md`:
**VM_BOOT_SELECTION_VALIDATED**, ámbito `corrupted-B`.

En cada overlay se sobrescribió el superbloque primario ext4 de B. Se ejecutaron
tres arranques fallidos previstos, comprobando cmdline de B, error de montaje,
ausencia de éxito del evaluador y decrementos persistentes del contador. El cuarto
arranque seleccionó A y pasó todas las comprobaciones del evaluador.

12 arranques en total: 9 fallos inyectados esperados y 3 recuperaciones automáticas
a A. A/B **no se ha presentado como restauración de DATA**. La imagen fuente
permaneció intacta, hash comprobado al terminar cada suite.

Total de ejecuciones satisfactorias documentadas: **36 arranques**, de los cuales
27 terminaron con evaluación correcta y 9 son fallos de B inyectados y esperados.
No se mezclan con los intentos de desarrollo fallidos siguientes.

## 5. Incidencias encontradas y corregidas

| Evidencia bajo `.gaia/reports/` | Causa y tratamiento |
|---|---|
| `20261016T105001Z-1edea38e` | Helper mapea UID0 a subuid 100000 y no puede atravesar el home privado. Se sustituyó acceso directo por copy-in/copy-out de mmdebstrap, sin cambiar permisos del home |
| `20261016T105258Z-4eba07a3` | Primer boot UEFI y rootfs correctos; CORE tenía checksums inválidos y la VM quedó en emergencia, detenida por timeout de 240 s. Prueba de regresión reprodujo corrupción por mezclar buffered reads y lseek en copia dispersa. Se corrigió usando I/O sin búfer y hash de cada partición después de copiar |
| `20261016T111311Z-4751285f` | CORE ya montó; bind recursivo de `/` en bwrap falló sobre automount EFI. Sustituido por lista explícita de rutas; se evita dar toda la vista administrativa al worker |
| `20261016T113055Z-a9d2a6f2` | Invitado emitió éxito y se apagó, pero consola serie intercaló bytes UTF-8 inválidos. Decodificación tolerante solo para serial VM; se conservan logs binarios y el resto de comandos mantiene decodificación estricta |
| `20261016T114353Z-09fed40c` | El glob de default limitado a B seleccionaba B incluso agotado. Configuración corregida a selección de ambos slots y versión superior para el candidato; posterior suite verificó fallback 3/3 |

Los logs seriales locales de la imagen histórica pueden contener hostname
heredado del rootfs de construcción. Las nuevas construcciones normalizan
hostname/hosts a `gaia-vm`. No se exportan aquí los logs crudos: la evidencia
resumida omite hostname, MAC y serial. Los originales se conservan localmente.

## 6. Verificación de código

- **183 tests OK, 26.669 s, sin skips** en el runtime Torch del proyecto.
- Informe `.gaia/reports/20261016T121413Z-d376a187/REPORT.md`.
- 19 tests bootstrap, 9 rootfs y 10 nuevos tests de imágenes (38 específicos).
- Nuevas pruebas: CRC/primario/respaldo GPT y límites, PE con ImageBase no cero,
  extents fragmentados, rechazo de rootfs alterado antes de extraer, éxito VM no
  inferido por exit 0, rechazo de ejecución del ensamblador fuera del namespace,
  alteración de ledger y preservación de bytes de serial con fallo estricto por
  defecto. Persisten ResourceWarning ya existentes; no fallos de suite.
- `python3 -S gaia.py appliance-image --help`, correcto sin NumPy/Torch.

## 7. Uso implementado y reanudación

Construir desde el tar validado y ejecutar los tres smoke de fundación:

```bash
python3 gaia.py appliance-image --rootfs-manifest .gaia/reports/20261016T102648Z-70fc2c5a/rootfs-manifest.json
```

Reutilizar la imagen existente sin reconstruir Python/Torch ni los slots:

```bash
python3 gaia.py appliance-image --image-dir .gaia/reports/20261016T113055Z-a9d2a6f2
python3 gaia.py appliance-image --image-dir .gaia/reports/20261016T113055Z-a9d2a6f2 --boot-scenarios
```

También existen `--scenario <nombre>` (repetible), `--repeats 1..3` (por defecto 3)
y `--refresh-core` para crear una revisión nueva sin alterar ambos root slots.
El número de repeticiones reducido sirve para desarrollo; no cumple por sí solo
la puerta de tres repeticiones del plan. Cada fallo detiene la ejecución y guarda
el informe; no se reintenta automáticamente una ejecución fallida.

**No hace falta que el usuario vuelva a ejecutar estos comandos ahora.** La
acción pendiente es humana y de confianza: clave pública/huella y custodia offline.
Después: recuperación/instalación VM, backup y corrupción/restauración DATA,
publicación transaccional y promoción saludable, política CORE de release y firma.
Mantener F1/S1 abierta hasta verificar todos los criterios de §13.
