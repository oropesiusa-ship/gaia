"""Measured chat context policy; larger windows require explicit latency headroom."""


PROFILES={
    4096:{'maximum_ttft_s':15,'maximum_vram_increment_bytes':3*2**30},
    8192:{'maximum_ttft_s':30,'maximum_vram_increment_bytes':4*2**30},
    16384:{'maximum_ttft_s':65,'maximum_vram_increment_bytes':4*2**30},
}


def select_context(history,*,mode='auto',latency_budget_s=15,pending_characters=0):
    """Choose only among measured contexts using conservative character pressure."""
    if mode!='auto':
        value=int(mode)
        if value not in PROFILES:raise ValueError('UNVALIDATED_CHAT_CONTEXT')
        if latency_budget_s<PROFILES[value]['maximum_ttft_s']:raise ValueError('CHAT_LATENCY_BUDGET_TOO_SMALL')
        return {'context':value,'reason':'EXPLICIT_VALIDATED_CONTEXT','fallback':4096 if value>4096 else None}
    if type(pending_characters)is not int or pending_characters<0:raise ValueError('INVALID_PENDING_CONTEXT_SIZE')
    pressure=sum(len(v['payload']['content']) for v in history)+pending_characters+512
    context=4096
    if pressure>12000 and latency_budget_s>=PROFILES[16384]['maximum_ttft_s']:context=16384
    elif pressure>6000 and latency_budget_s>=PROFILES[8192]['maximum_ttft_s']:context=8192
    return {'context':context,'reason':'MEASURED_LATENCY_AND_HISTORY_PRESSURE','fallback':4096 if context>4096 else None,
            'history_characters':pressure-pending_characters-512,'pending_characters':pending_characters,
            'latency_budget_s':latency_budget_s}
