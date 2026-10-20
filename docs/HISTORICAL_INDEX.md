# Índice documental y precedencia

Status: Current.

Autoridad actual: README, arquitectura/evidencia v0.1 y límites de congelación.
Las fechas, métricas y números de tests en documentos históricos describen su
ejecución original, no la suite actual. Sus instrucciones no autorizan campañas,
instalación física, borrados, ampliación GPU ni trabajo de GAIA 0.2.

## CURRENT

- `../README.md`
- `ARCHITECTURE_V0_1.md`
- `EVIDENCE_V0_1.md`
- `STATUS_FROZEN_COMPONENTS.md`
- `HISTORICAL_INDEX.md`
- `CONSOLIDATION_POLICY.md`
- `BOOTSTRAP.md`: referencia del provisionamiento existente. Leer con el README:
  CPU requiere identidad/snapshot/bwrap; apartados GPU/appliance congelados.

## HISTORICAL — resultados, contratos de retirada y registro de ejecución

- `PLAN_FASES-COMPLETED.md`: plan TinyGPT ejecutado; nombre «v2» histórico, no GAIA 0.2.
- `PLAN_RENOMBRADO_GAIA_TRANSFORMER.md`
- `REFERENCIA_RENOMBRADO_GAIA_TRANSFORMER.md`
- `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`
- `TRANSICION_LEGACY_V0.md`: preserva decisiones de retirada y muestra estática;
  sus capacidades pendientes son futuro, no implementaciones actuales.
- `VALIDACION_CUDA_FASE_0_1.md`
- `VALIDACION_GAIA_TRANSFORMER_FASE_1.md`
- `VALIDACION_GAIA_TRANSFORMER_FASE_2.md`
- `VALIDACION_GAIA_TRANSFORMER_FASE_3.md`
- `VALIDACION_GAIA_TRANSFORMER_FASES_4_5.md`
- `VALIDACION_GAIA_TRANSFORMER_FASE_6.md`
- `VALIDACION_GAIA_TRANSFORMER_FASE_7.md`
- `VALIDACION_GAIA_TRANSFORMER_FASE_8.md`
- `PRERREGISTRO_MODO_B_20261019.md`: protocolo sellado, conservado sin añadir cabecera.
- `RESULTADO_MODO_B_MLP_20261019.md`: resultado cerrado; propuestas finales de otra
  sesión son diseño futuro, no el siguiente paso de consolidación.
- `PROMPT_EVALUAR_MODO_B.md`: prompt anterior al estudio, no una instrucción vigente.
- `EJECUCION_PLAN_MAESTRO_GAIA.md`: log cronológico, con siguientes pasos superados.
- `VALIDACION_APPLIANCE_S1_VM.md`
- `VALIDACION_APPLIANCE_S1_20261018.md`
- `VALIDACION_RECUPERACION_FIRMADA_S1_20261018.md`
- `VALIDACION_CANDIDATO_CPU_20261019.md`
- `VALIDACION_NVIDIA_WORKSPACE_20261019.md`
- `AVANCE_NVIDIA_OFICIAL_20261019.md`
- `CIERRE_CPU_VM_20261019.md`
- `CIERRE_S1_ENTREGA.md`
- `DIAGNOSTICO_MEDIO_RECUPERACION_20261019.md`
- `evidencia_appliance/**`, `evidencia_renombrado/**`: evidencia documental
  preservada. No reescribir ni eliminar sus logs, datos o fixtures.
- Scripts fechados/de renombrado bajo `docs/*.py`: tooling histórico, no runtime.
- `../examples/REPORT_ejemplo_sandbox.md`, `../examples/run_log_ejemplo.txt`:
  ejemplos estáticos de ejecuciones anteriores, no certificación actual.
- `../archives/text_prototype/`: muestra histórica estática, no corpus aprobado
  para un nuevo workload ni prototipo ejecutable vigente.

## FROZEN — referencias conservadas, ejecución suspendida

- `CHECKPOINT_APPLIANCE_PAUSADO_20261019.md`: autoridad conservada sobre el punto
  de pausa appliance; el estudio Modo B posterior ya tiene resultado histórico.
- `APPLIANCE_BOOTSTRAP.md`
- `APPLIANCE_BACKUP_CLAVE.md`
- `APPLIANCE_FIRMA_OFFLINE.md`
- `APPLIANCE_FIRMA_INSTALACION_VM.md`
- `APPLIANCE_FIRMA_CANDIDATO_CPU.md`
- `APPLIANCE_FIRMA_PREFLIGHT_GPU.md`
- `WORKSPACE_SSD_CONSTRUCCION_20261019.md`
- `PERFIL_FISICO_NVIDIA_20261019.md`
- `CONTRATO_GAIA_TRANSFORMER_CUDA_V1.md`: contrato GPU implementado por etapas;
  lenguaje de diseño/pending se conserva como historia, no como roadmap autorizado.
- `CORPUS_GAIA_TRANSFORMER_V1.md`: especificación del corpus congelado.

## FUTURE_DESIGN — no implementado ni autorizado por consolidación

- `PLAN_MAESTRO_GAIA.md`: F1 física incompleta y fases posteriores futuras.
- Matrices F4/F5 de `TRANSICION_LEGACY_V0.md`.
- Revisión Research Engine y réplica GPU propuestas al final de
  `RESULTADO_MODO_B_MLP_20261019.md`.
- GAIA 0.2, Self Observation, integración LLM y ampliaciones GPU/appliance:
  fuera de las capacidades consolidadas v0.1.

## Evidencia pendiente de archivo externo

`../demo_evidence/` es **HISTORICAL_EVIDENCE_PENDING_ARCHIVE**: demo generada
citada por el prerregistro, sin consumidores de tests. `state/` y el estado NumPy
legacy también requieren archivo antes de retirar. Reports/imágenes históricos
incluyen dependencias externas del estado GPU archivado. Nada de esto queda
autorizado para borrado por estar excluido de Git.
