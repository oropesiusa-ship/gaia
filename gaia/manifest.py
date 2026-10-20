"""Immutable CPU execution identities and a single fail-closed validation route."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys

from . import provenance
from .protected import sandbox

MANIFEST_SCHEMA = "mvp_cpu_manifest_v1"
HASHES = ("host_hash", "runtime_hash", "source_hash", "config_hash", "sandbox_policy_hash")
FIELD_POLICY = {
    "IDENTITY_CRITICAL": ["host.identity", "runtime", "source", "effective_config", "sandbox.policy"],
    "CAPABILITY_CRITICAL": ["host.capabilities.available_ram_mb >= limits.max_ram_mb",
                            "host.capabilities.effective_memory_mb >= limits.max_ram_mb"],
    "INFORMATIONAL": ["host.information", "created_at", "execution_id", "sandbox.verification.bundle_sha256",
                      "invocation.until", "invocation.minutes", "invocation.max_experiments"],
}

digest = provenance.digest
canonical_json = provenance.canonical_json


def file_hash(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"Symlink artifact: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def _text(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


def host_identity(root, state):
    cpuinfo = _text("/proc/cpuinfo")
    cpu = next((line.split(":", 1)[1].strip() for line in cpuinfo.splitlines()
                if line.startswith(("model name", "Hardware"))), platform.machine())
    cores = set()
    for block in cpuinfo.split("\n\n"):
        fields = dict(line.split(":", 1) for line in block.splitlines() if ":" in line)
        fields = {key.strip(): value.strip() for key, value in fields.items()}
        if "physical id" in fields and "core id" in fields:
            cores.add((fields["physical id"], fields["core id"]))
    memory = {line.split(":")[0]: int(line.split()[1]) / 1024
              for line in _text("/proc/meminfo").splitlines()
              if line.startswith(("MemTotal:", "MemAvailable:"))}
    total = memory.get("MemTotal", 0)
    available = memory.get("MemAvailable", 0)
    limit = None
    for maximum, current in (("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
                             ("/sys/fs/cgroup/memory/memory.limit_in_bytes", "/sys/fs/cgroup/memory/memory.usage_in_bytes")):
        raw = _text(maximum)
        if raw.isdigit() and int(raw) / 2**20 < total:
            limit = int(raw) / 2**20
            used = _text(current)
            if used.isdigit():
                available = min(available, max(0, limit - int(used) / 2**20))
    local_id = _text("/etc/machine-id")
    identity = {"host_id": digest({"domain": "gaia-local-host-v1", "local_id": local_id or cpu,
                                  "architecture": platform.machine()}),
                "system": platform.system(), "architecture": platform.machine(),
                "cpu_model": cpu, "logical_cpus": os.cpu_count(), "physical_cores": len(cores) or None,
                "effective_cpus": len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()}
    return {"identity": identity,
            "capabilities": {"available_ram_mb": available, "effective_memory_mb": min(total, limit or total)},
            "information": {"platform": platform.platform(), "kernel": platform.release(),
                            "ram_total_mb": total, "memory_limit_mb": limit,
                            "workspace_free_mb": shutil.disk_usage(root).free / 2**20,
                            "state_free_mb": shutil.disk_usage(state).free / 2**20}}


def runtime_identity(root, cfg):
    import numpy
    fp = provenance.runtime_identity()
    protected = Path(root) / "gaia/protected"
    bundle = {name: file_hash(protected / name) for name in ("worker.py", "runtime.py", "sandbox.py")}
    declarations = {p: file_hash(Path(root) / p) for p in provenance.source_paths(root)
                    if p.startswith("requirements")}
    build = getattr(numpy.__config__, "CONFIG", {}).get("Build Dependencies", {})
    backends = {name: {key: info.get(key) for key in ("name", "version", "openblas configuration")}
                for name, info in build.items() if name in ("blas", "lapack")}
    return {"python": fp["python"], "implementation": platform.python_implementation(), "libc": list(platform.libc_ver()),
            "interpreter": {"logical_path": "venv/bin/python" if sys.prefix != sys.base_prefix else "system/python",
                            "sha256": file_hash(Path(sys.executable).resolve())},
            "numpy": {"version": fp["numpy"], "module_sha256": file_hash(fp["numpy_file"]),
                      "declared_native_backends": backends},
            "dependency_declarations": declarations, "worker_sha256": bundle["worker.py"],
            "runtime_bundle": bundle, "runtime_bundle_sha256": digest(bundle),
            "deterministic_environment": sandbox.environment(cfg["limits"].get("worker_threads", 1)),
            "rlimits": sandbox.rlimit_policy(cfg["limits"])}


def effective_config(cfg, benchmark):
    value = provenance.experimental_config(cfg)
    value["benchmark"] = benchmark
    n = cfg["acceptance"]["confirm_seeds"]
    value["actual_confirmation_seeds"] = list(range(1000, 1000 + n))
    value["extended_confirmation_seeds"] = [seed + 5 for seed in range(1000, 1000 + n)]
    return json.loads(canonical_json(value))


def source_identity(root, state, snapshot, genome, trainer):
    files = {entry["path"]: entry["sha256"] for entry in provenance.inventory(root)["files"]}
    protected = {p: h for p, h in files.items() if p.startswith("gaia/protected/")}
    return {"snapshot": snapshot, "protected_files": protected, "protected_hash": digest(protected),
            "snippets_sha256": files["gaia/snippets.py"],
            "benchmark_sha256": file_hash(Path(state) / "benchmark.json"),
            "baseline_trainer_sha256": hashlib.sha256(trainer.encode()).hexdigest(),
            "baseline_genome_sha256": digest(genome)}


def identities(host, runtime, source, configuration, policy):
    hashes = {"host_hash": digest(host["identity"]), "runtime_hash": digest(runtime),
              "source_hash": digest(source), "config_hash": digest(configuration),
              "sandbox_policy_hash": digest(policy)}
    return {**hashes, "environment_hash": digest(hashes)}


def seal(value):
    value = json.loads(canonical_json(value))
    value["manifest_hash"] = digest({k: v for k, v in value.items() if k != "manifest_hash"})
    return value


def write_manifest(path, document):
    """Create once, never update. Publication transactions belong to Step 4."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical_json(document))
    path.chmod(0o444)


