# Traspaso verificable del prototipo de texto

Fecha de inspección y retirada verificada: 2026-10-16. El prototipo histórico se
retiró en fase 6 después de verificar sus doce hashes. Las capacidades siguientes siguen pendientes de
F4/F5 del plan maestro; no son capacidades migradas al runtime sintético actual.

## Inventario real y decisiones

El inventario exhaustivo con tamaño y SHA-256 de **los 12 archivos existentes**
está en `evidencia_renombrado/inventario_fase0.json`, entradas `legacy_v0/`.
Se recorrieron también archivos no versionados: no existen checkpoints,
`checkpoints/`, historial `experiments/`, ni archivos STOP o temporales.

| Activo original | Clasificación y destino | Verificación |
|---|---|---|
| `data/train.txt` | Preservado en `../archives/text_prototype/sample_corpus.txt` como fixture histórico, no corpus aprobado | 24120 bytes; SHA-256 `3d8922516deb38620bc1edd5f5bd4c3194dc42b255d80dea890a9d85a8f8b4e7`; comparación binaria antes de retirada |
| `config.py`, `data.py`, `tokenizer.py` | Conocimiento preservado en esta especificación y configuración detallada inferior; fuente ejecutable retirada en fase 6 | Contratos UTF-8, partición y ventanas descritos; hashes originales en inventario |
| `model.py`, `train.py`, `sample.py` | Conocimiento preservado aquí; motor ejecutable retirado en fase 6 | Arquitectura, entrenamiento y generación descritos; no se afirma compatibilidad de pesos |
| `evolution.py`, `evaluator.py`, `main.py` | Conocimiento preservado aquí; búsqueda antigua sustituida por campaña/ledger/evaluación independiente actuales | Suite previa: 145 tests OK; repetición de puertas GPU prevista fases 3–4 |
| `README.md`, `requirements.txt` | Instrucciones y dependencias obsoletas descartables tras traspaso | No aportan datos únicos; no fijan entorno reproducible del motor activo |

El texto contiene tres frases didácticas en español repetidas, con separadores
literales `\\n`. Procedencia: muestra local incluida en el prototipo, sin atribución
externa registrada. No se infiere licencia ni calidad de corpus de producción.
Se preservan exactamente los bytes; F4 revisará procedencia, duplicación y licencia.
No hay pesos ni historial que convertir o preservar. La ausencia es observada,
no deducida del control de versiones (este workspace no contiene repositorio Git).

## Pipeline y parámetros originales

- Lectura binaria completa (`read_bytes`); no valida UTF-8 al cargar. `encode`
  convierte texto válido a lista de bytes UTF-8; `decode` convierte enteros a bytes
  y decodifica con `errors="replace"`. Vocabulario fijo 0..255 sin pesos externos.
- Corte contiguo `int(0.9 * len(raw))`; train/valid son tensores long. Cada partición
  debe tener al menos `context+2` bytes. No hay deduplicación ni auditoría separada.
- Ventanas aleatorias con `torch.randint(0,len(data)-context-1)` (límite superior
  exclusivo), entradas de contexto y targets desplazados un byte. RNG CPU explícito.
- Config: context=128, dim=128, heads=4, layers=2, dropout=0.1, batch=16,
  steps=100, eval_batches=12, lr=0.0003, max_minutes=120, max_cycles=100,
  max_temp_c=78, cool_seconds=90, device=auto, seed=42.
- Embeddings de bytes y posiciones aprendidos, `TransformerEncoderLayer` pre-norm,
  feedforward 4*dim, GELU, dos capas, máscara triangular causal booleana,
  LayerNorm final y proyección sin bias ligada al embedding. Inicialización normal
  std=0.02 en embeddings/lineales y biases cero. No es la arquitectura actual de
  atención explícita; no son checkpoints intercambiables.
- Cada candidato copia al campeón; AdamW nuevo en cada ensayo, weight_decay=0.01,
  zero_grad(set_to_none=True), CE en todas las posiciones, clipping norma 1.0.
  Semilla de batches `seed+cycle`; guard antes de cada paso y tras entrenamiento.
  CUDA sincroniza al final; CPU usa hasta seis hilos.
