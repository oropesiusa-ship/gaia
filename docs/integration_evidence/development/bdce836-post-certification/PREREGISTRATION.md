# Pre-registration: post-certification evidence for GAIA 1.0.1

Committed before any of the runs below. The definitive series in [`final/`](final/) is not
modified, extended or re-run: its state (`state_integration_final2`) and lineages stay as
certified. Everything here runs on the same certified bytes: source identity
`48041114f55406f06ba3db0cf43f0ff169f7ea219225c382eaa3866593d5370b`, protected hash
`9376438978e4c78ecee88ca5c839914760b13f312f340f4691905ddc94261e1f`. No evaluator, benchmark,
acceptance criterion, policy, threshold or budget changes.

## 1. Cognitive plan selection (counterbalanced)

Tool: `tools/eval_cognitive_selection.py`, committed before running. The cases and their expected
answers are fixed in the tool.

- **PRODUCTION:** the certified `Services.compare` code, unchanged. It runs on every multi-candidate COMPARE input recorded by the definitive CONTROLLED campaigns, under every cyclic rotation of the candidate order, plus 5 evidence-decisive cases in both orders.
- **PROBE:** the same selected 0.8 backend, outside the certified path, given every candidate field and the previous outcome. It measures what the model can use, not what GAIA does.

Pre-declared reading:

- If PRODUCTION picks the first listed candidate regardless of order, the cognitive selection reproduces the deterministic default and adds no value.
- Value requires the same plan across rotations and the expected plan in both orders of a case.

## 2. Natural promotion on the certified bytes (independent replication series)

- Fresh state `state_integration_replication` and one new numpy lineage with `IMPROVE_NUMPY_MLP_EXISTING_CRITERIA`. Default limits are identical to the definitive series.
- Series: DRY_RUN → SHADOW → **exactly 6** CONTROLLED_AUTONOMOUS campaigns with promotion allowed.
- No early stop, no reruns, no extra campaigns. Every campaign is reported and audited, whatever its outcome.
- Outcome: `PROMOTION_REACHED` if any campaign records a verified promotion; otherwise `NOT_REACHED`. Either is reported as found.
- This series is not combined with the definitive series. It answers whether the natural chain is reachable on these bytes. It does not estimate a promotion rate.

## 3. Rollback drill (fault injection, only if section 2 promotes)

Natural autonomous rollback stays `NOT_EXERCISED` unless it happens naturally. If, and only if, section 2
ends with a promoted current version, one additional declared drill campaign runs after the series:

- **Fault:** host memory pressure only. A separate process holds enough RAM that available memory falls below the configured 3000 MB budget. Nothing in the state, the sources or the configuration is touched.
- **Expected path:** the CONTROLLED admission health check runs the existing gates; G5 reports `RESOURCE_BUDGET_FAILED`; the existing Engine rollback restores the predecessor version; the campaign stops `HEALTH_INVALID` and the lineage is BLOCKED for review. No experiment is measured under the fault.
- **Labeling:** reported as `ROLLBACK_DRILL_FAULT_INJECTED`, never as natural rollback.

Inference promotion and inference rollback stay `NOT_EXERCISED`: the selection pointer can only
move after a real 0.8-guarded gain. A drill would need a fabricated promotion.
