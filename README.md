# GAIA — automejora computacional verificable

GAIA propone variantes de un entrenador, las evalúa bajo supervisión independiente
y publica únicamente mejoras verificadas. El workload activo de v0.1 es
`numpy_mlp`: una tarea sintética local en CPU con NumPy.

## Estado actual

**GAIA v0.1 CPU autonomous MVP certificado.** La Prueba A certificó el pipeline
end-to-end; la Prueba B observó una promoción autónoma real de origen `search`,
con **46,90 % de mejora** según su informe, recarga y rollback verificados.
La consolidación 0.1.1 conserva ese comportamiento, sin ampliar capacidades.

### Qué está certificado

- Procedencia local mediante snapshots inmutables y SHA-256; **Git no es una
  dependencia del runtime**.
- Candidatos CPU dentro de **bwrap obligatorio**, con handshake verificado,
  namespaces, bundle de solo lectura y límites. No existe fallback certificable
  a ejecución directa.
- Manifiestos de entorno, gates G0–G5, confirmación estadística y evidencia.
- Evaluación y promoción separadas: un resultado aceptado no publica por sí solo.
- Publicación transaccional, ledger encadenado y versiones recuperables mediante
  rollback explícito y durable. `--skip-gate` y `--force` son errores en MVP;
  no permiten saltarse gates ni forzar promociones.

La certificación es local, para este workload y entorno; no acredita descubrimiento
de técnicas nuevas ni automejora universal. Véase [la evidencia](docs/EVIDENCE_V0_1.md).

### Qué no está implementado como capacidad de v0.1

GAIA 0.2 y su propuesta de Self Observation no están implementadas. El perfilado
interno existente no es esa capacidad futura. No hay integración LLM ni Internet
en los trials CPU; el bootstrap puede descargar dependencias al provisionar un
entorno. No hay appliance física/instalador finalizados.

## Componentes congelados

- **GPU — FROZEN:** workload CUDA separado. No tiene todas las garantías del CPU
  MVP y no debe presentarse como una certificación equivalente.
- **Appliance — FROZEN:** construcción/VM históricas; validación física e
  instalador pendientes. El checkpoint conservado rige cualquier reanudación.
- **Estudio Modo B MLP — HISTORICAL_STUDY:** comparación histórica inconcluyente;
  no es el pipeline vigente. El Research Engine CPU existente sigue formando
  parte del código, sin revisión funcional en esta consolidación.

Detalle: [estado de componentes congelados](docs/STATUS_FROZEN_COMPONENTS.md).

## Cómo ejecutar CPU

Se requieren Linux, Python/NumPy compatibles y bwrap funcional. El arranque
gestionado selecciona entorno y estado por perfil/huella; `--no-bootstrap`
selecciona el Python y la configuración manuales. `gaia.json` es opcional.

```bash
python3 gaia.py prepare
python3 gaia.py run
python3 gaia.py status
python3 gaia.py report
python3 gaia.py audit
python3 gaia.py rollback --to v0000 --reason "Motivo explícito del operador"
```

`report` escribe `REPORT.md`; `audit` ejecuta mediciones adicionales y guarda
resultados: ninguno es un verificador histórico estrictamente de lectura.
`run` se detiene en la primera mejora salvo `--keep-going`, o al agotar presupuesto,
recibir STOP o necesitar intervención.

Los estados legacy no se migran: quedan bloqueados para campañas certificables.
Para una baseline nueva, elegir un `workload.state_dir` nuevo y vacío en la
configuración manual y ejecutar explícitamente:

```bash
python3 gaia.py --no-bootstrap prepare --initialize-mvp
```

`--refreeze` no permite adoptar fuentes modificadas bajo un snapshot antiguo.
Cambios críticos requieren otra línea experimental, conservando la anterior.

Entradas explícitas de certificación, **no necesarias para verificar los archivos
históricos**; cada invocación crea un estado nuevo y ejecuta trabajo real:

```bash
python3 gaia.py certify-pipeline        # Prueba A: pipeline controlado, no autonomía
python3 gaia.py verify-autonomous-mvp   # Prueba B: una campaña normal y verificación
```

No ejecutarlas como parte de una limpieza. [BOOTSTRAP](docs/BOOTSTRAP.md) conserva
la referencia de aprovisionamiento; sus apartados GPU/appliance son congelados.

## Estructura básica

```text
gaia.py                  Dispatcher / CLI
gaia/                    Engine CPU, evolución, evidencia y persistencia
gaia/protected/          Evaluación, benchmark, worker y sandbox CPU
gaia/gaia_transformer/   GPU congelado
gaia/appliance_*         Appliance y payload congelados
tests/                   Suites CPU, GPU y appliance
docs/                    Arquitectura, evidencia, políticas e histórico
tools/                   Herramientas administrativas/históricas
.gaia/, state*/          Runtime local; fuera del futuro commit
```

## Tests

La suite usa `unittest`. Ejecutar con un entorno local ya provisionado; evitar
bootstrap y bytecode nuevo durante consolidación:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -W error::ResourceWarning -m unittest discover -s tests
```

**Atención:** el test
`test_certification.RealCertificationTests.test_real_unmocked_cli_certifies_pipeline_only_and_preserves_normal_state`
lanza una Prueba A real en un directorio temporal. El runner administrativo de
consolidación debe omitirlo explícitamente cuando estén prohibidas nuevas A/B.
Los tests GPU pueden requerir Torch/CUDA y declarar skips: deben registrarse.

**Current consolidation validation: 406 tests** (20-10-2026): 405 ejecutados y
1 skip explícito por la prohibición de una nueva Prueba A real; 0 fallos,
0 errores y 0 ResourceWarnings, con `-W error::ResourceWarning`. Suite crítica:
171 contabilizados, 170 ejecutados y el mismo skip. La suite completa usó el
venv Torch/CUDA existente, sin skips por dependencias GPU. Estos resultados no
son una nueva certificación A/B. Informes y motivo exacto del skip en el archivo
externo, bajo `manifests/step3/{critical,full}.result.json`.

## Documentación

- [Arquitectura v0.1](docs/ARCHITECTURE_V0_1.md)
- [Evidencia y hashes del hito](docs/EVIDENCE_V0_1.md)
- [Componentes congelados](docs/STATUS_FROZEN_COMPONENTS.md)
- [Índice histórico y clasificación documental](docs/HISTORICAL_INDEX.md)
- [Política source/runtime/evidencia](docs/CONSOLIDATION_POLICY.md)
