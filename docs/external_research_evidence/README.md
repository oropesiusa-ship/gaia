# GAIA 0.7 evidence captures

The real request retrieved only two explicitly authorized official Python
documentation URLs, plus `robots.txt`, through GAIA's restricted client.
`real-source-*.json` retain original decoded HTTP body bytes as base64, with
SHA-256, public-destination/TLS retrieval attestations and robots rules.
Original public HTML is retained to make extraction and citations reproducible;
it is not rendered or executed and carries UNTRUSTED_EXTERNAL_CONTENT boundaries.

The capture is evidence about what those sources reported, not proof of the
local Python build, scientific correctness or authority to apply their advice.
Dates in HTTP metadata remain source assertions. The documentation title says
3.14.8 while the explicitly supplied runtime snapshot says 3.14.4.

`real-acquisition.json` records the authorized fetch phase independently from
`real-run.json`. `offline-replay-receipt.json` documents socket/DNS-denied replay.

The injection and hardware files are labelled LOCAL_REPLAY_FIXTURE: they are
controlled tests, not live claims made by those domains. No experiment, package
installation, external code execution or local operational knowledge adoption occurred.

The authoritative final-source audit/test/regression receipts are `verified-*`.
Earlier receipts retain their own source hashes as development history. The
final date-metadata guard does not alter the captured real claims or conclusion.
