# Evidencia de Fase 0.1: plataforma CUDA local

> Evidencia histórica TinyGPT anterior al renombrado; nombres, comandos, rutas
> y mediciones originales. La reconstrucción nueva se registra en
> `VALIDACION_RENOMBRADO_GAIA_TRANSFORMER.md`.

Fecha: 15-10-2026. Resultado: **CUDA_ENVIRONMENT_READY**.

## Plataforma y entorno

| Elemento | Resultado |
|---|---|
| CPU | Intel Core i7-4790, 8 hilos lógicos |
| RAM detectada | 15353 MiB |
| GPU | NVIDIA GeForce GTX 1060 6GB, capacidad 6.1 |
| Driver | 580.178.04 |
| Python | CPython 3.14.4, estándar, sin ensurepip |
| Sistema | Linux x86_64, glibc 2.43 |
| Perfil | `tinygpt-cuda-pascal` |
| Contrato | `tinygpt_cuda/v1.1` |
| Runtime | Torch 2.14.0+cu126, NumPy 2.3.5, CUDA 12.6 |
| Cubins Torch | sm_50, sm_60, sm_70, sm_75, sm_80, sm_86, sm_90 |
| Entorno | `.gaia/venvs/tinygpt-cuda-pascal-6661fab15a7e6424/` |
| Configuración | `.gaia/configs/6661fab15a7e6424.json` |
| Estado futuro | `state_tinygpt_cuda_6661fab15a7e6424/` (no creado) |

La cobertura de Pascal 6.1 se consigue mediante el cubin `sm_60`. La comprobación
real de kernels es necesaria además de comprobar esa lista.

- SHA-256 del intérprete resuelto:
  `52e0a13e60a981d8c4b6478be2ba5176f69da07948a056bf49cf6f077e30cb41`.
- SHA-256 del lock:
  `b8cd74c7ba6c4cab32f41e88442789fb040e2cae082338f00bd9e3e128327919`.
- Wheel Torch oficial, SHA-256:
  `b15e1e62ab842d099ae9b19312374f62579668171efed8b676108b60fa75e5b0`.

Virtualenv se aprovisionó desde los artefactos verificados del proyecto y sembró
pip sin sudo. Pip instaló las 30 dependencias fijadas con `--require-hashes` y
`--only-binary=:all:`; `pip check` pasó. La instalación utiliza la caché normal de
pip y las herramientas auxiliares usan la caché del proyecto.

## Pruebas reales

```bash
python3 gaia.py doctor --profile tinygpt-cuda-pascal --preflight
python3 gaia.py bootstrap --profile tinygpt-cuda-pascal
python3 gaia.py doctor --profile tinygpt-cuda-pascal
python3 gaia.py selftest
```

El probe ejecutó matmul fp32, layer norm, GELU, entropía cruzada, backward y tres
actualizaciones de pesos en CUDA. Sincronizó antes/después de medir, comprobó
gradientes finitos, repitió semilla y distinguió otra semilla. No es TinyGPT.

- Flags: algoritmos deterministas activos, `CUBLAS_WORKSPACE_CONFIG=:4096:8`,
  TF32 y autotuning desactivados, cuDNN determinista, una GPU visible por UUID.
- Salidas, pérdidas y hashes de los tres gradientes **idénticos** entre proceso
  normal y dos procesos aislados `-I` con entorno mínimo.
- Hash SHA-256 de salida con semilla 123:
  `d0cf7ff3fc4b8e485d17599a4db4718d092d1b3610fe7e054623d0a6a841651e`.
- Pérdidas observadas: 4.5034666061, 4.5028524399, 4.5022377968.
- Pico RSS máximo de los tres probes: 1080.1 MiB.
- Pico de VRAM **reservada por el allocator Torch**: 66 MiB. No representa toda
  la VRAM del proceso (contexto/driver/bibliotecas); la supervisión total del trial
  pertenece al laboratorio de Fase 2.
- Límites locales iniciales: 3000 MiB RSS y 3000 MiB VRAM.
- `doctor` posterior reutilizó el entorno, sin crear venv ni instalar paquetes.
- Suite completa: **67 pruebas OK**, incluidas reglas de compatibilidad,
  selección multigpu, flags, diferencias de runtime y rechazo de campañas futuras.

Se corrigió durante la validación una diferencia de representación del UUID:
`nvidia-smi` incluye el prefijo `GPU-`, mientras Torch entrega el UUID sin él.
La comparación normaliza ese prefijo y dispone de una prueba de regresión.

## Informes locales completos

- Instalación y validación final:
  `.gaia/reports/20261015T153657Z-0f906ddc/REPORT.md`.
- Diagnóstico de reutilización:
  `.gaia/reports/20261015T154103Z-e469a5dd/REPORT.md`.
- Suite completa:
  `.gaia/reports/20261015T153827Z-a89ee126/REPORT.md`.

Cada directorio incluye JSON, stdout/stderr por etapa e inventario completo.
Estos archivos son evidencia local; este resumen conserva los resultados aunque
no se distribuyan los entornos ni los logs de `.gaia/`.

## Siguiente criterio

La Fase 1 puede comenzar usando este perfil. Quedan pendientes el corpus y su
digest, TinyGPT entrenable y reproducible, la evaluación privada, el laboratorio
GPU y sus puertas G0-G5. No se han inicializado campañas TinyGPT ni reutilizado
resultados CPU para demostrar entrenamiento GPU.
