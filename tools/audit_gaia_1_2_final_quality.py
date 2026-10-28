#!/usr/bin/env python3
"""Offline recomputation of the pre-registered GAIA 1.2 final quality gate."""
import json
from pathlib import Path
import sys


def _load(root,name):return json.loads((root/name).read_bytes())


def audit(root):
    prereg=_load(root,'GAIA_1_2_FINAL_QUALITY_PREREGISTRATION_V1.json')
    names=prereg['sources'];memory=_load(root,names['memory_quality'])['memory']
    independent=_load(root,names['independent_quality'])['baseline']
    context=_load(root,names['context_chat']);regression=_load(root,names['regression'])
    passed=memory['objective']['passed']+independent['passed'];total=memory['objective']['total']+independent['total']
    format_passed=memory['objective']['format_passed']+independent['format_passed']
    errors=memory['failures']+independent['errors'];thresholds=prereg['thresholds']
    observed_contexts={row['context']for row in context['context_quality']}
    observed_contexts.add(context['decision']['maximum_functional_observed'])
    checks={
        'objective_rate':passed/total>=thresholds['minimum_combined_objective_rate'],
        'format_rate':format_passed/total>=thresholds['minimum_combined_format_rate'],
        'inference_errors':errors<=thresholds['maximum_inference_errors'],
        'global_regression':regression['global']['failures']<=thresholds['global_regression_failures']and regression['global']['errors']<=thresholds['global_regression_errors'],
        'required_real_contexts':set(thresholds['required_real_contexts'])<=observed_contexts,
        'restart':context['chat']['restarts_between_turns']is True and context['chat']['status']=='PASS',
        'functional_coverage':all(path in regression['coverage']['test_files'] for path in (
            'tests/test_cognition_conversation.py','tests/test_stage1_recovery_drill.py',
            'tests/test_stage2_ownership_race.py')),
    }
    subjective=[row for row in memory['rows'] if row.get('subjective')=='NOT_SCORED']
    return {'schema':'gaia_1_2_final_quality_audit_v1','status':'PASS'if all(checks.values())else'FAIL','authority':'NONE',
        'checks':checks,'objective':{'passed':passed,'total':total,'rate':passed/total,'format_passed':format_passed,'format_rate':format_passed/total,'errors':errors},
        'performance':{'memory_median_latency_s':memory['median_latency_s'],'independent_median_latency_s':independent['median_latency_s'],
                       'maximum_functional_context':context['decision']['maximum_functional_observed']},
        'functional':{'global_tests':regression['global']['tests'],'skips':regression['global']['skips'],'test_files':regression['coverage']['test_file_count'],
                      'restart_between_turns':context['chat']['restarts_between_turns']},
        'subjective':{'policy':prereg['subjective_outputs'],'samples':subjective},
        'claims':{'bounded_quality_gate':'PASS'if all(checks.values())else'FAIL','cognitive_improvement':'NOT_CLAIMED'},
        'preregistration':{'schema':prereg['schema'],'status':prereg['status']}}


if __name__=='__main__':
    value=audit(Path(sys.argv[1]));print(json.dumps(value,indent=2,sort_keys=True,ensure_ascii=False));raise SystemExit(value['status']!='PASS')
