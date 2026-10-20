"""GAIA 0.2 factual contracts, persistence, privacy and real offline CLI."""
import copy
import getpass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from gaia import config, provenance
from gaia.observation import capabilities, collector, components, gpu, host, resources, runtime
from gaia.observation.compare import compare, metric_change
from gaia.observation.schema import OBSERVATION_SCHEMA, canonical_json, seal, validate
from gaia.observation.stability import summarize
from gaia.observation.store import ObservationStore

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return {"observation_id": "o000001", "schema": OBSERVATION_SCHEMA,
            "timestamp": "2026-10-20T12:00:00+00:00", "collector_version": "test",
            "source_identity": {"hash": "s"}, "host_identity": {"hash": "h"},
            "runtime_identity": {"hash": "r"}, "environment_identity": {"hash": "e"},
            "sections": {"facts": {"host": {"cpu": {"logical_cores": 8}}, "runtime": {"python": "3.14"}},
                         "measurements": {}, "capabilities": [], "context": {"mode": "quick"}}}


class SchemaTests(unittest.TestCase):
    def test_canonical_order_and_evidence_hashes(self):
        value = seal(fixture())
        self.assertEqual(canonical_json(value), canonical_json(dict(reversed(list(value.items())))))
        self.assertEqual(value["evidence_hashes"]["facts"], provenance.digest(value["sections"]["facts"]))
        self.assertEqual(validate(value), value)

    def test_required_fields(self):
        value = seal(fixture())
        for key in value:
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                validate({k: v for k, v in value.items() if k != key})

    def test_invalid_schema_and_nan(self):
        for field, value in (("schema", "future"), ("observation_id", "../escape"), ("timestamp", "2026-10-20")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                seal({**fixture(), field: value})
        with self.assertRaises(ValueError):
            seal({**fixture(), "dynamic": float("nan")})

    def test_tamper_detected(self):
        value = seal(fixture())
        value["sections"]["facts"]["host"]["cpu"]["logical_cores"] = 64
        with self.assertRaisesRegex(ValueError, "evidence"):
            validate(value)

    def test_invalid_capability_status(self):
        value = fixture()
        value["sections"]["capabilities"] = [{"name": "gpu", "status": "CERTIFIED"}]
        with self.assertRaises(ValueError):
            seal(value)


class StoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = ObservationStore(temporary.name)

    def test_round_trip_list_latest_and_order(self):
        self.assertEqual(self.store.ids(), [])
        self.assertIsNone(self.store.latest())
        value = fixture()
        value.pop("observation_id")
        a, b = self.store.save(value), self.store.save(value)
        self.assertEqual(self.store.ids(), ["o000001", "o000002"])
        self.assertEqual(self.store.latest(), b)
        self.assertEqual(self.store.read(a["observation_id"]), a)
        self.assertEqual(self.store._path("o000001").stat().st_mode & 0o222, 0)

    def test_no_overwrite(self):
        value = self.store.save(fixture())
        before = self.store._path("o000001").read_bytes()
        with self.assertRaises(FileExistsError):
            self.store.save(value)
        self.assertEqual(before, self.store._path("o000001").read_bytes())

    def test_atomic_failure_leaves_no_visible_partial_or_staging(self):
        with patch("gaia.observation.store.os.link", side_effect=OSError("fault")):
            with self.assertRaises(OSError):
                self.store.save(fixture())
        self.assertEqual(self.store.ids(), [])
        self.assertEqual(list(self.store.directory.glob(".pending-*")), [])

    def test_atomic_visibility(self):
        link = os.link
        def check(source, target):
            self.assertFalse(Path(target).exists())
            validate(json.loads(Path(source).read_bytes()))
            link(source, target)
        with patch("gaia.observation.store.os.link", side_effect=check):
            self.store.save(fixture())

    def test_baseline_is_separate_immutable_reference(self):
        self.store.save(fixture())
        self.store.set_baseline("o000001")
        self.assertEqual(self.store.baseline()["observation_id"], "o000001")
        with self.assertRaises(FileExistsError):
            self.store.set_baseline("o000001")
        self.assertFalse((self.store.directory.parent / "stable").exists())
        self.assertFalse((self.store.directory.parent / "ledger.jsonl").exists())

    def test_traversal_symlinks_and_noncanonical_rejected(self):
        with self.assertRaises(ValueError):
            self.store.read("../secret")
        value = self.store.save(fixture())
        path = self.store._path("o000001")
        path.chmod(0o644)
        path.write_text(json.dumps(value, indent=2))
        with self.assertRaises(ValueError):
            self.store.read("o000001")
        path.unlink()
        path.symlink_to("/etc/passwd")
        with self.assertRaises(ValueError):
            self.store.read("o000001")

    def test_concurrent_writers_get_unique_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        value = fixture()
        value.pop("observation_id")
        with ThreadPoolExecutor(max_workers=4) as pool:
            saved = list(pool.map(lambda _: self.store.save(value), range(8)))
        self.assertEqual(len({v["observation_id"] for v in saved}), 8)
        self.assertEqual(len(self.store.ids()), 8)


class SamplingTests(unittest.TestCase):
    def test_statistics_and_stable(self):
        stats = summarize([10, 10, 10])
        self.assertEqual(stats["stability"], "STABLE")
        for key in ("mean", "median", "min", "max"):
            self.assertEqual(stats[key], 10)
        self.assertEqual(stats["standard_deviation"], 0)

    def test_noisy_insufficient_zero_and_invalid_samples(self):
        self.assertEqual(summarize([1, 4, 9])["stability"], "NOISY")
        self.assertEqual(summarize([1, 1])["stability"], "INSUFFICIENT_DATA")
        self.assertEqual(summarize([0, 0, 0])["stability"], "STABLE")
        self.assertEqual(summarize([None, float("nan")])["count"], 0)

    def test_real_repeated_resource_samples(self):
        value = resources.collect(ROOT, 4, 10, 0.1, time.perf_counter() + 2)
        self.assertEqual(len(value["samples"]), 4)
        self.assertIsNone(value["samples"][0]["system_cpu_utilization_percent"])
        self.assertIsNotNone(value["samples"][-1]["system_cpu_utilization_percent"])
        self.assertGreater(value["samples"][-1]["wall_s"], value["samples"][0]["wall_s"])
        self.assertGreater(value["statistics"]["filesystem_free_bytes"]["median"], 0)
        self.assertLessEqual(value["statistics"]["filesystem_available_bytes"]["median"],
                             value["statistics"]["filesystem_free_bytes"]["median"])

    def test_deadline_bounds_sampling(self):
        value = resources.collect(ROOT, 30, 100, 0.1, time.perf_counter() - 1)
        self.assertEqual(value["status"], "UNAVAILABLE")
        self.assertEqual(value["samples"], [])

    def test_config_validation_and_evolution_identity_unchanged(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        before = provenance.experimental_config(cfg)
        cfg["observation"]["full_samples"] = 7
        self.assertEqual(before, provenance.experimental_config(cfg))
        for key, invalid in (("full_samples", 0), ("max_duration_seconds", -1), ("include_workload", "true")):
            cfg["observation"][key] = invalid
            with self.assertRaises(ValueError):
                collector.settings(cfg)
            cfg = copy.deepcopy(config.DEFAULTS)


class ComparisonTests(unittest.TestCase):
    def documents(self):
        a = fixture()
        b = copy.deepcopy(a)
        b["observation_id"] = "o000002"
        return a, b

    def test_hardware_runtime_and_added_removed_values(self):
        a, b = self.documents()
        b["host_identity"] = {"hash": "different"}
        b["runtime_identity"] = {"hash": "different"}
        b["sections"]["facts"]["host"]["cpu"] = {"model": "new"}
        diff = compare(seal(a), seal(b))
        self.assertTrue(diff["hardware_changed"])
        self.assertTrue(diff["runtime_changed"])
        self.assertEqual({x["kind"] for x in diff["fields"]}, {"added", "removed"})

    def test_capability_change(self):
        a, b = self.documents()
        b["sections"]["capabilities"] = [{"name": "gpu", "status": "FROZEN", "evidence": {}, "conditions": []}]
        self.assertTrue(compare(seal(a), seal(b))["capability_changed"])

    def test_significance_noise_and_insufficient(self):
        stable = summarize([1, 1, 1])
        self.assertEqual(metric_change(stable, summarize([1.2] * 3), .15)["classification"], "POSSIBLY_SIGNIFICANT")
        self.assertEqual(metric_change(stable, summarize([1.01] * 3), .15)["classification"], "WITHIN_NOISE")
        self.assertEqual(metric_change(stable, summarize([0.8, 1.2, 1.6]), .15)["classification"], "WITHIN_NOISE")
        self.assertEqual(metric_change(stable, summarize([2]), .15)["classification"], "INSUFFICIENT_DATA")

    def test_different_protocols_never_compared_as_significant(self):
        a, b = self.documents()
        for doc, protocol, samples in ((a, "a", [1]*3), (b, "b", [2]*3)):
            doc["sections"]["measurements"]["workload"] = {"protocol_hash": protocol, "statistics": {"wall_s": summarize(samples)}}
        diff = compare(seal(a), seal(b))
        self.assertEqual(diff["measurements"][0]["classification"], "INSUFFICIENT_DATA")


class CollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.quick = seal({**collector.collect(ROOT, ROOT, config.DEFAULTS, quick=True), "observation_id": "o000001"})

    def test_host_cpu_ram_os_storage(self):
        value = self.quick["sections"]["facts"]["host"]
        self.assertGreater(value["cpu"]["logical_cores"], 0)
        self.assertTrue(value["cpu"]["architecture"])
        self.assertGreater(value["ram"]["total_bytes"], 0)
        self.assertTrue(value["os"]["kernel"])
        self.assertGreater(value["storage"]["source"]["total_bytes"], 0)
        self.assertIn("source_archive_same_filesystem", value["storage"])

    def test_runtime_python_numpy_and_sandbox(self):
        value = self.quick["sections"]["facts"]["runtime"]
        self.assertEqual(value["python"]["version"], sys.version.split()[0])
        self.assertTrue(value["libraries"]["numpy"])
        self.assertIn("verified", value["sandbox"])
        self.assertTrue(value["python"]["executable_sha256"])

    def test_explicit_inventory_and_certification_distinction(self):
        inventory = self.quick["sections"]["facts"]["components"]
        self.assertEqual(len(inventory), 11)
        self.assertTrue(all(c["source_files"] for c in inventory))
        caps = {c["name"]: c for c in self.quick["sections"]["capabilities"]}
        for name in ("gpu_campaign_code_present", "appliance_code_present"):
            self.assertEqual(caps[name]["status"], "FROZEN")
            self.assertTrue(caps[name]["evidence"]["code_present"])
            self.assertFalse(caps[name]["evidence"]["certified_equivalent_to_cpu"])

    def test_no_username_hostname_or_paths(self):
        raw = canonical_json(self.quick).decode()
        for sensitive in (getpass.getuser(), socket.gethostname(), str(Path.home()), str(ROOT), sys.executable):
            if len(sensitive) >= 4:
                self.assertNotIn(sensitive, raw)
        self.assertNotIn('"hostname"', raw)
        self.assertNotIn('"username"', raw)

    def test_environment_secrets_excluded(self):
        with patch.dict(os.environ, {"GAIA_PRIVATE_TOKEN": "PRIVATE_CANARY_8ef71", "SSH_AUTH_SOCK": "/secret/socket"}):
            value = collector.collect(ROOT, ROOT, config.DEFAULTS, quick=True)
        self.assertNotIn("PRIVATE_CANARY_8ef71", canonical_json(value).decode())
        self.assertNotIn("/secret/socket", canonical_json(value).decode())

    def test_optional_failure_is_nonfatal_and_sanitized(self):
        with patch.object(gpu, "collect", side_effect=RuntimeError("/home/private TOKEN")):
            value = collector.collect(ROOT, ROOT, config.DEFAULTS, quick=True)
        error = value["sections"]["facts"]["gpu"]
        self.assertEqual(error["status"], "ERROR")
        self.assertTrue(error["nonfatal"])
        self.assertNotIn("TOKEN", canonical_json(value).decode())
        self.assertTrue(value["sections"]["facts"]["host"]["cpu"])

    def test_gpu_and_nvml_absent(self):
        with patch("gaia.observation.gpu.Path.glob", return_value=[]), patch("gaia.observation.gpu.shutil.which", return_value=None), patch("gaia.observation.gpu.ctypes.util.find_library", return_value=None):
            value = gpu.collect()
        self.assertEqual(value["status"], "UNAVAILABLE")
        self.assertFalse(value["usable_gpu"])
        self.assertEqual(value["nvml"], "UNAVAILABLE")

    def test_nvidia_profile_without_torch(self):
        with patch("gaia.observation.gpu.Path.glob", return_value=[]), patch("gaia.observation.gpu.shutil.which", return_value="nvidia-smi"), patch("gaia.observation.gpu.command", return_value="Local GPU, 4096, 3072, 1.2, 6.1"), patch("gaia.observation.gpu.ctypes.util.find_library", return_value=None):
            value = gpu.collect()
        self.assertEqual(value["devices"][0]["vram_total_bytes"], 4096 * 2**20)
        self.assertEqual(value["campaign_status"], "FROZEN")
        self.assertEqual(value["torch_cuda_available"], "UNKNOWN")

    def test_git_is_optional(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(runtime.git(temporary), {"repo_present": False})

    def test_quick_never_executes_workload_or_engine(self):
        with patch("gaia.observation.workload.collect", side_effect=AssertionError("not allowed")):
            value = collector.collect(ROOT, ROOT, config.DEFAULTS, quick=True)
        self.assertEqual(value["sections"]["measurements"]["workload"]["reason"], "quick_mode")

    def test_no_verified_sandbox_no_workload_bypass(self):
        with patch("gaia.observation.runtime.provenance.bwrap_capability", return_value={"available": False, "verified": False, "capabilities": []}), patch("gaia.observation.workload.collect", side_effect=AssertionError("not allowed")):
            value = collector.collect(ROOT, ROOT, config.DEFAULTS)
        self.assertEqual(value["sections"]["measurements"]["workload"]["status"], "UNAVAILABLE")

    def test_local_subprocess_environment_is_allowlisted(self):
        from gaia.observation.local import command
        from types import SimpleNamespace
        with patch("gaia.observation.local.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="ok")) as run:
            command(["local-program"])
        self.assertEqual(set(run.call_args.kwargs["env"]), {"PATH", "LC_ALL", "HOME"})


class RealCLITests(unittest.TestCase):
    def test_real_quick_full_history_read_compare_and_baseline(self):
        with tempfile.TemporaryDirectory(prefix="gaia-observation-cli-") as temporary:
            state = Path(temporary) / "state"
            def run(*args):
                result = subprocess.run([sys.executable, str(ROOT / "gaia.py"), *args, "--state-dir", str(state), "--json"],
                                        cwd=ROOT, capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return json.loads(result.stdout)
            quick = run("observe", "--quick", "--baseline")
            full = run("observe")
            self.assertEqual(quick["sections"]["context"]["mode"], "quick")
            workload = full["sections"]["measurements"]["workload"]
            self.assertEqual(workload["status"], "AVAILABLE", workload)
            self.assertEqual(workload["success_count"], config.DEFAULTS["observation"]["full_samples"])
            self.assertTrue(all(s["sandbox_validation"] for s in workload["samples"]))
            self.assertTrue(all(s["batches"] == 300 for s in workload["samples"]))
            self.assertGreater(workload["statistics"]["descendant_cpu_s_lower_bound"]["median"], 0)
            self.assertEqual(len(run("observations")), 2)
            self.assertEqual(run("observation", "latest"), full)
            self.assertEqual(run("observation", "baseline"), quick)
            diff = run("compare-observations", "o000001", "o000002")
            self.assertFalse(diff["hardware_changed"])
            self.assertEqual(sorted(p.name for p in state.iterdir()), ["observations"])


if __name__ == "__main__":
    unittest.main()
