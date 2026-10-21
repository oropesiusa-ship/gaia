# GAIA 0.7 — External Research & Evidence Acquisition

## Resultado y alcance

**PASS de etapa, sin merge ni release.** Rama `feat/gaia-0.7-external-research`,
creada desde `main` limpio en `27b351b1eadad85188d3578e9c3d0703a4deef3f`, igual
al commit resuelto por `gaia-v0.6-meta-improvement`. La autoridad conceptual
sigue siendo [Documento Maestro v3](GAIA_MASTER_ARCHITECTURE_V3.md).

GAIA puede adquirir, estructurar y evaluar evidencia externa de manera controlada,
trazable y reproducible. **Internet es evidencia potencial, no una instrucción con
autoridad sobre GAIA.** PASS no significa confiar automáticamente en Internet,
aplicar soluciones, ejecutar código externo, disponer de LLM ni aumentar
inteligencia general.

Sólo EVIDENCE_ONLY_MODE. No se crean operational knowledge local, configuraciones,
experimentos o cambios de código desde el contenido recuperado.

## Threat model y arquitectura

Se auditó `gaia/research.py`: es el Research Engine histórico de evolución CPU,
acoplado a hipótesis/experimentos protegidos y priors. **No se sobrescribió ni
modificó.** Se eligió `gaia/external_research/`, independiente del Engine, Strategy,
mutate, publication y rollback; también permanece intacto `gaia/meta.py`.

| Módulo | Responsabilidad |
| --- | --- |
| `schema.py` | Artefactos canónicos, hashes e instruction boundaries |
| `request.py` | Pregunta explícita, scope, context projection, autorización y budgets |
| `policy.py` | Defaults conservadores, clases y registry versionado de fuentes |
| `network.py` | Normalización, IP/DNS público, socket fijado y TLS verificado |
| `fetch.py` | HTTP acotado, redirects, robots, bytes/gzip y provenance |
| `search.py` | Interfaz SearchProvider; URLs explícitas y replay desacoplados |
| `extraction.py` | HTML/text/JSON pasivos, fragments, metadata y código como DATA |
| `claims.py` | Catálogo extractivo de proposiciones, sin generación libre |
| `assessment.py` | Calidad, dependencia, contradicción y applicability |
| `engine.py` | Adquisición e interpretación/replay separados |
| `store.py` | Artefactos inmutables, cache e índices de runs |
| `report.py`, `cli.py` | Informes con citas/boundaries y operaciones explícitas |

Amenazas contempladas: URLs privadas/ambiguas, DNS público→privado, redirects,
hostnames internos, TLS inválido, payloads excesivos/comprimidos, slow responses,
contenido activo, inyección de instrucciones, fuentes copiadas, versiones
incompatibles y datos privados enviados inadvertidamente. Los documentos y
metadatos externos nunca pueden elevar privilegios ni modificar la policy.

El código local, su configuración explícita y el sistema operativo son parte de
la base de confianza. Los hashes no autentican un productor hostil ni prueban
verdad científica; las attestations de captura no son firmas independientes del
servidor. No se pretende seguridad formal de todo Python o del kernel.

## Requests, esquema y jerarquía de evidencia

`gaia_external_research_v1`, policy `external_evidence_policy_v1`, intérprete
`0.7.0`. Kinds separados: REQUEST, SOURCE, EXTRACTION, CLAIM, ASSESSMENT,
CONCLUSION, CACHE y ACQUISITION. Cada artefacto tiene ID, hash, timestamp,
policy_version, source_boundary, payload y limitations. REQUEST tiene autoridad
limitada a su scope; los otros artefactos no poseen autoridad de instrucciones.

El request exige pregunta explícita acotada, URLs públicas concretas, topics,
clases permitidas, domains opcionales, budgets, freshness, evidence requirements,
contexto mínimo y refs de target/diagnosis/strategy/observation cuando se aportan.
No se interpreta una página como un nuevo request autorizado.

