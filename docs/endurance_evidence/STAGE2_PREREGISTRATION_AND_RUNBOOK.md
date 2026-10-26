# GAIA 1.1 — Stage 2 Medium Endurance: preregistro y runbook

**Estado:** `DESIGNED_NOT_AUTHORIZED`. No ejecutar hasta revisión y autorización explícita.

Stage 1 permanece cerrado: `STAGE_1_ENDURANCE = PASS` y
`POST_PROMOTION_RECOVERY_REAL_DRILL = NOT_EXERCISED`. Este documento no reabre Stage 1,
no convierte ese drill en PASS y no autoriza Stage 3 ni una release 1.1.

## Claim y exclusiones

Stage 2 prueba que dos sesiones separadas preservan y reconcilian estado operativo,
presupuestos y learning de campañas acotadas, y que reabrir una campaña terminal no
causa acciones nuevas. Quedan fuera: promotion, rollback post-promotion, fault injection,
research, red, cambios de código, y cambios de evaluadores, benchmarks, thresholds o
policies. Los fault injections son de Stage 0; recovery natural no observado será
`NOT_EXERCISED`, no PASS.

## Freeze previo a toda acción

El contrato inmutable de ejecución debe contener estos valores, sus SHA-256, el hash de
este preregistro, del ejecutor Stage 2, configuración efectiva, runtime, árbol limpio,
boot ID, inventario y baseline. Cualquier diferencia bloquea admisión.

| Elemento | Valor congelado |
| --- | --- |
| Commit de partida | `b3ea4303e42a5a01a3bf538a6ffc3acf931d0107` |
| Source identity | `9e79cda91d6770aeebb73d04406df935dba43cc066d7e1a3b76671ced58c860d` |
| Protected-source hash | `9376438978e4c78ecee88ca5c839914760b13f312f340f4691905ddc94261e1f` |
| Protocol freeze | `1a127812564fe9fc2765b7ff20aebadf997ad3f50c46e7b32380a7b6600a2f6e` |
| Engine-config hash | `9b53fe850f81d5a018f264452bb875148ca0a480f4b50d8c6101feb1f8c85f17` |
| Local backend selection/hash | `lia02f893b5c87c4b4880e8fc0` / `2b73f933605849a7313c01eb8b5c84489e4efc7874532975b13e7fe35cddc0f1` |
| Local stack/hash | `stack-a424bbb1c10e43df` / `360ed8b681f5f751ee88eb7bb4024b1884978bdaea272a8a0a93b7051bd085ce` |

El ejecutor administrativo está en `tools/stage2_executor.py` y
`tools/stage2_runtime.py`. Requiere revisión independiente y nuevo commit/contrato
con árbol limpio antes de ejecutar; no cambia `gaia/`, evaluadores, thresholds ni
policies. No se permiten pasos manuales ad hoc. Los valores históricos anteriores
se conservan; el contrato nuevo congela el commit y hashes administrativos efectivos.

Estado de implementación (no evidencia de endurance): `prepare` crea exclusivamente
estado/linaje NumPy nuevos bajo el intento. Sólo emite `READY_TO_EXECUTE` si pasan
árbol limpio, Stage 1 cerrado, reservas, sandbox y freeze. READY no autoriza ejecutar.
El contrato v1 queda conservado pero no es admisible. Después de revisión, un operador
puede usar las rutas siguientes (no se han ejecutado durante esta implementación):

```sh
.venv-observation/bin/python -B tools/stage2_executor.py prepare --out .gaia/stage2/NUEVO_INTENTO
.venv-observation/bin/python -B tools/stage2_executor.py run-first-session --contract .gaia/stage2/NUEVO_INTENTO/contract.json --authorize-stage2-s1
```

