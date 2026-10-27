"""Pure S2-C3/C4 catalogue assessments; never create executable proposals.

Bindings must come from actual campaign/reference state. This module does not
manufacture bindings, accepted references, reuse decisions or campaign evidence.
An empty catalogue cannot demonstrate cross-surface incompatibility or reuse.
"""
from gaia.autonomy.catalog import BINDING, applicability
import json
from pathlib import Path
import re
from tools import stage2_executor as ex
from gaia.autonomy.lineage import engine_state_dir


def numpy_binding(root, lineage):
    """Read the actual champion and execution-manifest identity, without Engine."""
    if lineage.get('surface') != 'numpy_mlp':
        raise ValueError('FACTUAL_NUMPY_LINEAGE_REQUIRED')
    native = Path(root) / engine_state_dir(lineage['lineage_id'])
    ex.inventory([native], include_cache=True)  # Reject symlinks before reading.
    version = (native / 'stable/CURRENT').read_text().strip()
    if not re.fullmatch(r'v[0-9]{4,}', version):
        raise ValueError('INVALID_NATIVE_CHAMPION_VERSION')
    stable = native / 'stable' / version
    manifest = json.loads((stable / 'manifest.json').read_bytes())
    genome = json.loads((stable / 'genome.json').read_bytes())
    value = {'source_identity_hash': lineage['source_identity_hash'],
             'environment_hash': manifest.get('environment_hash'),
             'surface': lineage['surface'], 'objective': lineage['objective'],
             'reference_version': version, 'reference_baseline_hash': ex.digest(genome)}
    if any(value.get(k) is None for k in BINDING):
        raise ValueError('INCOMPLETE_NATIVE_EXECUTION_BINDING')
    return value


def surface_probe(references, lineage):
    """Prove non-reuse from a factual lineage surface without inventing hashes.

    Inference has no NumPy execution-manifest environment hash (Services returns
    context=None). A known surface mismatch is sufficient to forbid reuse, but
    does NOT turn a partial binding into an EXACT/full-binding assessment.
    """
    if lineage.get('surface') != 'local_inference':
        raise ValueError('FACTUAL_INFERENCE_LINEAGE_REQUIRED')
    if not lineage.get('lineage_id') or not lineage.get('hash'):
        raise ValueError('VERIFIED_LINEAGE_CONTRACT_REQUIRED')
    rows = []
    for reference in references:
        source = reference['binding'].get('surface')
        if source is None:
            raise ValueError('REFERENCE_SURFACE_MISSING')
        if source != lineage['surface']:
            rows.append({'record_hash': reference['record_hash'],
                         'status': 'INCOMPATIBLE_BINDING', 'differing': ['surface'],
                         'source_surface': source, 'consumer_surface': lineage['surface'],
                         'executable_effect': False})
    return {'lineage_id': lineage['lineage_id'], 'lineage_hash': lineage['hash'],
            'status': 'PASS' if rows else 'NOT_EXERCISED', 'references': rows,
            'full_binding_assessment': 'NOT_CLAIMED', 'execution_prohibited': True}