def build_baseline(eng, snapshot, genome, trainer, verification):
    evidence = verification.get("sandbox_evidence", {})
    policy = sandbox.policy(eng.lim)
    if (verification.get("status") != "ok" or verification.get("sandbox_validation") is not True
            or evidence.get("validated") is not True or evidence.get("active_limits") != policy["rlimits"]
            or not evidence.get("checks") or not all(evidence["checks"].values())
            or evidence.get("handshake", {}).get("environment") != policy["environment"]):
        raise ValueError("Baseline manifest requires verified real CPU sandbox evidence")
    host = host_identity(eng.root, eng.store.dir)
    if any(host["capabilities"][key] < eng.lim["max_ram_mb"] for key in ("available_ram_mb", "effective_memory_mb")):
        raise ValueError("ENVIRONMENT_MISMATCH: host memory below required RAM limit")
    runtime = runtime_identity(eng.root, eng.cfg)
    if (evidence.get("worker_sha256") != runtime["worker_sha256"]
            or evidence.get("candidate_sha256") != hashlib.sha256(trainer.encode()).hexdigest()):
        raise ValueError("Baseline sandbox worker/candidate identity mismatch")
    if any(evidence["bundle_hashes"].get(name) != value for name, value in runtime["runtime_bundle"].items()):
        raise ValueError("Baseline runtime bundle identity mismatch")
    source = source_identity(eng.root, eng.store.dir, snapshot, genome, trainer)
    configuration = effective_config(eng.cfg, eng.bench)
    doc = {"manifest_schema": MANIFEST_SCHEMA, "kind": "baseline", "baseline_version": "v0000",
           **provenance.purpose_metadata(eng.cfg),
           "created_at": timestamp(), "execution_id": eng.execution_id, "field_policy": FIELD_POLICY,
           "host": host, "runtime": runtime, "source": source, "effective_config": configuration,
           "effective_config_hash": digest(configuration),
           "sandbox": {"policy": policy, "verification": {"validated": True,
                       "worker_sha256": evidence["worker_sha256"], "bundle_sha256": evidence["bundle_sha256"],
                       "evidence_hash": digest(evidence)}}}
    doc.update(identities(host, runtime, source, configuration, policy))
    return seal(doc)