S1 usa el supervisor existente: dos slots de una hora, una campaña al inicio de cada
slot y observación activa del idle hasta 7.200 s. Cada admisión reserva duraderamente
1.800 s antes de crear campaña. El límite interno de ejecución es más estricto,
1.740 s, dejando margen de supervisión; el guard detiene un hijo aún vivo a 1.770 s.
El cargo real y su auditoría usan `max(supervised_s, report_wall_s)`. Un exceso de
1.800 s es FAIL, nunca una ampliación de reserva. No hay refund, adopción, recovery ni
retry automático tras interrupción. El ledger bloquea un segundo arranque de S1.

El almacenamiento acumulado incluye intento, estado persistente, engine de linaje y
scratch `work` del backend seleccionado, sin restar baseline ni contar roots solapados
dos veces. Hay headroom de 64 MiB y reserva adicional de 512 MiB antes de admisión.
Estos son gates de polling con margen, **no una cuota física absoluta**: una escritura
puede exceder el techo entre muestras. Una violación observada detiene y falla el
intento; no se cambian las policies ni los mecanismos de presupuesto de producción,
ni se promete impedir físicamente todo exceso. Se conservan logs y telemetría sin truncado/rotación destructiva. Se registran baseline,
procesos/start-time, RSS/PSS/CPU/FD, archivos/bytes por root, catálogo, hashes terminales,
reservas/cargos, idle y VRAM. El auditor tiene perfil Stage 2, checks de bandas, pendiente
RSS idle, gaps y cargos conservadores. La autorización arranca un proceso runtime
dedicado, sin otros hijos gestionados concurrentes. Antes de ejecutar se registra el
baseline de hijos directos (debe estar vacío), se activa y verifica Linux
`PR_SET_CHILD_SUBREAPER` y se exige soporte pidfd/waitid. Cada campaña abre una época
de ownership exclusiva. Los huérfanos, incluso `fork`/`setsid`/doble fork entre muestras,
se adoptan en ese proceso; se registran PID/start-time, reparenting, señales y reap.
Cleanup usa pidfds fijados a identidades verificadas, vuelve a descubrir adoptados
durante TERM/KILL y sólo termina cuando `waitid` confirma `ECHILD`, sin supervivientes.
No acepta booleanos de propiedad ni mata grupos desconocidos. Se restaura y verifica
el valor previo de subreaper únicamente con la frontera drenada; si no se puede
drenar/restaurar, falla cerrado sin siguiente campaña ni resultado observado exitoso.
La evidencia final se sella después de verificar la restauración. SIGTERM/SIGHUP
ordinarios permiten cleanup; no se promete recuperación ante SIGKILL del supervisor,
fallo de kernel o procesos que el kernel no permita terminar.

La reapertura verifica terminalidad antes del CLI real y compara bytes y reporte.
No demuestra ausencia de hijos efímeros. Ese claim bloquea el PASS final, no la
admisión segura de S1. `S1_OBSERVED` sólo describe S1 observado/auditado, nunca Stage 2
PASS. También quedan explícitamente no ejercitados: S2 y su reconciliación de frontera,
atribución completa de drift externo, holders de locks y vinculación completa entre
referencias elegibles del catálogo y decisiones ejecutables. Se guardan consultas de
catálogo y refs reales sin inventar reuse. No hay CLI de S2 ni transición automática.
Los tests desechables no son evidencia de endurance ni autorización de lanzamiento.

## Límites inmutables

| Ámbito | Límite |
| --- | --- |
| Sesiones | exactamente 2 ventanas, hasta 2 h observadas cada una |
| Campañas nuevas | hasta 2 por sesión; hasta 4 total |
| Cada campaña | 1.800 s wall/compute local; 5 iteraciones; 3 experimentos; 512 MiB propios |
| Compute agregado | 7.200 s máximo; suma de wall de campañas, no CPU-seconds |
| Almacenamiento de Stage | 4 GiB acumulados, desglosado por propietario |
| Research / red / promotion | 0 / 0 / deshabilitada |
| Concurrencia | una ejecución candidate/model; NumPy e inferencia local nunca solapados |
| Recovery | hasta 2 intentos por campaña no terminal y 3 por sesión, sólo inequívoco |
| Intervención correctiva | 0 |

