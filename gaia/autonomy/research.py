"""0.7 evidence-only acquisition, with pre-reserved public HTTP request budget."""
from urllib.parse import urlsplit
from ..external_research.request import create
from ..external_research.policy import identity,settings
from ..external_research.engine import acquire,analyze,attach_acquisition,validate_acquisition
from ..external_research.schema import artifact,reference
from ..external_research.store import ResearchStore


def needed(diagnosis):
    return any(h['kind']in ('RUNTIME_REGRESSION','CAPABILITY_GAP')for h in diagnosis['hypotheses'])


# Closed mapping from the triggering hypothesis to a bounded question and 0.7 topics.
QUESTIONS={'RUNTIME_REGRESSION':('What official CPython runtime requirements are relevant to an observed runtime change for a CPU numpy workload?',
                                 ['PYTHON_GIL_CPU_THREADING','PYTHON_FREE_THREADED_BUILD']),
           'CAPABILITY_GAP':('What official requirements apply to an unavailable acceleration capability on this host?',['CUDA_MIN_COMPUTE_CAPABILITY'])}
DEFAULT=('What official runtime requirements are relevant to bounded CPU Python threading verification?',['PYTHON_GIL_CPU_THREADING'])


def question(diagnosis):
    kinds=[h['kind']for h in diagnosis['hypotheses']if h['kind']in QUESTIONS]
    return {'question':QUESTIONS[kinds[0]][0],'topics':QUESTIONS[kinds[0]][1],'hypothesis_kind':kinds[0]}if kinds else{'question':DEFAULT[0],'topics':DEFAULT[1],'hypothesis_kind':None}


def investigate(contract,state,remaining,diagnosis=None):
    if not contract['network_authorized']or remaining<1 or not contract['research_urls']:raise ValueError('NETWORK_NOT_AUTHORIZED')
    cfg={'external_research':{'network_enabled':True,'max_requests':remaining,'max_sources':min(4,len(contract['research_urls']))}}
    asked=question(diagnosis)if diagnosis is not None else{'question':DEFAULT[0],'topics':DEFAULT[1]}
    request=create(asked['question'],contract['research_urls'],
        topics=asked['topics'],allowed_domains=sorted({urlsplit(u).hostname for u in contract['research_urls']}),
        network_authorized=True,budget={'max_requests':remaining},configuration=cfg)
    store=ResearchStore(state);store.put(request);sources,result=acquire(request,store,cfg)
    phase=artifact('ACQUISITION',{'request_ref':reference(request),'policy':identity(settings(cfg)),'result':result})
    validate_acquisition(request,phase);store.put(phase);run=attach_acquisition(analyze(request,sources),reference(phase));store.save_run(run,request,sources)
    return {'status':'EVIDENCE_ONLY','request':request,'sources':sources,'acquisition':phase,'run':run,'requests':result['requests'],
            'instruction_authority':'NONE','solutions_executed':0}
