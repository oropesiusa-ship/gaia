#!/usr/bin/env python3
"""Project explicit CPU archive artifacts into portable allowlisted learning evidence.

This verifies artifact/ledger linkages, not full historical campaign certification.
archive-aggregate is an externally verified custody anchor, not recalculated by this bounded reader.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.learning.ingestion import curate_archive
from gaia.provenance import canonical_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--archive-aggregate", required=True)
    parser.add_argument("--gaia-version", default="gaia-v0.1")
    parser.add_argument("--experiment", action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = curate_archive(args.archive, archive_aggregate=args.archive_aggregate,
                                gaia_version=args.gaia_version, experiment_ids=args.experiment)
        with args.output.open("xb") as stream:
            stream.write(canonical_json(result))
        print(json.dumps({"status": "PASS", "experiments": len(result["experiments"]), "source_hash": result["source_hash"]}))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print("Learning curation: FAIL (invalid archive or projection)")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
