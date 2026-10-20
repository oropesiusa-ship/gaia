# GAIA 0.6 static evidence

The authoritative final certification evidence is under `final/`.
The `final/verified-*` receipts bind to the source hashes of the final interpreter
and include the CLI audit, tests and unchanged-baseline checks. Earlier receipts
inside `final/` remain source-specific development history; they do not replace
the verified receipts.

The JSON files directly in this directory retain the preliminary validation
at `22835a2`, before the cross-summary exact-negative guard was strengthened.
They are development history, superseded for certification by `final/`, not
additional experimental outcomes or independent replications.

Historical Test B uses real saved v0.5 knowledge with an explicitly controlled
target labelled HISTORICAL_ANALYSIS. It does not claim a current host problem.
Other synthetic cases are labelled by filename; no plan was executed.