Los límites son techos, no cuotas. Idle, supervisión y reconciliación no cuentan como
compute. Una reapertura terminal es verificación read-only, no campaña nueva: cualquier
admisión, intent, proceso, gasto o escritura es fallo.

## Escenarios y orden fijo

Los IDs concretos se asignan al contrato; los roles y el orden son inmutables.

### Sesión 1: producir y consumir learning compatible

1. **S1-C1, productor NumPy.** Campaña `numpy_mlp` en linaje persistente nuevo, con
   binding congelado. Conserva catálogo, ledger, receipts, progreso, presupuesto y el
   learning natural. No se fabrica un candidato ni resultado para producir learning.
2. **S1-C2, consumidor compatible NumPy.** Nuevo campaign con binding exactamente igual.
   Consulta primero el catálogo persistido. Si hay record elegible de S1-C1, debe
   registrar `reused`, evidence ref y efecto sobre la decisión; ignorarlo o duplicar
   acción vedada es FAIL. Si no hay record elegible, registra `no_eligible_record` y su
   razón factual, sin inventar reuse; no podrá afirmarse *reuse observed*.

Tras cada terminal se capturan hashes de sus archivos propios, ledger, catálogo y todos
los contadores de presupuesto.

### Límite entre sesiones: persistencia, reconciliación e idempotencia

Antes de admitir S2-C3, un supervisor nuevo abre el mismo directorio y ejecuta sólo
inspección read-only. Reconcilia con S1: estado/phase/stop reason/cursor; ledger,
receipts e intents; contadores de campaña y agregados; catálogo/learning; procesos,
locks, FDs, scratch y telemetría; y hashes terminales.

Después invoca la ruta normal de reapertura de S1-C1 y S1-C2, en modo de verificación
que rechaza admisión. La prueba pasa sólo con `TERMINAL_NOOP` (o equivalente congelado),
cero hijos, cero intent/receipt/experimento/transición/puntero, bytes propios idénticos y
contadores idénticos antes/después. Reparar cursor, escribir timestamp o tomar un lock
que modifique estado no es noop: FAIL.

### Sesión 2: incompatibilidad y learning post-sesión

3. **S2-C3, sonda de binding incompatible.** Antes de admisión, una consulta read-only
   usa un binding factual distinto al NumPy de S1. La variante preferida es inferencia
   local prevista por el plan. Una referencia NumPy debe resultar `INCOMPATIBLE_BINDING`,
   con diferencias de binding y sin efecto ejecutable.

   La campaña local sólo se admite si el preflight confirma exactamente selección, stack
   y hashes congelados, reservas y aislamiento. Corre sola: ningún proceso NumPy vivo ni
   `HOST_EXPERIMENT_BUSY`. Si no está autorizada/cualificada, queda
   `NOT_ADMITTED_BACKEND`, sin sustitución silenciosa. Se puede continuar, pero no
   declarará cubierta la incompatibilidad entre superficies sin una sonda factual.
4. **S2-C4, consumidor NumPy post-sesión.** Binding idéntico a S1-C1. Relee catálogo tras
   el límite de sesión. Cada entrada elegible se reutiliza o se rechaza explícitamente
   por stale, contradicción, supersession o no aplicable. Binding exacto declarado
   incompatible, o reuse desde binding distinto, es FAIL. Sus contadores locales parten
   de cero; los agregados conservan todo lo consumido anteriormente.

Un stop válido (`NO_PROGRESS`, presupuesto, referencia no fiable, etc.) no se reintenta
para llenar tiempo. Dos fallos operativos consecutivos paran sesión. Corrupción, drift
protegido, estado ambiguo, escalamiento, huérfano o exceso paran Stage y preservan
evidencia antes de cleanup.

## Métricas y drift

Cadencias: heartbeat 10 s; controller/descendientes 15 s; VRAM 30 s; disco/file-count
60 s. Hueco inexplicado: ≥2× su cadencia; heartbeat ausente 30 s inicia diagnóstico.
Cada muestra tiene UTC, monotonic, boot ID, session/campaign ID y calidad.