def assess_catalogue(references, binding, *, role):
    if role not in ('S2-C3', 'S2-C4'):
        raise ValueError('INVALID_STAGE2_LEARNING_ROLE')
    if not isinstance(binding, dict) or any(binding.get(k) is None for k in BINDING):
        raise ValueError('INCOMPLETE_FACTUAL_BINDING')
    expected_surface = 'local_inference' if role == 'S2-C3' else 'numpy_mlp'
    if binding['surface'] != expected_surface:
        raise ValueError('UNEXPECTED_STAGE2_SURFACE')
    assessments = []
    for reference in references:
        assessment = applicability(reference, binding)
        cross_surface = reference['binding'].get('surface') not in (None, binding['surface'])
        if assessment['status'] == 'UNASSESSED' and not cross_surface:
            raise ValueError('INCOMPLETE_REFERENCE_BINDING')
        # C3 must not call same-surface evidence a cross-surface probe.
        assessments.append({'record_hash': reference['record_hash'],
                            'applicability': assessment,
                            'cross_surface': cross_surface,
                            'executable_effect': False})
    demonstrated = any(row['cross_surface'] and
                       row['applicability']['status'] == 'INCOMPATIBLE'
                       for row in assessments)
    return {'role': role, 'assessments': assessments,
            'incompatibility_claim': 'OBSERVED' if demonstrated else 'NOT_EXERCISED',
            'reuse_claim': 'NOT_EXERCISED',
            'eligible_record_hashes': [row['record_hash'] for row in assessments
                                       if row['applicability']['status'] == 'EXACT'],
            'empty_reason': 'NO_VERIFIED_REFERENCES_IN_PERSISTED_CATALOGUE'
                            if not assessments else None,
            'execution_prohibited': True}


def decision_coverage(references, binding, executed_records):
    """Explain each catalogue entry from actual executed plans, never force reuse.

    A reference used by a materialization must link the original experiment AND
    the exact candidate. Other entries are explicitly not applicable to those
    executed plans. An unknown reference-using class is a gap, not a rejection.
    """
    assessed = assess_catalogue(references, binding, role='S2-C4')
    no_reference_classes = {'EXPLORATION', 'CONTROL_EXPERIMENT',
                            'BASELINE_RECONFIRMATION', 'MEASUREMENT_REFINEMENT'}
    unknown = [r['experiment_id'] for r in executed_records
               if not r['proposed_change'].get('reference')
               and r['proposed_change']['class'] not in no_reference_classes]
    decisions = []
    forbidden = []
    for reference, assessment in zip(references, assessed['assessments']):
        row = {'record_hash': reference['record_hash'], 'assessment': assessment,
               'executed_experiment_ids': [r['experiment_id'] for r in executed_records]}
        uses = []
        for record in executed_records:
            used = record['proposed_change'].get('reference') or {}
            if (reference['experiment_id'] in used.get('source_experiments', [])
                    and used.get('claim', {}).get('configuration_hash') == reference['candidate_hash']):
                uses.append({'experiment_id': record['experiment_id'],
                             'learning_id': used['learning_id'], 'learning_hash': used['hash']})
        if uses and (assessment['cross_surface'] or assessment['applicability']['status'] != 'EXACT'):
            row.update(decision='FORBIDDEN_REUSE', reason='REUSE_FROM_INCOMPATIBLE_BINDING', uses=uses)
            forbidden.append(reference['record_hash'])
        elif assessment['cross_surface']:
            row.update(decision='REJECTED', reason='INCOMPATIBLE_SURFACE_NO_REUSE')
        elif assessment['applicability']['status'] != 'EXACT':
            row.update(decision='REJECTED', reason='INCOMPATIBLE_CURRENT_EXECUTION_BINDING')
        else:
            if uses:
                row.update(decision='REUSED', reason='EXACT_LINKED_MATERIALIZATION_REFERENCE', uses=uses)
            elif unknown:
                row.update(decision='UNASSESSED', reason='MATERIALIZATION_REFERENCE_TRACE_MISSING')
            else:
                row.update(decision='REJECTED', reason='NOT_APPLICABLE_TO_ACTUALLY_EXECUTED_PLANS'
                           if executed_records else 'NO_EXPERIMENT_EXECUTED')
        decisions.append(row)
    return {'status': 'FAIL' if unknown or forbidden else 'PASS', 'decisions': decisions,
            'forbidden_reuse': forbidden,
            'unknown_reference_experiments': unknown,
            'reuse_claim': 'OBSERVED' if any(r['decision'] == 'REUSED' for r in decisions)
                          else 'NOT_EXERCISED',
            'empty_reason': assessed['empty_reason'], 'authority': 'AUDIT_ONLY_NO_PROMOTION_AUTHORITY'}