def reference(doc):
    return {key: doc[key] for key in ("manifest_hash", "environment_hash", *HASHES)}


def build_experiment(eng, experiment_id, context, genome, trainer, parent_genome, parent_trainer):
    from .readiness import validate_report
    campaign = getattr(eng, "_campaign_context", None)
    if eng.cfg.get("state_purpose") == "autonomous_mvp":
        proposal = getattr(eng, "_proposal_context", None) or {}
        if proposal.get("candidate_origin") not in ("search", "research") or not proposal.get("proposal_trace_path"):
            raise ValueError("Autonomous experiment requires its normal proposal trace, never a manual candidate")
    if not campaign:
        raise ValueError("Experiment requires an explicit successful G0-G5 campaign report")
    checked = validate_report(eng, campaign, genome_hash=digest(genome),
                              trainer_hash=hashlib.sha256(trainer.encode()).hexdigest(), parent=eng.store.current_version())
    if not checked["ok"]:
        raise ValueError(str(checked["errors"]))
    return seal({"manifest_schema": MANIFEST_SCHEMA, "kind": "experiment", "experiment_id": experiment_id,
                 **provenance.purpose_metadata(eng.cfg),
                 **(getattr(eng, "_proposal_context", None) or {}),
                 **campaign,
                 "created_at": timestamp(), "execution_id": eng.execution_id, "baseline_version": "v0000",
                 "baseline_manifest_hash": context["manifest_hash"],
                 **{key: context[key] for key in ("environment_hash", *HASHES)},
                 "source_snapshot_hash": context["source_snapshot"]["aggregate_sha256"],
                 "effective_config_hash": context["config_hash"], "parent_version": eng.store.current_version(),
                 "parent_genome_hash": digest(parent_genome),
                 "parent_trainer_hash": hashlib.sha256(parent_trainer.encode()).hexdigest(),
                 "candidate_genome_hash": digest(genome),
                 "candidate_trainer_hash": hashlib.sha256(trainer.encode()).hexdigest(),
                 "strategy": eng.state["strategy"], "invocation": getattr(eng, "invocation", {})})


