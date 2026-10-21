"""Documentary registries compiled from explicit GAIA research captures, with UNKNOWN kept visible."""
import base64
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from ..external_research.extraction import extract
from ..external_research.schema import reference
from .discovery import runtime_metadata, source_json, SEEDS, CATEGORIES
from .qualification import runtime_eligibility
from .schema import artifact,ref

# Taxonomic seeds only. Hardware eligibility still comes from observed host + cited source facts.
TAXONOMY={'ggml-org/llama.cpp':('CORE_RUNTIME',['llama.cpp']), 'LostRuins/koboldcpp':('CORE_RUNTIME_FORK',['llama.cpp']),
          'EricLBuehler/mistral.rs':('CORE_RUNTIME',['candle']), 'microsoft/onnxruntime-genai':('CORE_RUNTIME',['onnxruntime']),
          'mlc-ai/mlc-llm':('COMPILED_RUNTIME',['tvm']), 'turboderp-org/exllamav3':('SPECIALIZED_RUNTIME',['exllama']),
          'turboderp-org/exllamav2':('SPECIALIZED_RUNTIME',['exllama']), 'OpenNMT/CTranslate2':('CORE_RUNTIME',['ctranslate2']),
          'microsoft/BitNet':('SPECIALIZED_RUNTIME',['bitnet.cpp','llama.cpp-derived']), 'kvcache-ai/ktransformers':('SPECIALIZED_RUNTIME',['ktransformers']),
          'vllm-project/vllm':('SERVER_LAYER',['vllm']), 'sgl-project/sglang':('SERVER_LAYER',['sglang']),
          'NVIDIA/TensorRT-LLM':('COMPILED_RUNTIME',['tensorrt-llm']), 'mudler/LocalAI':('SERVER_LAYER',['multiple-backends','llama.cpp']),
          'mozilla-ai/llamafile':('WRAPPER',['llama.cpp']), 'ollama/ollama':('SERVER_LAYER',['ggml','llama.cpp-derived']),
          'hongfaqiu/strata-manager':('FRONTEND',['Niko1221/Strata']), 'robertkarl/UnbiasedStrata':('SPECIALIZED_RUNTIME_FORK',['Niko1221/Strata']),
          'VecSzn/PolyStrata':('MULTI_ENGINE_WRAPPER',['Niko1221/Strata','PolyStrata-native']),
          'Niko1221/Strata':('SPECIALIZED_RUNTIME',['Strata-native']), 'ro99/strata':('SPECIALIZED_RUNTIME',['ro99-strata'])}


def _text(source):
    e=extract(source)
    return '\n'.join(f['text'] for f in e['payload']['fragments']),e


