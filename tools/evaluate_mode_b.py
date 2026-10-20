#!/usr/bin/env python3
"""HISTORICAL TOOL — incompatible with current certified CPU MVP state format.

Closed, preregistered MLP pilot. No bootstrap, installs or existing state writes.
Retained as the historical producer, not as current operational guidance.
"""
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from gaia import config, genome as G, integrity, readiness, search, stats
from gaia.engine import Engine
from gaia.store import atomic_write

OUT = ROOT / ".gaia/reports/modo_b_mlp_20261019"
PROTOCOL = ROOT / "docs/PRERREGISTRO_MODO_B_20261019.md"
SEEDS = [20261019, 20261020, 20261021, 20261022]


def save(path, value):
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PairedEngine(Engine):
    def __init__(self, root, cfg, seed, phase="gates"):
        super().__init__(root, cfg, log=lambda text: print(text, flush=True))
        self.seed, self.phase = seed, phase

    def _load(self):
        super()._load()
        self.rng = np.random.default_rng(self.seed)

    def trial(self, *args, **kwargs):
        start = time.perf_counter()
        result = super().trial(*args, **kwargs)
        with (self.root / "trials.jsonl").open("a") as handle:
            handle.write(json.dumps({"phase": self.phase, "elapsed_s": time.perf_counter() - start,
                                     "seed": args[1] if len(args) > 1 else kwargs.get("seed"),
                                     "result": result}) + "\n")
        return result


