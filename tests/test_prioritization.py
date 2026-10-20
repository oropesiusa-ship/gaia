"""Ordinal prioritization tests from validated diagnostic fixtures; no host execution."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gaia import config, provenance
from gaia.diagnosis.engine import diagnose
from gaia.diagnosis.schema import seal as seal_diagnosis
from gaia.prioritization.engine import prioritize
from gaia.prioritization.policy import DEFAULTS, decide, ordering, settings
from gaia.prioritization.schema import seal, validate
from gaia.prioritization.store import PriorityStore
from test_diagnosis import fixture, metric, reseal

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "docs/diagnosis_evidence"


def diagnosis(case="compute"):
    value = fixture()
    baseline = None
    if case in ("compute", "dependent"):
        metric(value, "resources", "system_cpu_utilization_percent", [98] * 5)
    if case == "dependent":
        metric(value, "workload", "wall_s", [1, 2, 1, 2, 1])
    if case == "unknown":
        baseline = fixture()
        metric(value, "workload", "wall_s", [1.5] * 5)
    if case == "gpu":
        value["sections"]["facts"]["gpu"] = {"devices": [{"vram_total_bytes": 1000}]}
        value["sections"]["measurements"]["gpu"] = [{"vram_available_bytes": 1}]
    if case == "failure":
        value["sections"]["measurements"]["workload"]["status"] = "ERROR"
    return diagnose(reseal(value), baseline)


def dimensions(**overrides):
    return {**{"impact": "HIGH", "diagnostic_confidence": "MEDIUM", "investigation_cost": "LOW", "risk": "LOW",
               "reversibility": "EASY", "information_value": "HIGH", "blocking_power": "NONE", "evidence_completeness": "SUFFICIENT"}, **overrides}


class PolicyTests(unittest.TestCase):
    def tier(self, **kwargs):
        return decide(dimensions(**kwargs), [], DEFAULTS)[0]

    def test_A_high_impact_supported_cheap_is_p1(self):
        self.assertEqual(self.tier(), "P1")

    def test_p0_requires_all_critical_conditions(self):
        self.assertEqual(self.tier(diagnostic_confidence="HIGH", blocking_power="HIGH"), "P0")
        self.assertEqual(self.tier(diagnostic_confidence="LOW", blocking_power="HIGH"), "P1")
        self.assertNotEqual(self.tier(diagnostic_confidence="HIGH", blocking_power="HIGH", evidence_completeness="PARTIAL"), "P0")

    def test_B_low_support_low_information_defers(self):
        self.assertEqual(self.tier(diagnostic_confidence="VERY_LOW", information_value="LOW"), "DEFER")

    def test_confidence_influence(self):
        self.assertEqual(self.tier(diagnostic_confidence="MEDIUM", information_value="LOW"), "P1")
        self.assertEqual(self.tier(diagnostic_confidence="LOW", information_value="LOW"), "P3")

    def test_cost_influence(self):
        self.assertEqual(self.tier(investigation_cost="HIGH"), "P3")
        self.assertEqual(self.tier(investigation_cost="LOW"), "P1")

    def test_risk_and_reversibility_reduce_priority(self):
        for values in ({"risk": "HIGH"}, {"risk": "MEDIUM"}, {"reversibility": "DIFFICULT"}, {"reversibility": "UNKNOWN"}):
            self.assertEqual(self.tier(**values), "P3")

    def test_information_value_can_justify_uncertainty_reduction(self):
        self.assertEqual(self.tier(diagnostic_confidence="LOW", information_value="HIGH"), "P1")
        self.assertEqual(self.tier(diagnostic_confidence="LOW", information_value="LOW"), "P3")

    def test_blocking_quality_boost(self):
        self.assertEqual(self.tier(impact="LOW", blocking_power="HIGH", information_value="HIGH", investigation_cost="VERY_LOW", diagnostic_confidence="LOW"), "P1")

    def test_blockers_dominate_even_high_impact(self):
        self.assertEqual(decide(dimensions(), ["FROZEN_COMPONENT"], DEFAULTS)[0], "DEFER")

    def test_unknown_policy_keys_and_unsafe_frozen_policy_rejected(self):
        for value in ({"frozen_component_policy": "ALLOW"}, {"unknown": 1}, {"large_regression_relative": 0}):
            with self.assertRaises(ValueError):
                settings({"prioritization": value})

    def test_configuration_does_not_affect_evolution(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        before = provenance.experimental_config(cfg)
        cfg["prioritization"]["max_cost_for_p1"] = "MEDIUM"
        self.assertEqual(before, provenance.experimental_config(cfg))


class TargetTests(unittest.TestCase):
    def test_F_no_significant_issue_never_creates_target(self):
        result = prioritize([diagnosis("none")])
        self.assertEqual(result["candidate_targets"], [])
        self.assertEqual(result["exclusions"][0]["reason"], "NO_SIGNIFICANT_ISSUE")

    def test_D_unknown_with_real_large_regression_acquires_evidence(self):
        result = prioritize([diagnosis("unknown")])
        target = result["candidate_targets"][0]
        self.assertEqual(target["target_class"], "UNKNOWN_REQUIRES_EVIDENCE")
        self.assertEqual(target["intent"], "ACQUIRE_EVIDENCE")
        self.assertEqual(target["dimensions"]["impact"], "HIGH")
        self.assertEqual(target["dimensions"]["diagnostic_confidence"], "LOW")

    def test_E_frozen_gpu_deferred(self):
        target = prioritize([diagnosis("gpu")])["candidate_targets"][0]
        self.assertEqual(target["target_class"], "GPU_RUNTIME_EFFICIENCY")
        self.assertEqual(target["priority"], "DEFER")
        self.assertIn("FROZEN_COMPONENT", target["blocked_by"])

    def test_G_duplicates_consolidate_and_preserve_all_refs(self):
        a = diagnosis()
        b = seal_diagnosis({**a, "diagnosis_id": "d000002"})
        one, many = prioritize([a]), prioritize([a, a, b])
        self.assertEqual(len(one["candidate_targets"]), len(many["candidate_targets"]))
        for target in many["candidate_targets"]:
            self.assertEqual(len(target["source_refs"]), 2)
            self.assertEqual(target["dimensions"]["diagnostic_confidence"], one["candidate_targets"][[t["target_class"] for t in one["candidate_targets"]].index(target["target_class"])]["dimensions"]["diagnostic_confidence"])

    def test_C_H_dependency_measurement_precedes_dependent(self):
        result = prioritize([diagnosis("dependent")])
        measurement = next(t for t in result["candidate_targets"] if t["target_class"] == "MEASUREMENT_QUALITY")
        self.assertEqual(measurement["priority"], "P1")
        dependent = [t for t in result["candidate_targets"] if t["dependencies"]]
        self.assertTrue(dependent)
        for t in dependent:
            self.assertEqual(t["priority"], "DEFER")
            self.assertIn(measurement["target_id"], t["dependencies"])
            self.assertLess(result["ordering"].index(measurement["target_id"]), result["ordering"].index(t["target_id"]))

    def test_unrelated_noisy_diagnosis_does_not_block_other_history(self):
        noisy, normal = diagnosis("dependent"), diagnosis()
        result = prioritize([noisy, normal])
        self.assertTrue(any(t["dependencies"] for t in result["candidate_targets"]))
        # Grouping retains both sources and conservatively keeps the known dependency.
        self.assertTrue(any(len(t["source_refs"]) == 2 for t in result["candidate_targets"]))

    def test_impact_not_inferred_from_compute_name(self):
        target = next(t for t in prioritize([diagnosis()])["candidate_targets"] if t["target_class"] == "CPU_RUNTIME_EFFICIENCY")
        self.assertEqual(target["dimensions"]["impact"], "UNKNOWN")

    def test_failure_is_high_impact_but_cause_remains_unknown(self):
        target = prioritize([diagnosis("failure")])["candidate_targets"][0]
        self.assertEqual(target["dimensions"]["impact"], "HIGH")
        self.assertEqual(target["target_class"], "UNKNOWN_REQUIRES_EVIDENCE")
        self.assertNotEqual(target["priority"], "P0")

    def test_controlled_multiple_targets_cost_and_dependency_order(self):
        baseline, current = fixture(), fixture()
        current["sections"]["facts"]["runtime"]["identity"]["python"] = "3.15"
        metric(current, "workload", "wall_s", [1.5] * 5)
        metric(current, "workload", "final_acc", [.4] * 5)
        changed = diagnose(reseal(current), baseline)
        result = prioritize([changed, diagnosis("dependent"), diagnosis("gpu")])
        by_class = {t["target_class"]: t for t in result["candidate_targets"]}
        self.assertEqual(by_class["QUALITY_REGRESSION"]["priority"], "P1")
        self.assertEqual(by_class["MEASUREMENT_QUALITY"]["priority"], "P1")
        self.assertEqual(by_class["RUNTIME_CONFIGURATION"]["priority"], "P3")
        self.assertEqual(by_class["GPU_RUNTIME_EFFICIENCY"]["priority"], "DEFER")
        self.assertTrue(by_class["RESOURCE_CONTENTION"]["dependencies"])
        order = result["ordering"]
        self.assertLess(order.index(by_class["QUALITY_REGRESSION"]["target_id"]), order.index(by_class["RUNTIME_CONFIGURATION"]["target_id"]))

    def test_required_capability_blocks_runtime_efficiency_but_not_gap_inquiry(self):
        value = fixture()
        metric(value, "resources", "system_cpu_utilization_percent", [98] * 5)
        value["sections"]["capabilities"] = [{"name": "bwrap_sandbox_available", "status": "UNAVAILABLE", "evidence": {}, "conditions": []}]
        result = prioritize([diagnose(reseal(value))])
        by_class = {t["target_class"]: t for t in result["candidate_targets"]}
        self.assertIn("CAPABILITY_UNAVAILABLE", by_class["CPU_RUNTIME_EFFICIENCY"]["blocked_by"])
        self.assertFalse(by_class["CAPABILITY_GAP"]["blocked_by"])

    def test_no_input_or_corrupt_input_fails(self):
        with self.assertRaises(ValueError):
            prioritize([])
        value = diagnosis()
        value["diagnosis_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            prioritize([value])

    def test_input_order_does_not_change_semantics(self):
        a, b = diagnosis(), diagnosis("gpu")
        x, y = prioritize([a, b]), prioritize([b, a])
        for key in ("timestamp", "cost", "prioritization_hash"):
            x.pop(key); y.pop(key)
        self.assertEqual(x, y)


class SchemaAuditTests(unittest.TestCase):
    def test_hash_schema_canonical_required(self):
        value = prioritize([diagnosis()])
        self.assertEqual(validate(value), value)
        self.assertEqual(provenance.canonical_json(value), provenance.canonical_json(dict(reversed(list(value.items())))))
        for key in value:
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                validate({k: v for k, v in value.items() if k != key})
        with self.assertRaises(ValueError):
            seal({**value, "schema": "future"})

    def test_false_priority_rejected_even_resealed(self):
        value = prioritize([diagnosis()])
        value["candidate_targets"][0]["priority"] = "P0"
        with self.assertRaises(ValueError):
            seal(value)

    def test_appliance_cannot_bypass_frozen_component_policy(self):
        value = prioritize([diagnosis()])
        value["candidate_targets"][0]["component_id"] = "appliance"
        with self.assertRaises(ValueError):
            seal(value)

    def test_cycle_and_unknown_dependency_rejected(self):
        value = prioritize([diagnosis("dependent")])
        value["candidate_targets"][0]["dependencies"] = ["t9999"]
        with self.assertRaises(ValueError):
            seal(value)

    def test_no_recollection_diagnosis_or_evolution(self):
        with patch("gaia.diagnosis.engine.diagnose", side_effect=AssertionError("no diagnosis")), patch("gaia.observation.collector.collect", side_effect=AssertionError("no collection")):
            prioritize([diagnosis_saved()])

    def test_private_context_and_fields_not_echoed(self):
        value = diagnosis()
        value["limitations"].append("PRIVATE_CANARY_04")
        value["source_observations"][0]["private"] = "PRIVATE_CANARY_04"
        # Keep evidence source refs matching the expanded source reference.
        for e in value["evidence"]:
            if e["observation_ref"]["role"] == value["source_observations"][0]["role"]:
                e["observation_ref"]["private"] = "PRIVATE_CANARY_04"
        value = seal_diagnosis(value)
        self.assertNotIn("PRIVATE_CANARY_04", provenance.canonical_json(prioritize([value])).decode())

    def test_audit_reproduces_and_detects_added_advice(self):
        from tools.audit_prioritization import audit_document, source_policy
        value = diagnosis()
        result = prioritize([value])
        self.assertEqual(audit_document(result, [value])["status"], "PASS")
        self.assertTrue(source_policy()["no_execution_authority"])
        result["limitations"].append("Change threads now")
        with self.assertRaises(ValueError):
            audit_document(seal(result), [value])

    def test_audit_requires_exact_sources(self):
        from tools.audit_prioritization import audit_document
        with self.assertRaises(ValueError):
            audit_document(prioritize([diagnosis()]), [])

    def test_policy_identity_and_low_confidence_intent_cannot_be_forged(self):
        value = prioritize([diagnosis("unknown")])
        modified = copy.deepcopy(value)
        modified["policy"]["hash"] = "0" * 64
        with self.assertRaises(ValueError):
            seal(modified)
        modified = copy.deepcopy(value)
        modified["candidate_targets"][0]["intent"] = "INVESTIGATE_ISSUE"
        with self.assertRaises(ValueError):
            seal(modified)

    def test_raw_observation_is_not_a_diagnosis_input(self):
        with self.assertRaises(ValueError):
            prioritize([fixture()])

    def test_unknown_information_strings_not_persisted(self):
        value = diagnosis()
        value["hypotheses"][0]["missing_evidence"].append("PRIVATE_CANARY_04")
        self.assertNotIn("PRIVATE_CANARY_04", provenance.canonical_json(prioritize([seal_diagnosis(value)])).decode())


def diagnosis_saved():
    return json.loads((REAL / "current-diagnosis.json").read_bytes())


class StoreCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = PriorityStore(self.tmp.name)
        self.value = prioritize([diagnosis()])

    def test_store_canonical_immutable_and_latest(self):
        self.assertIsNone(self.store.latest())
        a, b = self.store.save(self.value), self.store.save(self.value)
        self.assertEqual(self.store.ids(), ["p000001", "p000002"])
        self.assertEqual(self.store.latest(), b)
        self.assertEqual(self.store.read("p000001"), a)
        with self.assertRaises(FileExistsError):
            self.store.save(self.value, prioritization_id="p000001")
        self.assertEqual(self.store.path("p000001").stat().st_mode & 0o222, 0)

    def test_atomic_failure_does_not_expose_partial(self):
        with patch("gaia.prioritization.store.os.link", side_effect=OSError("fault")):
            with self.assertRaises(OSError):
                self.store.save(self.value)
        self.assertEqual(self.store.ids(), [])
        self.assertEqual(list(self.store.directory.glob(".pending-*")), [])

    def test_concurrent_unique_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            saved = list(pool.map(lambda _: self.store.save(self.value), range(8)))
        self.assertEqual(len({v["prioritization_id"] for v in saved}), 8)

    def test_traversal_symlink_and_tamper_rejected(self):
        with self.assertRaises(ValueError):
            self.store.read("../escape")
        self.store.save(self.value)
        path = self.store.path("p000001")
        path.chmod(0o644); path.write_text("{}")
        with self.assertRaises(ValueError):
            self.store.read("p000001")
        path.unlink(); path.symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            self.store.read("p000001")

    def test_real_cli_multiple_list_read_and_failure(self):
        def cli(*args, expected=0):
            proc = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", str(ROOT / "gaia.py"),
                                   *args, "--state-dir", self.tmp.name, "--json"], capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
            return json.loads(proc.stdout) if expected == 0 else proc.stdout
        no_issue = cli("prioritize", str(REAL / "historical-comparative-diagnosis.json"), str(REAL / "additional-current-diagnosis.json"))
        self.assertEqual(no_issue["candidate_targets"], [])
        noisy = cli("prioritize", str(REAL / "current-diagnosis.json"))
        self.assertEqual(noisy["candidate_targets"][0]["priority"], "P3")
        self.assertEqual(noisy["candidate_targets"][0]["target_class"], "MEASUREMENT_QUALITY")
        self.assertEqual(cli("priority", "latest"), noisy)
        self.assertEqual(len(cli("priorities")), 2)
        self.assertIn("INVALID_INPUT", cli("prioritize", "missing", expected=2))
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ["priorities"])


if __name__ == "__main__":
    unittest.main()
