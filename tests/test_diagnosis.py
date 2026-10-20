"""Synthetic diagnostic cases plus genuine v0.2 inputs; no live campaigns."""
import copy
import getpass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from gaia import config, provenance
from gaia.observation.schema import seal as seal_observation
from gaia.observation.stability import summarize
from gaia.diagnosis.confidence import assess
from gaia.diagnosis.engine import diagnose, settings
from gaia.diagnosis.evidence import Evidence, pointer, validate_input
from gaia.diagnosis.schema import DIAGNOSIS_SCHEMA, seal, validate
from gaia.diagnosis.store import DiagnosisStore

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "docs/observation_evidence/final"


def reseal(value):
    value = copy.deepcopy(value)
    facts = value["sections"]["facts"]
    value["host_identity"] = {"stable_hash": provenance.digest({"host": facts["host"], "gpu": facts["gpu"]})}
    runtime = facts["runtime"]
    runtime["identity_hash"] = provenance.digest(runtime["identity"])
    value["runtime_identity"] = {"stable_hash": runtime["identity_hash"]}
    files = facts["source_files"]
    value["source_identity"] = {"source_aggregate_hash": "a" * 64, "observation_source_hash": provenance.digest(files),
                                "protected_source_identity": provenance.digest({k: v for k, v in files.items() if k.startswith("gaia/protected/")}),
                                "inventory_complete": True}
    value["environment_identity"] = {"identity_hash": provenance.digest({"host": value["host_identity"],
                                      "runtime": value["runtime_identity"], "source": value["source_identity"]})}
    return seal_observation(value)


def fixture():
    stats = lambda samples: summarize(samples)
    value = {"schema": "gaia_system_observation_v1", "observation_id": "o000001", "timestamp": "2026-10-20T12:00:00+00:00",
             "collector_version": "synthetic-fixture", "sections": {
                 "facts": {"host": {"ram": {"total_bytes": 1000 * 2**20}, "storage": {"source": {"total_bytes": 1000 * 2**20}}},
                           "gpu": {"devices": []}, "runtime": {"identity": {"python": "3.14"}}, "source_files": {}},
                 "measurements": {"workload": {"status": "AVAILABLE", "protocol_hash": "b" * 64,
                                                "cpu_measurement_method": "process_cpu_clock",
                                                "statistics": {"wall_s": stats([1] * 5), "process_cpu_s": stats([.9] * 5),
                                                               "final_acc": stats([.8] * 5), "peak_rss_mb": stats([20] * 5)}},
                                  "resources": {"statistics": {"system_cpu_utilization_percent": stats([25] * 5),
                                                 "system_ram_available_bytes": stats([700 * 2**20] * 5),
                                                 "filesystem_available_bytes": stats([700 * 2**20] * 5),
                                                 "swap_available_bytes": stats([100 * 2**20] * 5)}}, "gpu": []},
                 "capabilities": [], "context": {}}}
    return reseal(value)


def metric(value, scope, name, samples):
    value["sections"]["measurements"][scope]["statistics"][name] = summarize(samples)


def kinds(value):
    return {h["kind"] for h in value["hypotheses"]}