def arm(name):
    root = OUT / name
    cfg = json.loads((root / "effective_config.json").read_text())
    eng = PairedEngine(root, cfg, int(name.split("_")[0][1:]) + SEEDS[0] - 1)
    result = {"name": name, "seed": eng.seed, "enabled": cfg["research"]["enabled"]}
    total = time.perf_counter()
    try:
        t = time.perf_counter()
        ready = readiness.prepare(eng)
        result["gates_s"] = time.perf_counter() - t
        result["gates_status"] = ready["status"]
        result["cv"] = ready.get("gates", {}).get("G2_reliability", {}).get("cv")
        if ready["status"] != "READY_FOR_CAMPAIGN":
            result["status"] = "blocked_gates"
            return 30
        if result["cv"] > 0.025:
            result["status"] = "blocked_noise"
            return 30
        assert not readiness.check_identity(eng)
        eng.phase = "campaign"
        t = time.perf_counter()
        result["outcome"] = eng.run(until="budget", minutes=10, max_experiments=12, meta=False)
        result["campaign_s"] = time.perf_counter() - t
        records = eng.store.records()
        ends = [r for r in records if r["type"] == "end"]
        starts = [r for r in records if r["type"] == "start"]
        accepted = [r for r in ends if r.get("decision") == "accepted"]
        result.update({"experiments": len(ends), "starts": len(starts),
            "research_experiments": sum(r.get("origin") == "research" for r in ends),
            "research_cycles": sum(r["type"] == "research_diagnosis" for r in records),
            "promotions": len(accepted), "unique_promotions": len({G.genome_hash(r["genome"]) for r in accepted}),
            "unique_promoted_hashes": sorted({G.genome_hash(r["genome"]) for r in accepted}),
            "candidate_errors": sum((r.get("screen") or {}).get("status") in ("error", "timeout", "invalid") for r in ends),
            "final_version": eng.store.current_version(), "final_source_sha256": digest(eng.store.stable / eng.store.current_version() / "trainer.py"),
            "research_results": [r for r in records if r["type"] == "research_result"],
            "status": "complete" if len(ends) == 12 and result["outcome"] == "budget" else "incomplete"})
        assert len(starts) <= 12 and len(ends) <= 12
        return 0 if result["status"] == "complete" else 10
    except Exception:
        result["status"], result["exception"] = "error", traceback.format_exc()
        traceback.print_exc()
        return 1
    finally:
        result["total_s"] = time.perf_counter() - total
        save(root / "result.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)


def initialize():
    OUT.mkdir(parents=True, exist_ok=False)
    shutil.copy2(PROTOCOL, OUT / "PREREGISTRATION.md")
    snapshot = OUT / "source"
    snapshot.mkdir()
    sources = list((ROOT / "gaia/protected").glob("*.py"))
    sources += [ROOT / "gaia" / (n + ".py") for n in
                ("engine", "research", "readiness", "config", "search", "genome", "mutate", "snippets", "store", "stats", "integrity", "observe_worker")]
    sources += [Path(__file__).resolve(), ROOT / "tests/test_research_budget.py"]
    hashes = {}
    for path in sources:
        relative = path.relative_to(ROOT)
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        hashes[str(relative)] = digest(path)
    save(OUT / "preregistration_seal.json", {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "protocol_sha256": digest(PROTOCOL), "sources": hashes,
        "benchmark_source": "state_numpy_mlp_6446deabc01ec4be/benchmark.json",
        "benchmark_sha256": digest(ROOT / "state_numpy_mlp_6446deabc01ec4be/benchmark.json"),
        "python": sys.executable, "loadavg": os.getloadavg(), "affinity": sorted(os.sched_getaffinity(0))})
    # Construct every independent initial state before any measurement.
    for i, seed in enumerate(SEEDS, 1):
        for enabled in (True, False):
            name = f"p{i}_{'on' if enabled else 'off'}"
            root = OUT / name
            root.mkdir()
            (root / "gaia").symlink_to(ROOT / "gaia", target_is_directory=True)
            cfg = config.load(root)
            cfg["limits"].update(max_total_minutes=10, max_experiments=12)
            cfg["meta"]["enabled"] = False
            cfg["research"].update(enabled=enabled, trigger_after=2, max_hypotheses=2)
            save(root / "effective_config.json", cfg)
            eng = PairedEngine(root, cfg, seed)
            shutil.copy2(ROOT / "state_numpy_mlp_6446deabc01ec4be/benchmark.json", eng.store.dir / "benchmark.json")
            base = G.new_genome()
            eng.store.promote(base, G.render(base), {"note": "independent baseline, no transferred search history"})
            eng.store.save_state({"n_experiments": 0, "since_promotion": 0, "ref": None,
                "strategy": dict(search.DEFAULT_STRATEGY), "search_seconds": 0.0,
                "consecutive_errors": 0, "plateau_meta_used": False, "created": 0})
            integrity.write_manifest(root, eng.store.dir)
            save(root / "initial_hashes.json", {str(p.relative_to(root)): digest(p) for p in eng.store.dir.rglob("*") if p.is_file()})


def audit_pair(i):
    engines, sources = {}, {}
    for who in ("on", "off"):
        root = OUT / f"p{i}_{who}"
        cfg = json.loads((root / "effective_config.json").read_text())
        engines[who] = PairedEngine(root, cfg, SEEDS[i - 1], phase="audit")
        engines[who]._load()
        sources[who] = engines[who].store.load_version()[1]
    sources["baseline"] = engines["on"].store.load_version("v0000")[1]
    runs = {who: [] for who in sources}
    orders = []
    start = time.perf_counter()
    for j, seed in enumerate(range(5000, 5005)):
        order = ["baseline", "on", "off"]
        offset = (j + i - 1) % 3
        order = order[offset:] + order[:offset]
        orders.append(order)
        for who in order:
            eng = engines["off" if who == "off" else "on"]
            runs[who].append(eng.trial(sources[who], seed))
    acc = engines["on"].acc
    comparisons = {"on_vs_off": stats.decide(runs["off"], runs["on"], acc),
                   "off_vs_on": stats.decide(runs["on"], runs["off"], acc)}
    for who in ("on", "off"):
        comparisons[who + "_vs_baseline"] = stats.decide(runs["baseline"], runs[who], acc)
    result = {"pair": i, "orders": orders, "runs": runs, "comparisons": comparisons,
        "elapsed_s": time.perf_counter() - start,
        "quality_ok": all(r.get("reached") and r.get("status") == "ok" for rs in runs.values() for r in rs),
        "saturated": any(statistics.median(r["cost_s"] for r in runs[who]) < 0.06 for who in ("on", "off"))}
    save(OUT / f"audit_p{i}.json", result)
    return result


def summarize(blocker=None):
    arms = [json.loads(p.read_text()) for p in sorted(OUT.glob("p*/result.json"))]
    audits = [json.loads(p.read_text()) for p in sorted(OUT.glob("audit_p*.json"))]
    valid = not blocker and len(arms) == 8 and len(audits) == 4
    valid = valid and all(a["status"] == "complete" and
        ((a["research_experiments"] > 0 and a["research_cycles"] > 0) if a["enabled"] else a["research_experiments"] == 0) for a in arms)
    valid = valid and all(a["quality_ok"] and not a["saturated"] for a in audits)
    metrics = {}
    if len(audits) == 4 and len(arms) == 8:
        on = {a["name"]: a for a in arms}
        ratios = [a["comparisons"]["on_vs_off"].get("ratio") for a in audits]
        metrics = {"on_wins": sum(a["comparisons"]["on_vs_off"]["decision"] == "accepted" for a in audits),
            "off_wins": sum(a["comparisons"]["off_vs_on"]["decision"] == "accepted" for a in audits),
            "geomean_on_off": math.exp(statistics.mean(math.log(r) for r in ratios)) if all(ratios) else None,
            "median_total_time_on_off": statistics.median(on[f"p{i}_on"]["total_s"] / on[f"p{i}_off"]["total_s"] for i in range(1, 5)),
            "median_unique_promotions_on": statistics.median(on[f"p{i}_on"]["unique_promotions"] for i in range(1, 5)),
            "median_unique_promotions_off": statistics.median(on[f"p{i}_off"]["unique_promotions"] for i in range(1, 5))}
    win = valid and metrics["on_wins"] >= 3 and metrics["off_wins"] == 0 and metrics["geomean_on_off"] <= 0.95 and metrics["median_total_time_on_off"] <= 1.25 and metrics["median_unique_promotions_on"] >= metrics["median_unique_promotions_off"]
    decision = "consistent_on_advantage" if win else "no_demonstrated_value" if valid else "inconclusive"
    result = {"decision": decision, "valid": bool(valid), "blocker": blocker,
        "metrics": metrics, "arms": arms, "audits": [{k: v for k, v in a.items() if k != "runs"} for a in audits]}
    save(OUT / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm")
    args = parser.parse_args()
    if args.arm:
        return arm(args.arm)
    initialize()
    commands, blocker = [], None
    try:
        for i in range(1, 5):
            for who in (("on", "off") if i % 2 else ("off", "on")):
                name = f"p{i}_{who}"
                command = [sys.executable, str(Path(__file__).resolve()), "--arm", name]
                commands.append({"argv": command, "cwd": str(ROOT), "env": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "GAIA_FP_TORCH")}})
                save(OUT / "commands.json", commands)
                print("START", name, flush=True)
                with (OUT / name / "run.log").open("w") as log:
                    p = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=1000)
                save(OUT / name / "process.json", {"returncode": p.returncode})
                print("END", name, p.returncode, flush=True)
                if p.returncode:
                    blocker = f"{name}: returncode {p.returncode}; see run.log/result.json"
                    return 30
            audit_pair(i)
    except Exception:
        blocker = traceback.format_exc()
        raise
    finally:
        summarize(blocker)
    return 0


if __name__ == "__main__":
    sys.exit(main())
