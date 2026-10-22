"""Read-only campaign inspection: an unambiguous recovery class from the committed journal, without locks or repair."""
from .store import CampaignStore,TERMINAL

# Pending intents whose side effect cannot be confirmed from evidence; run() refuses to repeat them.
AMBIGUOUS_INTENTS=('rollback_intent','research_intent','initialization_intent')
# Terminal reasons that leave committed state needing explicit review before anything continues.
REVIEW_REASONS=('NEEDS_RECOVERY','RECOVERY_COORDINATION_FAILED','ROLLBACK_FAILED','HEALTH_INVALID','REFERENCE_UNRELIABLE','REFERENCE_DRIFT',
                'LINEAGE_BLOCKED_NEEDS_RECOVERY')
CLASSES=('TERMINAL_OK','RECOVERABLE','NEEDS_RECOVERY','CORRUPT','NON_RECOVERABLE')


def classify(events,lineage_blocked=False):
    """(class, reason, action) from a committed journal. The table is the only source of the classification."""
    from .controller import IN_FLIGHT,effective_phase
    state=events[-1]['state'];phase=state['phase'];reason=state.get('reason')
    prior=events[-2]['state']if len(events)>1 else state
    if phase in TERMINAL:
        interrupted=effective_phase(prior)in IN_FLIGHT and reason!='POST_PROMOTION_REGRESSION_ROLLED_BACK'
        if reason in REVIEW_REASONS:return 'NEEDS_RECOVERY',reason,'HUMAN_REVIEW_THEN_LINEAGE_UNBLOCK'
        if interrupted:return 'NEEDS_RECOVERY','INTERRUPTED_IN_FLIGHT_'+effective_phase(prior),'HUMAN_REVIEW_THEN_LINEAGE_UNBLOCK'
        if phase=='FAILED':return 'NON_RECOVERABLE',reason,'NONE_EVIDENCE_PRESERVED'
        return 'TERMINAL_OK',reason,'NONE'
    pending=[k for k in AMBIGUOUS_INTENTS if state.get(k)]
    if pending:return 'NEEDS_RECOVERY','AMBIGUOUS_'+pending[0].upper(),'HUMAN_REVIEW'
    if lineage_blocked:return 'NEEDS_RECOVERY','LINEAGE_BLOCKED','HUMAN_REVIEW_THEN_LINEAGE_UNBLOCK'
    if state.get('meta_tune_intent'):return 'RECOVERABLE','INTERRUPTED_META_TUNE_RECORDED_NOT_REPLAYED','RUN'
    if phase=='EXPERIMENTING'and state.get('execution_intent'):return 'RECOVERABLE','COMMITTED_EVIDENCE_RECOVERY_ON_RUN','RUN'
    if phase=='PAUSED':return 'RECOVERABLE','PAUSED_AT_'+str(state.get('resume_phase')),'RESUME_THEN_RUN'
    return 'RECOVERABLE','RESUMES_AT_'+phase,'RUN'


def inspect_campaign(state_dir,identifier):
    """Pure inspection for status and supervisors: never locks, writes or repairs."""
    store=CampaignStore(state_dir,identifier)
    try:
        seen=store.inspect();contract=store.read('contract')
    except (OSError,ValueError,KeyError,TypeError)as exc:
        return {'campaign_id':identifier,'recovery':'CORRUPT','reason':str(exc)if str(exc).isupper()else type(exc).__name__,
                'action':'INSPECT_CORRUPTION','resumable':False,'inspection':'READ_ONLY_NO_LOCK_NO_REPAIR'}
    blocked=None
    if contract.get('lineage_id'):
        from .lineage import LineageStore
        try:blocked=LineageStore(state_dir,contract['lineage_id']).state()['blocked']
        except (OSError,ValueError,KeyError)as exc:
            return {'campaign_id':identifier,'recovery':'CORRUPT','reason':'LINEAGE_'+(str(exc)if str(exc).isupper()else type(exc).__name__),
                    'action':'INSPECT_CORRUPTION','resumable':False,'inspection':'READ_ONLY_NO_LOCK_NO_REPAIR'}
    cls,reason,action=classify(seen['events'],bool(blocked))
    state=seen['state']
    return {'campaign_id':identifier,'phase':state['phase'],'stopping_reason':state.get('reason'),'recovery':cls,'reason':reason,'action':action,
            'resumable':cls=='RECOVERABLE','events':len(seen['events']),'cursor':seen['cursor'],'lineage_id':contract.get('lineage_id'),
            'lineage_blocked':blocked,'iteration':state.get('iteration'),'experiments':state.get('experiments'),
            'inspection':'READ_ONLY_NO_LOCK_NO_REPAIR'}
