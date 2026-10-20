# Componentes congelados y estudio histórico

Status: Current — freeze boundaries for v0.1 consolidation.

## GPU — FROZEN

`gaia/gaia_transformer/` es un workload CUDA separado, con benchmark, laboratorio,
CampaignStore y JSONL propios. No tiene todas las garantías CPU de snapshot,
manifests, ledger encadenado, publicación/rollback y recovery. Los nombres G0–G5
no hacen equivalentes sus garantías. El estado archivado tiene CURRENT v0000 y
validación estática limitada; no es CPU MVP certificado.

Se conservan código, comandos, tests y evidencia. **No continuar desarrollo,
ampliar GPU ni endurecerla sin decisión explícita.** Tests existentes no son una
nueva certificación del estado GPU histórico.

## Appliance — FROZEN

Se conserva el trabajo de construcción, firma, VM y recuperación. Las pruebas
CPU/VM históricas no completan la appliance física ni el instalador físico.

El [checkpoint operativo conservado](CHECKPOINT_APPLIANCE_PAUSADO_20261019.md)
documenta el punto de pausa y las condiciones de reanudación. Sus siguientes
pasos sobre el estudio Modo B pertenecen a octubre de 2026, no sustituyen el
objetivo actual de consolidación. F1 física no está completada; no interpretar
firmas de propósito lab como autorización física.

No reanudar desarrollo, instalación, preparación de medios ni ampliación de
appliance sin decisión explícita. Reports, imágenes, rootfs, firmas y fixtures
de recuperación siguen protegidos contra retirada no autorizada.

## Modo B MLP — HISTORICAL_STUDY

La comparación ON/OFF del 19-10-2026 es un estudio cerrado, formalmente
inconcluyente: tres parejas completas, resultados desfavorables a ON y parada
por ruido antes de completar la cuarta. No repetirla para completar o reemplazar
resultados. No es un pipeline actual.

`tools/evaluate_mode_b.py` fue su productor histórico y es incompatible con el
formato certificado CPU actual. `tools/summarize_mode_b.py` es su analizador
histórico: consulta rutas específicas y escribe `analysis.json`; no ejecutarlo
directamente sobre un bundle protegido. El verificador administrativo externo
reproduce ese análisis en memoria usando fuentes históricas.

Esto no retira ni modifica `gaia/research.py`, el mecanismo CPU existente.
Replantearlo, añadir Self Observation o iniciar GAIA 0.2 quedan fuera de la
consolidación. Véase [el índice de evidencia](EVIDENCE_V0_1.md).
