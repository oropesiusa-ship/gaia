# Transición al perfil físico NVIDIA — 2026-10-19

## Estado

**Actualización:** ampliación de fuente aprobada y ejecutada. Driver580.178.04-1
oficial autenticado, módulos compilados y rootfs integrado/readback correcto.
El bloqueo de driver550 queda resuelto. Estado vigente: presupuesto de imagen
insuficiente, no GPU ni F1 aceptadas. Informe:
[AVANCE_NVIDIA_OFICIAL_20261019.md](AVANCE_NVIDIA_OFICIAL_20261019.md).
El contenido inferior conserva el diagnóstico anterior y su decisión de fuente.

**Bloqueo concreto: el driver del snapshot no satisface el mínimo del perfil CUDA
vigente.** No hay fallos de construcción repetidos ni se ha reconstruido el
candidato CPU. Hay que resolver la fuente/versionado del driver antes de construir
el candidato físico; el instalador físico sigue pendiente después de ese paso.

El propietario confirma «No me importa, usamos ese» tras el informe SMART del
ST9250315AS externo. Ese HDD continúa como destino autorizado de instalación y
recuperación con su baseline de defectos registrado. El bloqueo de sustitución
queda resuelto, sin declarar salud ni pedir otra confirmación equivalente.

## Trabajo realizado

1. Registrada la decisión del propietario en plan maestro, registro y diagnóstico.
2. Añadido `gaia/appliance_nvidia.py` y despacho CLI `appliance-nvidia`.
3. Consultado el snapshot Debian fijado `20261015T000000Z` en namespace
   mmdebstrap sin root del host, con main/contrib/non-free/non-free-firmware.
   Se mantienen firmas APT y keyring Debian; se ignora solamente la expiración de
   metadatos históricos, como en el constructor existente.
4. Resueltas versiones y simulada instalación con `--no-install-recommends`.
   Se conserva política APT, metadatos con SHA-256 de paquetes y simulación completa.
   No se ha instalado ni compilado el driver: esta fase verifica resolución.
5. Comprobada una alternativa Debian del mismo snapshot, trixie-backports.
   Es una consulta de alternativa concreta, no una repetición para forzar éxito.
6. Añadida comparación con el mínimo del catálogo CUDA existente, sin modificarlo.
   La comparación usa la versión upstream, no el epoch o revisión Debian.
7. Evaluados ambos informes con hashes de las evidencias, sin repetir la red/APT.
8. Cuatro tests específicos correctos: rechazo de ambas revisiones 550, candidato
   posterior sin atribuir aceptación física, tratamiento de epoch/revisión y
   rechazo de resolución APT incompleta. Sin skips.

## Evidencia y resultado de resolución

| Fuente | nvidia-driver / nvidia-kernel-dkms / nvidia-smi | linux-headers-amd64 |
|---|---|---|
| trixie, snapshot fijado | `550.163.01-2` | `6.12.107-1` |
| trixie + trixie-backports, mismo snapshot | `550.163.01-4~bpo13+1` | `7.2.6-1~bpo13+1` |

El módulo seleccionado por las simulaciones es **propietario**, no
`nvidia-open-kernel-dkms`. El metapaquete `nvidia-driver` arrastra también Xorg y
bibliotecas gráficas; la instalación compute-only deberá concretar su lista
necesaria en el perfil de construcción, sin aceptar toda esa simulación como
inventario final de la appliance.

- Resolución estable: `.gaia/reports/20261019T101241Z-c22b4fc6/REPORT.md`.
- Resolución backports: `.gaia/reports/20261019T101346Z-d5039ca4/REPORT.md`.
- Evaluación del mínimo:
  `.gaia/reports/20261019T101513Z-7a976e76/REPORT.md`,
  **NVIDIA_PROFILE_BLOCKED_DRIVER_MINIMUM**, salida 20 prevista de bloqueo.

Los dos primeros informes dicen `NVIDIA_SNAPSHOT_RESOLVED`: describen resolución
correcta, no aceptación GPU. La evaluación posterior explicita la incompatibilidad
con la política vigente; las consultas nuevas ya incorporan ese gate directamente.

Reproducción sin repetir las consultas APT:

```bash
python3 gaia.py appliance-nvidia \
  --assess-report .gaia/reports/20261019T101241Z-c22b4fc6 \
  --assess-report .gaia/reports/20261019T101346Z-d5039ca4
```

Comprobación ejecutada:

```bash
python3 -m unittest discover -s tests -p test_appliance_nvidia.py -v
```

## Por qué bloquea

`gaia/bootstrap_profiles.json`, perfil `gaia-transformer-cuda-pascal`, contrato
`gaia_transformer_cuda/v1.1`, fija:

- Torch `2.14.0+cu126`, CUDA `12.6`, CPython `3.14`.
- Driver mínimo **560.28.03**.
- GPU Pascal; mínimo de VRAM y demás condiciones sin cambios.

**550.163.01 < 560.28.03** en ambas fuentes comprobadas. El driver del Ubuntu
anfitrión no se copia ni sirve como validación del Debian de destino. La posible
compatibilidad menor dentro de CUDA 12 no permite atribuir éxito a Torch/modelo
sin prueba real ni modificar silenciosamente el contrato. Backports tampoco
resuelve la versión del driver y cambiaría el kernel elegido.

## Refinamiento necesario

Recomendación: ampliar las entradas de construcción del perfil físico a una fuente
oficial NVIDIA firmada que proporcione un driver propietario posterior al mínimo
y con soporte Pascal —investigar rama 580—, manteniendo Debian estable, kernel
exacto y el lock Python/Torch actual. Antes de construir se debe comprobar soporte
de la GTX 1060, origen/firma/hash de los paquetes, dependencia con el kernel y
compilación del módulo. No se afirma todavía que un paquete concreto de esa fuente
esté resuelto ni validado.

Esto refina la procedencia del driver respecto al snapshot Debian único. Alternar
a CUDA/Torch distintos o rebajar el mínimo sería otro cambio de contrato, con
impacto mayor y prueba real obligatoria; no se ha hecho. Se solicita decisión sobre
la ampliación de fuente antes de introducir una cadena nueva de paquetes NVIDIA.

Después de resolverla: construir módulos para el kernel fijado, perfil runtime
CUDA con acceso GPU acotado, instalador físico con gates S0, pruebas pertinentes,
firma del paquete físico listo y preparación del HDD autorizado. La compatibilidad
real se comprueba en la imagen física antes de aceptar F1.

## Informe de parada

- Decisión del HDD incorporada y bloqueo anterior resuelto.
- Dos resoluciones APT reales completadas; evaluación de compatibilidad bloqueada
  de manera explícita por versiones, no por un error del probe.
- Cuatro tests nuevos correctos; no se repitió la suite histórica de 224 tests ni
  la matriz CPU/VM. El cierre CPU/VM permanece aceptado.
- No hubo cambios al driver del host, imagen CPU, firmas, discos físicos ni claves.
- No se construyó todavía un rootfs NVIDIA, módulos ni instalador físico.
- Parada para refinar la fuente del driver; no se solicita otra firma CPU ni otro HDD.
