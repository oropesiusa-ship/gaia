"""Validated, operator-imported evidence snapshots; source text never becomes policy."""
import json
import base64
from ..provenance import digest,canonical_json
from .schema import seal,ref,safe_text

TOOLS={'observation':'observation.lookup','diagnosis':'diagnosis.lookup','priority':'prioritization.lookup',
       'learning':'learning.query','strategy':'strategy.query','research':'research.query','intelligence':'intelligence.status'}


def classify(document):
    schema=document.get('schema')
    if schema=='gaia_system_observation_v1':
        from ..observation.schema import validate
        domain='observation';identifier='observation_id';hashkey='observation_hash'
    elif schema=='gaia_system_diagnosis_v1':
        from ..diagnosis.schema import validate
        domain='diagnosis';identifier='diagnosis_id';hashkey='diagnosis_hash'
    elif schema=='gaia_target_prioritization_v1':
        from ..prioritization.schema import validate
        domain='priority';identifier='prioritization_id';hashkey='prioritization_hash'
    elif schema=='gaia_experimental_learning_v1':
        from ..learning.schema import validate
        domain='learning';identifier='learning_id';hashkey='hash'
    elif schema=='gaia_experiment_strategy_v1':
        from ..experiment_strategy.schema import validate
        domain='strategy';identifier='strategy_id';hashkey='output_hash'
    elif schema=='gaia_external_research_v1':
        from ..external_research.schema import validate
        if document['kind']not in ('SOURCE','CLAIM','CONCLUSION'):raise ValueError('UNSUPPORTED_RESEARCH_EVIDENCE')
        if document['kind']=='SOURCE':
            from ..external_research.fetch import validate_source as validate
        domain='research';identifier='artifact_id';hashkey='hash'
    elif schema=='gaia_local_intelligence_v1':
        from ..local_intelligence.schema import validate
        if document['kind']not in ('HOST_PROFILE','SELECTION','BENCHMARK'):raise ValueError('UNSUPPORTED_INTELLIGENCE_EVIDENCE')
        domain='intelligence';identifier='id';hashkey='hash'
    else:raise ValueError('UNSUPPORTED_EVIDENCE_SCHEMA')
    validate(document)
    return domain,document[identifier],document[hashkey]


def import_evidence(store,document,label):
    domain,identifier,sha=classify(document);safe_text(label,100)
    if len(canonical_json(document))>2*2**20:raise ValueError('EVIDENCE_IMPORT_BOUND')
    # Reject private-looking strings before persistence; never redact a signed/hash-bound source.
    safe_text(canonical_json(document).decode(),2*2**20)
    if domain=='research'and document['kind']=='SOURCE':
        safe_text(base64.b64decode(document['payload']['body_base64']).decode('utf-8',errors='replace'),2*2**20)
    record=store.put(seal('EVIDENCE',{'domain':domain,'label':label,'source_id':identifier,'source_hash':sha,
        'source_class':'EXTERNAL_UNTRUSTED_EVIDENCE'if domain=='research'else'LOCAL_VERIFIED_EVIDENCE',
        'instruction_authority':'NONE','document':document}))
    return {'tool_id':TOOLS[domain],**ref(record)}


