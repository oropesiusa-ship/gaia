# GAIA 0.2 — System Observation & Capability Profiling

## Resultado y alcance

**PASS**, 20 de octubre de 2026. GAIA puede observar y caracterizar de forma
estructurada su entorno y funcionamiento. Esto no demuestra que entienda por qué
funciona así, que sepa qué mejorar ni que haya incrementado su inteligencia.

Autoridad conceptual: [Documento Maestro v3.0](GAIA_MASTER_ARCHITECTURE_V3.md).
El texto proporcionado se conservó íntegro después de la sección inicial de estado.
Una mejora del trainer CPU no constituye una mejora demostrada de la inteligencia general de GAIA.

- Rama: `feat/gaia-0.2-self-observation`.
- Base común con `main`: `b5f1e6d43071e50f84e14684a486a330a5e9125c`.
- Es también el commit al que apunta `gaia-v0.1-autonomous-mvp` (tag anotado).
- Commit observado en las evidencias finales: `9a67e9358972d21e07380aa886309629ee95ffb7`.
- No se realizó merge ni se abrió PR.
- El único archivo previo sin seguimiento era el Documento Maestro aportado.
  Se incorporó como primer commit, sin descartar trabajo previo.

## Arquitectura y autoridad

Subsistema independiente `gaia/observation/`:

| Módulo | Responsabilidad |
| --- | --- |
| `schema.py` | Envelope, JSON canónico, validación y SHA-256 |
| `local.py` | Lecturas locales y comandos acotados con entorno allowlist |
| `host.py` | CPU, RAM, OS, filesystem y afinidad |
| `runtime.py` | Python, dependencias, BLAS/LAPACK, bwrap, Git e identidades |
| `gpu.py` | DRM/sysfs, nvidia-smi y detección local de bibliotecas |
| `components.py` | Registry explícito de once componentes |
| `capabilities.py` | Estados, condiciones y evidencia de disponibilidad |
| `resources.py` | Muestreo del observador y del sistema |
| `workload.py` | Protocolo fijo numpy_mlp mediante evaluador protegido |
| `stability.py` | Estadística descriptiva y estados de estabilidad |
| `store.py` | Historial inmutable y referencia de baseline independiente |
| `compare.py` | Diferencias factuales y significancia descriptiva |
| `collector.py` | Composición, coste y fallos no fatales |
| `report.py`, `cli.py` | Resumen humano e interfaz explícita offline |

No se instancia Engine desde observation. No se ejecuta `Strategy.propose()`,
no se crean candidatos de mejora y no existe ruta de promoción, rollback,
edición de configuración o cambios de hardware. La medición reutiliza
`genome.BASELINE`, `genome.render` y `protected.evaluator.run_trial` sin alterar
su implementación. Los únicos efectos son almacenamiento de observaciones,
referencia de baseline y archivos temporales propios de la ejecución protegida.

## Schema e identidad

`schema = "gaia_system_observation_v1"`; collector `0.2.0`.

Campos: `observation_id`, `schema`, `timestamp` UTC con timezone,
`source_identity`, `host_identity`, `runtime_identity`, `environment_identity`,
`collector_version`, `sections`, `evidence_hashes`, `observation_hash`.

Las secciones son exactamente `facts`, `measurements`, `capabilities`, `context`.
Cada sección tiene SHA-256 de su JSON canónico; el hash global cubre todo salvo
su propio campo. Se rechazan schema desconocido, campos obligatorios ausentes,
identificadores inválidos, NaN, evidencia modificada y hashes incoherentes.

La identidad de fuente reutiliza `provenance.inventory` y `aggregate_hash`;
añade un hash que cubre también los módulos de observation y un hash protegido.
La identidad runtime reutiliza `manifest.runtime_identity` cuando NumPy está
disponible, con fallback stdlib. Se identifican ejecutable por hash, ABI,
versiones, backends declarados y bundle protegido. No se reutiliza manifest como
base de datos. Git es metadata informativa: repo, branch, commit y dirty, nunca
credenciales/remotos; su ausencia no impide observar.

RAM libre, utilización, carga, RSS, VRAM disponible, timestamps y duración están
separados de los hechos estables. El perfil GPU estable no incluye VRAM libre.
Hay hashes de host, runtime, fuente y cada componente. No se guarda machine-id.

## Collectors e inventario