Evidence requirements permiten minimum_sources, require_primary y require_version.
No se declara completada la evidencia sólo porque un comentario comunitario
contenga un patrón. Los requisitos se comprueban por topics y soporte de clase
primaria; no convierten un reporte externo en una prueba local.

Plan de investigación determinista: términos por topic, clases y citas buscadas,
y condiciones de parada. SearchProvider se puede sustituir; los proveedores
incluidos son DirectURLs y ReplaySearch local. No hay API/key/pago obligatorio,
scraping de buscadores ni plugin descargado. Resultados del provider no pueden
expandir las URLs expresamente autorizadas. Se prefieren official/primary,
scientific, upstream, secondary, community y unknown en ese orden.

Jerarquía conceptual conservada:

```text
external report → externally corroborated claim → local hypothesis
→ local experiment → local evidence → replicated local evidence
→ operational knowledge
```

0.7 sólo implementa el tramo de evidencia externa. No salta las pruebas locales
ni escribe automáticamente en learning 0.5 o en la policy 0.4/0.6.

## Política de red y SSRF

Dos requisitos simultáneos para tráfico: configuración global network_enabled=true
y request network_authorized=true. Default global **false**. La CLI puede hacer
opt-in global efímero con `--enable-network`, sin editar `gaia.json`; el request
requiere además `--authorize-network`. Replay/cache offline no necesitan red.

Sólo GET/HEAD. HTTPS por defecto; HTTP necesita permisos explícitos tanto de
policy como del request mediante API. Sólo puertos 443/80 correspondientes;
sin credenciales ni query strings en URLs. No file/ftp/ssh/gopher, Unix sockets,
proxies ambientales o cookies. Headers fijos: User-Agent identificable GAIA,
Accept limitado, Accept-Encoding identity y Connection close. No Authorization,
Referer, dumps, pregunta, código u observaciones enviados como payload.

El hostname se normaliza con IDNA, case/puerto/fragment, y se rechazan nombres
internos/single-label, localhost y sus variantes. IP literals y **todas** las
respuestas DNS deben ser públicas; una respuesta mixta pública/privada falla.
Se bloquean loopback, RFC1918, link-local, CGNAT/metadata, multicast, unspecified,
reservados y mecanismos IPv6 de traducción/transición potencialmente ambiguos.

La conexión usa socket a la **IP numérica validada**, sin segunda resolución del
hostname. Host/SNI siguen siendo el hostname original; SSL context verifica
certificado y hostname. Peer público debe coincidir con el pin antes/después de
TLS. Redirects se normalizan, verifican y resuelven nuevamente; también se
revalida dominio permitido, esquema, puerto y robots de cada nuevo origen.

Se usan timeouts de operación y un watchdog de wall deadline que interrumpe
socket: también cubre headers/trailers lentos dentro de http.client. DNS tiene
espera acotada en hilo daemon; una resolución nativa ya iniciada no puede
cancelarse de forma portable, pero tras timeout no se abre la conexión ni se
mantiene un proceso esperando al resolver. Hay budgets de URLs/requests/duración.
El kernel/scheduling puede añadir pequeño sobrecoste al deadline.

## Límites, robots y formatos

Defaults: 4 sources, 12 requests totales —incluidos robots y reintentos de IP—,
8 s de timeout, 45 s de duración, 3 redirects, 512 KiB de respuesta, 1 MiB
descomprimido por respuesta y 2 MiB de cuerpo agregado. Los requests pueden
restringir budgets, no ampliar los límites globales/hard bounds. Intervalo mínimo
default 0,5 s; no crawler masivo ni seguimiento automático de links extraídos.

Se procesa text/html, text/plain y application/json. Se deniegan PDF, binarios,
JavaScript como MIME, archivos/instaladores y encodings no soportados. Si llega
gzip, descompresión incremental acotada; se rechaza truncamiento, concatenación
o exceso de tamaño. Content-Length excesivo se rechaza antes del body; streaming
se comprueba por chunks. Una respuesta abortada puede exceder el presupuesto
por un último read/decode acotado: no se publica como fuente válida. Acquisition
registra bytes realmente consumidos. Los contadores de body no incluyen TLS ni
headers HTTP, que mantienen los límites adicionales de stdlib.