class RuleTests(unittest.TestCase):
    def test_no_issue_stops_without_artificial_hypotheses(self):
        result = diagnose(fixture())
        self.assertEqual(result["outcome"], "NO_SIGNIFICANT_ISSUE")
        self.assertEqual(result["hypotheses"], [])
        self.assertIn("baseline_for_temporal_inference", result["missing_evidence"])

    def test_A_high_cpu_combined_evidence_compute_plausible(self):
        value = fixture()
        metric(value, "resources", "system_cpu_utilization_percent", [98] * 5)
        result = diagnose(reseal(value))
        compute = next(h for h in result["hypotheses"] if h["kind"] == "COMPUTE_PRESSURE")
        self.assertEqual(compute["confidence"], "MEDIUM")
        self.assertTrue(compute["alternative_ids"])
        self.assertIn("RULE_CPU_001", compute["rule_ids"])
        self.assertEqual(compute["causality"], "NOT_ESTABLISHED")

    def test_B_low_available_swap_consumption_and_repeated_peak_growth(self):
        value = fixture()
        metric(value, "resources", "system_ram_available_bytes", [50 * 2**20] * 5)
        metric(value, "resources", "swap_available_bytes", [100 * 2**20, 90 * 2**20, 70 * 2**20, 40 * 2**20, 20 * 2**20])
        metric(value, "workload", "peak_rss_mb", [20, 22, 25, 30, 40])
        result = diagnose(reseal(value))
        memory = next(h for h in result["hypotheses"] if h["kind"] == "MEMORY_PRESSURE")
        self.assertEqual(memory["confidence"], "MEDIUM")
        self.assertIn("swap_io_activity", memory["missing_evidence"])
        self.assertGreaterEqual(len(memory["confidence_basis"]["independent_support_groups"]), 3)
        self.assertNotEqual(memory["confidence"], "HIGH")

    def test_C_high_wall_variance(self):
        value = fixture()
        metric(value, "workload", "wall_s", [1, 5, 9, 2, 8])
        result = diagnose(reseal(value))
        self.assertIn("MEASUREMENT_NOISE", kinds(result))
        self.assertIn("HIGH_MEASUREMENT_VARIABILITY", {i["kind"] for i in result["issues"]})

    def test_variability_scope_does_not_conflate_evaluator_cpu_and_wall(self):
        value = fixture()
        metric(value, "workload", "evaluator_cpu_s", [.5, 1, 1.5, 2, 2.5])
        result = diagnose(reseal(value))
        issue = next(i for i in result["issues"] if i["kind"] == "HIGH_MEASUREMENT_VARIABILITY")
        self.assertEqual(issue["details"]["metric"], "evaluator_cpu_s")
        self.assertNotIn("PERFORMANCE_REGRESSION", {i["kind"] for i in result["issues"]})
        noise = next(h for h in result["hypotheses"] if h["kind"] == "MEASUREMENT_NOISE")
        self.assertFalse(noise["contradictions"])

    def test_D_runtime_change_and_slowdown_plausible_not_proven(self):
        baseline, current = fixture(), fixture()
        current["observation_id"] = "o000002"
        current["sections"]["facts"]["runtime"]["identity"]["python"] = "3.15"
        metric(current, "workload", "wall_s", [1.3] * 5)
        result = diagnose(reseal(current), baseline)
        self.assertIn("PERFORMANCE_REGRESSION", {i["kind"] for i in result["issues"]})
        hypothesis = next(h for h in result["hypotheses"] if h["kind"] == "RUNTIME_REGRESSION")
        self.assertIn(hypothesis["confidence"], ("LOW", "MEDIUM"))
        self.assertIn("temporal association is not causal proof", hypothesis["claim"])

    def test_E_unsupported_slowdown_unknown(self):
        a, b = fixture(), fixture()
        metric(b, "workload", "wall_s", [1.4] * 5)
        result = diagnose(reseal(b), a)
        self.assertEqual(kinds(result), {"UNKNOWN_CAUSE"})
        self.assertIn("controlled_comparison_evidence", result["missing_evidence"])

    def test_F_noisy_high_cpu_reduces_confidence(self):
        value = fixture()
        metric(value, "resources", "system_cpu_utilization_percent", [100] * 5)
        stable = diagnose(reseal(value))
        metric(value, "workload", "wall_s", [1, 2, 1, 2, 1])
        noisy = diagnose(reseal(value))
        for hypothesis in noisy["hypotheses"]:
            self.assertIn(hypothesis["confidence"], ("VERY_LOW", "LOW"))
        self.assertIn("MEDIUM", stable["confidence"].values())

    def test_high_system_cpu_low_exact_workload_cpu_contention_not_compute(self):
        value = fixture()
        metric(value, "resources", "system_cpu_utilization_percent", [100] * 5)
        metric(value, "workload", "process_cpu_s", [.1] * 5)
        result = diagnose(reseal(value))
        self.assertNotIn("COMPUTE_PRESSURE", kinds(result))
        self.assertIn("RESOURCE_CONTENTION", kinds(result))
        self.assertNotIn("HIGH", result["confidence"].values())

    def test_low_sampled_cpu_is_not_exact_negative_evidence(self):
        value = fixture()
        value["sections"]["measurements"]["workload"]["cpu_measurement_method"] = "sampled_proc_descendants_10ms_lower_bound"
        metric(value, "resources", "system_cpu_utilization_percent", [100] * 5)
        metric(value, "workload", "descendant_cpu_s_lower_bound", [.01] * 5)
        result = diagnose(reseal(value))
        first = result["issues"][0]
        primary = next(h for h in result["hypotheses"] if h["hypothesis_id"] == first["primary_hypothesis"])
        self.assertEqual(primary["kind"], "UNKNOWN_CAUSE")

    def test_cpu_alone_is_not_compute_bottleneck(self):
        value = fixture()
        value["sections"]["measurements"]["workload"]["statistics"].pop("process_cpu_s")
        metric(value, "resources", "system_cpu_utilization_percent", [100] * 5)
        result = diagnose(reseal(value))
        self.assertNotIn("COMPUTE_PRESSURE", kinds(result))
        self.assertNotIn("HIGH", result["confidence"].values())

    def test_low_free_but_normal_available_no_memory_pressure(self):
        value = fixture()
        metric(value, "resources", "system_ram_free_bytes", [1] * 5)
        result = diagnose(reseal(value))
        self.assertNotIn("MEMORY_PRESSURE", kinds(result))
        self.assertEqual(result["outcome"], "NO_SIGNIFICANT_ISSUE")

    def test_low_available_alone_considers_stable_rss_and_swap_contradictions(self):
        value = fixture()
        metric(value, "resources", "system_ram_available_bytes", [50 * 2**20] * 5)
        result = diagnose(reseal(value))
        memory = next(h for h in result["hypotheses"] if h["kind"] == "MEMORY_PRESSURE")
        self.assertTrue(memory["contradictions"])
        self.assertEqual(memory["confidence"], "LOW")
        self.assertTrue(memory["contradiction_search"])

    def test_quality_regression_has_its_own_threshold(self):
        a, b = fixture(), fixture()
        metric(b, "workload", "final_acc", [.75] * 5)
        result = diagnose(reseal(b), a)
        self.assertIn("QUALITY_REGRESSION", {i["kind"] for i in result["issues"]})
        self.assertNotIn("PERFORMANCE_REGRESSION", {i["kind"] for i in result["issues"]})

    def test_gpu_presence_does_not_imply_gpu_needed(self):
        value = fixture()
        value["sections"]["facts"]["gpu"] = {"devices": [{"vram_total_bytes": 1000}]}
        value["sections"]["measurements"]["gpu"] = [{"vram_available_bytes": 900}]
        self.assertEqual(diagnose(reseal(value))["outcome"], "NO_SIGNIFICANT_ISSUE")

    def test_passive_gpu_memory_low_is_not_workload_attribution(self):
        value = fixture()
        value["sections"]["facts"]["gpu"] = {"devices": [{"vram_total_bytes": 1000}]}
        value["sections"]["measurements"]["gpu"] = [{"vram_available_bytes": 10}]
        result = diagnose(reseal(value))
        self.assertIn("GPU_MEMORY_PRESSURE", kinds(result))
        self.assertIn("workload_gpu_participation", result["missing_evidence"])

    def test_storage_low_is_only_pressure_hypothesis(self):
        value = fixture()
        metric(value, "resources", "filesystem_available_bytes", [1] * 5)
        result = diagnose(reseal(value))
        self.assertIn("STORAGE_PRESSURE", kinds(result))
        self.assertNotIn("HIGH", result["confidence"].values())

    def test_capability_gap_excludes_intentionally_frozen_or_unconfigured(self):
        value = fixture()
        value["sections"]["capabilities"] = [{"name": "cpu_numpy_workload_available", "status": "UNAVAILABLE", "evidence": {}, "conditions": []},
                                             {"name": "gpu_campaign_code_present", "status": "FROZEN", "evidence": {}, "conditions": []}]
        result = diagnose(reseal(value))
        self.assertEqual(len(result["issues"]), 1)
        self.assertIn("CAPABILITY_GAP", kinds(result))

    def test_recorded_execution_error_does_not_guess_cause(self):
        value = fixture()
        value["sections"]["measurements"]["workload"]["status"] = "ERROR"
        result = diagnose(reseal(value))
        self.assertEqual(kinds(result), {"UNKNOWN_CAUSE"})
        self.assertEqual(result["issues"][0]["kind"], "WORKLOAD_INSTABILITY")

    def test_unstable_baseline_and_different_protocols_are_insufficient(self):
        a, b = fixture(), fixture()
        metric(a, "workload", "wall_s", [1, 4, 9, 2, 7])
        result = diagnose(b, reseal(a))
        self.assertEqual(result["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertNotIn("PERFORMANCE_REGRESSION", {i["kind"] for i in result["issues"]})
        a = fixture()
        a["sections"]["measurements"]["workload"]["protocol_hash"] = "c" * 64
        self.assertEqual(diagnose(b, reseal(a))["outcome"], "INSUFFICIENT_EVIDENCE")

    def test_hardware_change_is_environment_issue_not_storage_cause(self):
        a, b = fixture(), fixture()
        b["sections"]["facts"]["host"]["storage"]["source"]["total_bytes"] *= 2
        result = diagnose(reseal(b), a)
        self.assertIn("HARDWARE_CHANGED", {i["kind"] for i in result["issues"]})
        self.assertNotIn("STORAGE_PRESSURE", kinds(result))

    def test_resource_availability_change_does_not_prove_pressure(self):
        a, b = fixture(), fixture()
        metric(b, "resources", "system_ram_available_bytes", [500 * 2**20] * 5)
        result = diagnose(reseal(b), a)
        self.assertIn("RESOURCE_AVAILABILITY_CHANGED", {i["kind"] for i in result["issues"]})
        self.assertNotIn("MEMORY_PRESSURE", kinds(result))
        self.assertEqual(kinds(result), {"UNKNOWN_CAUSE"})


class ConfidenceTests(unittest.TestCase):
    def assess(self, supports, contradictions=(), **kwargs):
        defaults = dict(stable=True, searched=True, alternative_weakened=True, missing_critical=False, rule_ids=["r1", "r2"])
        return assess(supports, contradictions, **{**defaults, **kwargs})["level"]

    def test_isolated_evidence_cannot_be_high(self):
        self.assertEqual(self.assess([{"group": "cpu", "type": "DIRECT", "strength": "STRONG"}]), "LOW")

    def test_multiple_independent_controlled_evidence_can_be_high(self):
        self.supports = [{"group": g, "type": "DIRECT", "strength": "STRONG"} for g in ("a", "b", "c")]
        self.assertEqual(self.assess(self.supports), "HIGH")
        self.assertEqual(self.assess(self.supports, rule_ids=["r1"]), "MEDIUM")
        for key in ("stable", "searched", "alternative_weakened"):
            self.assertNotEqual(self.assess(self.supports, **{key: False}), "HIGH")
        self.assertNotEqual(self.assess(self.supports, missing_critical=True), "HIGH")
        self.assertEqual(self.assess(self.supports, [{"group": "d", "type": "NEGATIVE", "strength": "STRONG"}]), "LOW")

    def test_repeated_same_group_is_not_independent(self):
        supports = [{"group": "same", "type": "DIRECT", "strength": "STRONG"}] * 8
        self.assertEqual(self.assess(supports), "LOW")

    def test_noise_and_missing_reduce_confidence(self):
        supports = [{"group": g, "type": "CORRELATIONAL", "strength": "MODERATE"} for g in ("a", "b")]
        self.assertEqual(self.assess(supports), "MEDIUM")
        self.assertEqual(self.assess(supports, stable=False), "LOW")
        self.assertEqual(self.assess(supports, missing_critical=True), "LOW")


class InputSchemaEvidenceTests(unittest.TestCase):
    def test_canonical_sealing_and_required_fields(self):
        value = diagnose(fixture())
        self.assertEqual(value["schema"], DIAGNOSIS_SCHEMA)
        self.assertEqual(value, validate(value))
        self.assertEqual(provenance.canonical_json(value), provenance.canonical_json(dict(reversed(list(value.items())))))
        for key in value:
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                validate({k: v for k, v in value.items() if k != key})

    def test_invalid_diagnosis_schema_and_tamper(self):
        value = diagnose(fixture())
        with self.assertRaises(ValueError):
            seal({**value, "schema": "future"})
        value["outcome"] = "ISSUES_DETECTED"
        with self.assertRaises(ValueError):
            validate(value)

    def test_corrupt_observation_and_invalid_identity_fail_explicitly(self):
        value = fixture()
        value["observation_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            diagnose(value)
        value = fixture()
        value["host_identity"]["stable_hash"] = "0" * 64
        value = seal_observation(value)
        with self.assertRaises(ValueError):
            diagnose(value)

    def test_resealed_false_measurement_summary_is_rejected(self):
        value = fixture()
        value["sections"]["measurements"]["workload"]["statistics"]["wall_s"]["median"] = 9
        with self.assertRaises(ValueError):
            diagnose(reseal(value))

    def test_optional_data_missing_continues_without_invention(self):
        value = fixture()
        value["sections"]["measurements"] = {}
        result = diagnose(reseal(value))
        self.assertEqual(result["outcome"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["hypotheses"], [])

    def test_every_evidence_resolves_and_graph_is_bidirectional(self):
        value = fixture()
        metric(value, "resources", "system_cpu_utilization_percent", [98] * 5)
        value = reseal(value)
        result = diagnose(value)
        for e in result["evidence"]:
            self.assertEqual(pointer(value, e["field"]), e["value"])
            self.assertEqual(e["observation_ref"]["observation_hash"], value["observation_hash"])
        self.assertEqual(validate(result), result)

    def test_false_confidence_or_dangling_links_rejected_even_resealed(self):
        value = fixture()
        metric(value, "resources", "system_cpu_utilization_percent", [98] * 5)
        result = diagnose(reseal(value))
        result["hypotheses"][0]["confidence"] = "HIGH"
        with self.assertRaises(ValueError):
            seal(result)
        result = diagnose(reseal(value))
        result["hypotheses"][0]["supports"].append("e9999")
        with self.assertRaises(ValueError):
            seal(result)

    def test_configuration_separate_and_validated(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        before = provenance.experimental_config(cfg)
        cfg["diagnosis"]["cpu_utilization_high"] = 80
        self.assertEqual(before, provenance.experimental_config(cfg))
        self.assertEqual(settings(cfg)["cpu_utilization_high"], 80)
        for key, value in (("max_noise_cv", 0), ("cpu_utilization_high", 101), ("confidence_min_evidence", 1), ("unknown", 1)):
            with self.assertRaises(ValueError):
                settings({"diagnosis": {key: value}})

    def test_privacy_only_allowlisted_scalars_are_copied(self):
        value = fixture()
        secret = "PRIVATE_CANARY_03"
        value["sections"]["context"] = {"username": getpass.getuser(), "hostname": socket.gethostname(), "token": secret}
        value["sections"]["facts"]["private"] = str(Path.home())
        metric(value, "resources", secret, [1] * 5)
        value = reseal(value)
        result = diagnose(value, value)
        raw = provenance.canonical_json(result).decode()
        for text in (secret, str(Path.home()), getpass.getuser(), socket.gethostname()):
            if len(text) > 3:
                self.assertNotIn(text, raw)

    def test_inputs_unchanged_and_diagnosis_does_not_collect(self):
        value = fixture()
        before = copy.deepcopy(value)
        with patch("gaia.observation.collector.collect", side_effect=AssertionError("no recollection")):
            diagnose(value)
        self.assertEqual(value, before)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = DiagnosisStore(self.temporary.name)
        self.value = diagnose(fixture())

    def test_immutable_canonical_list_latest(self):
        self.assertIsNone(self.store.latest())
        a, b = self.store.save(self.value), self.store.save(self.value)
        self.assertEqual(self.store.ids(), ["d000001", "d000002"])
        self.assertEqual(self.store.latest(), b)
        self.assertEqual(self.store.read("d000001"), a)
        with self.assertRaises(FileExistsError):
            self.store.save(self.value, diagnosis_id="d000001")
        self.assertEqual(self.store.path("d000001").stat().st_mode & 0o222, 0)
        self.assertEqual(sorted(p.name for p in Path(self.temporary.name).iterdir()), ["diagnoses"])

    def test_atomic_failure_never_exposes_partial(self):
        with patch("gaia.diagnosis.store.os.link", side_effect=OSError("fault")):
            with self.assertRaises(OSError):
                self.store.save(self.value)
        self.assertEqual(self.store.ids(), [])
        self.assertFalse(list(self.store.directory.glob(".pending-*")))

    def test_concurrent_store_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.save(self.value), range(8)))
        self.assertEqual(len({v["diagnosis_id"] for v in results}), 8)

    def test_paths_symlinks_and_corruption_rejected(self):
        with self.assertRaises(ValueError):
            self.store.read("../escape")
        self.store.save(self.value)
        path = self.store.path("d000001")
        path.chmod(0o644)
        path.write_text("{}")
        with self.assertRaises(ValueError):
            self.store.read("d000001")
        path.unlink()
        path.symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            self.store.read("d000001")


class RealInputsAndCLITests(unittest.TestCase):
    def test_real_v02_comparison_no_invented_regression(self):
        a, b = [json.loads((REAL / name).read_bytes()) for name in ("o000002.json", "o000003.json")]
        result = diagnose(b, a)
        self.assertEqual(result["outcome"], "NO_SIGNIFICANT_ISSUE")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["hypotheses"], [])

    def test_real_cli_single_comparative_list_latest_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            def cli(*args, expected=0):
                proc = subprocess.run([sys.executable, "-B", "-W", "error::ResourceWarning", str(ROOT / "gaia.py"),
                                       *args, "--state-dir", temporary, "--json"], capture_output=True, text=True, timeout=20)
                self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
                return json.loads(proc.stdout) if expected == 0 else proc.stdout
            a = cli("diagnose", str(REAL / "o000003.json"))
            self.assertEqual(a["outcome"], "NO_SIGNIFICANT_ISSUE")
            b = cli("diagnose", str(REAL / "o000003.json"), "--baseline", str(REAL / "o000002.json"))
            self.assertEqual(b["outcome"], "NO_SIGNIFICANT_ISSUE")
            self.assertEqual(cli("diagnosis", "latest"), b)
            self.assertEqual(len(cli("diagnoses")), 2)
            self.assertIn("INVALID_INPUT", cli("diagnose", "missing", expected=2))
            self.assertEqual(sorted(p.name for p in Path(temporary).iterdir()), ["diagnoses"])


class AuditTests(unittest.TestCase):
    def test_reproduces_trace_and_source_policy(self):
        from tools.audit_diagnosis import audit_document, source_policy
        value = fixture()
        metric(value, "resources", "system_cpu_utilization_percent", [99] * 5)
        value = reseal(value)
        self.assertEqual(audit_document(diagnose(value), [value])["status"], "PASS")
        self.assertTrue(source_policy()["no_evolution_calls"])

    def test_resealed_private_or_recommendation_content_fails_allowlist(self):
        from tools.audit_diagnosis import audit_document
        value = fixture()
        result = diagnose(value)
        result["limitations"].append("PRIVATE_CANARY_03: change runtime")
        result = seal(result)
        with self.assertRaises(ValueError):
            audit_document(result, [value])

    def test_missing_or_wrong_evidence_observation_fails(self):
        from tools.audit_diagnosis import audit_document
        value = fixture()
        with self.assertRaises(ValueError):
            audit_document(diagnose(value), [])

    def test_deterministic_interpretation_excluding_clock_and_cost(self):
        value = fixture()
        a, b = diagnose(value), diagnose(value)
        dynamic = {"timestamp", "diagnosis_hash", "cost"}
        self.assertEqual({k: v for k, v in a.items() if k not in dynamic}, {k: v for k, v in b.items() if k not in dynamic})


if __name__ == "__main__":
    unittest.main()
