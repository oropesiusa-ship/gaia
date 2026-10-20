#!/usr/bin/env python3
"""Offline stage evidence: real CLI executions, immutable exports, regression audit.

Run using an existing local NumPy Python outside /tmp (the sandbox hides /tmp):
  python tools/audit_observation.py --state-dir state_observation_certification \
      --output docs/observation_evidence --test-log /local/full-suite-output
Output is create-only. No campaign, bootstrap, installation or network is invoked.
"""
import argparse
import ast
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia import config, provenance
from gaia.observation.compare import compare
from gaia.observation.schema import canonical_json, validate

BASE = "gaia-v0.1-autonomous-mvp"


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def write(path, value):
    with path.open("xb") as stream:
        stream.write(canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o444)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--test-log", type=Path, required=True)
    args = parser.parse_args()
    if git("branch", "--show-current").decode().strip() != "feat/gaia-0.2-self-observation":
        raise ValueError("Wrong authorized branch")
    baseline_commit = git("rev-parse", BASE + "^{}").decode().strip()
    assert git("merge-base", "HEAD", "main").decode().strip() == baseline_commit
    original = git("ls-tree", "-r", "--name-only", BASE).decode().splitlines()
    changed, preserved = [], []
    for name in original:
        same = (ROOT / name).read_bytes() == git("show", BASE + ":" + name)
        (preserved if same else changed).append(name)
    assert sorted(changed) == ["gaia.py", "gaia/config.py"], changed
    previous_defaults = next(node.value for node in ast.parse(git("show", BASE + ":gaia/config.py")).body
                             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULTS" for t in node.targets))
    old = ast.literal_eval(previous_defaults)
    assert {k: v for k, v in config.DEFAULTS.items() if k != "observation"} == old
    assert provenance.experimental_config(config.DEFAULTS) == provenance.experimental_config(old)
    tests_raw = args.test_log.read_bytes()
    tests = tests_raw.decode()
    match = re.search(r"Ran (\d+) tests in ([0-9.]+)s", tests)
    assert match and re.search(r"^OK \(skipped=9\)$", tests, re.M)
    warnings = re.findall(r"\b\w*Warning:", tests)
    assert not warnings, warnings
    # All checks precede creation; refusal to reuse a state/output preserves evidence.
    assert not args.state_dir.exists() and not args.output.exists()
    args.output.mkdir(parents=True)
    def cli(*arguments):
        proc = subprocess.run([sys.executable, str(ROOT / "gaia.py"), *arguments,
                               "--state-dir", str(args.state_dir), "--json"],
                              cwd=ROOT, capture_output=True, text=True, timeout=90)
        assert proc.returncode == 0, "Observation CLI failed"
        return json.loads(proc.stdout)
    observations = [cli("observe", "--quick", "--baseline"), cli("observe"), cli("observe")]
    assert len(cli("observations")) == 3
    assert cli("observation", "latest") == observations[-1]
    assert cli("observation", "baseline") == observations[0]
    for doc in observations:
        validate(doc)
        raw = canonical_json(doc).decode()
        for private in (getpass.getuser(), socket.gethostname(), str(Path.home()), str(ROOT), sys.executable):
            assert len(private) < 4 or private not in raw, "Privacy assertion failed"
        if doc["sections"]["context"]["mode"] == "full":
            measured = doc["sections"]["measurements"]["workload"]
            assert measured["status"] == "AVAILABLE" and measured["success_count"] == 5
            assert all(sample["sandbox_validation"] and sample["batches"] == 300 for sample in measured["samples"])
        write(args.output / (doc["observation_id"] + ".json"), doc)
    comparison = cli("compare-observations", "o000002", "o000003")
    assert comparison == compare(observations[1], observations[2])
    write(args.output / "comparison.json", comparison)
    protected = [name for name in preserved if name.startswith("gaia/protected/")]
    frozen = [name for name in preserved if name.startswith(("gaia/appliance_", "gaia/gaia_transformer/")) or name == "gaia/cuda_probe.py"]
    audit = {"schema": "gaia_observation_stage_audit_v1", "status": "PASS", "base_commit": baseline_commit,
             "observed_commit": git("rev-parse", "HEAD").decode().strip(),
             "original_files_unchanged": len(preserved), "original_files_changed": changed,
             "protected_files_unchanged": protected, "frozen_files_unchanged": len(frozen),
             "evolution_defaults_unchanged": True, "experimental_config_unchanged": True,
             "tests": {"total": int(match[1]), "skipped": 9, "warnings": len(warnings),
                       "duration_s": float(match[2]), "log_sha256": hashlib.sha256(tests_raw).hexdigest(),
                       "skip_reason": "Torch absent in NumPy profile"},
             "observation_ids": [doc["observation_id"] for doc in observations],
             "observation_hashes": [doc["observation_hash"] for doc in observations],
             "comparison_hash": provenance.digest(comparison), "privacy_checked": True,
             "scope": "local system characterization; no diagnosis or intelligence improvement claim"}
    audit["audit_hash"] = provenance.digest(audit)
    write(args.output / "audit.json", audit)
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
