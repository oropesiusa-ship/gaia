# S1 — Instalación y reparación firmadas desde USB virtual

Fecha: 2026-10-18. **Ensayo firmado positivo 3/3; S1/F1 siguen abiertas.**

## Resultado

La firma solicitada existe y corresponde al mensaje exacto y a la identidad fijada:

- Huella: `6BF5C62DC530889F3D7C644F678D00EC8B5BF748`.
- Manifiesto SHA-256:
  `0d0333fc6a7035cb7367b09b1ba160daadc2d1fad99971528a6b62705e25b0a2`.
- Firma SHA-256:
  `c49876bcbc035d43f157f1001ce8930c3af13817d98da7a3756c760ffa6edc0e`.
- Imagen SHA-256:
  `216be2f81c1ec29a726859085d6f89d9caadf911489c1090b829a93a05275c6f`.
- Propósito **lab**, perfil **vm-cpu-l0**; no autorización de instalación física.

Verificación del propietario:
`.gaia/reports/20261018T194012Z-42a20cef/REPORT.md`, `SIGNED_ARTIFACTS_VERIFIED`.
El controlador la volvió a verificar antes de consumir el paquete. No se usó
privada por el agente: gpg/gpgv del host y sqv del invitado solo reciben material
público. No se modificó la imagen/manifiesto firmados para corregir los problemas
del controlador.

Informe agregado definitivo:
**`.gaia/reports/20261018T203350Z-9e9b020a/REPORT.md` — VM_SIGNED_RECOVERY_VALIDATED.**

| Repetición | Instalación desde USB | Boot del instalado sin USB | B dañado y reparación desde USB | Boot reparado sin USB |
|---|---|---|---|---|
| 1 | OK | OK, ledger 1 | OK, DATA conservada | OK, ledger 2 |
| 2 | OK | OK, ledger 1 | OK, DATA conservada | OK, ledger 2 |
| 3 | OK | OK, ledger 1 | OK, DATA conservada | OK, ledger 2 |

Cada instalación exige firma/contexto/hashes del bundle, identidad del destino
virtual, ausencia de montajes, copia de la imagen y readback completo. La reparación
valida GPT contra la imagen firmada, reescribe solo ESP/CORE/A/B, comprueba hashes
de esas particiones y verifica que DATA no cambia. El arranque posterior exige
firma pública, CORE/root RO, política offline, catálogo L0, worker no root y
smoke CPU; la continuidad del ledger 1→2 acredita persistencia entre los boots.

El código de este perfil solo permite QEMU y el serial virtual `GAIA-LAB-TARGET`.
Ningún disco físico se ha pasado al invitado ni formateado/particionado aquí.

## Reanudación y procedencia de las evidencias

El propietario también había iniciado el controlador, además de firmar. Se revisó
ese trabajo antes de ejecutar nada duplicado:

1. `20261018T194147Z-3dd692af`: instalación 1 y boot independiente correctos.
   Falló después, preparando la reparación: mcopy pedía confirmar una colisión de
   archivo Unix aunque se usaba `-o`, con el prompt oculto en stderr; timeout 300 s.
2. `20261018T201343Z-e5cd54a4`: reanudación con firma, fuente, bundle completo y
   target comprobados. Reparación 1/boot correctos; instalación 2 completó readback,
   pero un printk de enumeración de particiones interrumpió el JSON de consola.
3. `20261018T203350Z-9e9b020a`: se recuperó el registro completo de instalación 2
   eliminando solo la notificación de particiones reconocida. Se comparó **todo**
   el destino qcow2 contra el raw firmado y se ejecutó su boot independiente antes
   de considerarla aceptada. Se completaron reparación 2, instalación 3 y reparación
   3 con sus boots. El informe contiene seis resultados únicos, prefijo heredado
   documentado y origen de cada reanudación; no se infirió éxito por exit 0.

Los informes fallidos anteriores se conservan como históricos, no se convierten
retroactivamente en éxitos. Los destinos temporales ya terminados se liberan según
la retención del controlador; se conserva el último destino reparado, los logs,
firmas, hashes y el paquete fuente. No se recreó el bundle de varias decenas de GiB.

## Cambios del controlador y verificación

- Readbacks UKI en rutas nuevas por invocación: no se sobrescriben diagnósticos ni
  se depende de que mcopy suprima un prompt sobre un destino Unix existente.
- `--resume-report` verifica mismo paquete/firma/imagen, prefijo de resultados
  válido, hash del bundle inmutable, formato/geometría/backing del target y que
  no haya modificaciones posteriores al fallo. Rechaza reanudar datos ambiguos.
- Consola de recuperación más silenciosa. El parser elimina únicamente mensajes
  de enumeración de particiones con formato conocido. JSON roto no reconocido,
  errores del kernel o resultados duplicados siguen rechazándose.
- Un resultado de instalación recuperado requiere comparación íntegra y boot
  independiente: nunca basta con reconstruir texto de consola.
- **215 tests OK, 29.697 s, sin skips** en el código actual:
  `.gaia/reports/20261018T210144Z-2d7effcc/REPORT.md`.
  Regresiones nuevas: doble preparación ESP sin colisión de readback, checkpoint
  de firma incorrecta/target modificado y transporte de JSON intercalado sin
  aceptar un error arbitrario del kernel.

## Relación con el objetivo completo

Este resultado completa el ensayo firmado positivo de instalación/reparación VM.
Se une a la matriz de diez escenarios 3/3 del mismo artefacto, descrita en
`VALIDACION_APPLIANCE_S1_20261018.md`. La imagen permanece de laboratorio:
`release_image=false`, no se declara apta para desplegar físicamente ni cerrada F1.

Pendientes de S1/entrega: perfil de release y retirada del toolchain de construcción,
revisión final de aceptación y preparación del medio físico verificable conforme
al plan. Posteriormente deben cumplirse S0/S2–S4: identificación/SMART del HDD,
compatibilidad NVIDIA real y perfil congelado, arranques físicos, baseline y
recuperación/backup físicos. F2–F8 no se inician antes del cierre de F1.

La firma prueba identidad y autorización del paquete lab. El almacenamiento
independiente de la privada y el registro externo de huella requieren la
declaración del propietario; no se afirman inspecciones de sus USB privados.