- CPU: vendor/modelo, arquitectura, núcleos físicos/lógicos, afinidad efectiva,
  intersección de flags visibles, cachés de CPU0 y frecuencias sysfs en kHz.
- RAM: total, páginas, swap total; RAM/swap disponibles en mediciones.
- Storage: tipo y tamaño de filesystem, espacio libre/disponible, igualdad de
  filesystem source/state y source/archive. No se almacenan mountpoints personales.
- OS: sistema, kernel, distro ID/version, libc y arquitectura.
- GPU: detección tolerante; NVIDIA registra modelo, cantidad, VRAM, driver y
  compute capability. Detección local CUDA/NVML independiente de Torch.
- Runtime: Python 3.14.4, ABI y ejecutable identificado; NumPy 2.3.5, BLAS/LAPACK
  declarados, versiones opcionales Torch/psutil y smoke de namespaces bwrap.
- Componentes: core, CPU evolution, protected evaluator, sandbox,
  manifest/provenance, ledger, publication, rollback, GPU, appliance y observation;
  cada entrada tiene categoría, estado, paths relativos, hashes, dependencias y scope.

Los estados de capability son `AVAILABLE`, `UNAVAILABLE`, `FROZEN`,
`NOT_CONFIGURED`, `UNKNOWN`. Código presente no equivale a certificación.
`cpu_campaign_available=AVAILABLE` expresa prerrequisitos técnicos observados;
`current_campaign_certified=false` y las condiciones exigen G0–G5 separados.
GPU y appliance siguen FROZEN y `certified_equivalent_to_cpu=false`.
Torch CUDA queda UNKNOWN sin importar Torch ni lanzar cómputo GPU. LLM queda
NOT_CONFIGURED para esta integración e Internet UNKNOWN/no probado.

## Sampling, workload y estabilidad

Se registran wall time, CPU del observador, RSS, peak RSS de vida del proceso,
RAM/swap disponibles, CPU del sistema por deltas `/proc/stat`, utilización CPU
del observador, filesystem libre y load average. El primer intervalo CPU no tiene
una medida de utilización válida. El scope del proceso y del sistema es explícito.

Protocolo `numpy_mlp_observation_v1`: benchmark existente `easy`, tarea `main`,
trainer baseline sin modificar, semillas data/init 9000, 300 batches fijos y
target 2.0 para medir el recorrido completo, sin parada por calidad. No es una
medición certificada de coste hasta objetivo ni una comparación de candidatos.

Cada repetición ejecuta el evaluador en un proceso separado; su worker usa el
mismo bwrap obligatorio, namespaces, handshake, entorno y límites de v0.1.
No existe fallback fuera de bwrap. Se guardan éxito/fallo, batches, calidad,
wall/train/eval/init, peak RSS, CPU del evaluador e identidad de entorno.
Durante el trial se muestrean descendientes cada 10 ms (CPU/RSS) y RAM del sistema.
La CPU de descendientes es una **cota inferior muestreada** de `/proc`, no una
medición exacta de CPU del worker ni el rusage del launcher bwrap.

Estadísticos: samples, count, mean, median, min/max, desviación estándar muestral
y CV. Mínimo 3 muestras; CV ≤ 0,10: STABLE; por encima: NOISY; sin muestras
suficientes o CV definido: INSUFFICIENT_DATA. No se elimina ruido para lograr PASS.

## Store, historial y comparación

Ubicación: `<state>/observations/oNNNNNN.json`; la store de certificación local es
`state_observation_final/observations/`. No se escribe ledger evolutivo,
stable versions, CURRENT ni experiments. La store usa lock flock, staging local,
fsync, permisos 0444 y hard-link atómico create-only (EEXIST si ya existe).
La lectura verifica schema, hashes, canonicalidad e identidad del archivo.
Se rechazan traversal y symlinks de observación. Archivos staging incompletos no
son observaciones visibles. Los permisos previenen escrituras accidentales;
los hashes detectan corrupción, no constituyen firma contra un propietario hostil.

Hay listado cronológico por secuencia, lectura por id/latest y baseline.
`baseline.json` referencia id/hash con creación atómica única: es la baseline de
**observación**, independiente de la baseline **evolutiva** v0.1.