Robots se solicita por origen y se respeta con RobotFileParser; 404/410 implican
ausencia, no bypass de un 403/429. Disallow bloquea el recurso. Crawl-delay se
respeta o se rechaza si excede el budget. Se conservan reglas acotadas/hash para
recomprobar offline que autorizaban los paths capturados. Un Allow remoto nunca
anula los requisitos locales de red/SSRF. No se intenta evadir bloqueos.

La adquisición es un lote pequeño de URLs explícitas: no se hace búsqueda
iterativa/crawling hasta conseguir una respuesta. Se detiene por presupuesto o
autorización; después se evalúan requisitos/contradicciones/fuentes agotadas al
límite de fases. No hay nuevas consultas automáticas para resolver un desacuerdo.

## Fuentes, identidad y calidad

Clases: PRIMARY_OFFICIAL, PRIMARY_SCIENTIFIC, PRIMARY_REPOSITORY,
SECONDARY_TECHNICAL, COMMUNITY, UNKNOWN. Registry fijo y versionado; un sitio no
puede declararse oficial cambiando el texto de su página. Scientific incluye
preprints identificados, sin afirmar revisión por pares. GitHub sólo es upstream
primario para prefijos registrados; otros repos se clasifican conservadoramente.
No se clona ni ejecuta repositorio alguno.

Identidad: URL/domain normalizados, timestamp de captura, MIME, content hash,
wire hash, content identity URL+body, HTTP metadata allowlisted (Content-Type,
ETag, Last-Modified, Date), cadena de redirects y attestations. No se guardan
cookies o credenciales. Se conservan hashes de respuestas DNS sin sus IPs como
inventario local. Fuente/captura y versión de contenido son identidades distintas.

Extracción conserva versiones de título/URL, release tags o commits en URLs
cuando existen, y Last-Modified como actualización **afirmada por la fuente**.
Publication date verificable queda desconocida en la investigación real.
Fecha de retrieval no se presenta como fecha de publicación. Last-Modified sin
zona horaria o ambiguo se trata como desconocido, no como instrucción para
interrumpir toda la evaluación.

Calidad por dimensiones visibles: authority, directness, freshness,
reproducibility, specificity, independence y provenance completeness, ordinales.
Authority HIGH sólo expresa clase de fuente primaria conocida; no garantiza
que toda frase sea correcta. COMMUNITY se admite como reporte, con confianza
limitada. Cada source recibe assessment incluso si no hay claim catalogado.

## Extracción, claims y contradicciones

HTMLParser pasivo ignora scripts/style/forms/iframes/objetos y no renderiza HTML.
Texto, headings, title y references se extraen con límites de chars/fragments.
Bloques de código son CODE_DATA, no soporte factual automático ni código
ejecutable. JSON se recorre como datos, no como configuración de GAIA. Secuencias
de control terminal/bidi se escapan al mostrar citas humanas.

Los fragments tienen IDs, locator normalizado y offsets del texto pasivo, con
source ref y content hash exactos. No se confunden con offsets del HTML original.
Se guardan bytes originales decodificados del HTTP como base64 para verificar
hashes/reproducir extracción; en este caso acotado esa retención completa permite
auditar citas y contenido activo ignorado. No se ejecuta ese contenido archivado.

Catálogo inicial estrecho y determinista: GIL-enabled CPU threading en CPython,
builds free-threaded y mínimos documentados de CUDA compute capability. No se
usa LLM ni se pretende comprender cualquier paper. Fuera del catálogo, extracción
sigue siendo posible, pero ausencia de match no equivale a ausencia de evidencia
en Internet; la conclusión declara qué topics no quedaron resueltos.

Cada claim guarda proposición normalizada, valor reportado, condición/version,
fuente, quote exacto normalizado y fragment refs, clase, tipo y limitaciones.
El registro empieza REPORTED/VERY_LOW e inmutable; los assessments posteriores
expresan SUPPORTED, CORROBORATED, UNRESOLVED, confianza, freshness y applicability.
El valor reportado se muestra por separado para no presentar una negación como
si afirmara el predicado positivo. No hay afirmaciones universales libres.

