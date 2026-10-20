"""Fase 8: ajuste y transferencia de estrategias en paisajes GPU cacheados."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gaia.bootstrap import locked, write_json
from gaia.gaia_transformer import benchmark_state, genome as G, meta_tasks as tasks, search_strategy as S
from gaia.gaia_transformer.campaign_store import CampaignStore
from gaia.gaia_transformer.lab import benchmark

PROTOCOL = {
    "version": "gaia_transformer_meta/v1", "tune_task": "periodic_tune", "holdout_task": "counter_holdout",
    "tune_model_seeds": [11000, 11001, 11002], "holdout_model_seeds": [21000, 21001, 21002],
    "tuning_search_seeds": list(range(100, 120)), "transfer_search_seeds": list(range(500, 540)),
    "query_budget": 4, "wall_budget_s": 90., "reference_steps": 100, "max_steps": 300,
    "eval_every": 25, "quality_tolerance": .05, "minimum_auc_gain": .01,
    "tuning_critical": 3.0, "transfer_critical": 2.023,
}


def catalog():
    result = [{"genome": dict(G.BASE), "operator": "baseline"}]
    for key, value in (("lr", .001), ("lr", .006), ("batch", 16), ("batch", 64),
                       ("dim", 32), ("layers", 1), ("heads", 4), ("weight_decay", 0.)):
        result.append({"genome": {**G.BASE, key: value}, "operator": key})
    return result


def strategies(previous):
    # Cuatro variantes conocidas, fijadas antes de acceder a datos GPU reservados.
    return [{**previous, "version": previous["version"] + 1, **change} for change in (
        {"ucb_c": .5, "p_global": .1, "small_model_prior": 0.},
        {"ucb_c": 2.0, "p_global": .4, "small_model_prior": 0.},
        {"ucb_c": 1., "p_global": .1, "small_model_prior": .3},
        {"ucb_c": .5, "p_global": .25, "small_model_prior": .6})]


def protocol_digest():
    here = Path(__file__).parent
    sources = {name: hashlib.sha256((here / name).read_bytes()).hexdigest()
               for name in ("metastudy.py", "meta_tasks.py", "meta_tasks_v1.json", "search_strategy.py", "genome.py")}
    return hashlib.sha256(json.dumps({"protocol": PROTOCOL, "catalog": catalog(), "sources": sources}, sort_keys=True).encode()).hexdigest()


def simulate(strategy, landscape, seed, random_search=False):
    """Adaptador de catálogo finito del mismo selector UCB. No promociona modelos."""
    S.validate(strategy)
    rng = random.Random(seed)
    remaining = list(range(1, len(landscape)))
    base = landscape[0]["fitness"]
    best, elapsed, trace = base, 0., []
    stats = {item["operator"]: {"attempts": 0, "reward": 0.} for item in landscape[1:]}
    for query in range(PROTOCOL["query_budget"]):
        available = {key: value for key, value in stats.items() if any(landscape[i]["operator"] == key for i in remaining)}
        if not remaining:
            trace.append(math.log(best / base))
            continue
        if random_search:
            index = rng.choice(remaining)
        else:
            operator = S.choose_operator(available, rng, query, strategy)
            # La política v0 comienza por lr; los priors de arquitectura ajustados pueden cambiarlo.
            if query == 0 and not strategy["small_model_prior"] and strategy["p_global"] == 0 and "lr" in available:
                operator = "lr"
            choices = [i for i in remaining if landscape[i]["operator"] == operator]
            index = (next(i for i in choices if landscape[i]["genome"]["lr"] == .006)
                     if query == 0 and operator == "lr" and not strategy["small_model_prior"] and not strategy["p_global"]
                     else rng.choice(choices))
        item = landscape[index]
        remaining.remove(index)
        if elapsed + item["resource_s"] <= PROTOCOL["wall_budget_s"]:
            elapsed += item["resource_s"]
            improved = item["fitness"] < best * .95
            stats[item["operator"]]["attempts"] += 1
            stats[item["operator"]]["reward"] += float(improved)
            best = min(best, item["fitness"])
        else:
            elapsed = PROTOCOL["wall_budget_s"]
        trace.append(math.log(best / base))
    return {"auc": statistics.mean(trace), "final_ratio": best / base, "resource_s": elapsed,
            "queries": PROTOCOL["query_budget"]}


def score(strategy, landscape, seeds, random_search=False):
    return [simulate(strategy, landscape, seed, random_search)["auc"] for seed in seeds]


class Builder:
    def __init__(self, task, cfg, runtime, directory):
        self.task, self.cfg, self.runtime, self.directory = task, cfg, runtime, directory
        directory.mkdir(parents=True, exist_ok=True)
        self.runner = tasks.evaluator_for(task)
        self.identity = tasks.TaskBenchmark(task).identity()
        self.count = 0

    def trial(self, source, seed, target, directory):
        result_path = directory / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text())
            if (result["candidate_sha256"] != hashlib.sha256(source.encode()).hexdigest()
                    or result["protected_sha256"] != self.identity or result["spec"]["seed"] != seed
                    or result["spec"]["target_loss"] != target):
                raise RuntimeError("Caché de paisaje distinta a su identidad")
        else:
            result = self.runner(source, self.cfg, self.runtime, directory,
                                 benchmark.TrialSpec(seed=seed, steps=100 if target is None else 300,
                                                     eval_every=25, target_loss=target),
                                 expected_identity=self.identity, require_sandbox=True, stop_file=ROOT / "STOP")
            self.count += 1
        if result["status"] != "ok" or not result["valid"]:
            raise RuntimeError(f"Trial de metaestudio inválido {directory}: {result['error']}")
        print(f"[meta GPU] {self.task} {directory.name} seed={seed} loss={result['final_loss']:.4f} "
              f"reached={result['reached']}", file=sys.stderr, flush=True)
        return result

    def build(self, seeds):
        source = G.render(G.BASE)
        refs = [self.trial(source, seed, None, self.directory / f"calibration-{seed}") for seed in seeds]
        target = max(t["final_loss"] for t in refs) + PROTOCOL["quality_tolerance"]
        entries = catalog()
        measured = {index: [] for index in range(len(entries))}
        # Alternar orden del catálogo entre semillas para no alinear siempre tamaño y temperatura.
        for position, seed in enumerate(seeds):
            order = list(range(len(entries)))
            if position % 2:
                order.reverse()
            for index in order:
                trial = self.trial(G.render(entries[index]["genome"]), seed, target,
                                   self.directory / f"candidate-{index:02d}-seed-{seed}")
                measured[index].append(trial)
        landscape = []
        for index, entry in enumerate(entries):
            trials = measured[index]
            reached = all(t["reached"] for t in trials)
            fitness = statistics.median(t["cost_s"] for t in trials) if reached else 20.
            landscape.append({**entry, "fitness": fitness, "all_quality": reached,
                              "resource_s": sum(t["wall_s"] for t in trials),
                              "costs": [t["cost_s"] for t in trials], "seeds": seeds})
        if not landscape[0]["all_quality"]:
            raise RuntimeError("Baseline del paisaje no alcanza su objetivo congelado")
        result = {"task": self.task, "corpus": tasks.manifest(self.task), "target_loss": target,
                  "identity": self.identity, "landscape": landscape, "fresh_trials": self.count}
        write_json(self.directory / "landscape.json", result)
        return result


def run(args, report):
    cfg = json.loads(args.config.read_text())
    runtime = json.loads(args.bootstrap_report.read_text())["cuda_probes"][0]["runtime"]
    frozen, _ = benchmark_state.load(ROOT, cfg, runtime)
    store = CampaignStore(ROOT, cfg["workload"]["state_dir"])
    with locked(store.dir / "calibration.lock"), locked(store.dir / "campaign.lock"):
        store.verify_versions()
        registry = store.dir / "meta_gpu_v1"
        registry.mkdir(exist_ok=True)
        completed = registry / "completed.json"
        if completed.exists():
            raise RuntimeError("Holdout v1 ya consumido; consultar el informe. Otro ajuste requiere nuevas tareas/protocolo.")
        commit = registry / "selection.json"
        study_identity = {"protocol_digest": protocol_digest(), "production_benchmark": frozen,
                          "runtime": runtime, "config": cfg}
        store.tmp.mkdir(exist_ok=True)
        tempfile.tempdir = str(store.tmp)
        if commit.exists():
            selection = json.loads(commit.read_text())
            if selection["identity"] != study_identity:
                raise RuntimeError("Estudio interrumpido con otra identidad: no reutilizar holdout")
            evidence_root = Path(selection["evidence_root"])
            report.update(selection["report"])
        else:
            evidence_root = args.output
            previous = S.load(store.dir, frozen)
            fit = Builder(PROTOCOL["tune_task"], cfg, runtime, evidence_root / "tuning").build(PROTOCOL["tune_model_seeds"])
            previous_scores = score(previous, fit["landscape"], PROTOCOL["tuning_search_seeds"])
            options = strategies(previous)
            comparisons = []
            for candidate in options:
                scores = score(candidate, fit["landscape"], PROTOCOL["tuning_search_seeds"])
                comparisons.append({"strategy": candidate, "scores": scores,
                                    "comparison": S.paired_bound(previous_scores, scores, PROTOCOL["tuning_critical"])})
            selected = min(comparisons, key=lambda item: statistics.mean(item["scores"]))
            report.update(protocol=PROTOCOL, protocol_digest=protocol_digest(), production_benchmark=frozen,
                          previous=previous, selected=selected["strategy"], tuning_comparison=selected["comparison"],
                          tuning_candidates=comparisons, tuning_previous_scores=previous_scores,
                          tuning_landscape=str(evidence_root / "tuning/landscape.json"))
            # Compromiso ANTES de crear/calibrar/medir la tarea reservada. No se cambia tras verla.
            selection = {"identity": study_identity, "evidence_root": str(evidence_root), "report": report}
            write_json(commit, selection)
            store.append({"type": "meta_selection_committed", "strategy": report["selected"],
                          "protocol_digest": protocol_digest(), "evidence": str(commit)})
        transfer = Builder(PROTOCOL["holdout_task"], cfg, runtime, evidence_root / "transfer").build(PROTOCOL["holdout_model_seeds"])
        transfer_scores = {"previous": score(report["previous"], transfer["landscape"], PROTOCOL["transfer_search_seeds"]),
                           "selected": score(report["selected"], transfer["landscape"], PROTOCOL["transfer_search_seeds"]),
                           "random": score(S.DEFAULT, transfer["landscape"], PROTOCOL["transfer_search_seeds"], True)}
        comparisons = {key: S.paired_bound(transfer_scores[key], transfer_scores["selected"], PROTOCOL["transfer_critical"])
                       for key in ("previous", "random")}
        adopt = report["tuning_comparison"]["supported"] and all(c["supported"] for c in comparisons.values())
        report.update(status="GPU_META_COMPLETE", transfer_scores=transfer_scores, transfer_comparisons=comparisons,
                      transfer_landscape=str(evidence_root / "transfer/landscape.json"), adopted=adopt,
                      conclusion="verified_transfer_on_cached_tasks" if adopt else
                      "adjustment_without_verified_transfer" if report["tuning_comparison"]["supported"] else "no_verified_search_improvement",
                      inference_scope="Catálogo finito, dos tareas y paisajes medidos; no prueba universal de mejora recursiva",
                      champion_unchanged=True)
        benchmark_state.load(ROOT, cfg, runtime)
        write_json(args.output / "result.json", report)
        if adopt:
            write_json(store.dir / "strategy_gpu.json", {"strategy": report["selected"], "evidence": str(args.output / "result.json")})
        write_json(completed, {"evidence": str(args.output / "result.json"), "adopted": adopt, "protocol_digest": protocol_digest()})
        store.append({"type": "meta_complete", "adopted": adopt, "conclusion": report["conclusion"],
                      "evidence": str(args.output / "result.json"), "protocol_digest": protocol_digest()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--bootstrap-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING"}
    try:
        run(args, report)
    except BaseException as exc:
        report.update(status="FAILED", reason=f"{type(exc).__name__}: {exc}")
        write_json(args.output / "NEEDS_HUMAN.json", {"reason": report["reason"]})
        raise
    finally:
        write_json(args.output / "result.json", report)
    print(json.dumps({"status": report["status"], "adopted": report["adopted"], "conclusion": report["conclusion"],
                      "result": str(args.output / "result.json")}))


if __name__ == "__main__":
    main()
