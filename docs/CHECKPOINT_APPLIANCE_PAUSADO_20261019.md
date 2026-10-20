# Checkpoint: appliance pausado; prioridad a evaluar el Modo B

Fecha: 2026-10-19. Decisión explícita del propietario: detener el trabajo del
appliance y volver a las pruebas del proceso de descubrimiento de GAIA.
Este checkpoint sustituye las instrucciones anteriores de continuar con el HDD
y las solicitudes de firma que hayan quedado pendientes en documentos históricos.

## Estado conservado

- CPU/VM: `S1_CPU_VM_ACCEPTED`, informe
  `.gaia/reports/20261019T100144Z-91a97bb3/REPORT.md`.
- Imagen NVIDIA candidata: `/mnt/gaia-build/artifacts/20261019T111348Z-95cd9936/`.
  `disk.raw`: 25075646464 bytes, SHA-256
  `63dc4c7ee9d905edcf2cd61a0f107c7861d03d7bad8c36332e1f0cd5f795b0a4`.
- NVIDIA oficial 580.178.04, kernel 6.12.107+deb13-amd64, objetivo GTX 1060 6 GB.
- Matriz NVIDIA VM: diez escenarios con tres repeticiones, 63 arranques
  seleccionados; auditoría `.gaia/reports/20261019T125118Z-1bba0062/REPORT.md`.
  El primer runner terminó por timeout; la auditoría excluye parciales/duplicados.
- Última suite appliance registrada: 88 tests correctos, sin skips.
- **Firma ya recibida y verificada**, comprobada leyendo el informe
  `.gaia/reports/20261019T132311Z-8e0ae907/REPORT.md`:
  `SIGNED_ARTIFACTS_VERIFIED`, propósito `lab`, sin autorización de instalación.
- Manifiesto firmado:
  `/mnt/gaia-build/artifacts/20261019T125118Z-1bba0062/gpu-preflight-manifest.json`.
  SHA-256 `2f2401fe2092e3e9bfd5a82780270eb05addb88683966dfede7fce4b0a973c77`.
  Firma `.asc`: SHA-256
  `a373f9610d0b17bde6ad1cec4924d800f6c61549fe2b2d6fe4ac71961922944c`.
- Workspace configurado: `/mnt/gaia-build`, ext4 UUID
  `40b184e0-21a2-43e9-8d02-df296c6d28af`, respaldo
  `/run/media/mingororo/661EC3B41EC37C15/GAIA-build-workspace.ext4` (120 GiB).
  Su montaje actual debe comprobarse antes de cualquier uso futuro.

GPU física y CUDA real aún no validados. HDD externo sin preparación física
registrada. Instalador físico y pruebas S0/S2–S4 pendientes. F1 no completada.
No se ejecuta ningún nuevo paso físico como consecuencia de la firma.

## Material que se conserva

No borrar ni regenerar código, imágenes, firmas, informes, decisiones D1–D4 ni
hallazgos del driver. Este checkpoint es documental, no una copia independiente
de los archivos grandes: para retomarlos deben seguir disponibles proyecto y SSD.

- `docs/PLAN_MAESTRO_GAIA.md` y `docs/EJECUCION_PLAN_MAESTRO_GAIA.md`.
- `docs/VALIDACION_NVIDIA_WORKSPACE_20261019.md`.
- `docs/AVANCE_NVIDIA_OFICIAL_20261019.md`.
- `docs/WORKSPACE_SSD_CONSTRUCCION_20261019.md`.
- `docs/APPLIANCE_FIRMA_PREFLIGHT_GPU.md` (procedimiento histórico ya ejecutado).
- Código `gaia/appliance_*`, payload, pruebas y `.gaia/reports/`.

## Por qué cambia la prioridad

La pregunta prioritaria es si la investigación del Modo B mejora de forma
reproducible el proceso de descubrimiento frente al mismo laboratorio sin ella.
Construir el sistema operativo no resuelve esa comparación.

El propietario aporta como antecedentes: seis puertas del laboratorio superadas,
recuperación de kill -9, correcciones de ID reutilizado/torch del worker/memoria;
CV de 0.5 %, control nulo 1.00, mejora MLP de unas 13 veces con saturación y
técnicas conocidas, y una hipótesis del Modo B refutada en el siguiente campeón.
Son antecedentes a localizar y contrastar en los informes originales antes de
usarlos como resultados de una nueva comparación. No demuestran por sí solos
que el Modo B sea útil o inútil.

## Trabajo siguiente (otra sesión)

1. Localizar configuración, CLI, evidencia y semántica real de `research.enabled`.
   Comprobar que activarlo puede influir en las propuestas dentro del presupuesto.
2. Antes de ejecutar, dejar protocolo fechado: campañas MLP cortas y emparejadas
   ON/OFF, mismas semillas por pareja, estado inicial independiente e idéntico,
   mismo presupuesto de experimentos, puertas y recursos. Alternar el orden;
   aislar campeones, historial y cachés para impedir transferencia entre brazos.
3. Fijar número de parejas, umbral de consistencia y reglas de fallo/saturación
   antes de ver resultados. Contar mejoras verificadas, ganancia final, tiempo
   total (incluida investigación), fallos y coste. No igualar resultados por
   presupuesto si cambian el número real de candidatos evaluados: documentarlo.
4. Sin ventaja consistente: Modo B no ha demostrado valor en esta prueba;
   replantear Research Engine. Con ventaja: ampliar espacio y workload.
   Resultado inconcluyente o benchmark saturado: declararlo, sin atribuirlo al SO.
5. Repetir en TinyGPT/CUDA solo si la carga y el runtime del host ya están listos,
   manteniendo las puertas existentes. No instalar drivers ni retomar appliance
   para desbloquear esta comparación.
6. Aislamiento barato solo si el CV empeora: proponer medida concreta y verificar
   efecto. No cambiar governor ni ejecutar `systemctl isolate` automáticamente.

No ejecutar campañas en esta sesión de checkpoint. El presupuesto concreto se
prerregistra en la siguiente tras inspeccionar el laboratorio; el texto anterior
no constituye resultados ni un protocolo estadístico ya ejecutado.

## Condición para retomar el appliance

Solo con nueva decisión del propietario por ruido del host que no se controle
baratamente, investigación explícita de cambios de sistema o appliance como
objetivo propio. Retomar desde W2 como punto solicitado, contrastándolo con el
plan y este estado real para saltar lo ya completado. Revalidar montaje, hashes,
identidad del medio y permisos vigentes antes de operaciones físicas. La firma
lab existente no equivale a aceptación física ni autorización general de escritura.

Prompt para otra sesión: `docs/PROMPT_EVALUAR_MODO_B.md`.
