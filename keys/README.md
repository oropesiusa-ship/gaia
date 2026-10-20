# Identidad pública de firma GAIA

Huella OpenPGP completa comunicada por el propietario:

`6BF5C62DC530889F3D7C644F678D00EC8B5BF748`

El archivo `gaia-release-signing.fingerprint.txt` fija la identidad esperada.
Recibidas y verificadas `gaia-release-signing.pub.asc` y `.pub.gpg`: misma clave
binaria, primaria Ed25519 de firma, huella coincidente. Informe público:
`.gaia/reports/20261016T133757Z-78fc1d87/REPORT.md`.
Firma del propietario sobre `gaia-custody-backup-check.json` recibida y verificada:
`.gaia/reports/20261016T134648Z-33248432/REPORT.md`, `SIGNED_ARTIFACTS_VERIFIED`.
Coinciden desafío y hashes fijados; es una prueba pública de laboratorio, no una
autorización de release. Metadatos de ambos USB comprobados cerrados después.
Pendientes confirmación humana explícita del registro externo y de que la firma
se hizo desde el backup con el primario cerrado, según el procedimiento indicado.
Instrucciones: [backup de clave](../docs/APPLIANCE_BACKUP_CLAVE.md).

También recibida y verificada la firma del paquete de instalación lab, manifiesto
`0d0333fc6a7035cb7367b09b1ba160daadc2d1fad99971528a6b62705e25b0a2`.
Instalación/reparación VM 3/3: `.gaia/reports/20261018T203350Z-9e9b020a/REPORT.md`.
Esto no convierte el perfil de laboratorio en una release física ni cierra F1.

Este directorio solo contiene material público. La privada, el homedir GnuPG,
la revocación y las contraseñas permanecen en la custodia externa. Procedimiento
y estado: [firma offline](../docs/APPLIANCE_FIRMA_OFFLINE.md).