def _document(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Manifest symlink forbidden")
    doc = json.loads(path.read_bytes())
    if doc["manifest_schema"] != MANIFEST_SCHEMA:
        raise ValueError("Unsupported manifest_schema")
    if doc["manifest_hash"] != digest({k: v for k, v in doc.items() if k != "manifest_hash"}):
        raise ValueError("Manifest hash mismatch")
    return doc


def _state_path(state, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid state evidence reference")
    path = Path(state) / relative
    if path.is_symlink() or not path.resolve().is_relative_to(Path(state).resolve()):
        raise ValueError("State evidence reference escapes state")
    return path


def _execution_evidence(path, experiment, baseline):
    execution = json.loads(Path(path).read_bytes())
    payload = {k: v for k, v in execution.items() if k != "evidence_hash"}
    if execution["evidence_hash"] != digest(payload):
        raise ValueError("Experiment evidence hash mismatch")
    if any(execution.get(k) != v for k, v in provenance.purpose_metadata(baseline).items()):
        raise ValueError("Certification execution purpose mismatch")
    if (execution["id"] != experiment["experiment_id"] or
            execution["experiment_manifest_hash"] != experiment["manifest_hash"] or
            execution["baseline_manifest_hash"] != baseline["manifest_hash"] or
            execution["environment_hash"] != baseline["environment_hash"] or
            execution["candidate_genome_hash"] != experiment["candidate_genome_hash"] or
            execution["candidate_trainer_hash"] != experiment["candidate_trainer_hash"] or
            execution["execution_id"] != experiment["execution_id"] or
            execution["parent_version"] != experiment["parent_version"]):
        raise ValueError("Experiment evidence references changed")
    if any(execution.get(key) != experiment.get(key) for key in ("campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")):
        raise ValueError("Experiment campaign/gate evidence references changed")
    if experiment.get("proposal_trace_path") and any(execution.get(key) != experiment[key] for key in (
            "proposal_trace_path", "proposal_trace_hash", "candidate_origin")):
        raise ValueError("Experiment proposal origin references changed")
    sandboxes = [trial["result"].get("sandbox_evidence", {}) for trial in execution["trial_metrics"]]
    if digest(sandboxes) != execution["sandbox_evidence_hash"]:
        raise ValueError("Trial sandbox evidence hash mismatch")
    for key in ("started_at", "finished_at"):
        datetime.fromisoformat(execution[key])
    if execution["promotable"] is True and (execution["decision"] != "accepted" or not sandboxes or any(
            trial["result"].get("promotable") is not True or trial["result"].get("status") != "ok" or
            trial["result"].get("sandbox_evidence", {}).get("validated") is not True for trial in execution["trial_metrics"])):
        raise ValueError("Promotable result lacks validated sandbox evidence")
    return execution


def validate_stable_artifacts(eng, directory, baseline, *, expected_version):
    """Validate a stable version (also usable on staging before CURRENT exists)."""
    from . import genome as G, publication
    directory = Path(directory)
    if directory.is_symlink() or {p.name for p in directory.iterdir()} != publication.ARTIFACTS:
        raise ValueError("Stable version must contain exactly four regular artifacts")
    if any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
        raise ValueError("Stable artifact is not a regular file")
    doc = _document(directory / "manifest.json")
    evidence = json.loads((directory / "evidence.json").read_bytes())
    if any(doc.get(k) != v or evidence.get(k) != v for k, v in provenance.purpose_metadata(baseline).items()):
        raise ValueError("Certification stable version purpose mismatch")
    genome = json.loads((directory / "genome.json").read_bytes())
    source = (directory / "trainer.py").read_bytes().decode("utf-8")
    if doc["kind"] != "stable" or doc["version"] != expected_version:
        raise ValueError("Stable manifest version/kind mismatch")
    if source != G.render(genome) or file_hash(directory / "trainer.py") != doc["candidate_trainer_hash"] or digest(genome) != doc["candidate_genome_hash"]:
        raise ValueError("Stable trainer/genome hash/render mismatch")
    if (doc["baseline_version"] != "v0000" or doc["baseline_manifest_hash"] != baseline["manifest_hash"] or
            doc["source_snapshot"] != baseline["source"]["snapshot"] or doc["effective_config_hash"] != baseline["config_hash"] or
            any(doc[key] != baseline[key] or evidence[key] != baseline[key] for key in ("environment_hash", *HASHES))):
        raise ValueError("Stable environment/source/config/sandbox identity mismatch")
    payload = {k: value for k, value in evidence.items() if k not in ("manifest_hash", "evidence_hash")}
    if evidence["manifest_hash"] != doc["manifest_hash"] or evidence["evidence_hash"] != doc["evidence_hash"] or digest(payload) != doc["evidence_hash"]:
        raise ValueError("Stable evidence hash/manifest reference mismatch")
    path = _state_path(eng.store.dir, doc["experiment_manifest_path"])
    experiment = _document(path)
    evidence_path = _state_path(eng.store.dir, doc["experiment_evidence_path"])
    if evidence_path != path.with_name("evidence.json"):
        raise ValueError("Stable experiment evidence path mismatch")
    completed = _execution_evidence(evidence_path, experiment, baseline)
    from . import readiness
    gates = readiness.validate_report(eng, experiment, genome_hash=experiment["candidate_genome_hash"],
                                      trainer_hash=experiment["candidate_trainer_hash"], parent=experiment["parent_version"], compare_current=False)
    if not gates["ok"]:
        raise ValueError(str(gates["errors"]))
    readiness.validate_pre_promotion(eng, evidence, experiment, completed, compare_current=False)
    if any(doc[key] != evidence[key] for key in ("pre_promotion_path", "pre_promotion_hash")):
        raise ValueError("Stable pre-promotion manifest/evidence reference mismatch")
    for key in ("parent_version", "experiment_id", "candidate_genome_hash", "candidate_trainer_hash", "execution_id"):
        if doc[key] != experiment[key]:
            raise ValueError("Stable experiment reference mismatch: " + key)
    parent = doc["parent_version"]
    if not isinstance(parent, str) or not parent.startswith("v") or not parent[1:].isdigit() or int(parent[1:]) >= int(expected_version[1:]):
        raise ValueError("Invalid stable parent lineage")
    parent_manifest = _document(eng.store.stable / parent / "manifest.json")
    pg, ps = eng.store.load_version(parent)
    if (doc["parent_manifest_hash"] != parent_manifest["manifest_hash"] or
            digest(pg) != experiment["parent_genome_hash"] or _sha_text(ps) != experiment["parent_trainer_hash"]):
        raise ValueError("Stable parent manifest/artifacts changed")
    if (doc["experiment_manifest_hash"] != experiment["manifest_hash"] or doc["experiment_evidence_hash"] != completed["evidence_hash"] or
            experiment["baseline_manifest_hash"] != baseline["manifest_hash"] or
            any(experiment[key] != baseline[key] for key in ("environment_hash", *HASHES))):
        raise ValueError("Stable origin evidence/reference mismatch")
    if (evidence["version"] != expected_version or evidence["parent_version"] != parent or
            evidence["promoted_from"] != experiment["experiment_id"] or evidence["experiment_id"] != experiment["experiment_id"] or
            evidence["decision"] != "accepted" or evidence["timestamp"] != doc["created_at"] or
            evidence["trainer_hash"] != doc["candidate_trainer_hash"] or evidence["genome_hash"] != doc["candidate_genome_hash"] or
            evidence["baseline_manifest_hash"] != baseline["manifest_hash"] or
            evidence["experiment_manifest_hash"] != doc["experiment_manifest_hash"] or
            evidence["experiment_evidence_hash"] != doc["experiment_evidence_hash"]):
        raise ValueError("Stable promotion evidence is incomplete/inconsistent")
    if evidence["confirm"] != publication.confirmation(baseline, experiment, completed):
        raise ValueError("Stable statistical evidence mismatch")
    return doc


def _sha_text(source):
    return hashlib.sha256(source.encode()).hexdigest()


def validate_manifest(eng, path=None, *, compare_current=True, expected_hash=None, require_current_parent=False,
                      _baseline_dir=None, _current_version=None):
    """One route for baseline/delta integrity and current-environment compatibility."""
    checks = {name: False for name in ("manifest", "source", "environment", "runtime", "config", "sandbox_policy", "host")}
    result = {"ok": False, "code": "ENVIRONMENT_MISMATCH", "checks": checks, "errors": []}
    try:
        base_dir = Path(_baseline_dir) if _baseline_dir is not None else eng.store.stable / "v0000"
        if {p.name for p in base_dir.iterdir()} != {"trainer.py", "genome.json", "manifest.json", "evidence.json"}:
            raise ValueError("Baseline has incomplete/unexpected stable artifacts")
        if base_dir.is_symlink() or any(p.is_symlink() or not p.is_file() for p in base_dir.iterdir()):
            raise ValueError("Baseline artifacts must be regular files")
        baseline = _document(base_dir / "manifest.json")
        if expected_hash is not None and (path is None or Path(path) == base_dir / "manifest.json") and baseline["manifest_hash"] != expected_hash:
            raise ValueError("Baseline manifest expected hash mismatch")
        state = eng.store.load_state()
        evidence = json.loads((base_dir / "evidence.json").read_bytes())
        if baseline["kind"] != "baseline" or baseline["baseline_version"] != "v0000":
            raise ValueError("Invalid baseline manifest kind/version")
        purpose = provenance.purpose_metadata(eng.cfg)
        if bool(baseline.get("certification_only")) != bool(purpose.get("certification_only")):
            raise ValueError("Certification/autonomous manifest purpose mismatch")
        if any(baseline.get(k) != v or evidence.get(k) != v or state.get(k) != v for k, v in purpose.items()):
            raise ValueError("Certification purpose markers changed")
        if baseline["field_policy"] != FIELD_POLICY:
            raise ValueError("Unsupported manifest compatibility policy")
        if state["baseline_manifest_hash"] != baseline["manifest_hash"]:
            raise ValueError("Baseline manifest/state anchor mismatch")
        for key, value in reference(baseline).items():
            if evidence[key] != value:
                raise ValueError(f"Baseline evidence reference mismatch: {key}")
        expected = identities(baseline["host"], baseline["runtime"], baseline["source"],
                              baseline["effective_config"], baseline["sandbox"]["policy"])
        if any(baseline[key] != value for key, value in expected.items()):
            raise ValueError("Manifest hierarchical hashes mismatch")
        if baseline["effective_config_hash"] != baseline["config_hash"]:
            raise ValueError("Effective config hash mismatch")
        if baseline["sandbox"]["verification"]["validated"] is not True:
            raise ValueError("Baseline lacks sandbox validation")
        proof = evidence["sandbox_verification"]
        if (digest(proof) != baseline["sandbox"]["verification"]["evidence_hash"] or
                proof["validated"] is not True or proof["active_limits"] != baseline["runtime"]["rlimits"] or
                proof["handshake"]["environment"] != baseline["runtime"]["deterministic_environment"] or
                evidence["timestamp"] != baseline["created_at"] or
                evidence["execution_id"] != baseline["execution_id"] or
                evidence["benchmark_summary"] != baseline["effective_config"]["benchmark"]["calibrated"]):
            raise ValueError("Baseline execution evidence mismatch")
        checks["manifest"] = True
        source = baseline["source"]
        if state["source_snapshot"] != source["snapshot"]:
            raise ValueError("Snapshot reference changed")
        if evidence["source_snapshot"] != source["snapshot"]:
            raise ValueError("Baseline evidence snapshot changed")
        snapshot_id = source["snapshot"]["snapshot_id"]
        if not isinstance(snapshot_id, str) or not snapshot_id.startswith("src-") or not snapshot_id[4:].isdigit():
            raise ValueError("Invalid source snapshot path")
        directory = eng.store.dir / "provenance/snapshots" / snapshot_id
        snapshot = provenance.validate_snapshot(directory, source["snapshot"])
        if not snapshot["ok"]:
            raise ValueError("Source snapshot integrity failed: " + str(snapshot))
        genome = json.loads((base_dir / "genome.json").read_bytes())
        trainer = (base_dir / "trainer.py").read_text()
        from . import genome as G
        if trainer != G.render(genome):
            raise ValueError("Baseline trainer differs from G.render(genome)")
        if (digest(genome) != source["baseline_genome_sha256"] or
                file_hash(base_dir / "trainer.py") != source["baseline_trainer_sha256"] or
                file_hash(eng.store.dir / "benchmark.json") != source["benchmark_sha256"]):
            raise ValueError("Baseline trainer/genome/benchmark changed")
        if evidence["trainer_hash"] != source["baseline_trainer_sha256"] or evidence["genome_hash"] != digest(genome):
            raise ValueError("Baseline artifact evidence mismatch")
        current_version = _current_version if _current_version is not None else eng.store.current_version()
        if (not isinstance(current_version, str) or not current_version.startswith("v") or
                not current_version[1:].isdigit()):
            raise ValueError("Invalid current stable version")
        if current_version != "v0000":
            validate_stable_artifacts(eng, eng.store.stable / current_version, baseline, expected_version=current_version)
        checks["source"] = True
        current_bench = eng.bench if eng.bench is not None else json.loads((eng.store.dir / "benchmark.json").read_bytes())
        if compare_current:
            if eng.lim != eng.cfg["limits"] or eng.acc != eng.cfg["acceptance"]:
                raise ValueError("Engine active limits/acceptance differ from effective configuration")
            current_source = source_identity(eng.root, eng.store.dir, state["source_snapshot"], genome, trainer)
            comparison = provenance.compare_sources(eng.root, directory, eng.cfg)
            if not comparison["ok"] or current_source != source:
                checks["source"] = False
                raise ValueError("Certified source/protected files/worker mismatch: " + str(comparison))
            current_runtime = runtime_identity(eng.root, eng.cfg)
            checks["runtime"] = digest(current_runtime) == baseline["runtime_hash"]
            checks["config"] = digest(effective_config(eng.cfg, current_bench)) == baseline["config_hash"]
            checks["sandbox_policy"] = digest(sandbox.policy(eng.cfg["limits"])) == baseline["sandbox_policy_hash"]
            current_host = host_identity(eng.root, eng.store.dir)
            checks["host"] = digest(current_host["identity"]) == baseline["host_hash"]
            required = eng.cfg["limits"]["max_ram_mb"]
            if any(current_host["capabilities"][k] < required for k in ("effective_memory_mb", "available_ram_mb")):
                raise ValueError("Host memory below required RAM limit (CAPABILITY_CRITICAL)")
            for name in ("runtime", "config", "sandbox_policy", "host"):
                if not checks[name]:
                    raise ValueError(f"{name} identity mismatch (IDENTITY_CRITICAL)")
        else:
            checks.update(runtime=True, config=True, sandbox_policy=True, host=True)
        checks["environment"] = True
        if path is not None and Path(path) != base_dir / "manifest.json":
            experiment = _document(path)
            if expected_hash is not None and experiment["manifest_hash"] != expected_hash:
                raise ValueError("Version/experiment manifest anchor mismatch")
            if experiment["kind"] == "stable":
                result["stable"] = validate_stable_artifacts(eng, Path(path).parent, baseline,
                                                            expected_version=Path(path).parent.name)
                result.update(ok=True, code=None, identity=reference(baseline), baseline=baseline)
                return result
            if experiment["kind"] != "experiment" or experiment["baseline_manifest_hash"] != baseline["manifest_hash"]:
                raise ValueError("Experiment baseline reference mismatch")
            if any(experiment.get(k) != v for k, v in provenance.purpose_metadata(baseline).items()):
                raise ValueError("Certification experiment purpose mismatch")
            if experiment.get("proposal_trace_path"):
                trace = json.loads(_state_path(eng.store.dir, experiment["proposal_trace_path"]).read_bytes())
                if (trace["trace_hash"] != experiment["proposal_trace_hash"] or trace["trace_hash"] != digest({k: v for k, v in trace.items() if k != "trace_hash"}) or
                        trace["genome_hash"] != experiment["candidate_genome_hash"] or trace["trainer_hash"] != experiment["candidate_trainer_hash"] or
                        trace["candidate_origin"] != experiment["candidate_origin"]):
                    raise ValueError("Proposal trace identity mismatch")
            from .readiness import validate_report
            gates = validate_report(eng, experiment, genome_hash=experiment["candidate_genome_hash"],
                                    trainer_hash=experiment["candidate_trainer_hash"], parent=experiment["parent_version"], compare_current=False)
            if not gates["ok"]:
                raise ValueError(str(gates["errors"]))
            if experiment["invocation"] != gates["report"]["invocation"]:
                raise ValueError("Experiment invocation differs from campaign gates")
            if any(experiment[key] != baseline[key] for key in ("environment_hash", *HASHES)):
                raise ValueError("Experiment environment reference mismatch")
            if (experiment["source_snapshot_hash"] != source["snapshot"]["aggregate_sha256"] or
                    experiment["effective_config_hash"] != baseline["config_hash"]):
                raise ValueError("Experiment snapshot/config reference mismatch")
            experiment_dir = Path(path).parent
            candidate = json.loads((experiment_dir / "genome.json").read_bytes())
            if digest(candidate) != experiment["candidate_genome_hash"] or file_hash(experiment_dir / "trainer.py") != experiment["candidate_trainer_hash"]:
                raise ValueError("Candidate genome/trainer mismatch")
            parent = experiment["parent_version"]
            if not isinstance(parent, str) or not parent.startswith("v") or not parent[1:].isdigit():
                raise ValueError("Invalid experiment parent")
            pg, ps = eng.store.load_version(parent)
            if digest(pg) != experiment["parent_genome_hash"] or hashlib.sha256(ps.encode()).hexdigest() != experiment["parent_trainer_hash"]:
                raise ValueError("Experiment parent changed")
            if require_current_parent and eng.store.current_version() != parent:
                raise ValueError("Current parent changed during experiment")
            evidence_path = experiment_dir / "evidence.json"
            if evidence_path.exists():
                _execution_evidence(evidence_path, experiment, baseline)
            result["experiment"] = experiment
        result.update(ok=True, code=None, identity=reference(baseline), baseline=baseline)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        result["errors"].append("ENVIRONMENT_MISMATCH: " + str(exc))
    return result