La comparación indica campos añadidos/eliminados/cambiados, cambios de identidad,
capabilities y métricas. Para repetidas exige al menos 3 muestras en ambos lados,
mediana inicial distinta de cero y protocolos workload iguales. Un cambio es
POSSIBLY_SIGNIFICANT si supera simultáneamente 15 % relativo y dos desviaciones
estándar (la mayor de ambas series). El resto es WITHIN_NOISE o
INSUFFICIENT_DATA. Es una regla descriptiva conservadora, no causalidad ni test
estadístico avanzado. WITHIN_NOISE significa que no supera esa regla, no prueba
de equivalencia. No se atribuyen causas a los cambios.

## Privacidad, fallos y coste

Allowlist explícita de campos. No se captura username, hostname, IP, MAC,
machine-id, secretos, entorno completo, claves SSH, remotos Git o rutas personales.
Los comandos auxiliares reciben solamente PATH, LC_ALL y HOME no personal.
Errores persisten collector, clase/código de causa y `nonfatal=true`, sin stderr,
tracebacks ni mensajes con rutas. La ausencia de GPU, NVML, Torch o NumPy no
impide la observación quick. Un collector opcional que falla no bloquea CPU/host.
La fuente local es crítica; una identidad de fuente ilegible no se certifica.

`observe` retorna éxito cuando se registra la observación; hay que inspeccionar
el estado de workload para afirmar éxito de la medición. Registrar un fallo no
lo convierte en un workload exitoso. La certificación exige cinco trials válidos.

La configuración `observation` tiene quick_samples=3, full_samples=5,
sample_interval_ms=100, stability_cv_threshold=0.10,
significant_relative_change=0.15, include_workload=true, max_duration_seconds=60.
Se validan rangos. El presupuesto acota sampling/trials; collectors locales tienen
timeouts propios y cleanup puede añadir sobrecoste al límite. Se registra coste
total de colección, sampling y workload (sin incluir impresión/fsync posterior).
Sin dependencias nuevas de monitorización; psutil sólo se inventaría si existe.

## Observaciones reales finales

Evidencia canónica final en [observation_evidence/final/](observation_evidence/final/).
La primera revisión auditada se conserva en el directorio padre, con su propia
identidad y log, anterior a incorporar el campo de espacio disponible de filesystem.
Se ejecutó CLI real, sin mocks, desde un entorno local con el wheel NumPy 2.3.5
archivado y sin descargas. El Python del sistema también ejecutó quick sin NumPy.

Host: Intel Core i7-4790 @ 3.60 GHz, 4 cores físicos/8 lógicos, 14,99 GiB RAM;
GPU NVIDIA GeForce GTX 1060 6GB, VRAM total 6144 MiB, driver 580.178.04,
compute capability 6.1. Python 3.14.4, NumPy 2.3.5; bwrap presente y verificado.

| Medida | o000001 quick/baseline | o000002 full | o000003 full |
| --- | ---: | ---: | ---: |
| Duración colección (s) | 0,375820 | 3,774217 | 3,787694 |
| Sampling (s) | 0,207382 | 0,408495 | 0,410547 |
| Workload total (s) | no ejecutado | 3,189470 | 3,210815 |
| Trials exitosos | no ejecutado | 5/5 | 5/5 |
| Wall mediano por trial (s) | — | 0,469623 | 0,472447 |
| CV wall / estado | — | 2,39 % / STABLE | 1,30 % / STABLE |
| Train mediano (s) | — | 0,092982 | 0,094822 |
| Calidad mediana | — | 0,5816 | 0,5816 |
| Peak RSS mediano (MiB) | — | 66,7734 | 66,7266 |
| CPU descendientes, cota inferior (s) | — | 0,27 | 0,27 |

Todas las métricas workload finales son STABLE. Utilización CPU del sistema:
NOISY en ambos full. La revisión anterior conserva también una medición de CPU
del evaluador clasificada NOISY (CV 12,67 %); no se eliminó esa evidencia.
La quick tiene sólo dos intervalos CPU válidos: INSUFFICIENT_DATA para utilización.

Comparación full A/B: hardware/runtime/source/capabilities sin cambios; wall
mediano +0,6014 %, train +1,9793 %, calidad sin cambio. Todas las métricas
comparadas quedan WITHIN_NOISE; no se diagnostica el motivo.

Hashes de observación:

```text
o000001 b4da1028174819c5e4090596500f8a7c9db30998a2f525dbe4b6b1a8692df435
o000002 bca2afe79e714b480af2b2e2f5289a0dc9811957bf5402471814366dc9e461fe
o000003 f301fc00910147bf0e6d2944e36c5e57cd09d3645cc1d7a13e5af7557529e8a1
```

