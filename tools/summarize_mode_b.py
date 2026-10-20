#!/usr/bin/env python3
"""HISTORICAL ANALYZER — tables for the closed MLP pilot, not a current pipeline.

Uses historical ROOT/OUT paths and writes analysis.json. For protected archives,
use the external verifier that captures analysis in memory instead of writing.
"""
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".gaia/reports/modo_b_mlp_20261019"


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    summary = load(OUT / "summary.json")
    seal = load(OUT / "preregistration_seal.json")
    checks = {"protocol_unchanged": sha(OUT / "PREREGISTRATION.md") == seal["protocol_sha256"],
        "source_snapshot_matches_seal": all(sha(OUT / "source" / p) == h for p, h in seal["sources"].items()),
        "executed_sources_still_match": all(sha(ROOT / p) == h for p, h in seal["sources"].items())}
    rows, sources, research = [], {"on": set(), "off": set()}, []
    blocked = []
    all_trials = 0
    for i in range(1, 5):
        roots = {who: OUT / f"p{i}_{who}" for who in ("on", "off")}
        a, b = [load(roots[who] / "effective_config.json") for who in ("on", "off")]
        a["research"].pop("enabled")
        b["research"].pop("enabled")
        checks[f"pair_{i}_only_enabled_differs"] = a == b
        checks[f"pair_{i}_identical_initial_state"] = load(roots["on"] / "initial_hashes.json") == load(roots["off"] / "initial_hashes.json")
        checks[f"pair_{i}_separate_state_inodes"] = (roots["on"] / "state/state.json").stat().st_ino != (roots["off"] / "state/state.json").stat().st_ino
        audit_path = OUT / f"audit_p{i}.json"
        if not audit_path.exists():
            for root in roots.values():
                if (root / "result.json").exists():
                    result = load(root / "result.json")
                    result["measured_trials"] = len((root / "trials.jsonl").read_text().splitlines())
                    all_trials += result["measured_trials"]
                    blocked.append(result)
            continue
        audit = load(audit_path)
        for who, root in roots.items():
            result = load(root / "result.json")
            records = [json.loads(line) for line in (root / "state/ledger.jsonl").read_text().splitlines()]
            ends = [r for r in records if r["type"] == "end"]
            starts = [r for r in records if r["type"] == "start"]
            checks[f"p{i}_{who}_bounded_unique_ids"] = len(starts) == len(ends) == 12 and len({r["id"] for r in starts}) == 12
            checks[f"p{i}_{who}_all_gates_pass"] = all(g["ok"] for g in load(root / "state/readiness.json")["gates"].values())
            checks[f"p{i}_{who}_preregistered_seed"] = result["seed"] == 20261018 + i
            promoted = []
            for r in ends:
                if r.get("promoted_to"):
                    promoted.append(sha(root / "state/stable" / r["promoted_to"] / "trainer.py"))
            sources[who].update(promoted)
            trial_count = len((root / "trials.jsonl").read_text().splitlines())
            all_trials += trial_count
            research.extend(result["research_results"])
            ratio = audit["comparisons"][who + "_vs_baseline"].get("ratio")
            rows.append({"pair": i, "arm": who, "seed": result["seed"],
                "candidates": result["experiments"], "research_candidates": result["research_experiments"],
                "promotions": result["promotions"], "unique_promoted_sources": len(set(promoted)),
                "gain_baseline_over_final": 1 / ratio if ratio else None,
                "final_vs_baseline": audit["comparisons"][who + "_vs_baseline"],
                "campaign_s": result["campaign_s"], "gates_s": result["gates_s"],
                "total_s": result["total_s"], "trials_including_gates_audit": trial_count,
                "g2_cv": result["cv"], "errors": result["candidate_errors"],
                "final_median_s": statistics.median(r["cost_s"] for r in audit["runs"][who])})
    partial = summary["audits"]
    ratios = [a["comparisons"]["on_vs_off"].get("ratio") for a in partial]
    import math
    aggregate = {"checks": checks, "all_checks_pass": all(checks.values()), "rows": rows,
        "blocked_arms": blocked, "preregistered_decision": summary["decision"],
        "completed_pairs": len(partial), "partial_descriptive_metrics": {
            "on_wins": sum(a["comparisons"]["on_vs_off"]["decision"] == "accepted" for a in partial),
            "off_wins": sum(a["comparisons"]["off_vs_on"]["decision"] == "accepted" for a in partial),
            "geomean_on_off": math.exp(statistics.mean(math.log(r) for r in ratios)) if ratios and all(ratios) else None,
            "median_total_time_on_off": statistics.median(rows[j]["total_s"] / rows[j+1]["total_s"] for j in range(0, len(rows), 2)) if rows else None},
        "total_measured_trials": all_trials,
        "unique_promoted_sources_on": len(sources["on"]), "unique_promoted_sources_off": len(sources["off"]),
        "unique_promoted_sources_union": len(sources["on"] | sources["off"]),
        "research_verdict_counts": {status: sum(r["status"] == status for r in research)
            for status in ("supported", "refuted", "refuted_screen", "inconclusive")},
        "campaign_seconds_on": sum(r["campaign_s"] for r in rows if r["arm"] == "on"),
        "campaign_seconds_off": sum(r["campaign_s"] for r in rows if r["arm"] == "off"),
        "total_seconds_on": sum(r["total_s"] for r in rows if r["arm"] == "on"),
        "total_seconds_off": sum(r["total_s"] for r in rows if r["arm"] == "off"),
        "audit_seconds": sum(a["elapsed_s"] for a in summary["audits"])}
    (OUT / "analysis.json").write_text(json.dumps(aggregate, indent=2, ensure_ascii=False))
    print(json.dumps(aggregate, indent=2, ensure_ascii=False))
    print("\n| Pareja | Brazo | Candidatos B/total | Promociones | Ganancia final | Campaña s | Total con puertas s | CV |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['pair']} | {r['arm'].upper()} | {r['research_candidates']}/{r['candidates']} | {r['promotions']} | {r['gain_baseline_over_final']:.3f}× | {r['campaign_s']:.1f} | {r['total_s']:.1f} | {100*r['g2_cv']:.2f}% |")


if __name__ == "__main__":
    main()
