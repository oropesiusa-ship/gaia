# GAIA 1.0.1 integration evidence

The current certification runs on commit `09de7eb` (source identity `3383b6a2…1290`). It was
pre-registered in [`PREREGISTRATION.md`](PREREGISTRATION.md) before any run on those bytes.

- [`final/`](final/): the definitive series (state `state_integration_cert4`): one numpy lineage and one inference lineage, each running DRY_RUN → SHADOW → 2 × CONTROLLED.
- [`replication/`](replication/): the pre-registered promotion/rollback series (state `state_integration_cert4_replication`): one numpy lineage, DRY_RUN → SHADOW → exactly 6 CONTROLLED.
- `tests.json`: the full-suite result on the certified bytes.

[`development/`](development/) holds everything earlier. It is **never** combined with the current certification:

| Path | Bytes | Content |
| --- | --- | --- |
| `development-history.json` | four early identities | 19 development and superseded campaigns |
| `af70650-final/` | `af70650` | first final series (natural promotion chain) |
| `BDCE836_CERTIFICATION.md`, `bdce836-final/`, `bdce836-tests.json` | `bdce836` | previous certification, invalidated by the fixes |
| `bdce836-post-certification/` | `bdce836` | pre-registered replication series, rollback, counterbalanced cognitive evaluation and their pre-registration |
| `26c828c-interrupted/` | `26c828c` | re-certification interrupted externally. The recovered campaign fails its own audit (`ROLLBACK_WITHOUT_REFERENCE_REMEASUREMENT`), which led to the `09de7eb` fix. The inference SHADOW campaign that was stopped mid-run is not exported. |
| `09de7eb-suite-attempts.json` | `09de7eb` | two full-suite runs under interactive desktop load, each with one host-timing failure |

Layout of each export:

- `campaigns/<label>.json`: for each campaign, the contract, the final report, the offline v2 audit result produced on the original local state, and its Annex B experiment records.
- `lineages/<id>.json`: the committed lineage contract and journal, and the derived state.
- `manifest.json`: SHA-256 digests of the exported documents.

Audits are bound to source identity. Re-audit an export with the auditor from its own commit:

```sh
python3 -B tools/audit_closed_loop.py --state-dir <state> --campaign <campaign-id>
```

The exporter refuses any export that would contain a private path. Not exported: engine trial
attestations with local mount paths, runtime binaries, model weights, raw logs and hidden reasoning.