Hubo una ejecución exploratoria fallida con el intérprete en `/tmp`: el sandbox
oculta esa ruta deliberadamente. Se conservó el fallo como observación no fatal;
se resolvió alojando el entorno de validación en `.venv-observation/`, sin relajar
el sandbox. Estas pruebas previas están en otra store, no en las evidencias finales.

## CLI y reproducción

Usar un Python local existente; estos comandos nunca aprovisionan un runtime:

```sh
python gaia.py observe --quick --baseline --state-dir state_observation
python gaia.py observe --state-dir state_observation
python gaia.py observations --state-dir state_observation
python gaia.py observation latest --state-dir state_observation
python gaia.py observation baseline --state-dir state_observation
python gaia.py compare-observations o000001 o000002 --state-dir state_observation
```

Todos aceptan `--json`. Sin `--state-dir`, se utiliza el state configurado y
exclusivamente su subdirectorio `observations/`. El resumen humano incluye host,
runtime, resources, capabilities, components, workload, stability, coste y cambios.

`tools/audit_observation.py` reproduce quick + dos full en una store nueva,
exporta observaciones canónicas y comparación, valida privacidad y baseline,
y audita v0.1 frente al tag. Requiere un log completo de unittest y destinos
nuevos; nunca sobrescribe evidencias. Git es necesario sólo para esta auditoría
de desarrollo, no para el subsistema de observación.

## Tests y auditoría de no regresión

```sh
.venv-observation/bin/python -W error::ResourceWarning -m unittest discover -s tests -p test_observation.py -v
.venv-observation/bin/python -m unittest discover -s tests -v
```

- 34 tests nuevos: schema/hashes, privacidad, collectors, capacidades, store,
  atomicidad y concurrencia, sampling, estabilidad, comparación, fallos y CLI real.
- Suite completa final: **440 tests**, **9 skips**, **0 warnings**, **1159,722 s**.
  La revisión anterior también pasó la suite completa (1162,951 s).
- Skips: tests GPU/modelo existentes por Torch ausente en el perfil NumPy.
- Incluye Prueba A real y contratos de Prueba B, G0–G5, sandbox, identidad,
  ledger, publicación y rollback. No se inició una nueva Prueba B autónoma.
  Los tests heredados usan sus estados aislados; observation no lanza campañas.
- Auditoría: 326 de los 328 archivos originales idénticos byte a byte.
  Sólo `gaia.py` (+5 líneas de dispatch) y `gaia/config.py` (+5 líneas de defaults
  observation) cambian entre los archivos preexistentes.
- Ocho archivos protegidos y 66 archivos frozen idénticos.
- Defaults evolutivos y `experimental_config` idénticos a v0.1.
- Hash del log completo y detalles en [audit.json](observation_evidence/final/audit.json).
- `git diff --check` limpio; secretos/rutas personales ausentes en los exports.

## Limitaciones y alcance certificado

Certificado aquí: autoperfilado local Linux real, hardware/runtime verificables,
inventario explícito, capacidades condicionadas, recursos, workload protegido,
repetición/estabilidad, historial, comparación, privacidad y tolerancia opcional.
El sistema expone incertidumbre y ruido en lugar de inferir causalidad.

Interfaces `/proc`, sysfs, flock y bwrap son Linux; otros OS pueden tener campos
no disponibles y no se certifican como plataformas de ejecución en esta etapa.
La topología refleja lo visible al proceso, no garantiza descubrir recursos
ocultos de contenedores ni certifica cuotas cgroup. RSS del observador y peak RSS
del worker tienen scopes distintos. El monitor introduce sobrecoste; sus tiempos
son observacionales, no sustituyen los benchmarks de promoción v0.1. La detección
CUDA/NVML por biblioteca puede no encontrar bibliotecas fuera del loader local;
UNKNOWN no significa ausencia comprobada. Torch y ejecución GPU no se probaron.
No hay inferencia estadística avanzada, equivalencia formal ni atribución causal.

No implementado: diagnosis, target selection, recommendations, LLM, Internet,
auto-modification. Los componentes GPU/appliance conservan sus contratos frozen.

Siguiente etapa propuesta: **GAIA 0.3 — Diagnosis & Bottleneck Attribution**.
