"""Independent restrictive budgets; task data can reduce, never increase authority."""
from ..config import DEFAULTS


def settings(configuration=None):
    defaults=DEFAULTS['cognition'];supplied=(configuration or {}).get('cognition',{})
    if set(supplied)-set(defaults):raise ValueError('UNKNOWN_COGNITION_SETTING')
    cfg={**defaults,**supplied}
    for k in ('max_steps','max_tool_calls','max_input_tokens','max_output_tokens','retry_limit','max_duration'):
        if type(cfg[k])is not int or not (0 if k=='retry_limit'else 1)<=cfg[k]<=defaults[k]:raise ValueError('INVALID_COGNITION_LIMIT')
    if cfg['default_allowed_authority']!=['READ_ONLY']or cfg['network_default']is not False or cfg['grounding_required_by_task_type']!=defaults['grounding_required_by_task_type']:raise ValueError('COGNITION_AUTHORITY_ESCALATION')
    return cfg
