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
