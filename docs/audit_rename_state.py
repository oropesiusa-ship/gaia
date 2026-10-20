"""Read-only audit of the rebuilt state; never measures or consumes holdout."""
import json
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gaia.protected import runtime
from gaia.gaia_transformer import benchmark_state
from gaia.gaia_transformer.campaign_store import CampaignStore


def main():
    cfg = json.loads((ROOT / ".gaia/configs/df1f7863934daabc.json").read_text())
    benchmark, source = benchmark_state.load(ROOT, cfg, runtime.fingerprint(with_torch=True))
    store = CampaignStore(ROOT, cfg["workload"]["state_dir"])
    store.verify_versions()
    records = store.records()
    starts = [r for r in records if r["type"] == "start"]
    ends = [r for r in records if r["type"] == "end"]
    assert len({r["id"] for r in starts}) == len(starts)
    assert {r["id"] for r in starts} == {r["id"] for r in ends}
    ready = json.loads((store.dir / "readiness_gpu.json").read_text())
    assert all(g["ok"] for g in ready["gates"].values())
    assert not list(store.tmp.iterdir())
    result = {"status": "STATE_INTEGRITY_OK", "state": cfg["workload"]["state_dir"],
              "baseline_sha256": benchmark["baseline_sha256"], "target_loss": benchmark["target_loss"],
              "reference_cost_s": benchmark["reference_cost_s"], "versions": store.versions(),
              "champion": store.current_version(), "ledger_records": len(records),
              "experiments": [{"id": r["id"], "decision": r["decision"]} for r in ends],
              "gates": {k: v["ok"] for k, v in ready["gates"].items()}}
    cleanup_path = ROOT / "docs/evidencia_renombrado/limpieza_fase6_aplicada.json"
    if cleanup_path.exists():
        cleanup = json.loads(cleanup_path.read_text())
        assert all(not (ROOT / name).exists() for name in cleanup["roots"])
        assert not (ROOT / "legacy_v0").exists()
        assert importlib.util.find_spec("gaia.tinygpt") is None
        inventory = json.loads((ROOT / "docs/evidencia_renombrado/inventario_fase0.json").read_text())
        preserved = cleanup["preserved_roots"]
        preserved += [r["path"] + "/" for r in cleanup["report_review"] if r["action"] == "preserve"]
        checked = []
        for entry in inventory["files"]:
            if any(entry["path"] == prefix.rstrip("/") or entry["path"].startswith(prefix) for prefix in preserved):
                assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"], entry["path"]
                checked.append(entry["path"])
        assert (ROOT / ".gaia/venvs/cpu-numpy-6446deabc01ec4be/bin/python").exists()
        assert hashlib.sha256((ROOT / "archives/text_prototype/sample_corpus.txt").read_bytes()).hexdigest() == "3d8922516deb38620bc1edd5f5bd4c3194dc42b255d80dea890a9d85a8f8b4e7"
        result["preserved_files_verified"] = checked
        result["cleanup_verified"] = True
        result["legacy_corpus_verified"] = True
    completed = store.dir / "meta_gpu_v1/completed.json"
    if completed.exists():
        from gaia.gaia_transformer.search_strategy import load
        from gaia.gaia_transformer import metastudy
        result["strategy"] = load(store.dir, benchmark)
        result["meta_completed"] = json.loads(completed.read_text())
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (completed, completed.with_name("selection.json"), store.ledger)}
        args = SimpleNamespace(config=ROOT / ".gaia/configs/df1f7863934daabc.json",
                               bootstrap_report=ROOT / ".gaia/reports/20261016T080758Z-b50b1272/report.json",
                               output=ROOT / "docs/evidencia_renombrado/unused_holdout_output")
        try:
            metastudy.run(args, {})
        except RuntimeError as error:
            assert "Holdout v1 ya consumido" in str(error)
            result["holdout_reuse_rejected"] = str(error)
        else:
            raise AssertionError("Consumed holdout was reusable")
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in before.items())
        meta = json.loads(Path(result["meta_completed"]["evidence"]).read_text())
        result["meta_summary"] = {k: meta[k] for k in ("selected", "conclusion", "tuning_comparison", "transfer_comparisons")}
    tag = sys.argv[1] if len(sys.argv) > 1 else "fase4"
    output = ROOT / "docs/evidencia_renombrado" / f"integridad_{tag}.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    summary = {k: v for k, v in result.items() if k != "preserved_files_verified"}
    if "preserved_files_verified" in result:
        summary["preserved_files_count"] = len(result["preserved_files_verified"])
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
