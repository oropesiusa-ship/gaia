"""Explicit component registry; code presence never implies certification."""
from ..provenance import digest

REGISTRY = (
    ("core", "core", "AVAILABLE", ("gaia/engine.py", "gaia/config.py"), ("numpy",), "v0.1 CPU orchestration"),
    ("cpu_evolution", "evolution", "AVAILABLE", ("gaia/search.py", "gaia/genome.py", "gaia/snippets.py"), ("protected_evaluator",), "v0.1 numpy_mlp A/B"),
    ("protected_evaluator", "evaluation", "AVAILABLE", ("gaia/protected/",), ("numpy", "sandbox"), "v0.1 CPU G0–G5"),
    ("sandbox", "isolation", "AVAILABLE", ("gaia/protected/sandbox.py",), ("bwrap",), "v0.1 CPU bwrap"),
    ("manifest_provenance", "identity", "AVAILABLE", ("gaia/manifest.py", "gaia/provenance.py"), (), "v0.1 CPU identity"),
    ("ledger", "history", "AVAILABLE", ("gaia/ledger.py",), (), "v0.1 evolution chain"),
    ("publication", "publication", "AVAILABLE", ("gaia/publication.py", "gaia/atomic_publish.py"), ("ledger",), "v0.1 transactional publication"),
    ("rollback", "recovery", "AVAILABLE", ("gaia/rollback.py",), ("ledger",), "v0.1 ancestor rollback"),
    ("gpu", "evolution", "FROZEN", ("gaia/gaia_transformer/", "gaia/cuda_probe.py"), ("torch",), "not CPU-equivalent certified"),
    ("appliance", "deployment", "FROZEN", ("gaia/appliance_",), (), "not CPU-equivalent certified"),
    ("observation", "observation", "AVAILABLE", ("gaia/observation/",), (), "local factual observation; see stage report"),
)


def collect(root):
    import hashlib
    result = []
    for component, category, status, paths, dependencies, scope in REGISTRY:
        files = {}
        # Explicit registry prefixes only, including frozen code as read-only evidence.
        for prefix in paths:
            for path in sorted(root.glob(prefix + "**/*" if prefix.endswith("/") else prefix + "*" if prefix.endswith("_") else prefix)):
                if path.is_file() and path.suffix == ".py" and not path.is_symlink():
                    files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        result.append({"component_id": component, "category": category, "status": status if files else "UNAVAILABLE",
                       "source_paths": list(paths), "source_files": files, "source_hash": digest(files),
                       "dependencies": list(dependencies), "certified_scope": scope, "code_present": bool(files)})
    return result
