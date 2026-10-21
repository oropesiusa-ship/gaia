import copy
import json
import os
from pathlib import Path

DEFAULTS = {
    "local_intelligence": {"network_enabled": False, "installation_enabled": False, "inference_enabled": False,
                           "selection_policy": "local_intelligence_selection_v1"},
    "external_research": {
        "network_enabled": False, "https_only": True, "timeout_seconds": 8,
        "max_sources": 4, "max_requests": 12, "max_response_bytes": 524288,
        "max_decompressed_bytes": 1048576, "max_total_bytes": 2097152,
        "max_duration_seconds": 45, "max_redirects": 3, "min_interval_seconds": 0.5,
        "cache_max_age_seconds": 86400, "high_freshness_cache_seconds": 60,
        "max_text_chars": 150000, "max_fragments": 512,
    },
    "meta_strategy": {
        "replication_bonus": 4, "exact_repeat_penalty": 20, "information_value_weight": 3,
        "improvement_potential_weight": 1, "cost_penalty": 2, "risk_penalty": 3,
        "verification_bonus": 2, "exploitation_bonus": 3, "knowledge_validation_bonus": 3,
        "exploration_floor": 1, "max_candidate_plans": 24, "max_trials_per_plan": 20,
    },
    "learning": {
        "minimum_evidence_for_consolidation": 1, "minimum_independent_replications": 2,
        "stale_on_runtime_change": True, "stale_on_hardware_change": True,
        "contradiction_confidence_penalty": 1, "higher_lr_factor": 1.10,
    },
    "prioritization": {
        "large_regression_relative": 0.30, "min_impact_for_p1": "HIGH",
        "max_cost_for_p1": "LOW", "blocking_priority_boost": True,
        "frozen_component_policy": "DEFER",
    },
    "diagnosis": {
        "memory_available_low_ratio": 0.10, "gpu_memory_available_low_ratio": 0.10,
        "storage_available_low_ratio": 0.05, "swap_consumption_bytes": 64 * 2**20,
        "cpu_utilization_high": 90.0, "process_cpu_wall_high": 0.75,
        "process_cpu_wall_low": 0.30, "rss_growth_relative": 0.20,
        "quality_regression_relative": 0.02, "performance_regression_relative": 0.15,
        "max_noise_cv": 0.10, "confidence_min_evidence": 3,
    },
    "observation": {
        "quick_samples": 3, "full_samples": 5, "sample_interval_ms": 100,
        "stability_cv_threshold": 0.10, "significant_relative_change": 0.15,
        "include_workload": True, "max_duration_seconds": 60,
    },
    # El estado se separa por workload: nunca se comparan ni mezclan campañas distintas.
    "workload": {"id": "numpy_mlp", "state_dir": "state"},
    "benchmark_profile": "hard",   # "easy" = MLP rápido (se satura en ~15 experimentos)
    "limits": {                      # todo ajustable sin tocar código (gaia.json)
        "max_total_minutes": 60,     # tiempo total de una ejecución de `run`
        "max_experiment_seconds": 20,
        "max_ram_mb": 3000,
        "max_disk_mb": 500,
        "max_experiments": 100000,
        "worker_threads": 1,
    },
    "acceptance": {
        "min_gain": 0.05,            # mejora práctica mínima del coste (5 %)
        "confirm_seeds": 5,
        "mem_tolerance": 1.25,       # RAM máx. permitida frente al campeón
        "screen_slack": 1.3,         # tope de cribado = 1.3 x coste del campeón
        "t_crit_one_sided_95": {"1": 6.314, "2": 2.920, "3": 2.353, "4": 2.132, "5": 2.015,
                                 "6": 1.943, "7": 1.895, "8": 1.860, "9": 1.833},
    },
    "stop": {
        "plateau_experiments": 80,   # sin mejora verificada -> pide ayuda humana
        "max_consecutive_infra_errors": 6,
        "drift_tolerance": 0.35,     # deriva del reloj de referencia -> pide ayuda humana
        "recalibrate_every": 20,
        "min_resolvable_s": 0.06,    # por debajo, el ruido domina: benchmark saturado
        "max_ref_spread": 0.25,
    },
    "meta": {"enabled": True, "every": 60, "budget": 20, "seeds": 6, "rounds": 3},
    "research": {                    # Modo B: investigación autónoma
        "enabled": True,
        "trigger_after": 40,         # experimentos sin mejora antes de investigar (además del diagnóstico)
        "max_hypotheses": 4,         # hipótesis contrastadas por ciclo
        "min_expected_gain": 0.05,   # cota de Amdahl mínima para que merezca un experimento
        "profile_batches": 600,
    },
    "readiness": {                   # puertas G0-G5 antes de una campaña
        "reliability_runs": 5, "max_cv": 0.20, "max_warmup_ratio": 1.35,
        "control_pairs": 5, "require_sandbox": True,
    },
}


def load(root):
    cfg = copy.deepcopy(DEFAULTS)
    root = Path(root).resolve()
    p = root / "gaia.json"
    local = os.environ.get("GAIA_LOCAL_CONFIG")
    # Una configuración administrada pertenece a una raíz concreta. No debe
    # propagarse a otros proyectos ni a las raíces temporales de los tests.
    if local and Path(local).resolve().parent == (root / ".gaia" / "configs").resolve():
        p = Path(local)
    if p.exists():
        user = json.loads(p.read_text())
        for k, v in user.items():
            if isinstance(v, dict) and k in cfg:
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg
