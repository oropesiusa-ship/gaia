"""Conservative bounded HTTP policy and fixed source registry, independent of remote content."""
from ..provenance import digest

VERSION = "external_evidence_policy_v1"
MIMES = {"text/html", "text/plain", "application/json"}
SOURCE_CLASSES = {"PRIMARY_OFFICIAL", "PRIMARY_SCIENTIFIC", "PRIMARY_REPOSITORY", "SECONDARY_TECHNICAL", "COMMUNITY", "UNKNOWN"}
DEFAULTS = {"network_enabled": False, "https_only": True, "timeout_seconds": 8,
            "max_sources": 4, "max_requests": 12, "max_response_bytes": 524288,
            "max_decompressed_bytes": 1048576, "max_total_bytes": 2097152,
            "max_duration_seconds": 45, "max_redirects": 3, "min_interval_seconds": 0.5,
            "cache_max_age_seconds": 86400, "high_freshness_cache_seconds": 60,
            "max_text_chars": 150000, "max_fragments": 512}
REGISTRY = {"docs.python.org": ("PRIMARY_OFFICIAL", "python"), "www.python.org": ("PRIMARY_OFFICIAL", "python"),
            "docs.nvidia.com": ("PRIMARY_OFFICIAL", "nvidia"), "developer.nvidia.com": ("PRIMARY_OFFICIAL", "nvidia"),
            "numpy.org": ("PRIMARY_OFFICIAL", "numpy"), "scipy.org": ("PRIMARY_OFFICIAL", "scipy"),
            "www.phoronix.com": ("SECONDARY_TECHNICAL", "phoronix"), "www.anandtech.com": ("SECONDARY_TECHNICAL", "anandtech"),
            "arxiv.org": ("PRIMARY_SCIENTIFIC", "arxiv_preprint_unknown_authorship"),
            "stackoverflow.com": ("COMMUNITY", "stackoverflow"), "www.reddit.com": ("COMMUNITY", "reddit")}
UPSTREAM = {"/python/cpython/": "python", "/numpy/numpy/": "numpy", "/pytorch/pytorch/": "pytorch"}


def settings(configuration=None):
    supplied = (configuration or {}).get("external_research", {})
    if set(supplied) - DEFAULTS.keys():
        raise ValueError("Unknown external research setting")
    cfg = {**DEFAULTS, **supplied}
    bounds = {"timeout_seconds": (0.1, 30), "max_sources": (1, 10), "max_requests": (1, 30),
              "max_response_bytes": (1, 2097152), "max_decompressed_bytes": (1, 4194304),
              "max_total_bytes": (1, 8388608), "max_duration_seconds": (0.1, 180), "max_redirects": (0, 5),
              "min_interval_seconds": (0.1, 10), "cache_max_age_seconds": (0, 604800),
              "high_freshness_cache_seconds": (0, 300), "max_text_chars": (100, 500000), "max_fragments": (1, 1000)}
    for key in ("network_enabled", "https_only"):
        if type(cfg[key]) is not bool:
            raise ValueError("Boolean network settings required")
    for key, (low, high) in bounds.items():
        typ = (int, float) if key in ("timeout_seconds", "max_duration_seconds", "min_interval_seconds") else (int,)
        if type(cfg[key]) not in typ or not low <= cfg[key] <= high:
            raise ValueError("External research setting out of bounds")
    return cfg


def identity(cfg):
    return {"version": VERSION, "settings": cfg, "registry_hash": digest({"registry": REGISTRY, "upstream": UPSTREAM}),
            "hash": digest({"version": VERSION, "settings": cfg, "registry": REGISTRY, "upstream": UPSTREAM})}


def classify(host, path):
    if host == "github.com":
        for prefix, publisher in UPSTREAM.items():
            if path.startswith(prefix):
                return "PRIMARY_REPOSITORY", publisher
        return "COMMUNITY", "github_unknown_upstream"
    return REGISTRY.get(host, ("UNKNOWN", host))