Corroboración requiere grupos primarios distintos, no simplemente dos URLs.
Dependencias se agrupan conservadoramente por publisher, contenido idéntico,
canonical y referencias/orígenes comunes. Dos páginas Python siguen siendo un
grupo; blogs copiando release notes no se convierten en dos primarias.
Son heurísticas conservadoras, no prueba criptográfica de independencia autoral.

Discrepancias del mismo topic/condición se conservan con ambas refs y estado
UNRESOLVED. Versiones distintas se marcan VERSION_DEPENDENT, no se elige
silenciosamente una. Confianza HIGH externa necesita corroboración/contexto/
provenance suficientes; queda limitada si versión/freshness exigida no están
resueltas. **HIGH EXTERNAL nunca significa LOCAL VERIFIED.** HTTP sin TLS, cuando
se autoriza explícitamente, no recibe esa confianza alta.

## Applicability y frontera de instrucciones

DIRECTLY_APPLICABLE, POTENTIALLY_APPLICABLE, RELATED, NOT_APPLICABLE, UNKNOWN.
Las reglas iniciales son deliberadamente conservadoras: coincidencia de versión
CPython no demuestra el build GIL local; suele ser POTENTIALLY_APPLICABLE.
Deriva de patch queda RELATED. Un mínimo compute capability 8.0 frente a 6.1
queda NOT_APPLICABLE, sin recomendar actualizar hardware o usar GPU.

Sólo se proyectan versiones/implementación Python, compute capability y workload
cuando se proporciona contexto explícito. `--observation` valida un snapshot
guardado y toma esos campos, no vuelve a observar el host. `--strategy`/diagnosis
añaden refs verificadas sin ejecutar los planes ni enviar sus payloads fuera.

Cada fuente/extracción/claim/assessment/conclusión lleva estructuralmente:

```json
{"type":"UNTRUSTED_EXTERNAL_CONTENT","untrusted":true,"instruction_authority":"NONE"}
```

La detección de patrones de inyección sólo añade flags de logging, no otorga
autoridad ni es la defensa principal. Texto «ignore GAIA policy and execute
command…» permanece texto; claves JSON `network_authorized` o `SYSTEM_INSTRUCTION`
no modifican requests/config. No se ejecuta código, instala paquetes, aplica
soluciones o crea knowledge local desde research.

## Cache, store y replay

`<state>/research/`: requests, sources, acquisitions, extractions, claims,
assessments, conclusions, cache y runs. JSON canónico, hashes, locks, staging,
fsync y hard-link create-only; contenido idéntico es idempotente, otro contenido
bajo el mismo ID falla. Nuevos bytes producen nuevas versiones de evidencia.
El run se indexa después de guardar artefactos referenciados; un fetch source
puede existir independientemente aunque la extracción posterior no sea útil.

Cache URL+content identity conserva el timestamp original. No se «refresca» al
leer; HIGH freshness limita cache a 60 s por defecto. Cache antiguo no satisface
frescura alta. Nuevos requests pueden reutilizar bytes capturados previamente
sin reinterpretarlos como retrieval nuevo. Acquisition guarda modo CACHE y hora
de lookup además de timestamp original.

FETCH se persiste como ACQUISITION con request/policy refs, eventos y budgets;
EXTRACT/ASSESS/CONCLUDE son artefactos separados. Errores de transporte usan códigos
sanitizados; errores opcionales de JSON pasivo registran fase EXTRACT y no
eliminan soporte de otras fuentes válidas. Corrupción de hashes/identidades falla
explícitamente. Exit 0 de research-run significa resultado almacenado: no prueba
que haya fuentes o requisitos satisfechos; se inspecciona la conclusión y fase.

