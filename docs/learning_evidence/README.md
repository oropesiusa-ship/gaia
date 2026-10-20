# Curated GAIA 0.5 evidence

`test-b-sources.json` is a bounded, allowlisted projection of the archived GAIA
v0.1 autonomous Test B artifacts, not a new campaign. Original artifact SHA-256,
manifest/evidence hashes and relevant ledger record hashes are retained.

Historical archive aggregate:
`da15a56bf3c508955ebea945a925b0d886131601eb98674ad6a80fa039f3cab9`.
This custody anchor matches the v0.1 historical evidence index. The projection
can be reproduced from an explicit local archive with
`tools/curate_learning_sources.py`. Its bounded verification checks manifests,
genotypes, benchmark, ledger chain and completion/promotion linkages; it does
not rerun or recertify the original experimental pipeline.

Portable consumers validate the curated source hash and schema; hashes alone
cannot prove the fidelity of a projection without its original artifacts.
There are no personal paths or runtime dumps in the curated projection.
