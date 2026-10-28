# Pre-registration: GAIA 1.1 Stage 0 (pre-flight)

Committed before the Stage 0 run. Stage 0 follows the "Stage 0 — Pre-flight" section of
[`GAIA_1_1_ENDURANCE_PLAN.md`](../GAIA_1_1_ENDURANCE_PLAN.md). It is executed by
`tools/stage0_preflight.py`, which writes one JSON evidence file per action.

- **Base:** `main` at `gaia-v1.0.1`, i.e. 1.0.1 certified and merged.
- **Branch:** `feat/gaia-1.1-endurance`.
- **Bytes:** code commit `9b9222e`, source identity `9e79cda91d6770aeebb73d04406df935dba43cc066d7e1a3b76671ced58c860d` (protected hash unchanged: `9376438978e4c78ecee88ca5c839914760b13f312f340f4691905ddc94261e1f`).
- **States:** fresh disposable states `state_endurance_stage0` and `state_endurance_stage0_faults`.
- **Host:** at rest, run detached from the operator session.

## Earlier attempts (development evidence, not part of Stage 0)

1. **Attempt 1, on `477644f`.** Stopped at action 12 by a runbook bug: argument shadowing in `tools/`. Actions 1–11 had passed.
2. **Attempt 2.** Stopped by the operator during fault injection. That stop exposed a real defect, now fixed in `9b9222e`:
   - an operator STOP sent while a v2 campaign was experimenting interrupted the trial and blocked the lineage;
   - this contradicted the controller's deferral of STOP and PAUSE.

Because `gaia/` changed, Stage 0 restarts from fresh states on the bytes below.

## Actions (plan order)

### Re-run registered 2026-10-25

The run on `6ab6c0b` ended FAIL: action 13 failed although action 14 passed.
Diagnosis reproduced a shared `time.time` mock leaking from a test (patches
stopped in FIFO rather than LIFO order). Commit `aa139cb` fixes test isolation,
reaps the supervisor test's bystander process, and retains complete suite output.
No `gaia/` or evaluator bytes changed; the source identity above is unchanged.
The 215 specific tests pass after these fixes, without ResourceWarnings; the
previous full re-check passed 998 tests with 9 skips before the cleanup change.
Repeat all Stage 0 actions, including both suites, on fresh disposable states
`state_endurance_stage0_attempt3` and `state_endurance_stage0_attempt3_faults`.
Preserve the failed evidence in `.gaia/stage0/20261025T200310`.

1. **Commit, tag and working tree.** Sources clean; `gaia-v1.0.1` is an ancestor.
2. **Observation.** A full observation, which measures the protected workload.
3. **bwrap.** Verified.
4. **Protocol freeze.** Commit, identities, configuration and acceptance criteria, the Stage 0 lineage, and the selected inference backend with its stack hash.
5. **Store inventory.** Sizes and file counts of every existing state, and the filesystem.
6. **Resource baseline.** Host memory against its reserve, VRAM, filesystem, load and process count.
7. **Supervisor and heartbeat.** Observed live during action 11: heartbeat age stays under twice its cadence, plus a margin.
8. **Read-only inspection.** Session and campaign status are read repeatedly while the campaign runs; the purity tests are cited.
9. **DRY_RUN session** (1 campaign).
10. **SHADOW session** (1 campaign).
11. **Short controlled cycle.** One CONTROLLED campaign under the Stage 0 budgets.
12. **Fault injection**, in disposable states only:

    | Case | Method | Repeats |
    | --- | --- | --- |
    | Process kill | SIGKILL of the real controller while experimenting | 3 |
    | Timeout or hang | SIGSTOP of the real controller in a session's second campaign, hang timeout 240 s | 3 |
    | Lock after holder death | live holder blocks; dead holder frees; an inherited descriptor in a surviving child keeps the lock and is attributed | once |
    | Disk pressure | simulated with a tiny session ceiling; the real disk is never filled | once |
    | Interrupted write | the process is killed between the temporary write and the link | once |
    | Invalid transition | an invalid journal transition is attempted | once |
    | Corrupted evidence | journal and artifact tampering, on copies | once |
    | Backend unavailable | missing intelligence state | once |
    | Sandbox failure | existing fail-closed tests | once |
    | Regression-matrix child | existing supervisor cleanup tests | once |

13. **Specific tests.** Endurance and autonomy modules.
14. **Full suite.**
15. **Seal.** Digests of all evidence, identity, commit, sessions and limits.

## Stage 0 budgets (from the plan)

At most 3 iterations and 1 experiment per campaign, 15 min of wall and compute per campaign, 512 MiB
of disk, no network, `numpy_mlp` only, promotion disabled.

## Fixed reading rules

- **PASS** requires every action to PASS:
  - every Stage 0 session passes `tools/audit_endurance_session.py --stage stage0`;
  - recovery is safe: a fault ends RECONCILED or in a durable SAFE_BLOCK, never with a duplicated experiment;
  - no process survives cleanup;
  - telemetry has no gap of twice its cadence or more inside a campaign;
  - the limits are equal to or stricter than 1.0.
- **FAIL:**
  - corruption;
  - authority escalation;
  - an ambiguous state classified as safe;
  - orphan processes;
  - ineffective limits;
  - any need to relax an evaluator.

  Any failure follows the plan's gating: STOP, INVESTIGATE, FIX IN SAME FEATURE BRANCH, TEST, REPEAT STAGE 0. A fix that changes `gaia/` restarts Stage 0 from fresh states.
- The safe outcome of a fault is reported as it happened, RECONCILED or SAFE_BLOCK. Neither is rerun to get the other.