def runtime_registry(sources,profile):
    repositories={};releases={};documents=[];search_refs=[]
    for s in sources:
        try:d=source_json(s)
        except (ValueError,UnicodeError):d=None
        url=s['payload']['url']
        if isinstance(d,dict) and 'full_name'in d and 'default_branch'in d:
            name=d['full_name'];seed_url=s['payload']['requested_url']
            seeded=name in SEEDS or any(seed_url.lower()=='https://api.github.com/repos/'+seed.lower() for seed in SEEDS)
            repositories[name]={'source':s,'metadata':d,'origin':'SEED' if seeded else 'DISCOVERED'}
        if isinstance(d,dict) and isinstance(d.get('items'),list):
            search_refs.append(reference(s))
            for item in d['items']:
                if item.get('full_name') and item.get('default_branch'):
                    repositories.setdefault(item['full_name'],{'source':s,'metadata':item,'origin':'ACTIVE_PUBLIC_SEARCH'})
        if isinstance(d,dict) and 'tag_name'in d:
            match=re.search(r'/repos/([^/]+/[^/]+)/releases/',url)
            if match:releases[match.group(1)]=(d,s)
        if isinstance(d,dict) and isinstance(d.get('object'),dict) and re.fullmatch(r'[a-f0-9]{40}',d['object'].get('sha','')):
            match=re.search(r'/repos/([^/]+/[^/]+)/git/ref/heads/',url)
            if match and match.group(1)not in releases:releases[match.group(1)]=({'tag_name':'commit-'+d['object']['sha'],'version_kind':'COMMIT_HEAD'},s)
        if s['payload']['mime']!='application/json':documents.append(s)
    values=[]
    for name,item in sorted(repositories.items()):
        data=item['metadata'];s=item['source']
        # Project this row independently; never inherit a previous project's support claims.
        base=runtime_metadata(s,discovery=item['origin'],metadata=data)['payload']
        docs=[doc for doc in documents if '/'+name+'/' in doc['payload']['url']]
        if name=='vllm-project/vllm':docs += [doc for doc in documents if urlsplit(doc['payload']['url']).hostname=='docs.vllm.ai']
        if name=='EricLBuehler/mistral.rs':docs += [doc for doc in documents if urlsplit(doc['payload']['url']).hostname=='docs.mistralrs.dev']
        text='\n'.join(_text(doc)[0] for doc in docs)
        source_refs=[reference(s)]+[reference(doc) for doc in docs]
        release=releases.get(name)
        try:recent=(datetime.fromisoformat(s['created_at'])-datetime.fromisoformat(data['pushed_at'].replace('Z','+00:00'))).days<=180
        except (KeyError,ValueError,TypeError):recent=False
        base['maintenance_status']='ARCHIVED' if data.get('archived') else 'RECENT_UPSTREAM_PUSH' if recent else 'NO_RECENT_MAINTENANCE_PROOF'
        base.update(runtime_type=TAXONOMY.get(name,('UNKNOWN',[]))[0],shared_compute_ancestry=TAXONOMY.get(name,('UNKNOWN',[]))[1],
                    evidence_refs=source_refs,discovered_version=release[0]['tag_name'] if release else 'MISSING_EVIDENCE_TAGGED_VERSION',
                    version_evidence=reference(release[1]) if release else None,
                    version_kind=release[0].get('version_kind','TAGGED_RELEASE')if release else'UNKNOWN',
                    supported_OS=[os for token,os in [('Linux','Linux'),('Windows','Windows'),('macOS','Darwin')] if token.lower()in text.lower()],
                    supported_CPU_arch=['x86_64'] if re.search(r'x86.64|amd64',text,re.I) else [],
                    supported_CPU_ISA=[],
                    model_formats=[token for token in ('GGUF','GPTQ','AWQ','ONNX','UQFF') if token.lower() in text.lower()],
                    quantization_formats=[token for token in ('Q4','Q8','IQ','GPTQ','AWQ','EXL3','INT8','INT4','FP8') if token.lower() in text.lower()],
                    supported_model_architectures=[token.lower() for token in ('Qwen3','SmolLM3','Gemma4','Llama','Phi3','Mistral') if token.lower()in text.lower()],
                    CUDA_support='DOCUMENTED_MENTION' if 'cuda'in text.lower() else 'UNKNOWN',Vulkan_support='DOCUMENTED_MENTION' if 'vulkan'in text.lower()else 'UNKNOWN',
                    CPU_support='DOCUMENTED_MENTION' if re.search(r'\bCPU\b',text) else 'UNKNOWN',
                    missing_evidence=['UNLISTED_FEATURE_IS_UNKNOWN_NOT_UNSUPPORTED','MENTION_IS_NOT_EMPIRICAL_QUALIFICATION'],
                    source_quality={'capture_class':s['payload']['source_class'],'role':'CANONICAL_UPSTREAM_API_OR_ATTRIBUTED_SEARCH_METADATA','scope':'DOCUMENTARY_NOT_EMPIRICAL'})
        m=re.search(r'compute capability\s*(\d+\.\d+)\s*(?:or higher|and higher|\+)',text,re.I)
        if m:base['minimum_compute_capability']=m.group(1)
        base['qualification_status']='DISCOVERED'
        if name=='StanfordPL/strata' or 'textbook'in name or 'Strata-Sword'in name:
            base['runtime_type']='NOT_AN_LLM_RUNTIME';base['disposition']='OUT_OF_SCOPE_DISAMBIGUATED'
        elif base['runtime_type'] in ('FRONTEND','WRAPPER','SERVER_LAYER','MULTI_ENGINE_WRAPPER'):
            base['disposition']='WRAPPER_OR_SERVING_LAYER_ANCESTRY_RECORDED_NOT_AN_INDEPENDENT_BENCHMARK'
        else:base['disposition']='BOUNDED_FINALIST_SCHEDULING_OR_MORE_EVIDENCE_REQUIRED'
        record=artifact('RUNTIME',base)
        if base['minimum_compute_capability']:
            decision=runtime_eligibility(record,profile,backend='CUDA')
            base={**base,'static_cuda_evaluation':{k:v for k,v in decision.items()if k!='runtime_ref'}};record=artifact('RUNTIME',base)
        if name=='Niko1221/Strata':
            minimum=re.search(r'(?:at least|need at least)\s*(\d+)\s*GB of RAM',text,re.I)
            required=int(minimum.group(1))*2**30 if minimum else None
            combined=(profile['payload'].get('ram_total_bytes')or 0)+sum(d.get('vram_total_bytes')or 0 for d in profile['payload']['gpu'].get('devices',[]))
            base={**base,'documented_default_min_combined_memory_gib':int(minimum.group(1)) if minimum else None,
                  'default_model_eligibility':'DOCUMENTED_DEFAULT_BUNDLE_EXCEEDS_OBSERVED_COMBINED_MEMORY'if required and required>combined else'UNKNOWN_REQUIRES_BUNDLE_SPECIFIC_EVALUATION',
                  'alternative_model_support':'UNKNOWN_NOT_UNIVERSAL_ENGINE_REJECTION'};record=artifact('RUNTIME',base)
        values.append(record)
    coverage=artifact('DISCOVERY',{'runtime_candidates':len(values),'seed_count':len(SEEDS),'active_search_refs':search_refs,
        'discovered_outside_seeds':[v['payload']['upstream'] for v in values if v['payload']['discovery_origin']!='SEED'],
        'categories_investigated':list(CATEGORIES),'coverage_claim':'BROAD_DIRECTED_SURVEY_NOT_EXHAUSTIVE_BEST_AVAILABLE',
        'runtime_refs':[ref(v)for v in values], 'unknown_fields_are_explicit':True})
    return values,coverage


