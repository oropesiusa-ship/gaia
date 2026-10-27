"""Second-session adapter; S1 remains unchanged and no work runs on import.

The caller must supply a separately frozen session with the factual inference
lineage first and original NumPy lineage second, after boundary and recovery
gates. This adapter does not authorize that caller or a real campaign by itself.
"""
from tools import stage2_executor as ex
from tools.stage2_runtime import FirstSessionSupervisor, HEADROOM
from tools.stage2_learning import surface_probe, numpy_binding, native_probe_reference, assess_catalogue, decision_coverage
from gaia.autonomy.catalog import catalog, records
from gaia.autonomy.clock import stamp
from gaia.autonomy.lineage import LineageStore
from gaia.autonomy.store import durable
from gaia.autonomy.supervisor import Supervisor


ROLES = ('S2-C3', 'S2-C4')


def experiment_process(command):
    """Recognize GAIA processes, not desktop services merely named 'worker'."""
    return any(token in command for token in
               ('autonomy-run', 'gaia.autonomy.regression', '/lab/worker.py', '/gaia/worker.py'))


def session2_lineages(state, identifiers, original_numpy):
    """Validate order and provenance, not just caller-supplied surface labels."""
    if len(identifiers) != 2 or identifiers[1] != original_numpy:
        raise ValueError('S2_ORIGINAL_NUMPY_LINEAGE_REQUIRED')
    values = [LineageStore(state, identifier).read() for identifier in identifiers]
    if [value['surface'] for value in values] != ['local_inference', 'numpy_mlp']:
        raise ValueError('S2_LINEAGE_SURFACE_ORDER')
    if values[0]['source_identity_hash'] != values[1]['source_identity_hash']:
        raise ValueError('S2_LINEAGE_SOURCE_MISMATCH')
    if any(LineageStore(state, identifier).state()['blocked'] for identifier in identifiers):
        raise ValueError('S2_LINEAGE_BLOCKED')
    return values


