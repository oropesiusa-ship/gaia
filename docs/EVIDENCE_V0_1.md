# Índice de evidencia — GAIA v0.1 Autonomous MVP

Status: Current — historical milestone evidence index.

Archivo externo local:
`/home/mingororo/Projects/gaia-evidence-archive/gaia-v0.1/`.
El índice administrativo es `gaia-v0.1-evidence-index.json`; los manifiestos y
verificadores están bajo `manifests/`. Los bundles no se copian a Git.

**Las rutas locales son referencias administrativas, no parte de la identidad
criptográfica del contenido del bundle.** El aggregate es SHA-256 del JSON
canónico del array ordenado `{path,size,sha256}`. El hash del manifiesto se calcula
excluyendo su propio campo: protege también metadatos y rutas registradas, por lo
que una edición de esos campos sí cambia el hash del manifiesto. Trasladar un
bundle sin editar sus bytes no cambia su aggregate.

## Prueba A — pipeline end-to-end

- Resultado histórico: **PASS**, `pipeline_certified=true`.
- Propósito: probar el pipeline real con baseline/candidata controladas,
  publicación v0001, recarga, rollback a v0000 y verificación final.
- No certifica autonomía: `autonomous_self_improvement_certified=false`.
- Bundle: `/home/mingororo/Projects/gaia-evidence-archive/gaia-v0.1/certification-a/`.
- Manifiesto: `manifests/certification-a.sha256.json`.
- Aggregate: `0eea959eaca505c81e3c4a99b99cb65f983e787670b87cd668607636faf016fa`.
- Manifest hash: `0905c3451ddf853082bba8e55b5d31c36f68f3cc829aa78a5e111db4eb7e195b`.

Copia íntegra y checks portátiles PASS. El verificador integral A compara la ruta
y nombre originales del estado: al reubicar devuelve identidad incompatible.
La validación archivada es **PARCIAL por esa limitación**, sin reescribir evidencia.

## Prueba B — automejora autónoma

- Resultado histórico: **PASS**; promoción y automejora autónomas certificadas.
- Ganador de origen `search`, una campaña normal, trazas reproducibles y
  **46,90 % de mejora** registrada; recarga y rollback verificados.
- Bundle: `/home/mingororo/Projects/gaia-evidence-archive/gaia-v0.1/autonomous-mvp-b/`.
- Manifiesto: `manifests/autonomous-mvp-b.sha256.json`.
- Aggregate: `da15a56bf3c508955ebea945a925b0d886131601eb98674ad6a80fa039f3cab9`.
- Manifest hash: `786179e4ef2e954e0039b77b89476e3ae670688db24ee228faee5eb941657a75`.
- Verificación histórica archivada: **PASS**. CURRENT final v0000 tras rollback;
  v0001 conserva la mejora promovida. No se interpreta el rollback como pérdida
  de la certificación de la promoción observada.

## Modo B MLP — estudio histórico

- Clasificación: **HISTORICAL_STUDY**; resultado formal **inconcluyente**, valor
  no demostrado. Tres de cuatro parejas completas, tres victorias OFF.
- Bundle: `/home/mingororo/Projects/gaia-evidence-archive/gaia-v0.1/modo-b-mlp/`.
- Manifiesto: `manifests/modo-b-mlp.sha256.json`.
- Aggregate: `2bbae84c62f91df545891601cf284853d95080b000fceaa5e3af9a653dec2a75`.
- Manifest hash: `e7305e462047be69bbe4d49f867b7dad0d33f5644385cbb9bbba9b548d438dc3`.
- Verificación histórica: **PASS**, análisis reproducido en memoria y contrastado
  con `analysis.json`, usando las fuentes selladas. Ocho symlinks externos se
  conservan sin recorrer; no son entradas del análisis offline.
- Contexto: [resultado](RESULTADO_MODO_B_MLP_20261019.md) y
  [prerregistro](PRERREGISTRO_MODO_B_20261019.md), ambos históricos.

## GPU Frozen — alcance limitado

- Clasificación: **GPU_FROZEN**, no certificado al nivel CPU MVP.
- Bundle: `/home/mingororo/Projects/gaia-evidence-archive/gaia-v0.1/gpu-frozen/`.
- Manifiesto: `manifests/gpu-frozen.sha256.json`.
- Aggregate: `fae61b4b784c4c125f952368c5cb687328b9391c27ba59a6cd1e5578f9002570`.
- Manifest hash: `49e6496bf857e403992e9e0600cd7c4a73f3e2a6418d783ce9d981c56643184e`.
- Verificación semántica: **PARCIAL**, checks estáticos PASS. CURRENT v0000,
  hashes de baseline/estrategia y asociaciones internas coherentes. El estado
  referencia reports y fuentes externos; no contiene un snapshot CPU-equivalente.
  No se ejecutaron CUDA, campañas ni recovery para archivarlo.

## Verificación y preservación

`manifests/verify-archived-evidence.py` verifica A/B con sus snapshots;
`manifests/verify-step2-evidence.py` verifica Modo B/GPU sin campañas. Requieren
las dependencias indicadas en sus cabeceras. Los informes administrativos
conservan limitaciones y coincidencia original/copia; los bundles son de solo
lectura, no un mecanismo de inmutabilidad contra su propietario.

Los originales A/B, Modo B y GPU siguen preservados en el workspace. Legacy,
`demo_evidence/` (**HISTORICAL_EVIDENCE_PENDING_ARCHIVE**), imágenes/rootfs y
otros reports no están autorizados para retirada por estos archivos parciales.