def model_registry(sources):
    metadata={};origins={};dates={}
    for s in sources:
        try:d=source_json(s)
        except (ValueError,UnicodeError):continue
        rows=d if isinstance(d,list) else [d]
        for item in rows:
            if isinstance(item,dict) and isinstance(item.get('modelId')or item.get('id'),str):
                name=item.get('modelId')or item.get('id')
                if '/'not in name:continue
                if name not in metadata or 'siblings'in item:
                    metadata[name]=item;dates[name]=s['created_at']
                origins.setdefault(name,[]).append(reference(s))
    values=[]
    for name,data in sorted(metadata.items()):
        config=data.get('config')or{};gguf=data.get('gguf')or{};card=data.get('cardData')or{}
        license=card.get('license')or next((t[8:]for t in data.get('tags',[])if t.startswith('license:')),None)
        files=[x['rfilename']for x in data.get('siblings',[])]
        quant=[q for q in ('Q4_K_M','Q4_0','Q5_K_M','Q6_K','Q8_0','IQ2','GPTQ','AWQ','EXL3','INT4','INT8')if any(q.lower()in f.lower()for f in files)]
        values.append(artifact('MODEL',{'model_id':name,'family':name.split('/')[0],'version':data.get('sha')or'MISSING_EVIDENCE_COMMIT',
            'parameters':(data.get('safetensors')or{}).get('total')or gguf.get('total'),'architecture':gguf.get('architecture')or config.get('model_type')or'UNKNOWN',
            'license':license or'UNKNOWN','weights_license':license or'UNKNOWN','context':gguf.get('context_length')or'UNKNOWN',
            'tokenizer_chat_template':'SOURCE_PUBLISHED_TEMPLATE_DATA' if gguf.get('chat_template')or config.get('chat_template_jinja')else'UNKNOWN',
            'reasoning_mode':'SOURCE_TEMPLATE_DEPENDENT_NOT_ASSUMED','tool_support':'UNKNOWN_REQUIRES_LOCAL_FORMAT_TEST',
            'language_support':card.get('language')or'UNKNOWN','model_formats_available':['GGUF']if gguf else ['ONNX']if 'onnx'in data.get('tags',[])else['SOURCE_CHECKPOINT'],
            'quantizations_available':quant,'estimated_memory_bytes':gguf.get('totalFileSize'),'memory_estimate_scope':'WEIGHT_BYTES_ONLY_EXCLUDES_RUNTIME_KV_AND_WORKSPACE',
            'upstream':'https://huggingface.co/'+name,'retrieval_date':dates[name],
            'source_quality':'ATTRIBUTED_MODEL_HUB_METADATA_NOT_LOCAL_QUALITY_PROOF','evidence_refs':origins[name],
            'qualification_status':'DISCOVERED','files':files,'task_type':data.get('pipeline_tag')or'UNKNOWN'}))
    return values
