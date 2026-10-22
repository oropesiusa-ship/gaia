# Pre-registration: GAIA 1.0.1 re-certification

Committed after the code commit and before any of the runs below. The previous certification
(commit `bdce836`) is invalidated by the changes to `gaia/`. Its evidence, and the
post-certification evidence that motivated the changes, are kept apart under
[`development/`](development/) and are never combined with this certification.

Bytes certified: commit `26c828c`, source identity
`170095035d90cb6818e63f451b003a41781182ccd0442f67b45ea9a08ea03078`, protected hash
`9376438978e4c78ecee88ca5c839914760b13f312f340f4691905ddc94261e1f` (unchanged).

## Changes certified

1. **Champion reference.** The champion reference is re-measured:
   - at the admission of every CONTROLLED numpy campaign, under the v0.1 drift guard;
   - after any rollback;
   - after a promotion;
   - and whenever the reference is not bound to the current champion, before the execution intent.

   Every experiment record carries its `screen_reference`. Reference drift, or an unreliable reference, stops the campaign and blocks the lineage for review.
2. **Regression matrix policy (operator-approved).**
   - The first full-matrix failure is recorded with its failing test IDs and tracebacks, as an explicit signal.
   - Only those tests are re-run, once, in a clean process. Any failure there means rollback.
   - If they all pass, the full matrix runs once more. A pass keeps the promotion; any failure means rollback.
   - There are no other retries, no threshold changes and no exclusions.
3. **Cognition.** The COMPARE call is now an advisory cognitive review with no influence on selection. The plan is always the first eligible plan in the deterministic ranking.

## Runs, in order, on the committed bytes

1. **Full suite:** `-B -W error::ResourceWarning`, with no concurrent load.
2. **Definitive series:** fresh state `state_integration_cert3`, one new numpy lineage and one new inference lineage. Each lineage runs DRY_RUN → SHADOW → 2 × CONTROLLED_AUTONOMOUS, with default limits. This is the same design as the previous certification.
3. **Promotion and rollback series:** fresh state `state_integration_cert3_replication`, one new numpy lineage, DRY_RUN → SHADOW → **exactly 6** CONTROLLED_AUTONOMOUS. There is no early stop and every campaign is reported.
4. **Audit and export:** every campaign gets the offline v2 auditor, and the evidence is exported to `final/` and `replication/`.

Fixed reading rules:

- A promotion or rollback counts only if it happened naturally in series 2 or 3.
- No campaign is added, rerun or dropped to obtain one.
- Whatever triggered any rollback, and every first matrix failure, is reported by test ID.
- If series 2 or 3 is interrupted by a host failure, the interrupted campaign is reported as such and the series is not restarted silently.