Se capturan baseline, durante, post-cleanup y reapertura: RSS/PSS del supervisor, CPU,
RAM/VRAM de campaña, bytes/file-count por propietario, FDs, procesos/start-time, locks,
telemetría, heartbeats, progreso, intents/receipts, experimentos, budgets y hashes.
Actividad externa demostrable se marca `INCONCLUSIVE_ENVIRONMENT`, nunca leak atribuido.

Umbrales congelados: supervisor en reposo ≤ max(baseline +64 MiB, +20 %) y pendiente
post-warm-up ≤1 MiB/h; VRAM post-unload dentro de baseline ±256 MiB; FDs ≤ baseline +5
sin crecimiento persistente; cero descendientes inesperados tras cleanup; reserva host
≥ max(2 GiB, 15 % RAM); filesystem ≥ max(5 GiB, 10 %). El techo 4 GiB y 512 MiB por
campaña no son tolerancias. Subida monótona atribuible que no retorna tras cleanup es
drift persistente aunque aún no alcance un techo.

## Stopping, recovery y reconciliación segura

No renovar deadline sólo por heartbeat. Ante límite, hash/boot distinto, reserva baja,
corrupción, intent ambiguo o discrepancia de ledger: detener sólo árbol propio, preservar
evidencia y clasificar `TERMINAL_OK`, `RECOVERABLE`, `NEEDS_RECOVERY`, `CORRUPT` o
`NON_RECOVERABLE`. Sólo `RECOVERABLE` inequívoco puede reanudar dentro de límite. Cambio
de boot ID es `INCONCLUSIVE_ENVIRONMENT`, no continuidad.

La auditoría offline compara contrato, ledger, receipts, catálogo, cursores, reportes,
telemetría, procesos, presupuestos y manifest SHA-256. Debe explicar todo byte/archivo
nuevo por propietario y todo compute por campaña; nunca borra o reescribe evidencia.

## Resultado

### PASS

Requiere las dos ventanas autorizadas, Stage 1 aún PASS, límites/auditorías/reconciliación
PASS y: learning/catálogo/budgets preservados; S2-C4 los interpreta por binding;
incompatibilidad declarada sin reuse; reapertura de S1-C1/C2 idempotente; cero corrupción,
escalamiento, duplicado, huérfano o drift persistente; supervisor/telemetría reconciliados;
cero intervención correctiva y cero cambios protegidos.

PASS no afirma promoción, rollback post-promoción, recovery real no ejercitado, cuatro
horas continuas de experimentación ni reuse observado sin record elegible.

### FAIL, BLOCKED e INCONCLUSIVE

- **FAIL:** límite excedido; acción o escritura terminal; presupuesto reiniciado;
  reuse incompatible; learning/budget perdido; contador sin explicación; drift,
  corrupción, hash/policy/evaluator drift, huérfano, telemetría no reconciliable o
  intervención correctiva.
- **BLOCKED_PREEXECUTION:** freeze, herramienta, backend o reserva no verificable; no
  empieza sesión.
- **INCONCLUSIVE_ENVIRONMENT:** boot ID cambia, carga externa impide atribución o faltan
  muestras por causa externa demostrable. No es PASS.
- **NOT_EXERCISED:** subclaim no alcanzado, por ejemplo backend local no admitido; nunca
  se eleva a PASS ni se cubre con tests unitarios.

## Evidencia y cierre

Cada sesión usa `.gaia/stage2/<attempt-id>/`: contrato, baseline, verificación freeze,
contrato de sesión, snapshots, trazas de learning/applicability, terminal noop,
telemetría, auditoría/reconciliación, inventario proceso/lock, recursos y manifest
SHA-256. Se conservan intentos PASS, FAIL, BLOCKED e INCONCLUSIVE.

El informe separará tiempo observado/active/idle/compute, campañas/experimentos,
learning reutilizado/no aplicable/rechazado, incompatibilidades, reaperturas, recovery,
drift y acción humana. No inicia Stage 3 automáticamente. GAIA 1.1 sólo cierra tras
Stages 3 y 4 y auditoría final.
