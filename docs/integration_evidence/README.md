# GAIA 1.0.1 integration evidence

Portable export of the **definitive** certification series in [`final/`](final/). All eight
campaigns ran on the frozen bytes of commit `bdce836` (source identity `48041114…370b`) in a
fresh state (`state_integration_final2`) with two new lineages, one numpy lineage and one
inference lineage.

[`superseded-af70650/`](superseded-af70650/) is the first final series, run on `af70650`
(identity `2a93e2be…78b6`). It shows the complete natural promotion chain, and it was superseded
because later fixes changed hashed sources. It is development evidence and is never combined
with `final/`.

Layout of each export:

- `campaigns/<surface>-<mode>.json`: for each campaign, the contract, the final report, the offline v2 audit result produced on the original local state, and its Annex B experiment records.
- `lineages/<id>.json`: the committed lineage contract and journal, and the derived state.
- `manifest.json`: SHA-256 digests of the exported documents.
- `development-history.json` (top level): all development and superseded campaigns under earlier source identities. They are **not** part of the final series and must not be combined with it.
- `tests.json` (top level): the full-suite result on the definitive bytes.

Re-audit the original local state (requires the same source identity):

```sh
python3 -B tools/audit_closed_loop.py --state-dir state_integration_final2 --campaign <campaign-id>
```

Re-export (read-only on state; the export is refused if it would contain a private path):

```sh
python3 -B tools/export_integration_evidence.py --state-dir state_integration_final2 --out <dir> label=<campaign-id> ...
```

Not exported: engine trial attestations with local mount paths, runtime binaries, model
weights, raw logs and hidden reasoning. The audit results embedded here were computed on
the originals before export.
