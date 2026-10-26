# Stage 1 — separately authorized recovery drill

The operator explicitly authorized one additional isolated, disposable campaign,
up to 60 minutes, permitting promotion only through existing controls. This is
an exception for a recovery drill, not an expansion of endurance authority.
No downloads, network, installations, evaluator changes or forced promotions.

## Fixed setup

- Fresh `state_endurance_stage1_recovery_attempt1` and a new numpy lineage/native
  engine. Never reuse or mutate the endurance lineages.
- Real CLI session/supervisor and controller, real learning, native sandbox,
  acceptance, publication, matrix, rollback and reference measurement.
- One campaign: 3 iterations, 2 experiments, 3000 s wall and compute, 512 MiB.
  The standard bounded bookkeeping grace is 600 s; 50 + 10 minutes fits the
  authorized hour. Session wall/compute ceilings: 3600 s; storage: 2 GiB.
- Promotion enabled only in this disposable session, subject to every existing
  gate and the unchanged 1600 s verification reserve. No crafted candidate,
  synthetic costs, injected acceptance or changes to thresholds.
- Supervisor heartbeat 2 s; one relaunch/recovery maximum. No operator retry.
- Run after the 90-minute observation session, not concurrently.

## The one planned fault

Wait for a natural published promotion to enter VERIFYING, with a live native
regression matrix descendant. Wait at least 5 s and require the external
supervisor heartbeat to identify that matrix. Persist the exact controller
pid/start-time and process tree, then SIGKILL that controller once. Let the real
supervisor clean up and perform its one normal recovery. Do not kill unrelated
processes or edit a journal to produce a desired state.

## Strict outcomes

PASS requires: the planned fault was actually injected; offline audits pass;
native rollback returns to the evaluation's previous version; AFTER_ROLLBACK
reference is MEASURED and bound to that native version; native ledger verifies;
lineage is not blocked; all reserved experiments have distinct evaluation
receipts; no captured process survives; terminal replay changes no owned bytes.

No natural promotion/matrix means NOT_EXERCISED, not PASS. A valid resumed
promotion without rollback is NOT_EXERCISED_ROLLBACK for this requirement.
Neither is silently retried. Corruption, duplicates, failed audit, survivors or
unmeasured reference are FAIL. Preserve all outcomes and stop progression.

The final Stage 1 decision also requires the actual 90-minute coverage and
idempotence evidence. No automatic Stage 2 launch.

## Auditor correction for the completed observation window

The original observation run in `.gaia/stage1/attempt2-window-20261026T081635`
retains its FAIL seal. All five campaigns, terminal replay and full window
coverage passed. The single audit failure grouped host VRAM samples by campaign
id: idle (`null`) samples consequently appeared to have holes during campaigns,
despite actual sensor samples throughout. There are 179 real VRAM samples,
with a largest global interval of 34.529 s, below the existing 60 s limit.

The tool-only correction audits this global host sensor as one continuous
stream, including idle; it does not change cadence, discard samples or waive
real gaps. A regression test demonstrates both the false positive and rejection
of genuine gaps. Preserve the original audit/seal and append a separately
identified re-analysis with tool commit and raw telemetry hashes. No `gaia/`
or evaluator bytes change; source identity remains
`9e79cda91d6770aeebb73d04406df935dba43cc066d7e1a3b76671ced58c860d`.

## Operator-authorized continuation — 2026-10-26

The first drill ended NOT_EXERCISED: two distinct informative rejected experiments,
no promotion, no injected fault, native version v0000, verified ledger, cleanly
closed unblocked lineage. Its operational audit passed. Preserve its evidence in
`.gaia/stage1/recovery-attempt1-20261026T101918` without reclassification.

After being informed of that outcome, the operator explicitly requested to
continue. Authorize exactly one additional sequential campaign with the same
limits and the same one-fault mechanism above. Use the existing **disposable**
lineage `ale07ce6b7ed344fcab4ad39b4` in
`state_endurance_stage1_recovery_attempt1` via explicit `--continue-lineage`.
Create a new session, campaign and output directory. Keep every prior journal,
native experiment, reference and learning record; do not start the search over,
select a hand-crafted winner or modify any evaluation result. Freeze the new
session on the current native pointer and evidence.

Continuation is refused on a source mismatch, blocked or open lineage, live
previous controller, non-terminal previous campaign, or non-disposable namespace.
Record the previous lineage journal tip and experiment count before admission.
Normal admission still remeasures the reference and applies its drift guard.
Keep NOT_EXERCISED/FAIL as measured; no further campaign is automatically allowed.

## Final authorized drill and claim separation — 2026-10-26

The operator explicitly authorized ONE FINAL drill, then full regression,
offline re-audit and Stage 1 closure, with no Stage 2 launch. No further search
is allowed after this drill, regardless of whether promotion occurs.

Use the same isolated disposable lineage named above, retaining all four prior
rejected experiments and learning, never the natural endurance lineage. Exactly
one new session/campaign; at most 3 iterations and 2 additional experiments;
3000 s campaign wall/compute plus the existing 600 s bookkeeping grace, within
the 3600 s authorized envelope. Storage, sandbox, thresholds, policy, promotion
reserve and one permitted supervisor relaunch remain as specified above.
The unchanged checkpoint is VERIFYING with a live native regression-matrix
descendant, observed for at least 5 s and present in the supervisor heartbeat.
One SIGKILL of the exact controller pid/start-time, never a forced publication.

All three drill attempts are retained and reported, including the two earlier
NOT_EXERCISED outcomes; this is not a best-of series or an improvement claim.
If this final bounded campaign yields no legitimate promotion/checkpoint,
POST_PROMOTION_RECOVERY_REAL_DRILL = NOT_EXERCISED. Do not repeat it.

The operator resolves the earlier claim coupling prospectively: endurance
closure is assessed from the full 90-minute natural session, stability,
idempotence, learning, stopping, resources, frozen-source identity, full-suite
result and offline audits. Absence of a natural promotion in the separate drill
does NOT invalidate STAGE_1_ENDURANCE = PASS. An actually injected fault with
unsafe recovery remains FAIL, not NOT_EXERCISED. The native recovery claim is
never inferred from unit fixtures, earlier versions or the endurance PASS.

Run `tools/stage1_final_close.py`: one drill only, then the full suite once,
reaudits and a consolidated report. Failures are preserved without automatic
test retries, campaign retries, threshold changes, new authority or Stage 2.
