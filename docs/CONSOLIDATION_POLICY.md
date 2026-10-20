# Política de consolidación v0.1

Status: Current.

| Categoría | Definición | Futuro Git / retirada |
|---|---|---|
| SOURCE | Código, tests, documentación, plantillas, schemas y dependencias declaradas | Sí, con selección explícita; sin runtime |
| RUNTIME | Estados, entorno local, configuración gestionada y controles de campaña | Fuera de Git; no borrar por el mero hecho de estar ignorado |
| HISTORICAL_EVIDENCE | Datos y resultados de un hito o estudio ya ejecutado | Bundles completos externos; resúmenes y hashes sí versionables |
| GENERATED | Bytecode, caches y productos derivados | Fuera de Git; retirar solo reconstruibles autorizados |
| FROZEN_COMPONENT | Código/evidencia conservados sin desarrollo activo | Código/tests/docs sí; runtime externo; sin cambio funcional |
| FIXTURE | Entrada estática intencional consumida por pruebas o ejemplos | Sí, aunque su extensión parezca un artefacto runtime |

Venvs, `.gaia/`, `state/` y estados `state_*` no se versionan. El README estático
de `state_gaia_transformer_cuda/` es una excepción explícita. Los lockfiles de
`requirements/`, claves públicas y logs estáticos de evidencia documental no se
ocultan por patrones genéricos de generados. El material privado se excluye.

## Restricciones vigentes

- `.gitignore` previene staging accidental; **no autoriza borrar**.
- Prueba A/B, Modo B y GPU tienen copias externas verificadas. Sus originales
  permanecen intactos; no retirar por ello otros reports referenciados.
- Legacy (`state/`, `state_numpy_mlp_*`) y `demo_evidence/` deben archivarse antes
  de cualquier retirada. Demo tiene estado **HISTORICAL_EVIDENCE_PENDING_ARCHIVE**:
  no es fixture de tests, pero contiene antecedentes únicos citados por docs.
- Imágenes/rootfs/VM, firmas y reports históricos siguen bloqueados para limpieza
  indiscriminada, incluidos archivos compartidos por hardlinks.
- `.gaia/bootstrap-cache/`: **SAFE_DELETE_NEXT**, condicionado a la siguiente
  autorización y prueba del flujo limpio/pre-Git; no se elimina en paso 3.
- En paso 3 solo se limpian caches/bytecode autorizados fuera de `.gaia/`, estados,
  evidencia documental, demo y archivo externo. No se eliminan locks sin prueba
  de inactividad; no se ha autorizado una retirada genérica de locks.

La arquitectura y la evidencia de referencia son v0.1 CPU; consolidar no modifica
thresholds, búsqueda, benchmark, gates, sandbox, publicación o rollback. GPU y
appliance permanecen congelados. Git todavía no está inicializado.

El mapa administrativo externo `manifests/runtime-source-separation.json` registra
el inventario previo y sus bloqueos. Los cambios y pruebas del paso 3 se registran
separadamente bajo `manifests/step3/`, fuera del source.
