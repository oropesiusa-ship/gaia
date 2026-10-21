# Local intelligence evidence — GAIA 0.8

This directory is a portable, **offline** evidence export. `manifest.json` binds
each JSON document by SHA-256 and identifies the final benchmark set, host-bound
budget revision, and selection. It contains public research captures, observation
evidence, immutable qualification records, benchmark responses, and controlled
inference receipts. Executables, weights, caches, private scratch directories,
and signed CDN download URLs are retained outside this export.

```sh
python3 -B tools/audit_local_intelligence.py docs/local_intelligence_evidence
```

The audit checks identities, upstream acquisition proofs, observed resource
budgets, complete protected workloads, recomputed quality/statistics, final
isolation evidence, and reproducibility of selection/Pareto decisions. It neither
downloads nor runs anything. Recorded runtime measurements are host-bound
observations, not independent hardware attestations or a universal model ranking.

Historical failures remain in the export. The final manifest selects the final
measurement set explicitly; earlier attempts preserve their original implementation
hashes and are not silently combined into a single comparable run. Model outputs
and public source content remain untrusted data with no tool or policy authority.