def project(record):
    """Small, versioned projections, keeping original field paths for exact audit."""
    p=record['payload'];d=p['document'];domain,identifier,sha=classify(d)
    expected_class='EXTERNAL_UNTRUSTED_EVIDENCE'if domain=='research'else'LOCAL_VERIFIED_EVIDENCE'
    if domain!=p['domain']or identifier!=p['source_id']or sha!=p['source_hash']or p['instruction_authority']!='NONE'or p['source_class']!=expected_class:raise ValueError('EVIDENCE_BINDING_MISMATCH')
    fields=[]
    def add(path,value):
        if value is not None:fields.append({'field':path,'value':value})
    if domain=='observation':
        h=d['sections']['facts']['host']
        for key in ('model','physical_cores','logical_cores','architecture'):add('sections.facts.host.cpu.'+key,h['cpu'].get(key))
        add('sections.facts.host.ram.total_bytes',h.get('ram',{}).get('total_bytes'))
        add('sections.facts.gpu.devices',d['sections']['facts'].get('gpu',{}).get('devices',[]))
    elif domain=='diagnosis':
        add('outcome',d['outcome'])
        add('limitations',d['limitations'])
        for i,item in enumerate(d['issues'][:3]):
            for key in ('kind','details'):add(f'issues.{i}.{key}',item.get(key))
        for i,item in enumerate(d['hypotheses'][:2]):
            for key in ('kind','confidence','causality'):add(f'hypotheses.{i}.{key}',item[key])
    elif domain=='priority':
        add('ordering',d['ordering'])
        for i,t in enumerate(d['candidate_targets'][:2]):
            for key in ('target_class','priority','reasons','dimensions','blocked_by'):add(f'candidate_targets.{i}.{key}',t[key])
    elif domain=='learning':
        for key in ('claim_type','confidence','replication_status','status','hierarchy','quality','claim','limitations'):add(key,d[key])
    elif domain=='strategy':
        for key in ('mode','analysis_mode','ranking','confidence'):add(key,d[key])
        for i,plan in enumerate(d['candidate_plans'][:2]):
            for key in ('class','mode','rationale','execution'):add(f'candidate_plans.{i}.{key}',plan[key])
    elif domain=='research':
        if d['kind']=='CLAIM':
            for key in ('normalized_proposition','reported_value','support.quote','topic'):
                val=d['payload']
                for k in key.split('.'):val=val.get(k)if isinstance(val,dict)else None
                add('payload.'+key,val)
        elif d['kind']=='SOURCE':
            from ..external_research.extraction import extract
            for i,f in enumerate(extract(d)['payload']['fragments'][:4]):add(f'extracted.fragments.{i}.text',f['text'])
        else:
            for key in ('status','summary','limitations','recommendation_status'):
                add('payload.'+key,d['payload'].get(key))
    elif d['kind']=='SELECTION':
        add('payload.claim',d['payload']['claim'])
        stack=d['payload']['primary']['stack']
        for key in ('runtime','runtime_version','model_id','backend','gpu_layers','kv','context'):add('payload.primary.stack.'+key,stack[key])
        add('payload.rationale',d['payload']['rationale'])
    elif d['kind']=='BENCHMARK':
        for key in ('status','evaluation.quality','evaluation.json_reliability','statistics.decode_tokens_per_s.median','statistics.latency_s.median'):
            val=d['payload']
            for k in key.split('.'):val=val[k]
            add('payload.'+key,val)
    else:
        for key in ('cpu','ram_total_bytes','missing_evidence'):add('payload.'+key,d['payload'][key])
    facts=[]
    for f in fields:
        safe_text(canonical_json(f).decode(),200000)
        # Long strings are split at word boundaries, not silently truncated.
        value=f['value']
        if isinstance(value,str)and len(value)>240:
            words=value.split();chunks=[];chunk=[]
            for word in words:
                if len(' '.join(chunk+[word]))>240 and chunk:chunks.append(' '.join(chunk));chunk=[]
                chunk.append(word)
            if chunk:chunks.append(' '.join(chunk))
            parts=[{**f,'value':part,'chunk':i,'support_scope':'WORD_NORMALIZED_SOURCE_FRAGMENT'}for i,part in enumerate(chunks)]
        elif len(canonical_json(value))>700:
            # Filter structured aggregates into independently cited leaves.
            parts=[{**f,'value':v,'field':f['field']+'.'+str(k)}for k,v in (value.items()if isinstance(value,dict)else enumerate(value))if len(canonical_json(v))<=700]
        else:parts=[f]
        for part in parts:
            facts.append({**part,'fact_id':'F'+digest({'record':ref(record),'fact':part})[:10],
                          'evidence_ref':ref(record),'source_id':identifier,'source_hash':sha,'source_class':p['source_class'],'instruction_authority':'NONE'})
    return facts
