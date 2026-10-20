"""Modo B GPU: observar, formular, contrastar y recordar; nunca promueve versiones."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gaia.bootstrap import locked, write_json
from gaia.gaia_transformer import benchmark_state, genome as G, observation
from gaia.gaia_transformer.campaign_store import CampaignStore
from gaia.gaia_transformer.lab.calibration import SPEC, decide, valid_trial


FAMILIES = {"optimizer_foreach": ("optimizer", "optimizer_impl"), "clip_foreach": ("clip", "clip_impl")}


def champion_key(source):
    return hashlib.sha256(source.encode()).hexdigest()


def memory(records, key):
    result = {}
    for record in records:
        if record.get("type") == "research_end" and record.get("champion_sha256") == key:
            result.setdefault(record["family"], []).append(record)
    return result


def priors(records):
    result = {family: {"supported": 0, "refuted": 0, "inconclusive": 0} for family in FAMILIES}
    for record in records:
        if record.get("type") == "research_end" and record.get("family") in result and record.get("verdict") in result[record["family"]]:
            result[record["family"]][record["verdict"]] += 1
    for counts in result.values():
        counts["support_prior"] = (counts["supported"] + 1) / (counts["supported"] + counts["refuted"] + 2)
    return result


def unlocked_options(records, source):
    """Solo aceptaciones verificables del mismo campeón pueden desbloquear propuestas."""
    unlocked = []
    for family, attempts in memory(records, champion_key(source)).items():
        for record in attempts:
            if record.get("verdict") != "supported" or family not in FAMILIES:
                continue
            comparison = record.get("comparison", {})
            if decide(comparison.get("champion", []), comparison.get("candidate", []), SPEC["confirm_seeds"])["decision"] != "accepted":
                continue
            option = FAMILIES[family][1]
            candidate = record.get("candidate_genome", {})
            if candidate.get(option) != "foreach":
                continue
            expected = champion_key(G.render(candidate))
            if (all(t.get("candidate_sha256") == expected for t in comparison["candidate"])
                    and all(t.get("candidate_sha256") == champion_key(source) for t in comparison["champion"])):
                unlocked.append(option)
    return sorted(set(unlocked))


def should_trigger(records, source, after=40):
    key = champion_key(source)
    completed = [record for record in records if record.get("type") == "end" and record.get("decision") not in ("aborted", "error")]
    last_promotion = max((i for i, r in enumerate(completed) if r.get("decision") == "accepted"), default=-1)
    since = len(completed) - last_promotion - 1
    last_trigger = max((r.get("completed", -1) for r in records if r.get("type") == "research_trigger"
                        and r.get("champion_sha256") == key), default=0)
    return since >= after and len(completed) - last_trigger >= after, len(completed)


def hypotheses(diagnosis, genome, records, source):
    past = memory(records, champion_key(source))
    prior = priors(records)
    result = []
    for family, (phase, option) in FAMILIES.items():
        attempts = past.get(family, [])
        terminal = any(r.get("verdict") in ("supported", "refuted", "pruned") for r in attempts)
        if terminal or len(attempts) >= 2 or genome.get(option) == "foreach":
            continue
        bound = diagnosis["estimated_cost_phase_shares"][phase]
        result.append({"family": family, "option": option, "value": "foreach", "component": phase,
            "mechanism": "Agrupar operaciones de tensores con foreach para reducir lanzamientos/overhead Python",
            "evidence": {"estimated_cost_share": bound, "profiling_overhead": diagnosis["instrumentation_overhead_ratio"]},
            "estimated_max_gain": bound, "expected_gain_if_phase_halved": bound * .5,
            "falsification": "Refutada si falla calidad/RAM/VRAM o IC95% inferior del ratio >=0.95; si no es concluyente, no desbloquear",
            "acceptance": "Cinco pares válidos, calidad en todos, IC95% superior <0.95 y RAM/VRAM <=1.25x",
            "cost": "Un cribado campeón/candidato y cinco pares intercalados; trial limitado a 20s por defecto",
            "risk": "foreach puede usar más memoria o no disponer de kernels deterministas compatibles",
            "prior": prior[family], "provenance": "known"})
    return sorted(result, key=lambda h: h["estimated_max_gain"] * h["prior"]["support_prior"], reverse=True)


def verdict(comparison):
    decision = comparison["decision"]
    if decision["decision"] == "accepted":
        return "supported"
    if (decision["decision"] == "pareto_alternative" or decision.get("lower95", 0) >= 1 - SPEC["min_gain"]
            or any(not valid_trial(t) for t in comparison["candidate"])):
        return "refuted"
    return "inconclusive"


def cycle(store, cfg, runtime, frozen, output, bootstrap_report, lab, deadline):
    output.mkdir(parents=True, exist_ok=False)
    version = store.current_version()
    genome, source = store.load_version()
    key = champion_key(source)
    before = unlocked_options(store.records(), source)
    report = {"status": "RUNNING", "champion": version, "champion_sha256": key, "hypotheses": [],
              "unlocked_before": before, "promotions": 0, "prior_counts": priors(store.records())}
    try:
        if (ROOT / "STOP").exists():
            raise InterruptedError("STOP solicitado")
        # Si todas las familias están resueltas no se repite ni el perfilado.
        past = memory(store.records(), key)
        remaining = [family for family in FAMILIES if not any(r.get("verdict") in ("supported", "refuted", "pruned")
                     for r in past.get(family, [])) and len(past.get(family, [])) < 2]
        if remaining:
            if time.monotonic() + cfg.get("limits", {}).get("max_experiment_seconds", 20) * 2 + 5 >= deadline:
                raise TimeoutError("Presupuesto insuficiente para observación de Modo B")
            obs_dir = output / "observation"
            obs_dir.mkdir()
            write_json(output / "config.json", cfg)
            observed = {}
            observation.run(SimpleNamespace(config=output / "config.json", bootstrap_report=bootstrap_report,
                                             output=obs_dir, steps=100), observed, already_locked=True)
            report["observation"] = str(obs_dir / "result.json")
            candidates = hypotheses(observed["diagnosis"], genome, store.records(), source)
        else:
            candidates = []
            report["skip_reason"] = "Familias resueltas o límite de dos contrastes inconclusos para este campeón"
        for hypothesis in candidates:
            family = hypothesis["family"]
            event = {"family": family, "champion_sha256": key, "champion": version, "hypothesis": hypothesis}
            store.append({"type": "research_start", **event, "evidence": str(output / "result.json")})
            if hypothesis["estimated_max_gain"] < SPEC["min_gain"]:
                outcome = {"verdict": "pruned", "reason": "Cota ideal estimada de Amdahl inferior al 5%; no consumir trials"}
            else:
                proposal = {**genome, hypothesis["option"]: "foreach"}
                candidate_source = G.render(proposal)
                champion_screen = lab.trial(source, 0)
                if not valid_trial(champion_screen):
                    raise RuntimeError("El campeón no alcanza calidad durante investigación")
                screen = lab.trial(candidate_source, 0)
                if not valid_trial(screen):
                    outcome = {"verdict": "refuted", "reason": "El cribado no alcanza calidad", "screen": screen,
                               "candidate_genome": proposal}
                elif screen["cost_s"] > champion_screen["cost_s"] * SPEC["screen_slack"]:
                    outcome = {"verdict": "inconclusive", "reason": "Cribado excede 1.3x; no consumir confirmación",
                               "screen": {"champion": champion_screen, "candidate": screen}, "candidate_genome": proposal}
                else:
                    comparison = lab.paired(source, candidate_source, SPEC["confirm_seeds"])
                    outcome = {"verdict": verdict(comparison), "comparison": comparison, "candidate_genome": proposal,
                               "screen": {"champion": champion_screen, "candidate": screen}}
            if store.current_version() != version or key != champion_key(store.load_version()[1]):
                raise RuntimeError("El campeón cambió durante investigación")
            benchmark_state.load(ROOT, cfg, runtime)
            evidence = {**event, **outcome, "type": "research_end", "evidence": str(output / f"{family}.json")}
            write_json(output / f"{family}.json", evidence)
            store.append(evidence)
            report["hypotheses"].append({"family": family, "verdict": outcome["verdict"]})
            print(f"[Modo B GPU] {family}: {outcome['verdict']}", file=sys.stderr, flush=True)
        report.update(status="GPU_RESEARCH_COMPLETE", unlocked_after=unlocked_options(store.records(), source),
                      champion_unchanged=store.current_version() == version)
        return report
    except BaseException as exc:
        report.update(status="FAILED", reason=f"{type(exc).__name__}: {exc}")
        write_json(output / "NEEDS_HUMAN.json", {"reason": report["reason"]})
        raise
    finally:
        write_json(output / "result.json", report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--bootstrap-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--minutes", type=float, default=10)
    args = parser.parse_args()
    if not 1 <= args.minutes <= 60:
        parser.error("minutes debe ser 1..60")
    from gaia.gaia_transformer.campaign import CampaignLab
    cfg = json.loads(args.config.read_text())
    runtime = json.loads(args.bootstrap_report.read_text())["cuda_probes"][0]["runtime"]
    frozen, _ = benchmark_state.load(ROOT, cfg, runtime)
    store = CampaignStore(ROOT, cfg["workload"]["state_dir"])
    with locked(store.dir / "calibration.lock"), locked(store.dir / "campaign.lock"):
        store.verify_versions()
        if store.current_version() is None:
            raise RuntimeError("Preparar campeón con gaia-transformer-prepare primero")
        deadline = time.monotonic() + args.minutes * 60
        trials_dir = args.output.parent / (args.output.name + "-trials")
        trials_dir.mkdir(parents=True, exist_ok=False)
        lab = CampaignLab(cfg, runtime, trials_dir, frozen["identity"], frozen["target_loss"], deadline=deadline)
        result = cycle(store, cfg, runtime, frozen, args.output, args.bootstrap_report, lab, deadline)
    print(json.dumps({"status": result["status"], "result": str(args.output / "result.json"),
                      "hypotheses": result["hypotheses"], "unlocked": result["unlocked_after"]}))


if __name__ == "__main__":
    main()
