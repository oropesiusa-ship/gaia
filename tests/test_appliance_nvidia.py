"""The physical profile must not silently weaken the CUDA driver's gate."""
import unittest
from gaia.appliance_nvidia_source import index_digest, paragraphs

from gaia.appliance_nvidia import PACKAGES, candidates, driver_compatibility


class NvidiaProfileTests(unittest.TestCase):
    def test_debian_and_backports_550_fail_existing_cuda_gate(self):
        for version in ("550.163.01-2", "550.163.01-4~bpo13+1"):
            result = driver_compatibility(version, "560.28.03")
            self.assertFalse(result["meets_existing_minimum"])
            self.assertFalse(result["profile_accepted"])

    def test_newer_driver_is_only_a_candidate_not_hardware_acceptance(self):
        result = driver_compatibility("580.95.05-1", "560.28.03")
        self.assertTrue(result["meets_existing_minimum"])
        self.assertFalse(result["gpu_tested"])
        self.assertFalse(result["profile_accepted"])

    def test_comparison_uses_upstream_version_not_debian_epoch(self):
        self.assertFalse(driver_compatibility("9:550.163.01-99", "560.28.03")["meets_existing_minimum"])
        self.assertTrue(driver_compatibility("560.28.3-1", "560.28.03")["meets_existing_minimum"])
        with self.assertRaises(ValueError):
            driver_compatibility("(none)", "560.28.03")

    def test_incomplete_apt_profile_is_rejected(self):
        text = "\n".join(f"{p}:\n  Installed: (none)\n  Candidate: 1.2.3-1" for p in PACKAGES)
        self.assertEqual(set(candidates(text)), set(PACKAGES))
        with self.assertRaises(ValueError):
            candidates(text.replace("  Candidate: 1.2.3-1", "  Candidate: (none)", 1))

    def test_index_digest_uses_sha256_not_weaker_sections(self):
        digest = "a" * 64
        release = "MD5Sum:\n " + "b" * 32 + " 10 Packages.gz\nSHA256:\n " + digest + " 20 Packages.gz\n"
        self.assertEqual(index_digest(release, "Packages.gz"), (digest, 20))
        with self.assertRaises(ValueError):
            index_digest(release + " " + digest + " 20 Packages.gz\n", "Packages.gz")
        with self.assertRaises(ValueError):
            index_digest("MD5Sum:\n ab 20 Packages.gz\n", "Packages.gz")

    def test_package_metadata_rejects_duplicate_identity_and_preserves_dependencies(self):
        with self.assertRaises(ValueError):
            list(paragraphs("Package: libcuda1\nPackage: unexpected\n"))
        row = next(paragraphs("Package: libcuda1\nDepends: libc6,\n libnvidia-ml1\n"))
        self.assertEqual(row["Depends"], "libc6,\nlibnvidia-ml1")


if __name__ == "__main__":
    unittest.main()