class SecondSessionSupervisor(FirstSessionSupervisor):
    """Reuse containment, telemetry, campaign gates and idle slots from S1.

    Only campaign ordering/admission differ: factual incompatible inference
    probe, then original NumPy consumer, with the SAME cross-session budget.
    Existing Engine/Services retain all experiment/promotion/rollback authority.
    """
    def __init__(self, *args, original_numpy, orchestration_hashes=None, **kwargs):
        # Validate before the inherited constructor writes baseline evidence.
        root, state, sid = args[:3]
        from gaia.autonomy.session import SessionStore
        session = SessionStore(state, sid).read()
        if session['allow_promotion'] or session['stage'] != 'stage2':
            raise ValueError('S2_PROMOTION_FORBIDDEN')
        self.lineage_contracts = session2_lineages(state, session['lineages'], original_numpy)
        self.original_numpy = original_numpy
        self.orchestration_hashes = orchestration_hashes or {}
        self.catalogue_before = {}
        self.attribution_sampled = None
        super().__init__(*args, **kwargs)

    def guard(self):
        from tools.stage2_protocol import verify_tools
        from gaia.autonomy.supervisor import processes, alive
        verify_tools(self.root, self.orchestration_hashes)
        super().guard()
        allowed = {pid: row['starttime'] for pid, row in self.owned.items() if alive(pid, row['starttime'])}
        foreign = {pid: info for pid, info in processes().items()
                   if info[6] != 'Z' and allowed.get(pid) != info[7]
                   and experiment_process(info[5])}
        if foreign:
            self.environment_evidence.append({'clock': stamp(),
                'reason': 'EXTERNAL_EXPERIMENT_BUSY', 'processes': foreign})
            raise RuntimeError('EXTERNAL_EXPERIMENT_BUSY')
        if self.attribution_sampled is None or self.now() - self.attribution_sampled >= 10:
            import os
            from tools.stage2_observer import sample
            self.attribution_sampled = self.now()
            gpu = not hasattr(self, 'attribution_gpu') or self.now() - self.attribution_gpu >= 30
            evidence = sample(self.root, self.state, os.getpid(), gpu=gpu)
            if gpu:
                self.attribution_gpu = self.now()
            self.telemetry.append(evidence)
            if evidence['status'] != 'PASS':
                self.environment_evidence.append(evidence)
                raise RuntimeError('OWNERSHIP_ATTRIBUTION_INCOMPLETE_OR_FOREIGN_ACTIVITY')

    def next_lineage(self, view):
        ordinal = len(view['campaigns'])
        return self.contract['lineages'][ordinal] if ordinal < 2 else None

    def create_campaign(self, lineage_id, seconds):
        self.guard()
        view = self.session.state_view()
        ordinal = len(view['campaigns'])
        if ordinal >= 2 or view['running']:
            raise RuntimeError('S2_CAMPAIGN_ORDER')
        if lineage_id != self.contract['lineages'][ordinal]:
            raise RuntimeError('S2_LINEAGE_ORDER')
        if self.aggregate.storage() + 512 * 2**20 + HEADROOM >= 4 * 2**30:
            raise RuntimeError('STAGE_STORAGE_ADMISSION')
        if not self.locks_free(lineage_id):
            raise RuntimeError('LOCK_BUSY_OUTSIDE_SESSION')
        role = ROLES[ordinal]
        catalogue = catalog(self.state, self.contract['lineages'], self.root)
        evidence = {'clock': stamp(), 'role': role, 'catalogue': catalogue,
                    'lineage_hash': self.lineage_contracts[ordinal]['hash'],
                    'execution_authority': 'EXISTING_DETERMINISTIC_CAMPAIGN_GATES_ONLY'}
        if role == 'S2-C3':
            # Read-only qualification and a factual surface difference. Do not
            # invent an inference environment_hash using a NumPy manifest.
            ex.qualify_backend(self.root, self.contract['freeze'])
            references = catalogue['references']
            if not references:
                # The runbook requires a factual NumPy binding difference, not
                # an invented accepted experiment when no catalogue entry exists.
                reference = native_probe_reference(self.root, self.lineage_contracts[1])
                evidence['baseline_binding_probe'] = reference
                references = [reference]
            evidence['incompatible_probe'] = surface_probe(references, self.lineage_contracts[0])
        else:
            evidence['consumer_binding'] = numpy_binding(self.root, self.lineage_contracts[1])
            evidence['assessments'] = assess_catalogue(catalogue['references'],
                evidence['consumer_binding'], role='S2-C4')
            evidence['binding_scope'] = 'ORIGINAL_NUMPY_LINEAGE_AFTER_SESSION_BOUNDARY'
            evidence['reuse_claim'] = 'NOT_EXERCISED_PENDING_ACTUAL_DECISION_TRACE'
        durable(self.session.root / 'evidence' / f'{role}-catalogue-before.json', evidence, True)
        # Reserve before creating campaign state. No refund/retry on ambiguity.
        self.aggregate.reserve(self.session.identifier, role, 1800)
        cid = Supervisor.create_campaign(self, lineage_id, min(1740, int(seconds)))
        self.aggregate.bind(role, cid)
        self.roles[cid] = role
        self.catalogue_before[cid] = evidence
        return cid

    def finish(self, campaign_id, lineage_id, info, outcome, supervised):
        result = super().finish(campaign_id, lineage_id, info, outcome, supervised)
        if self.roles[campaign_id] == 'S2-C4':
            before = self.catalogue_before[campaign_id]
            executed = [r for r in records(LineageStore(self.state, lineage_id))
                        if r['campaign_id'] == campaign_id]
            proof = decision_coverage(before['catalogue']['references'],
                                      before['consumer_binding'], executed)
            durable(self.session.root / 'evidence' / f'{campaign_id}-catalogue-decisions.json', proof, True)
            if proof['status'] != 'PASS':
                raise RuntimeError('CATALOGUE_REFERENCE_DECISION_COVERAGE_MISSING')
        return result


def audit_second_aggregate(store, aggregate, first_session):
    """Reconcile both sessions and every reserved campaign without resetting caps."""
    view = aggregate.view()
    current = store.state_view()
    prior = first_session.state_view()
    failures = []
    if view['sessions'] != [first_session.identifier, store.identifier]:
        failures.append('STAGE_SESSION_LINK_MISMATCH')
    for session, roles in ((prior, ('S1-C1', 'S1-C2')), (current, ROLES)):
        if [view['bindings'].get(role) for role in roles] != session['campaigns']:
            failures.append('STAGE_CAMPAIGN_LINK_MISMATCH')
        for role in roles:
            cid = view['bindings'].get(role)
            charges = [row['wall_s'] for row in session['finished']
                       if row.get('campaign_id') == cid]
            if charges != [view['charges'].get(role)]:
                failures.append('STAGE_SESSION_CHARGE_MISMATCH:' + role)
    if len(view['charges']) != 4 or len(view['reservations']) != 4:
        failures.append('UNRECONCILED_STAGE_RESERVATION')
    if view['overrun'] or view['actual_compute_s'] > 7200:
        failures.append('STAGE_COMPUTE_EXCEEDED')
    if aggregate.storage() >= 4 * 2**30:
        failures.append('STAGE_STORAGE_EXCEEDED')
    return {'status': 'FAIL' if failures else 'PASS', 'failures': failures,
            'snapshot': view, 'owners': aggregate.ownership()}
