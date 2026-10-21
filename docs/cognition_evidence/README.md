# Cognitive orchestration evidence — GAIA 0.9

**The authoritative, final validation bundle is [`final/`](final/).**

```sh
python3 -B tools/audit_cognition.py --bundle docs/cognition_evidence/final
```

The final bundle contains operator-imported validated evidence snapshots,
bounded tasks, contexts with source boundaries, model-request hashes and metrics,
tool proposals, external authorization decisions, reproducible read-only results,
extractive claims, declarative plans, complete traces and protected case scoring.
It contains neither model weights/executables nor private runtime state.

The JSON files and `records/` directly in this parent directory are an earlier
**development validation export**, retained with their original implementation
hashes. Subsequent hardening added strict source-class binding and required-field
checks for plans; current source identity intentionally differs from that earlier
receipt. Do not combine its measurements with the final series or treat its
source-policy hash as the final implementation identity. Use the nested `final/`
bundle for the stage verdict and current offline audit.

No raw model output or hidden chain-of-thought is stored. Accepted bounded
decisions and short tool rationale are data, not authority. Research text remains
external/untrusted. The benchmark demonstrates a small, host-bound collection of
contracted tasks, not general autonomous agency or universal injection immunity.
