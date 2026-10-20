"""Explicit CPU archive projection. Fixed artifacts only; no Engine or executable source imports."""
import hashlib
import json
from pathlib import Path
import re

from ..provenance import canonical_json, digest
from .schema import HP, SLOTS, SOURCE_SCHEMA, finite, seal_source, validate_source


def project_configuration(genome):
    return {"genome_hash": digest(genome), "code_variation_hash": digest({"lits": genome.get("lits", {}), "drops": genome.get("drops", [])}),
            "hp": {k: genome["hp"][k] for k in sorted(HP)}, "slots": {k: genome["slots"][k] for k in sorted(SLOTS)}}


def load_source(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Source symlink forbidden")
    raw = path.read_bytes()
    value = validate_source(json.loads(raw))
    if canonical_json(value) != raw:
        raise ValueError("Source JSON must be canonical")
    return value


def curate_archive(root, *, archive_aggregate, gaia_version="gaia-v0.1", experiment_ids=None):
    root = Path(root).resolve()
    refs = {}
    def raw(relative):
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Unsafe archive reference")
        value = path.read_bytes()
        refs[relative] = {"path": relative, "sha256": hashlib.sha256(value).hexdigest()}
        return value
    def read(relative, field=None, exclusions=()):
        value = json.loads(raw(relative))
        if field and value.get(field) != digest({k: v for k, v in value.items() if k not in (field, *exclusions)}):
            raise ValueError("Archive artifact hash mismatch")
        return value
    baseline = read("stable/v0000/manifest.json", "manifest_hash")
    if baseline["manifest_schema"] != "mvp_cpu_manifest_v1" or baseline["kind"] != "baseline":
        raise ValueError("Unsupported archive")
    genome = read("stable/v0000/genome.json")
    if digest(genome) != baseline["source"]["baseline_genome_sha256"]:
        raise ValueError("Baseline genotype mismatch")
    benchmark = read("benchmark.json")
    if refs["benchmark.json"]["sha256"] != baseline["source"]["benchmark_sha256"]:
        raise ValueError("Benchmark identity mismatch")
    cfg = baseline["effective_config"]
    if cfg["workload"]["id"] != "numpy_mlp":
        raise ValueError("Only CPU numpy_mlp archives are supported")
    chain = [json.loads(line) for line in raw("ledger.jsonl").decode().splitlines()]
    previous = None
    for index, event in enumerate(chain, 1):
        if (event["ledger_schema"] != "mvp_cpu_ledger_v1" or event["sequence"] != index or event["previous_hash"] != previous
                or event["record_hash"] != digest({k: v for k, v in event.items() if k != "record_hash"})):
            raise ValueError("Archived ledger chain invalid")
        previous = event["record_hash"]
    ids = experiment_ids if experiment_ids is not None else [p.name for p in sorted((root / "experiments").glob("e[0-9]*"))]
    experiments = []
    for eid in ids:
        if not re.fullmatch(r"e[0-9]{5,}", eid):
            raise ValueError("Invalid experiment id")
        manifest = read(f"experiments/{eid}/manifest.json", "manifest_hash")
        evidence = read(f"experiments/{eid}/evidence.json", "evidence_hash")
        candidate = read(f"experiments/{eid}/genome.json")
        if (manifest["kind"] != "experiment" or manifest["experiment_id"] != eid or evidence["id"] != eid
                or evidence["experiment_manifest_hash"] != manifest["manifest_hash"]
                or evidence["baseline_manifest_hash"] != baseline["manifest_hash"]
                or digest(candidate) != evidence["candidate_genome_hash"] or digest(candidate) != manifest["candidate_genome_hash"]
                or any(manifest[k] != baseline[k] for k in ("host_hash", "runtime_hash", "environment_hash", "source_hash"))):
            raise ValueError("Archive experiment identity mismatch")
        events = [r for r in chain if r["event_type"] == "experiment_completed" and r["payload"].get("id") == eid]
        if len(events) != 1 or events[0]["payload"]["evidence_hash"] != evidence["evidence_hash"]:
            raise ValueError("Completion ledger reference mismatch")
        for ref in events[0].get("references", []):
            if ref["path"] in refs and refs[ref["path"]]["sha256"] != ref["sha256"]:
                raise ValueError("Ledger artifact reference mismatch")
        outcome = {"accepted": "ACCEPTED", "rejected": "REJECTED", "deferred": "INCONCLUSIVE", "pareto_alternative": "INCONCLUSIVE"}.get(evidence["decision"])
        if outcome is None:
            raise ValueError("Unsupported completion outcome")
        parent_version = manifest["parent_version"]
        if not re.fullmatch(r"v[0-9]{4,}", parent_version):
            raise ValueError("Unsafe parent version")
        parent_genome = genome if parent_version == "v0000" else read(f"stable/{parent_version}/genome.json")
        if digest(parent_genome) != manifest["parent_genome_hash"]:
            raise ValueError("Experimental parent genotype mismatch")
        confirmation = evidence.get("confirm")
        if confirmation:
            costs = list(zip(confirmation.get("champ_costs", []), confirmation.get("cand_costs", [])))
            costs = [(a, b) for a, b in costs if finite(a) and finite(b) and a > 0 and b > 0]
            confirmation = {"pairs": len(costs), "trial_count": confirmation["n"], "baseline_costs": [a for a, _ in costs],
                            "candidate_costs": [b for _, b in costs], "candidate_reached": confirmation["cand_reached"],
                            "baseline_reached": confirmation["champ_reached"], "ratio": confirmation.get("ratio"),
                            "upper95": confirmation.get("ratio_upper95"), "min_gain": cfg["acceptance"]["min_gain"],
                            "decision": confirmation["decision"]}
        promotions = [r for r in chain if r["event_type"] == "version_promoted" and r["payload"].get("experiment_id") == eid]
        versions = [manifest["parent_version"]]
        rollback = "NONE"
        publication_refs = []
        for event in promotions:
            version = event["payload"]["version"]
            if not re.fullmatch(r"v[0-9]{4,}", version):
                raise ValueError("Unsafe promoted version")
            promoted = read(f"stable/{version}/manifest.json", "manifest_hash")
            stable_evidence = read(f"stable/{version}/evidence.json", "evidence_hash", ("manifest_hash",))
            if (promoted["experiment_id"] != eid or promoted["experiment_evidence_hash"] != evidence["evidence_hash"]
                    or stable_evidence["experiment_evidence_hash"] != evidence["evidence_hash"]
                    or stable_evidence["manifest_hash"] != promoted["manifest_hash"]
                    or promoted["evidence_hash"] != stable_evidence["evidence_hash"]
                    or promoted["manifest_hash"] != event["payload"]["manifest_hash"]):
                raise ValueError("Promotion linkage mismatch")
            versions.append(version)
            publication_refs += [f"stable/{version}/manifest.json", f"stable/{version}/evidence.json"]
            rollbacks = [r for r in chain if r["event_type"] == "rollback" and r["payload"].get("from_version") == version]
            if rollbacks:
                # Only the exact historical verification label is recognized as non-adverse.
                rollback = "VERIFICATION" if all(r["payload"].get("reason") == "Autonomous MVP verification rollback" for r in rollbacks) else "UNKNOWN"
        relevant = [r["record_hash"] for r in events + promotions]
        relevant += [r["record_hash"] for r in chain if r["event_type"] == "rollback" and r["payload"].get("from_version") in versions[1:]]
        artifact_names = ["stable/v0000/manifest.json", "stable/v0000/genome.json", "benchmark.json", "ledger.jsonl",
                          f"experiments/{eid}/manifest.json", f"experiments/{eid}/evidence.json", f"experiments/{eid}/genome.json", *publication_refs]
        if parent_version != "v0000":
            artifact_names.append(f"stable/{parent_version}/genome.json")
        experiments.append({"experiment_id": eid, "execution_hash": digest({"execution_id": evidence["execution_id"]}),
                            "evidence_hash": evidence["evidence_hash"], "manifest_hash": manifest["manifest_hash"],
                            "context": {**{k: baseline[k] for k in ("environment_hash", "host_hash", "runtime_hash", "source_hash")},
                                        "benchmark_hash": baseline["source"]["benchmark_sha256"], "workload": "numpy_mlp", "trainer_family": "numpy_mlp",
                                        "quality_threshold": benchmark["calibrated"]["main"]["target"], "gaia_version": gaia_version,
                                        "baseline_version": manifest["parent_version"]},
                            "candidate": project_configuration(candidate), "baseline": project_configuration(parent_genome), "outcome": outcome,
                            "screen": {"status": evidence["screen"]["status"], "reached": evidence["screen"]["reached"],
                                       "cost_s": evidence["screen"].get("cost_s"), "baseline_cost_s": evidence.get("parent_cost")},
                            "confirmation": confirmation, "versions": sorted(set(versions)), "promotion": bool(promotions), "rollback": rollback,
                            "ledger_refs": relevant, "artifacts": [refs[p] for p in artifact_names], "finished_at": evidence["finished_at"]})
    return seal_source({"schema": SOURCE_SCHEMA, "provenance": {"kind": "CURATED_CPU_ARCHIVE", "archive_aggregate": archive_aggregate,
                                                                "projection_version": "cpu_projection_v1"}, "experiments": experiments})