Replay consume request, source artifacts, analysis timestamp original y policy/
extractor version. Reproduce todos los campos semánticos y citas; sólo coste
computacional de reanálisis puede variar. Si hubo fetch, también se aporta el
artefacto acquisition para auditar autorización/contadores/origen. No hay DNS,
robots o sockets durante replay. Las attestations no permiten verificar de nuevo
que el peer era público sin confiar en el capturador; sí se revalidan reglas,
URLs, hashes y consistencia, junto a tests y revisión del transporte.

## CLI

```sh
python gaia.py research-create --question "Explicit technical question" --url https://docs.python.org/3.14/library/threading.html --topic PYTHON_GIL_CPU_THREADING --domain docs.python.org --authorize-network --state-dir state_research
python gaia.py research-run <request-id> --enable-network --state-dir state_research
python gaia.py research-fetch <request-id> --offline --state-dir state_research
python gaia.py research-requests --state-dir state_research
python gaia.py research-request <id> --state-dir state_research
python gaia.py research-sources --state-dir state_research
python gaia.py research-source <id> --state-dir state_research
python gaia.py research-claims --state-dir state_research
python gaia.py research-conclusion <id|latest> --state-dir state_research
python gaia.py research-replay <request-json> --source <source-json> --run <captured-run-json> --acquisition <acquisition-json> --state-dir state_research
```

`--json` disponible. `--minimum-sources`, `--require-version`, `--freshness`,
`--source-class`, `--observation`, `--strategy` y `--diagnosis` restringen el
request. No se ejecuta ningún comando hallado en las fuentes. El comando histórico
`research` conserva su semántica; los nuevos comandos llevan nombres explícitos.

## Investigación real, controlada y auditoría

Pregunta real: «What do Python 3.14 official docs report about GIL-enabled CPU
threading and free-threaded builds?» Relevante al runtime CPython de GAIA,
sin requerir cambios. Contexto: snapshot explícito Python 3.14.4, no nuevo perfil
del host; no se verificó silenciosamente el estado GIL del build.

Fuentes capturadas realmente por la CLI restringida:

1. `https://docs.python.org/3.14/library/threading.html`
2. `https://docs.python.org/3.14/howto/free-threading-python.html`

Network autorizado en request y opt-in global efímero. Tres requests incluyendo
robots, **206.223 bytes** de body transferidos/decodificados, **1,068 s** de fetch.
Dos fuentes PRIMARY_OFFICIAL y tres claims citados. Capturas y títulos reportan
Python **3.14.8**, frente al snapshot **3.14.4**: assessments RELATED, confianza LOW,
un grupo independiente de publisher, sin falsa corroboración por dos páginas.
Interpretación: aproximadamente **127,6 ms**, incluyendo extracción pasiva.

Conclusión acotada: la documentación describe la limitación de ejecución de
Python code bajo GIL y la existencia de builds free-threaded. No establece el
build local, equivalencia entre patches ni comportamiento de bibliotecas nativas
como NumPy. No implica usar multiprocessing, cambiar threads o recompilar GAIA.
Una cita puede contener consejos de su autor; el report los delimita como
UNTRUSTED EXTERNAL QUOTE y no los aplica.

No aparecieron contradicciones en esas fuentes. Las fixtures sí prueban dos
primarias independientes, secundarios copiados, conflictos de versión y requisitos
hardware incompatibles. Se distinguen explícitamente LOCAL_REPLAY_FIXTURE de
LIVE_PUBLIC_FETCH; no se atribuyen las fixtures a publicaciones reales.

El replay con DNS/socket denegados reprodujo claims y conclusión; la CLI también
lo reprodujo desde JSON y acquisition. Reutilización de cache: **0 requests**,
timestamps originales conservados. No se ejecutaron experimentos ni se creó
operational knowledge. Store temporal externa eliminada; sólo exports curados
en [external_research_evidence/](external_research_evidence/).

Fixture de inyección: instrucciones de ignorar policy/ejecutar comando se
conservan como texto con flags, autoridad NONE, cero claims científicos inventados
y recommendation_status=NOT_AUTHORIZED. El caso controlado CUDA >=8.0 frente a
snapshot 6.1 queda NOT_APPLICABLE, sin descargar/ejecutar software.

