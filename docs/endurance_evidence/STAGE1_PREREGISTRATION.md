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
