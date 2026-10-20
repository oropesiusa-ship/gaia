# Corpus sintético GaiaTransformer: structured_bytes/v1

Esta especificación completa la generación prevista por `gaia_transformer_cuda/v1.1`
antes de cualquier calibración. Implementación: `gaia/gaia_transformer/data.py`.
Manifestación congelada: `gaia/gaia_transformer/corpus_v1.json`.

## Registros y splits

Vocabulario del modelo: bytes `0..255`. El corpus usa un subconjunto estructurado
de esos bytes; no requiere tokenizador, datos externos ni descargas.

| Split | Dominio ASCII | Semilla | Registros | Bytes |
|---|---|---:|---:|---:|
| train | T | 1701 | 4096 | 266240 |
| validation | V | 2903 | 256 | 16640 |
| audit | A | 3907 | 256 | 16640 |

Cada registro tiene exactamente 65 bytes: 64 de contexto más un siguiente byte.
El registro `index` se construye así:

1. Calcular SHA-256 de ASCII `structured_bytes/v1|<split>|<seed>|<index>`.
   `index` y `seed` se escriben en decimal sin ceros iniciales.
2. Elegir período `(2,4,8)[digest[0] % 3]`.
3. Alfabeto fijo: ASCII `abcdef0123456789`.
4. Crear un patrón usando los siguientes `period` bytes del digest: cada byte
   selecciona `alphabet[byte % 16]`.
5. Prefijo de 10 bytes: letra de dominio, índice hexadecimal en minúsculas de
   ocho dígitos y `:`; por ejemplo `T00000000:`.
6. Repetir el patrón y truncarlo a 55 bytes; concatenarlo al prefijo.
7. Concatenar los registros por índice ascendente.

No hay RNG global, red, reloj ni archivos externos en la generación. Las semillas
y etiquetas de dominio son independientes. El encabezado garantiza que no hay
registros iguales entre splits ni dentro de un split. Las distribuciones
comparten gramática y vocabulario deliberadamente; eso no representa una prueba
de transferencia a otra tarea.

## Uso para entrenamiento y validación

Train: cada lote selecciona registros con un `torch.Generator` CPU privado,
sembrado con la semilla del trial. Para cada registro, `x=record[:64]` y
`y=record[1:65]`. La pérdida train usa las 64 predicciones autoregresivas.

Validación: registros completos no solapados, sin ventanas que crucen límites de
registro. El worker solo recibe una copia `record[:64]` por ejemplo, no el byte
`record[64]`. Produce logits float32 `N x 256` del último contexto. El padre
calcula entropía cruzada next-token sobre los targets uint8 privados.

Los patrones repetidos hacen que el siguiente byte sea aprendible a partir del
contexto; repetir el mismo valor de byte dentro de un contexto no es compartir
el array privado de targets. La separación es de registros/ventanas y del flujo
de etiquetas, no de alfabetos disjuntos.

Audit queda reservado: sus bytes se generan para verificar su digest, pero no se
evalúan ni se usan para decisiones en la prueba de Fase 1.

## Identidad congelada

| Split | SHA-256 de sus bytes concatenados |
|---|---|
| train | `3abd85feda06aea7f0dd6b6fc6058a20c039a19af20931b6a46164c59c1833c8` |
| validation | `7970f4f848afb155aeb4b9646d484614349611a5b121ddbd295506a7ad249359` |
| audit | `fa8100de66ae30ee19d50780644df76ae8035c80f999fd5c2c565956c4d93e17` |

Digest conjunto:
`11d89e90478527ba77648d5a45be459c55133e12bb1b4463adf3901cb5d44285`.

Se calcula sobre el objeto de manifiesto sin su campo `sha256`, serializado con
`json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()`. Incluye
spec, hashes/tamaños de splits, tamaño de registro, alfabeto y dominios en hex.
El ejecutor lo recalcula y exige coincidencia con el JSON congelado antes de
entrenar. Toda modificación futura exige nueva identidad de corpus y calibración.