- Validación: eval/no_grad, doce batches, semilla fija 123456; media aritmética
  de pérdidas. Promoción antigua: pérdida finita menor que best-0.002. Reutiliza
  validación para seleccionar, no hay confirmación pareada ni auditoría retenida.
- Búsqueda Python random con seed=42; LR en [0.0001,0.0002,0.0003,0.0005,0.0008];
  pasos en [max(20,steps//2),steps]. Límite por minutos/ciclos, STOP y Ctrl+C;
  temperatura nvidia-smi con enfriamiento 90 s; lectura fallida no protege temperatura.
- Checkpoint esperado (ausente): `torch.save` de dict `state` (tensores CPU),
  `val_loss`, `cycle`, `architecture` (asdict de Config), publicación con `.tmp`
  y os.replace, sin hash/fsync. Recarga `weights_only=True`, comprobando context,
  dim,heads,layers,dropout y load_state_dict. No conserva optimizador ni RNG;
  reinicio no equivale a continuación exacta. Historial esperado JSONL con cycle,
  lr,steps,val_loss,best_loss,accepted,train_loss,seconds; no existe en disco.
- Generación: carga pesos/config, GPU si disponible, prompt UTF-8 (vacío => [32]),
  eval/no_grad, 120 pasos multinomial con temperatura 0.9 acotada inferiormente
  a 0.05, contexto deslizante de 128, devuelve prompt+salida con reemplazo de
  UTF-8 inválido. Sin EOS ni semilla de generación explícita.

## Matriz de capacidades y aceptación futura

| Origen | Equivalente activo | Destino y contrato | Prueba prevista | Estado |
|---|---|---|---|---|
| data/load_data | Corpus sintético congelado, no texto externo | F4: ingesta local versionada y particiones por origen/contenido | hashes, corpus pequeño, rechazo de fuga/duplicación, tres particiones | Pendiente F4 |
| tokenizer encode/decode | IDs byte-level del corpus sintético | F4: codec propio UTF-8 y política explícita de secuencias inválidas | ida/vuelta español, multibyte y vacío; bytes inválidos => reemplazo declarado | Pendiente F4 |
| data/batch | Batches sintéticos actuales | F4: ventanas de texto y shift causal | fixture conocido verifica límites y targets sin cruzar particiones | Pendiente F4 |
| model/forward | Transformer causal propio sintético | F4/F5: extender GaiaTransformer para texto sin importar pesos legacy | causalidad, shapes, entrenamiento→recarga→generación | Pendiente F4/F5 |
| train_steps | Entrenador sintético CUDA | F5: entrenamiento local desde cero con semillas, presupuesto y métricas | pérdida retenida, parada y reproducibilidad en perfil congelado | Pendiente F5 |
| atomic_save/recarga | Versiones estables de fuente, no checkpoint de lenguaje | F4/F5: pesos+config+datos+runtime+integridad, publicación atómica; semántica explícita de optimizador/RNG | roundtrip pesos/logits; corrupción e incompatibilidad rechazadas; continuación exacta solo si demostrada | Pendiente F4/F5 |
| generate/sample | No implementado en base activa | F4: prompt, contexto, semilla, temperatura, máximo salida y parada | end-to-end entrenar→guardar→recargar→generar, determinismo con semilla | Pendiente F4 |
| evaluate/evolution | Evaluación privada, confirmación y auditoría sintéticas | F5: evaluación de lenguaje independiente del benchmark CUDA | auditoría no usada para selección y controles nulos | Pendiente F5 |

## Puerta para la retirada

Comprobación ejecutada antes de borrar: SHA-256 de la muestra preservada correcto,
doce hashes originales coincidentes, fases 0–5 OK. Retirados los doce archivos;
la relación exacta y sus hashes permanecen en el inventario de fase 0.
Esta especificación conserva conocimiento, no un segundo runtime mantenido.
