"""Extensible current-ecosystem research using GAIA 0.7, not model knowledge as truth."""
import base64
import json
import re
from urllib.parse import urlsplit

from ..external_research.engine import acquire, analyze, attach_acquisition, validate_acquisition
from ..external_research.request import create
from ..external_research.schema import artifact as research_artifact, reference
from ..external_research.policy import identity, settings
from ..external_research.store import ResearchStore
from .schema import artifact, ref

SEEDS = ("ggml-org/llama.cpp", "LostRuins/koboldcpp", "EricLBuehler/mistral.rs", "mlc-ai/mlc-llm",
         "microsoft/onnxruntime-genai", "turboderp-org/exllamav3", "turboderp/exllamav2", "OpenNMT/CTranslate2",
         "microsoft/BitNet", "kvcache-ai/ktransformers", "vllm-project/vllm", "sgl-project/sglang", "NVIDIA/TensorRT-LLM",
         "mudler/LocalAI", "Mozilla-Ocho/llamafile", "ollama/ollama")
CATEGORIES = ("GGUF", "CUDA", "VULKAN", "CPU", "ONNX", "COMPILED", "GPTQ_AWQ_EXL", "SPECIALIZED_LOW_BIT", "MOE", "SERVING", "HYBRID")
DISCOVERY_BUDGET={'max_public_requests':192,'max_sources':128,'max_decoded_bytes':64*2**20}


def research(question, urls, state, *, configuration=None, authorized=False):
    if not authorized or not settings(configuration)['network_enabled']:
        raise ValueError('Explicit ecosystem network authorization and global opt-in required')
    cfg = configuration
    store = ResearchStore(state)
    prior=store.list('ACQUISITION')
    used_requests=sum(a['payload']['result']['requests'] for a in prior)
    used_bytes=sum(a['payload']['result']['decoded_bytes'] for a in prior)
    if used_requests>=DISCOVERY_BUDGET['max_public_requests'] or used_bytes>=DISCOVERY_BUDGET['max_decoded_bytes'] or len(store.list('SOURCE'))+len(urls)>DISCOVERY_BUDGET['max_sources']:
        raise ValueError('Explicit ecosystem phase research budget exhausted')
    request = create(question, urls, topics=["LOCAL_INFERENCE_ECOSYSTEM"],
                      allowed_domains=sorted({urlsplit(u).hostname for u in urls}), network_authorized=True, freshness="HIGH",
                      budget={'max_requests':min(settings(cfg)['max_requests'],DISCOVERY_BUDGET['max_public_requests']-used_requests),
                              'max_total_bytes':min(settings(cfg)['max_total_bytes'],DISCOVERY_BUDGET['max_decoded_bytes']-used_bytes)},
                      evidence_requirements={"require_primary": False}, configuration=cfg)
    store.put(request)
    sources, result = acquire(request, store, cfg)
    phase = research_artifact("ACQUISITION", {"request_ref": reference(request), "policy": identity(settings(cfg)), "result": result})
    validate_acquisition(request, phase)
    store.put(phase)
    run = attach_acquisition(analyze(request, sources), reference(phase))
    store.save_run(run, request, sources)
    return request, sources, run, phase


def source_json(source):
    return json.loads(base64.b64decode(source["payload"]["body_base64"]))


def runtime_metadata(source, *, discovery="SEED", metadata=None):
    data = source_json(source) if metadata is None else metadata
    upstream = data.get("full_name")
    if not isinstance(upstream, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", upstream):
        raise ValueError("Repository metadata missing canonical upstream")
    fields = {"runtime_id": upstream.lower().replace("/", "--"), "canonical_name": data["name"], "upstream": "https://github.com/" + upstream,
              "discovered_version": None, "retrieval_date": source["created_at"], "license": (data.get("license") or {}).get("spdx_id"),
              "maintenance_status": "ARCHIVED" if data.get("archived") else "RECENT_PUSH_REQUIRES_RELEASE_CHECK",
              "last_push": data.get("pushed_at"), "default_branch": data.get("default_branch"), "description": data.get("description"),
              "discovery_origin": discovery, "runtime_type": "UNKNOWN", "shared_compute_ancestry": [],
              "supported_OS": [], "supported_CPU_arch": [], "supported_CPU_ISA": [], "supported_GPU_vendors": [],
              "supported_GPU_architectures": [], "minimum_compute_capability": None,
              "CUDA_support": "UNKNOWN", "Vulkan_support": "UNKNOWN", "CPU_support": "UNKNOWN", "model_formats": [],
              "quantization_formats": [], "supported_model_architectures": [], "context_capabilities": "UNKNOWN", "KV_capabilities": "UNKNOWN",
              "batching": "UNKNOWN", "speculative_decoding": "UNKNOWN", "structured_output": "UNKNOWN", "native_tool_calls": "UNKNOWN",
              "multimodal": "UNKNOWN", "LoRA": "UNKNOWN", "build_requirements": [], "install_requirements": [],
              "source_quality": source["payload"]["source_class"], "evidence_refs": [reference(source)], "qualification_status": "DISCOVERED"}
    return artifact("RUNTIME", fields)


def discovered_repositories(source):
    data = source_json(source)
    values = data.get("items", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    return [v for v in values if isinstance(v, dict) and isinstance(v.get("full_name"), str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", v["full_name"])]