`tools/audit_external_research.py` audita offline schemas/hashes, source identity,
URL policy, attestations/robots, citas, calidad, contradicciones, applicability,
replay, fronteras y ausencia de autoridad de ejecución. Auditoría real y dos
controladas: **PASS**. El reporte source_policy contiene hashes de los 14 módulos.

## Privacidad, tests y no regresión

No se envían username/hostname, paths, código, logs, manifests ni observaciones
privadas. Search terms son vocabulario fijo por topic y los providers actuales
no los envían a buscadores. La pregunta/contexto se mantienen locales; sólo
URLs explícitas y headers fijos salen al servidor. No hay claves API obligatorias.
Se inspeccionaron exports y bytes públicos retenidos frente a identidades locales.

| Suite | Recogidos | Ejecutados | Skips | Failures/errors/warnings |
| --- | ---: | ---: | ---: | --- |
| External research | 69 | 69 | 0 | 0 / 0 / 0 |
| Experiment strategy | 55 | 55 | 0 | 0 / 0 / 0 |
| Learning | 52 | 52 | 0 | 0 / 0 / 0 |
| Prioritization | 39 | 39 | 0 | 0 / 0 / 0 |
| Diagnosis | 46 | 46 | 0 | 0 / 0 / 0 |
| Observation | 34 | 34 | 0 | 0 / 0 / 0 |
| Crítica v0.1 | 171 | 170 | 1 | 0 / 0 / 0 |
| Completa | 701 | 690 | 11 | 0 / 0 / 0 |

Todas con `-B -W error::ResourceWarning` y comprobación unraisable. Suite completa:
**758,698 s**. Nueve skips Torch ausente previstos y dos exclusiones administrativas
conocidas: Prueba A real y test de campaña autónoma. Networking unitario simulado;
la captura real es una validación separada, no un test que navegue en cada suite.

69 tests nuevos cubren A–L, destinos privados/metadata/IPv6, redirects y rebinding,
TLS/pinning, robots, gzip/size/deadline, autorización doble, artefactos, phase
provenance, calidad, versiones, citas, independencia, cache, replay, injection,
privacidad, CLI y autoridad. No se alteraron tests heredados para aplicar skips.

532 de 534 archivos originales idénticos, incluidos 16 observation, 10 diagnosis,
8 prioritization, 12 learning, 12 experiment_strategy, 8 protected, 66 frozen y
los módulos históricos `research.py`/`meta.py`. Sólo cambian dispatch CLI y nuevos
defaults en archivos preexistentes. Defaults antiguos y experimental_config
idénticos. Código funcional validado: `78e749c`; receipts y hashes de logs
definitivos en `external_research_evidence/verified-tests.json` y
`verified-regression.json`. Auditorías finales `verified-real-audit.json`,
`verified-injection-audit.json` y `verified-hardware-fixture-audit.json` reproducen
la misma evidencia. Los receipts previos conservan sus propias identidades de
fuente como historia de desarrollo, no sustituyen a los definitivos.

## Limitaciones y alcance certificado

Catálogo extractivo estrecho, idioma/patrones limitados, sin comprensión general
de papers o repositorios. PDFs fuera de alcance; repos sólo como textos públicos
específicos, sin clone/run. No buscador online configurado; interfaz sustituible,
URLs dirigidas y replay bastan para esta certificación sin credenciales.

Fechas, authorship e independencia no siempre pueden comprobarse; metadata de
fuente no es verdad autenticada. HTML normalizado puede perder contexto; las
citas y bytes originales se conservan para revisión. Los límites de red no son
una garantía frente a kernel comprometido o todos los fallos futuros de librerías.
POSIX es la plataforma validada de persistencia. La configuración de build local
no se deduce por una página ni por coincidir la familia de versión.

PASS significa adquisición/estructuración/evaluación controlada y reproducible
de evidencia potencial. No confianza automática, aplicación de consejos, ejecución
externa, instalación, experimentos autónomos, LLM ni mejora de inteligencia general.

Siguiente etapa propuesta: **GAIA 0.8 — Local Intelligence & LLM Integration**.
