"""Local CPU source snapshots: files, canonical JSON and SHA-256 only."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

STATE_SCHEMA = "mvp_cpu_v1"
SNAPSHOT_SCHEMA = "cpu_source_snapshot_v1"
CPU_MODULES = (
    "__init__", "atomic_publish", "bootstrap", "config", "engine", "genome", "integrity", "ledger", "manifest", "meta", "publication",
    "mutate", "observe_worker", "provenance", "readiness", "report", "research",
    "rollback", "search", "snippets", "stats", "store",
)
PROTECTED_MODULES = ("__init__", "benchmark", "evaluator", "guard", "runtime", "task", "worker")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_json(value)).hexdigest()


def certification_metadata(value):
    """Purpose labels only, never a permission to skip a validation."""
    if value.get("certification_only") is not True:
        return {}
    return {"certification": True, "certification_only": True, "state_purpose": "pipeline_certification",
            "candidate_origin": "certification_controlled", "autonomous_self_improvement_certified": False}


def purpose_metadata(value):
    certified = certification_metadata(value)
    if certified:
        return certified
    if value.get("state_purpose") == "autonomous_mvp":
        if value.get("certification") is not False or value.get("certification_only") is not False:
            raise ValueError("Autonomous MVP requires explicit non-certification state markers")
        return {"state_purpose": "autonomous_mvp", "certification": False, "certification_only": False}
    return {}


def source_paths(root):
    """The single CPU inclusion policy, including newly added relevant modules."""
    root = Path(root)
    paths = {"gaia.py", "gaia/bootstrap_profiles.json"}
    paths.update(f"gaia/{name}.py" for name in CPU_MODULES)
    paths.update(f"gaia/protected/{name}.py" for name in PROTECTED_MODULES)
    paths.update(p.relative_to(root).as_posix() for p in (root / "gaia").glob("*.py")
                 if not p.name.startswith("appliance_") and p.name != "cuda_probe.py")
    paths.update(p.relative_to(root).as_posix() for p in (root / "gaia/protected").glob("*.py"))
    for pattern in ("requirements.txt", "requirements/*cpu*", "gaia/bootstrap_tools.json"):
        paths.update(p.relative_to(root).as_posix() for p in root.glob(pattern) if p.is_file())
    return sorted(paths)


def _read_file(root, relative):
    path = Path(root) / relative
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError(f"Source symlink/path escape: {relative}")
    return path.read_bytes()


def inventory(root):
    result = {"files": [], "missing": [], "errors": []}
    for relative in source_paths(root):
        try:
            contents = _read_file(root, relative)
            result["files"].append({"path": relative, "sha256": hashlib.sha256(contents).hexdigest()})
        except FileNotFoundError:
            result["missing"].append(relative)
        except (OSError, ValueError) as exc:
            result["errors"].append(str(exc))
    result["ok"] = not result["missing"] and not result["errors"]
    return result


def runtime_identity():
    from .protected import runtime
    return runtime.fingerprint(with_torch=False)


def experimental_config(configuration):
    """Behavioral CPU fields only; UI/storage paths are not experimental identity."""
    keys = ("benchmark_profile", "limits", "acceptance", "stop", "meta", "research", "readiness")
    value = {key: configuration[key] for key in keys if key in configuration}
    value["workload"] = {"id": configuration.get("workload", {}).get("id", "numpy_mlp")}
    value.update(purpose_metadata(configuration))
    if "readiness" in value:
        value["readiness"] = {**value["readiness"], "require_sandbox": True}
    return json.loads(canonical_json(value))


def runtime_critical(value):
    return {key: value.get(key) for key in ("python", "executable", "prefix", "machine", "numpy", "numpy_file")}


def aggregate_hash(files, configuration):
    return digest({"schema": SNAPSHOT_SCHEMA, "state_schema": STATE_SCHEMA,
                   "files": sorted(files, key=lambda entry: entry["path"]),
                   "config_hash": digest(experimental_config(configuration))})


def bwrap_capability():
    binary = shutil.which("bwrap")
    result = {"available": bool(binary), "verified": False, "reason": None,
              "binary": binary, "capabilities": []}
    if not binary:
        result["reason"] = "bwrap not found"
        return result
    try:
        proc = subprocess.run([binary, "--die-with-parent", "--unshare-user", "--unshare-pid",
                               "--unshare-net", "--ro-bind", "/", "/", "--proc", "/proc",
                               "--dev", "/dev", "/usr/bin/true"],
                              capture_output=True, text=True, timeout=5)
        result["verified"] = proc.returncode == 0
        result["reason"] = None if result["verified"] else (
            f"bwrap smoke exit {proc.returncode}: {proc.stderr.strip()[:500]}")
        if result["verified"]:
            result["capabilities"] = ["user_namespace", "pid_namespace", "net_namespace"]
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["reason"] = str(exc)
    return result


def create_snapshot(root, state_dir, configuration, bwrap, execution_id):
    """Create once. Never overwrite, repair or migrate an existing snapshot."""
    if state_schema(state_dir) != "NEW":
        raise ValueError("Snapshot initialization requires a new empty state directory")
    if not bwrap["verified"]:
        raise ValueError("Snapshot requires verified bwrap capabilities")
    configuration = experimental_config(configuration)
    sources = inventory(root)
    if not sources["ok"]:
        raise ValueError("Source inventory invalid: " + str(sources))
    directory = Path(state_dir) / "provenance/snapshots/src-000001"
    directory.mkdir(parents=True, exist_ok=False)
    files = []
    for entry in sources["files"]:
        relative = entry["path"]
        contents = _read_file(root, relative)
        if hashlib.sha256(contents).hexdigest() != entry["sha256"]:
            raise ValueError(f"Source changed while snapshotting: {relative}")
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        files.append(entry)
    config_bytes = canonical_json(configuration)
    (directory / "effective-config.json").write_bytes(config_bytes)
    files.append({"path": "effective-config.json", "sha256": hashlib.sha256(config_bytes).hexdigest()})
    files.sort(key=lambda entry: entry["path"])
    runtime = runtime_identity()
    manifest = {"schema": SNAPSHOT_SCHEMA, "state_schema": STATE_SCHEMA,
                **purpose_metadata(configuration),
                "snapshot_id": directory.name, "created_at": datetime.now(timezone.utc).isoformat(),
                "creation_execution_id": execution_id,
                "files": files, "aggregate_sha256": aggregate_hash(files, configuration),
                "python": sys.version.split()[0], "platform": runtime["platform"],
                "architecture": runtime["machine"], "configuration": configuration,
                "config_hash": digest(configuration), "runtime": runtime,
                "runtime_id": digest(runtime), "bwrap": bwrap}
    manifest["manifest_sha256"] = digest(manifest)
    (directory / "manifest.json").write_bytes(canonical_json(manifest))
    reference = {key: manifest[key] for key in ("snapshot_id", "aggregate_sha256", "manifest_sha256")}
    checked = validate_snapshot(directory, reference)
    if not checked["ok"]:
        raise ValueError("Snapshot validation failed: " + str(checked))
    # An accidental write is prevented too; hashes remain the integrity boundary.
    for path in directory.rglob("*"):
        if path.is_file():
            path.chmod(0o444)
    return reference


def validate_snapshot(directory, expected=None):
    directory = Path(directory)
    result = {"ok": False, "snapshot": directory.is_dir() and not directory.is_symlink(),
              "manifest": False, "integrity": False, "modified": [], "missing": [],
              "new": [], "errors": []}
    try:
        manifest = json.loads(_read_file(directory, "manifest.json"))
        declared_digest = manifest["manifest_sha256"]
        payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        if digest(payload) != declared_digest:
            raise ValueError("Source manifest digest mismatch")
        if manifest["schema"] != SNAPSHOT_SCHEMA or manifest["state_schema"] != STATE_SCHEMA:
            raise ValueError("Unsupported source manifest schema")
        if manifest["snapshot_id"] != directory.name:
            raise ValueError("Snapshot identity/path mismatch")
        files, cfg = manifest["files"], manifest["configuration"]
        paths = [entry["path"] for entry in files]
        if paths != sorted(set(paths)) or any(
                Path(p).is_absolute() or ".." in Path(p).parts for p in paths):
            raise ValueError("Invalid or duplicate source manifest paths")
        required = set(source_paths(directory)) | {"effective-config.json"}
        if not required.issubset(paths):
            raise ValueError("Manifest omits required CPU sources")
        if manifest["config_hash"] != digest(cfg) or manifest["aggregate_sha256"] != aggregate_hash(files, cfg):
            raise ValueError("Source aggregate/configuration hash mismatch")
        if manifest["runtime_id"] != digest(manifest["runtime"]) or not manifest["bwrap"]["verified"]:
            raise ValueError("Invalid runtime/capability identity")
        if expected is not None and (not isinstance(expected, dict) or any(expected.get(key) != manifest[key] for key in (
                "snapshot_id", "aggregate_sha256", "manifest_sha256"))):
            raise ValueError("Source manifest differs from baseline reference")
        result["manifest"] = True
        for entry in files:
            try:
                if hashlib.sha256(_read_file(directory, entry["path"])).hexdigest() != entry["sha256"]:
                    result["modified"].append(entry["path"])
            except FileNotFoundError:
                result["missing"].append(entry["path"])
        actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*")
                  if p.is_file() or p.is_symlink()}
        result["new"] = sorted(actual - set(paths) - {"manifest.json"})
        if json.loads(_read_file(directory, "effective-config.json")) != cfg:
            raise ValueError("Snapshot effective configuration mismatch")
        result["integrity"] = not any(result[key] for key in ("modified", "missing", "new"))
        result["ok"] = result["snapshot"] and result["manifest"] and result["integrity"]
        result["identity"] = {key: manifest[key] for key in (
            "snapshot_id", "aggregate_sha256", "manifest_sha256")}
        result["runtime"] = manifest["runtime"]
        result["configuration"] = cfg
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["errors"].append(str(exc))
    return result


def compare_sources(root, directory, configuration):
    result = {"ok": False, "modified": [], "missing": [], "new": [], "errors": []}
    try:
        manifest = json.loads(_read_file(directory, "manifest.json"))
        current = inventory(root)
        was = {entry["path"]: entry["sha256"] for entry in manifest["files"]
               if entry["path"] != "effective-config.json"}
        now = {entry["path"]: entry["sha256"] for entry in current["files"]}
        result["missing"] = sorted(set(was) - set(now))
        result["new"] = sorted(set(now) - set(was))
        result["modified"] = sorted(p for p in set(now) & set(was) if now[p] != was[p])
        result["errors"] = current["errors"]
        if experimental_config(configuration) != manifest["configuration"]:
            result["errors"].append("Effective configuration differs from source snapshot")
        if runtime_critical(runtime_identity()) != runtime_critical(manifest["runtime"]):
            result["errors"].append("Runtime differs from source snapshot")
        result["ok"] = current["ok"] and not any(result[k] for k in ("modified", "missing", "new", "errors"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["errors"].append(str(exc))
    return result


def state_schema(directory):
    directory = Path(directory)
    state = directory / "state.json"
    if state.exists():
        try:
            metadata = json.loads(state.read_text())
            from .ledger import SCHEMA
            if (isinstance(metadata, dict) and metadata.get("state_schema") == STATE_SCHEMA
                    and metadata.get("ledger_schema") == SCHEMA):
                return "MVP_CPU_V1"
        except (ValueError, OSError):
            pass
        return "LEGACY_NON_CERTIFIABLE"
    if directory.exists() and any(p.name != "gaia.lock" for p in directory.iterdir()):
        return "LEGACY_NON_CERTIFIABLE"
    return "NEW"


def prerequisites(eng, initialize=False):
    bwrap = bwrap_capability()
    schema = state_schema(eng.store.dir)
    reasons = []
    source = {"ok": False, "snapshot": False, "manifest": False, "integrity": False}
    if not bwrap["verified"]:
        reasons.append(bwrap["reason"])
    if schema == "LEGACY_NON_CERTIFIABLE":
        reasons.append("Legacy state is read-only and non-certifiable; select a new empty state directory")
    elif schema == "NEW":
        source = {**source, "inventory": inventory(eng.root)}
        if not source["inventory"]["ok"]:
            reasons.append("CPU sources missing or unreadable: " + str(source["inventory"]))
        if not initialize:
            reasons.append("New baseline requires explicit prepare --initialize-mvp")
    elif initialize:
        reasons.append("--initialize-mvp requires a new empty state directory; existing state is preserved")
    else:
        try:
            state = json.loads((eng.store.dir / "state.json").read_text())
            reference = state["source_snapshot"]
            snapshot_id = reference["snapshot_id"]
            if not isinstance(snapshot_id, str) or not snapshot_id.startswith("src-") or not snapshot_id[4:].isdigit():
                raise ValueError("Invalid snapshot identity")
            directory = eng.store.dir / "provenance/snapshots" / snapshot_id
            source = validate_snapshot(directory, reference)
            baseline = json.loads((eng.store.stable / "v0000/evidence.json").read_text())
            if not isinstance(baseline, dict) or baseline.get("source_snapshot") != reference:
                raise ValueError("Baseline source reference differs from state snapshot")
            comparison = compare_sources(eng.root, directory, eng.cfg) if source["ok"] else None
            source["comparison"] = comparison
            if not source["ok"]:
                reasons.append("Source snapshot/manifest integrity failed: " + str(source))
            elif not comparison["ok"]:
                source["integrity"] = False
                reasons.append("Working CPU sources/runtime differ from certified snapshot; explicitly create a new baseline in a new state: " + str(comparison))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            reasons.append("Source snapshot reference missing/invalid: " + str(exc))
    environment = None
    recovery = None
    if schema == "MVP_CPU_V1" and not initialize:
        from .manifest import validate_manifest
        environment = validate_manifest(eng)
        if not environment["ok"]:
            reasons.extend(environment["errors"])
        recovery = eng.store.recover_publications(eng)
        if recovery["status"] != "READY":
            reasons.extend("PUBLICATION_BLOCKED: " + error for error in recovery["errors"])
    return {"ok": not reasons, "source": source, "bwrap": bwrap, "environment": environment,
            "state_schema": schema, "reasons": reasons, "publication_recovery": recovery}
