# GAIA 1.0 closed-loop evidence

The authoritative export is **[`final/`](final/)**, bound to the frozen implementation
and the final DRY_RUN, SHADOW and CONTROLLED_AUTONOMOUS campaigns.

```sh
python3 -B tools/audit_closed_loop.py --bundle docs/closed_loop_evidence/final
```

Original local CPU attestations were audited before export. Their private mount
paths are omitted in explicitly labelled native privacy projections. Projection
hashes and original-artifact commitments are distinct; the portable audit does
not pretend to recompute unpublished original bytes. It checks the public state
machine, permissions, materialization, projected sandbox checks, protected criteria,
learning and source identities. Original complete attestation audit receipts are
retained with the bundle.

`final/development-history.json` retains IDs, source hashes, outcomes and original
native evidence commitments for development campaigns. Their complete originals
remain in local custody. Do not combine their results with the final series or
relabel failed/interrupted development campaigns as successes.

No runtime, executable, model weight, private raw log or hidden chain-of-thought is
part of this export. Promotion and rollback are certified only if actually exercised
in the final campaign; unit coordination tests and historical v0.1 evidence have
separate, explicitly stated scopes.
