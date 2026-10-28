# GAIA 1.1 Stage 1 — pre-registration

Stage 0 prerequisite: PASS on all 15 actions in
`.gaia/stage0/attempt3-20261025T223404/`, on commit `378cf93`.
Both suites have no ResourceWarnings; 215 specific tests and 998 full tests
(9 dependency skips). The controlled session still passes the offline auditor.

Run `tools/stage1_endurance.py` on fresh state `state_endurance_stage1_attempt1`.
The code identity remains `9e79cda91d6770aeebb73d04406df935dba43cc066d7e1a3b76671ced58c860d`;
changes since Stage 0 are administrative tools and this registration only.
Record the actual commit and resource baseline before execution.

## Frozen limits

- CONTROLLED_AUTONOMOUS, numpy_mlp only, fresh persistent lineage.
- Window and aggregate compute ceiling: 5400 seconds.
- At most 5 sequential campaigns, each at most 900 seconds, 3 iterations,
  2 experiments, 512 MiB. Stage storage ceiling: 2 GiB.
- No network, no promotion, no authority expansion.
- Default heartbeat, telemetry, reserve and recovery policies remain in force.
- Minimum admission budget: 300 seconds; no campaign is admitted beyond the window.

## Reading rules

PASS requires all campaign offline audits and recovery classifications to pass,
no duplicate effects, unexplained stopping, corruption, escalation or surviving
controller, telemetry and supervisor resource bands within the Stage 0 limits,
and no corrective intervention. Preserve before/after resource evidence.
Learning/reuse and duplicate avoidance are read from campaign progress reports;
do not claim reuse if it was not applicable or observed.

The window is a ceiling, not a claim of 90 minutes of continuous experimentation.
Report measured duration and any early exhaustion of campaigns or candidates.
An early end must be assessed against the plan before accepting Stage 1 overall;
the session auditor PASS alone is not a blanket endurance certification.

On any failure: preserve evidence, stop progression, investigate. No automatic
Stage 2 launch. The previous Stage 0 failure remains preserved.

## Coverage completion pre-registration — 2026-10-26

The first session passed its operational audit but stopped at five campaigns
after 1289.915 s. It is not accepted as a 90-minute endurance window.
Its five terminal campaigns and stopped session were replayed via the real CLI:
all 862 owned files, including native engine state, retained identical content.
Supplemental evidence: `06-terminal-replay-complement.json` in that run's folder.

Repeat on fresh state `state_endurance_stage1_attempt2` using
`tools/stage1_endurance.py --paced`. Keep all original campaign and aggregate
ceilings, authority, evaluators, reserves and promotion restrictions unchanged.
The administrative `PacedSupervisor` extends only scheduling: after each
terminal campaign, observe labelled SCHEDULED_IDLE until the next 18-minute
slot. Five slots span 90 real minutes. During idle, check the frozen protocol,
storage, host memory, heartbeat and VRAM. Do not insert experiments or fabricate
busy time. The unchanged production supervisor still creates, runs, cleans up,
and accounts for every campaign; admission budgets are rechecked after idle.
An unsafe campaign is never paced or silently retried.

Require the full observed 5400 s, one boot, observation gaps under 25 s,
the existing offline audit, resource evidence and terminal byte-for-byte replay.
Report actual campaign elapsed compute separately from the scheduled idle.
Pacing is an explicitly different schedule, not a retroactive reinterpretation
of the first run. It measures low-duty-cycle stability, not 90 minutes of load.

Five new administrative tests and all 32 supervisor tests pass with
`-W error::ResourceWarning` before launch. No `gaia/` bytes changed.

### Unresolved post-promotion fault-drill requirement

The plan's introductory amendment asks for interruption during post-promotion
verification, with rollback and reference remeasurement. Stage 1 simultaneously
forbids promotion and caps campaigns at 900 s. The publication policy requires
1600 s remaining to authorize promotion, so the demanded state is unreachable
under this contract. Unit fixtures do not discharge a real end-to-end drill.
This completion run does not waive that requirement or authorize a wider scope.
Full Stage 1 closure remains pending either a separately authorized, disposable
real promotion/recovery drill with its own preregistered budgets, or an explicit
operator-approved resolution of the conflicting plan requirements. No Stage 2.
