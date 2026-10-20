"""Instrumentación de observación: AST de step, no cambia fuentes del laboratorio."""
import ast
import math
import statistics


PHASES = ("mode", "sampler_transfer", "gather", "forward_loss", "finite_check", "zero_grad",
          "backward", "clip", "optimizer", "loss_item", "bookkeeping")


def instrument(source):
    """Solo admite la estructura conocida de Trainer.step; falla si cambia su semántica."""
    tree = ast.parse(source)
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Trainer"]
    if len(matches) != 1:
        raise ValueError("Perfilador requiere la clase Trainer conocida")
    steps = [node for node in matches[0].body if isinstance(node, ast.FunctionDef) and node.name == "step"]
    if len(steps) != 1:
        raise ValueError("No se encontró un step instrumentable")
    step = steps[0]
    # Cada bloque está vinculado al código conocido; nunca se adivina una fase.
    expected = ["self.model.train()", "idx = torch.randint(len(self.data), (self.cfg.batch,), generator=self.rng).to(self.device)",
                "rows = self.data[idx]", "_, loss = self.model(rows[:, :-1], rows[:, 1:])",
                "if not torch.isfinite(loss).item():\n    raise RuntimeError('Loss no finita')",
                "self.optimizer.zero_grad(set_to_none=True)", "loss.backward()",
                "torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.cfg.clip_norm, error_if_nonfinite=True, foreach=False)",
                "self.optimizer.step()", "value = loss.item()", "self.steps += 1", "self.losses.append(value)", "return value"]
    normalized = lambda text: ast.dump(ast.parse(text), include_attributes=False)
    if len(step.body) != len(expected) or any(normalized(ast.unparse(node)) not in {
            normalized(text), normalized(text.replace("foreach=False", "foreach=True"))}
            for node, text in zip(step.body, expected)):
        raise ValueError("Trainer.step cambió; actualizar instrumentación y comprobar paridad antes de perfilar")
    wrapped = []
    groups = [[node] for node in step.body[:10]] + [step.body[10:12]]
    for phase, statements in zip(PHASES, groups):
        context = ast.Call(func=ast.Name(id="gaia_observe_phase", ctx=ast.Load()), args=[ast.Constant(phase)], keywords=[])
        wrapped.append(ast.With(items=[ast.withitem(context_expr=context)], body=statements))
    step.body = wrapped + [step.body[-1]]
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def validate_observation(result):
    runs = result["plain_runs"]
    if len(runs) != 3 or not result["parity"] or any(run["signature"] != runs[0]["signature"] for run in runs):
        raise ValueError("Observación sin paridad numérica o repetibilidad entre entrenamientos frescos")
    profile = result["instrumented"]
    if profile["signature"] != runs[0]["signature"]:
        raise ValueError("Instrumentación cambió el resultado numérico")
    if set(profile["phases"]) != set(PHASES):
        raise ValueError("Faltan fases medidas")
    for value in [run["train_s"] for run in runs] + [profile["train_s"]] + [p["wall_s"] for p in profile["phases"].values()]:
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("Duraciones de observación inválidas")
    for phase in profile["phases"].values():
        if (phase["count"] != result["steps"] or not math.isfinite(phase["cuda_stream_ms"])
                or phase["cuda_stream_ms"] < 0):
            raise ValueError("Contadores o eventos CUDA inválidos")
    if sum(phase["wall_s"] for phase in profile["phases"].values()) > profile["train_s"] * 1.01:
        raise ValueError("Contabilidad de fases solapada")


def history_metrics(records):
    starts = {record["id"]: record for record in records if record.get("type") == "start"}
    ends = {record["id"]: record for record in records if record.get("type") == "end"}
    regions = []
    operators = {}
    completed = []
    for ident, record in starts.items():
        if ident not in ends:
            continue
        end = ends[ident]
        if end.get("decision") == "aborted":
            continue
        completed.append(end)
        genome = record.get("genome", {})
        regions.append(tuple(genome.get(key) for key in ("dim", "layers", "heads", "optimizer", "batch", "dropout")))
        op = record.get("operator", "unknown")
        operators[op] = operators.get(op, 0) + 1
    n = len(completed)
    last_promotion = max((index for index, end in enumerate(completed) if end.get("decision") == "accepted"), default=-1)
    return {"completed": n, "aborted": sum(end.get("decision") == "aborted" for end in ends.values()),
            "distinct_regions": len(set(regions)), "region_repeat_fraction": 1 - len(set(regions)) / n if n else None,
            "operators": operators, "since_promotion": n - last_promotion - 1,
            "confirmation_fraction": sum(end.get("stage") == "confirmation" for end in completed) / n if n else None,
            "unknown_stage": sum("stage" not in end for end in completed)}


def reference_parity(observation, trial):
    if observation["warmup"] + observation["steps"] != trial["steps"]:
        return None  # No se comparan modelos con diferente número de actualizaciones.
    matches = observation["instrumented"]["signature"]["logits"] == trial["curve"][-1]["logits_sha256"]
    if not matches:
        raise ValueError("El perfilado cambió logits frente al trial normal con los mismos pasos y semilla")
    return True


def diagnose(observation, trial, records, min_gain=0.05, campaign_noise=None):
    validate_observation(observation)
    durations = [run["train_s"] for run in observation["plain_runs"]]
    median = statistics.median(durations)
    profile = observation["instrumented"]
    overhead = profile["train_s"] / median
    total = sum(item["wall_s"] for item in profile["phases"].values())
    fractions = {key: item["wall_s"] / total for key, item in profile["phases"].items()}
    cv = statistics.pstdev(durations) / statistics.mean(durations)
    cost = trial["cost_s"]
    train_share = trial["t_train_s"] / cost
    # Estimación explícita, nunca fracción observada del benchmark ni prueba de mejora.
    estimates = {key: train_share * share for key, share in fractions.items()}
    dominant = max(fractions, key=fractions.get)
    curve = trial["curve"]
    crossing = next((point["step"] for point in curve if point["loss"] <= trial["spec"]["target_loss"]), None)
    history = history_metrics(records)
    claims = [
        {"id": "dominant_training_phase", "phase": dominant, "instrumented_fraction": fractions[dominant],
         "interpretation": "Reparto medido con barreras adicionales, no coste de promoción"},
        {"id": "startup_share", "fraction": trial["t_init_s"] / cost,
         "interpretation": "Inicialización incluye intérprete, imports, contexto CUDA y construcción del candidato"},
        {"id": "profiling_perturbation", "ratio": overhead, "high": overhead > 1.25},
        {"id": "noise_vs_gain", "plain_cv": cv, "required_gain": min_gain,
         "comparable": cv >= min_gain / 2, "samples": 3},
        {"id": "evaluation_resolution", "eval_every_steps": trial["spec"]["eval_every"],
         "first_crossing_steps": crossing, "sustained_steps": trial["steps"],
         "eval_and_metric_share": (trial["t_eval_s"] + trial["t_metric_s"]) / cost},
        {"id": "search_coverage", "evidence": history, "enough_history": history["completed"] >= 10},
    ]
    if campaign_noise is not None:
        claims.append({"id": "campaign_noise_vs_gain", "evidence": campaign_noise,
                       "required_gain": min_gain, "comparable": campaign_noise["cv"] >= min_gain / 2,
                       "interpretation": "Variabilidad histórica de cinco trials completos, no del entrenamiento caliente"})
    return {"claims": claims, "plain_step_ms": median / observation["steps"] * 1000,
            "plain_train_cv": cv, "instrumentation_overhead_ratio": overhead,
            "instrumented_phase_fractions": fractions, "estimated_cost_phase_shares": estimates,
            "estimated_amdahl_speedup_bounds": {key: 1 / (1 - share) if share < 1 else None for key, share in estimates.items()},
            "instrumented_residual_s": profile["train_s"] - total,
            "estimate_caveat": "Proyección del reparto instrumentado sobre train del trial; exige contraste en laboratorio",
            "history": history, "promotion_evidence": False}
