"""Motor autónomo: propone, cribado, confirma, promueve o descarta, aprende, repite."""
import json
import shutil
import math
import statistics
import time
import uuid
import copy
from pathlib import Path

import numpy as np

from . import genome as G
from . import integrity, mutate, search, snippets, stats, provenance, manifest, publication, ledger, readiness
from .protected import benchmark, evaluator
from .store import Store, atomic_write

EXIT = {"improved": 0, "budget": 20, "stopped": 130, "needs_human": 10, "finished": 0}


class NeedsHuman(Exception):
    pass


class Engine:
    def __init__(self, root, cfg, log=print):
        if cfg["workload"]["id"] != "numpy_mlp":
            raise ValueError("Workload no implementado en el motor de campañas: " + cfg["workload"]["id"] +
                             ". Para verificar la baseline GaiaTransformer/CUDA usa gaia.py gaia-transformer-baseline.")
        self.root, self.cfg, self.log = Path(root), cfg, log
        self.certification_only = cfg.get("certification_only") is True
        if cfg.get("state_purpose") == "autonomous_mvp" and not cfg["workload"]["state_dir"].startswith("state_autonomous_mvp_cpu_"):
            raise ValueError("Autonomous verification requires its independent state_autonomous_mvp_cpu_ namespace")
        if self.certification_only and not cfg["workload"]["state_dir"].startswith("state_certification_cpu_"):
            raise ValueError("Certification requires its own state_certification_cpu_ namespace")
        self.store = Store(root, cfg["workload"]["state_dir"])
        try:
            stored = self.store.load_state()
        except (OSError, ValueError):
            stored = {}
        if not isinstance(stored, dict):
            stored = {}  # Structural corruption is diagnosed by G0/provenance.
        if stored and (stored.get("certification_only") is True) != self.certification_only:
            raise ValueError("Certification state cannot be opened as an autonomous MVP state (or vice versa)")
        if stored and stored.get("state_purpose") == "autonomous_mvp" and cfg.get("state_purpose") != "autonomous_mvp":
            raise ValueError("Autonomous verification state requires its frozen purpose/configuration")
        self.lim, self.acc = cfg["limits"], cfg["acceptance"]
        self.bench = None
        self.state = {}
        self.hist = search.History()
        self.rng = None
        self.last_end = None
        self.execution_id = uuid.uuid4().hex
        self._active_trials = None
        self._active_record = None
        self._expected_ledger_tip = None
        self.invocation = {}
        self._campaign_context = None
        self._proposal_context = None

    # ------------------------------------------------------------------ init
    def init(self, initialize_mvp=False):
        """Crea línea base v0000 y calibra el benchmark (solo la primera vez)."""
        bpath = self.store.dir / "benchmark.json"
        if bpath.exists():
            if initialize_mvp:
                raise ValueError("--initialize-mvp requires a new empty state directory")
            self.bench = json.loads(bpath.read_text())
            return False
        if not initialize_mvp:
            raise ValueError("New baseline requires explicit prepare --initialize-mvp")
        requirements = provenance.prerequisites(self, initialize=True)
        if not requirements["ok"]:
            raise ValueError("MVP initialization blocked: " + "; ".join(requirements["reasons"]))
        with self.store.exclusive():
            return self._initialize_mvp()

    def _initialize_mvp(self):
        bpath = self.store.dir / "benchmark.json"
        requirements = provenance.prerequisites(self, initialize=True)
        if not requirements["ok"]:
            raise ValueError("MVP initialization blocked: " + "; ".join(requirements["reasons"]))
        snapshot = provenance.create_snapshot(self.root, self.store.dir, self.cfg, requirements["bwrap"],
                                              self.execution_id)
        self.log("== Inicialización: construyendo línea base y calibrando el benchmark ==")
        base = G.new_genome()
        src = G.render(base)
        bench = json.loads(json.dumps(benchmark.PROFILES[self.cfg.get("benchmark_profile", "hard")]))
        for t in ("main", "audit"):
            bench = benchmark.calibrate(src, t, bench, self.lim, self.store.tmp, self.log)
        snapshot_dir = self.store.dir / "provenance/snapshots" / snapshot["snapshot_id"]
        if (not provenance.validate_snapshot(snapshot_dir, snapshot)["ok"] or
                not provenance.compare_sources(self.root, snapshot_dir, self.cfg)["ok"]):
            raise ValueError("Sources changed during baseline initialization; no baseline published")
        atomic_write(bpath, json.dumps(bench, indent=1))
        self.bench = bench
        verification = evaluator.check_correctness(src, limits=self.lim, include_evidence=True)
        document = manifest.build_baseline(self, snapshot, base, src, verification)
        evidence = {"note": "línea base (referencia experimental)", **manifest.reference(document),
                    **provenance.purpose_metadata(self.cfg),
                    "source_snapshot": snapshot, "execution_id": self.execution_id,
                    "trainer_hash": document["source"]["baseline_trainer_sha256"],
                    "genome_hash": document["source"]["baseline_genome_sha256"],
                    "timestamp": document["created_at"], "benchmark_summary": bench["calibrated"],
                    "sandbox_verification": verification["sandbox_evidence"]}
        self.state = {"state_schema": provenance.STATE_SCHEMA,
                       **provenance.purpose_metadata(self.cfg),
                       "ledger_schema": ledger.SCHEMA,
                       "source_snapshot": snapshot,
                       "baseline_manifest_hash": document["manifest_hash"],
                      "n_experiments": 0, "since_promotion": 0, "ref": None,
                      "strategy": dict(search.DEFAULT_STRATEGY), "search_seconds": 0.0,
                      "consecutive_errors": 0, "plateau_meta_used": False, "created": time.time()}
        self.store.save_state(self.state)
        name = self.store.promote(base, src, evidence, context=self, baseline_manifest=document)
        integrity.write_manifest(self.root, self.store.dir)
        self.store.append({"type": "init", "version": name,
                           **provenance.purpose_metadata(self.cfg),
                           "trainer_hash": evidence["trainer_hash"], "genome_hash": evidence["genome_hash"],
                           **manifest.reference(document),
                           "source_snapshot": snapshot, "execution_id": self.execution_id,
                           "calibrated": bench["calibrated"], "limits": self.lim})
        return True

    def _load(self):
        self.bench = json.loads((self.store.dir / "benchmark.json").read_text())
        self.state = self.store.load_state()
        snippets.set_unlocked(self.state.get("unlocked", []))
        self.rng = np.random.default_rng(self.state["n_experiments"] * 7919 + 13)
        self.hist = search.History()
        base = self.store.load_version("v0000")[0] if self.certification_only else G.new_genome()
        self.hist.add(base, self.bench["calibrated"]["main"]["ref_cost_s"], "ok", None, [])
        for r in self.store.records():
            if r["type"] == "end" and r.get("screen") and r.get("genome"):
                s = r["screen"]
                self.hist.add(r["genome"], s.get("cost_s"), s["status"],
                              r.get("parent_cost"), r.get("ops", []))

    # --------------------------------------------------------------- helpers
    def trial(self, src, seed, task="main", cap=None, **kw):
        self.source_context()
        cap = cap or self.lim["max_experiment_seconds"]
        result = evaluator.run_trial(src, self.bench, task, seed, seed, cap, self.lim,
                                     self.store.tmp, **kw)
        if self._active_trials is not None:
            self._active_trials.append({"trainer_hash": __import__("hashlib").sha256(src.encode()).hexdigest(),
                                        "task": task, "data_seed": seed, "init_seed": seed, "cap_s": cap,
                                        **{key: self._active_record[0][key] for key in ("campaign_id", "environment_hash", "stable_version", "source_sha")},
                                        "result": result})
        if result.get("reason") in ("SANDBOX_UNAVAILABLE", "SANDBOX_VIOLATION"):
            failure = NeedsHuman(result["error"])
            failure.trial_result = result
            raise failure
        self.source_context()
        return result

    def _slim(self, r):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items() if k != "curve"}

    def source_context(self):
        """Only run CPU code that still matches the baseline's immutable copy."""
        requirements = provenance.prerequisites(self)
        if not requirements["ok"]:
            raise NeedsHuman("Local source provenance BLOCKED: " + "; ".join(requirements["reasons"]))
        if self._active_record is not None and self._expected_ledger_tip is not None:
            checked = ledger.verify_ledger(self.store)
            if not checked["ok"] or checked.get("last_hash") != self._expected_ledger_tip:
                raise NeedsHuman("LEDGER_UNEXPECTED_CHANGE: ledger changed during experiment")
        identity = (requirements.get("environment") or {}).get("identity", {})
        return {"source_snapshot": self.store.load_state().get("source_snapshot", {}),
                **provenance.purpose_metadata(self.cfg),
                **identity, "execution_id": self.execution_id}

    def refresh_ref(self, src, reps=3, check_drift=True):
        """Coste de referencia del campeón AHORA (mismo reloj que verá el candidato)."""
        seed = self.bench["tiers"]["screen"][0]
        rs = [self.trial(src, seed) for _ in range(reps)]
        if any(not r["reached"] for r in rs):
            self.state["consecutive_errors"] += 1
            raise NeedsHuman("El campeón estable no alcanza el objetivo en la medición de referencia: "
                             f"{rs[0]['status']} {rs[0]['error']}. Revisa el entorno (carga de CPU, memoria).")
        cost = statistics.median(r["cost_s"] for r in rs)
        spread = statistics.pstdev(r["cost_s"] for r in rs) / cost
        floor = self.cfg["stop"]["min_resolvable_s"]
        if cost < floor or spread > self.cfg["stop"]["max_ref_spread"]:
            self.state["ref"] = {"cost": cost, "at": self.state["n_experiments"]}
            self.store.save_state(self.state)
            raise NeedsHuman(
                f"Benchmark saturado: el campeón tarda {cost:.3f}s (límite de resolución {floor}s; dispersión de "
                f"repeticiones {spread*100:.0f}%). Por debajo de eso el ruido de medida domina y GAIA ya no puede "
                "distinguir mejoras reales. Decide: (a) endurecer el benchmark en gaia/protected/benchmark.py "
                "(más datos n_train, más dimensiones d, menor tolerancia), borrar state/ y reiniciar con las "
                "versiones actuales como nueva referencia, o (b) dar por concluida esta fase. "
                f"Campeón actual: {self.store.current_version()} (la línea base v0000 sigue guardada).")
        old = (self.state.get("ref") or {}).get("cost")
        if check_drift and old and abs(cost / old - 1) > self.cfg["stop"]["drift_tolerance"]:
            self.state["ref"] = {"cost": cost, "at": self.state["n_experiments"]}
            self.store.save_state(self.state)
            raise NeedsHuman(f"Deriva del reloj de referencia: {old:.3f}s -> {cost:.3f}s "
                             f"(>{self.cfg['stop']['drift_tolerance']*100:.0f}%). Posible estrangulamiento térmico "
                             "o carga ajena en la máquina; las comparaciones dejan de ser fiables.")
        self.state["ref"] = {"cost": cost, "at": self.state["n_experiments"]}
        self.store.save_state(self.state)
        return cost

    def hypothesis(self, g, ops, detail, ref):
        meta = [mutate.OPS[o] for o in ops if o in mutate.OPS]
        prov = "generated" if any(m["prov"] == "generated" for m in meta) else "known"
        lim = "; ".join(sorted({m["limitation"] for m in meta})) or "exploración global del espacio"
        return {
            "limitation": lim,
            "component": ", ".join(sorted({m["component"] for m in meta})) or "genoma completo",
            "rationale": "; ".join(sorted({m["rationale"] for m in meta})) or "muestreo de zonas no exploradas",
            "expected": "coste hasta el objetivo < campeón x 0.95 con la misma calidad",
            "cost_estimate_s": round(ref * self.acc["screen_slack"] + 1.5, 2),
            "accept_rule": f"cribado: alcanzar objetivo y coste < {1 - self.acc['min_gain']/2:.3f}x ref; "
                           f"confirmación: IC95% sup. del cociente pareado < {1 - self.acc['min_gain']:.2f}",
            "regression_risk": "; ".join(sorted({m["risk"] for m in meta})) or "desconocido",
            "provenance": prov, "detail": detail}

    # ------------------------------------------------------------- experiment
    def experiment(self, proposal=None, research=None):
        with self.store.exclusive():
            return self._locked_experiment(proposal=proposal, research=research)

    def _locked_experiment(self, proposal=None, research=None):
        self._active_trials = []
        self._active_record = None
        try:
            return self._experiment(proposal=proposal, research=research)
        except NeedsHuman as exc:
            if self._active_record is not None:
                rec, started = self._active_record
                self._finish(rec, {"status": "invalid", "reached": False, "cost_s": None}, None,
                             "invalid", str(exc), started, validate=False)
            raise
        except (KeyboardInterrupt, InterruptedError) as exc:
            if self._active_record is not None:
                rec, started = self._active_record
                self._finish(rec, {"status": "invalid", "reached": False, "cost_s": None}, None,
                             "aborted", "INTERRUPTED: " + str(exc), started, validate=False)
            raise
        finally:
            self._active_trials = None
            self._active_record = None
            self._expected_ledger_tip = None

    def _experiment(self, proposal=None, research=None):
        if self.certification_only:
            from .certification import controlled_pair
            if proposal is None or research is not None or provenance.digest(proposal[0]) != provenance.digest(controlled_pair()[1]):
                raise NeedsHuman("Certification requires its explicit controlled genome; autonomous search/research is forbidden")
        if self.cfg.get("state_purpose") == "autonomous_mvp" and proposal is not None and research is None:
            raise NeedsHuman("EXTERNAL_PROPOSAL_FORBIDDEN: autonomous verification only calls normal Strategy.propose")
        source_context = self.source_context()
        st, acc = self.state, self.acc
        t_start = time.perf_counter()
        champ_g, champ_src = self.store.load_version()
        self._champ_g = champ_g
        ref = (st.get("ref") or {}).get("cost")
        strat = search.Strategy(st["strategy"], self.rng)
        history_identity = {"items": self.hist.items, "seen": sorted(self.hist.seen), "op_n": self.hist.op_n,
                            "op_sum": self.hist.op_sum, "since_improve": self.hist.since_improve, "best": self.hist.best}
        before_rng = copy.deepcopy(self.rng.bit_generator.state)
        prior_chain = ledger.verify_ledger(self.store)
        trace_input = {"strategy": copy.deepcopy(st["strategy"]), "rng_state": before_rng,
                       "history_hash": provenance.digest(history_identity), "history_items": len(self.hist.items),
                       "operator_counts": dict(self.hist.op_n), "operator_rewards": dict(self.hist.op_sum),
                       "unlocked": sorted([list(item) for item in snippets.UNLOCKED]),
                       "ledger_sequence": len(prior_chain["records"]), "ledger_head": prior_chain["last_hash"]}
        g, ops, parent_hash, parent_cost = proposal if proposal else strat.propose(self.hist)
        origin = "certification_controlled" if self.certification_only else "search" if proposal is None else "research" if research else "external_proposal"
        try:
            src = G.render(g)
        except (ValueError, KeyError, TypeError):
            src = ""
        index = max([int(p.stem[1:]) for p in (self.store.dir / "proposals").glob("p[0-9]*.json")], default=0) + 1
        trace = {"proposal_schema": "cpu_search_proposal_v1", **provenance.purpose_metadata(self.cfg),
                 "proposal_index": index, "proposal_id": str(uuid.uuid4()), "execution_id": self.execution_id,
                 "timestamp": manifest.timestamp(), "candidate_origin": origin,
                 "proposal_method": "gaia.search.Strategy.propose" if proposal is None else origin,
                 "input": trace_input, "genome": g, "genome_hash": provenance.digest(g),
                 "trainer_hash": __import__("hashlib").sha256(src.encode()).hexdigest() if src else None,
                 "ops": ops, "parent_hash": parent_hash, "parent_cost": parent_cost,
                 "rng_after": copy.deepcopy(self.rng.bit_generator.state)}
        trace["trace_hash"] = provenance.digest(trace)
        path = self.store.dir / "proposals" / f"p{index:06d}.json"
        path.parent.mkdir(exist_ok=True)
        with path.open("xb") as stream:
            stream.write(publication.genome_bytes(trace))  # Preserve genotype key order for exact replay/render.
        path.chmod(0o444)
        self._proposal_context = {"proposal_trace_path": str(path.relative_to(self.store.dir)),
                                  "proposal_trace_hash": trace["trace_hash"], "proposal_genome_hash": trace["genome_hash"],
                                  "candidate_origin": origin}
        recording = self._active_trials
        self._active_trials = None
        try:
            certified = readiness.run_gates(self, genome=g, source=src)
        finally:
            self._active_trials = recording
        if certified["status"] != "READY_FOR_CAMPAIGN":
            failed = [code for gate in certified["gates"].values() for code in gate["reason_codes"] if code != "PRIOR_GATE_FAILED"]
            candidate_invalid = any(code != "PRIOR_GATE_FAILED" for code in certified["gates"]["G1_correctness"]["reason_codes"])
            raise NeedsHuman("GATES_BLOCKED: " + ("INVALID_CANDIDATE: " if candidate_invalid else "") + ", ".join(failed))
        self._campaign_context = {key: certified[key] for key in ("campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")}
        checked = readiness.validate_report(self, self._campaign_context, genome_hash=provenance.digest(g),
                                            trainer_hash=__import__("hashlib").sha256(src.encode()).hexdigest(),
                                            parent=self.store.current_version())
        if not checked["ok"]:
            raise NeedsHuman("GATES_BLOCKED: " + str(checked["errors"]))
        st = self.state
        if ref is None:
            ref = certified["gates"]["G2_reliability"]["details"]["median_s"]
            st["ref"] = {"cost": ref, "at": st["n_experiments"]}
            self.store.save_state(st)
        st["n_experiments"] += 1
        eid = f"e{st['n_experiments']:05d}"
        detail = G.describe(g)
        hyp = self.hypothesis(g, ops, detail, ref)
        if research:
            hyp = {**hyp, **research}
        rec = {"id": eid, "genome": g, "ops": ops, "parent_hash": parent_hash, **source_context, **self._campaign_context,
               **self._proposal_context,
                "started_at": manifest.timestamp(),
               "parent_cost": parent_cost, "hypothesis": hyp,
               "strategy_version": st["strategy"].get("version", 0),
               "stable_version": self.store.current_version(),
                 "origin": origin}
        try:
            src = G.render(g)
            rec["source_sha"] = __import__("hashlib").sha256(src.encode()).hexdigest()
        except ValueError as e:
            raise NeedsHuman("Invalid genome before experiment start: " + str(e)) from e
        document = manifest.build_experiment(self, eid, source_context, g, src, champ_g, champ_src)
        directory = self.store.dir / "experiments" / eid
        manifest.write_manifest(directory / "manifest.json", document)
        with (directory / "genome.json").open("xb") as stream:
            stream.write(publication.genome_bytes(g))
        (directory / "genome.json").chmod(0o444)
        candidate_path = directory / "trainer.py"
        with candidate_path.open("x") as stream:
            stream.write(src)
        candidate_path.chmod(0o444)
        rec["experiment_manifest_hash"] = document["manifest_hash"]
        rec["experiment_manifest_path"] = str((directory / "manifest.json").relative_to(self.store.dir))
        self.store.append({"type": "start", **rec})
        self._active_record = (rec, t_start)
        self._expected_ledger_tip = ledger.verify_ledger(self.store)["last_hash"]

        # --- Etapa 1: cribado (1 semilla, tope respecto al campeón)
        sd = self.bench["tiers"]["screen"][0]
        cap = ref * acc["screen_slack"]
        screen = self.trial(src, sd, cap=cap)
        if screen["status"] in ("error", "timeout"):
            st["consecutive_errors"] += 1
        else:
            st["consecutive_errors"] = 0
        if st["consecutive_errors"] >= self.cfg["stop"]["max_consecutive_infra_errors"]:
            self._finish(rec, self._slim(screen), None, "rejected", "error", t_start)
            raise NeedsHuman(f"{st['consecutive_errors']} candidatos consecutivos fallan con error de "
                             f"ejecución ({screen['error'][:200]}). Probable fallo del entorno.")
        if screen["status"] != "ok":
            return self._finish(rec, self._slim(screen), None, "rejected",
                                f"{screen['status']}: {screen['error'][:120]}", t_start)
        if not screen["reached"]:
            return self._finish(rec, self._slim(screen), None, "rejected",
                                f"no alcanza el objetivo dentro de {cap:.2f}s (acc {screen['final_acc']:.3f})", t_start)
        if screen["cost_s"] > ref * (1 - acc["min_gain"] / 2):
            return self._finish(rec, self._slim(screen), None, "rejected",
                                f"cribado: {screen['cost_s']:.3f}s no mejora la referencia {ref:.3f}s", t_start)

        # --- Etapa 2: confirmación pareada e intercalada en semillas distintas
        seeds = [1000 + i for i in range(acc["confirm_seeds"])]
        champ_runs, cand_runs = [], []
        ccap = min(self.lim["max_experiment_seconds"], max(1.0, ref * 3))

        def run_pairs(sds, offset):
            for i, s in enumerate(sds):
                order = ("cand", "champ") if (i + offset) % 2 else ("champ", "cand")
                for who in order:
                    r = self.trial(src if who == "cand" else champ_src, s, cap=ccap)
                    (cand_runs if who == "cand" else champ_runs).append(r)
        run_pairs(seeds, 0)
        self._validate_experiment(rec)
        verdict = stats.decide(champ_runs, cand_runs, acc)
        if verdict["decision"] == "deferred":
            run_pairs([s + 5 for s in seeds], 1)     # una única ampliación, 5 pares más
            self._validate_experiment(rec)
            verdict = stats.decide(champ_runs, cand_runs, acc)
            verdict["extended"] = True
        confirm = {**verdict, "champ_costs": [r["cost_s"] for r in champ_runs],
                   "cand_costs": [r["cost_s"] for r in cand_runs]}
        return self._finish(rec, self._slim(screen), confirm, verdict["decision"],
                            verdict["reason"], t_start, src=src)

    def _validate_experiment(self, rec):
        self.source_context()
        if rec.get("experiment_manifest_path"):
            checked = manifest.validate_manifest(self, self.store.dir / rec["experiment_manifest_path"],
                                                 expected_hash=rec["experiment_manifest_hash"], require_current_parent=True)
            if not checked["ok"]:
                raise NeedsHuman("; ".join(checked["errors"]))

    def _finish(self, rec, screen, confirm, decision, reason, t_start, src=None, validate=True):
        if validate:
            self._validate_experiment(rec)
        current_context = None
        if decision == "accepted":
            current_context = self.source_context()
            if current_context["source_snapshot"] != rec.get("source_snapshot"):
                raise NeedsHuman("ENVIRONMENT_MISMATCH: source snapshot reference changed during experiment")
        st = self.state
        spent = time.perf_counter() - t_start
        out = {"type": "end", "id": rec["id"], "genome": rec["genome"], "ops": rec["ops"],
               **provenance.purpose_metadata(self.cfg),
               "parent_hash": rec["parent_hash"], "parent_cost": rec["parent_cost"],
               "screen": screen, "confirm": confirm, "decision": decision, "reason": reason,
               "search_cost_s": round(spent, 3), "provenance": rec["hypothesis"]["provenance"],
                "origin": rec.get("origin", "search"),
                "source_sha": rec.get("source_sha"),
                 "source_snapshot": rec.get("source_snapshot"), "execution_id": rec.get("execution_id")}
        out.update({key: rec.get(key) for key in ("manifest_hash", "environment_hash", "config_hash", "source_hash",
                                                 "sandbox_policy_hash", "experiment_manifest_hash")})
        out["baseline_manifest_hash"] = rec.get("manifest_hash")
        out.update({key: rec[key] for key in ("proposal_trace_path", "proposal_trace_hash", "candidate_origin")})
        out.update({key: rec[key] for key in ("campaign_id", "gate_report_hash", "gate_report_path", "overall_gates_passed")})
        out["result_code"] = ("INVALID_CANDIDATE" if decision == "invalid" else "INCONCLUSIVE" if decision == "deferred"
                              else "CANDIDATE_ACCEPTED" if decision == "accepted" else "CANDIDATE_REJECTED")
        out["candidate_genome_hash"] = provenance.digest(rec["genome"])
        out["candidate_trainer_hash"] = rec.get("source_sha")
        out["parent_version"] = rec["stable_version"]
        out["started_at"] = rec["started_at"]
        out["finished_at"] = manifest.timestamp()
        out["trial_metrics"] = self._active_trials or []
        sandbox_evidence = [trial["result"].get("sandbox_evidence", {}) for trial in out["trial_metrics"]]
        out["sandbox_evidence_hash"] = provenance.digest(sandbox_evidence)
        out["sandbox_evidence_reference"] = "evidence.json#/trial_metrics/*/result/sandbox_evidence"
        out["promotable"] = decision == "accepted" and bool(out["trial_metrics"]) and all(
            trial["result"].get("promotable") is True for trial in out["trial_metrics"])
        if decision == "accepted" and not out["promotable"]:
            raise NeedsHuman("ENVIRONMENT_MISMATCH: acceptance lacks valid sandbox trial evidence")
        st["search_seconds"] += spent
        st["since_promotion"] += 1
        if rec.get("experiment_manifest_path"):
            evidence_path = self.store.dir / rec["experiment_manifest_path"]
            out["evidence_path"] = str(evidence_path.with_name("evidence.json").relative_to(self.store.dir))
            out["evidence_hash"] = provenance.digest(out)
            manifest.write_manifest(self.store.dir / out["evidence_path"], out)
        self._active_record = None
        self.last_end = out
        if decision == "accepted":
            self.store.append(out)
            d = G.diff(self._champ_g, rec["genome"])
            ev = {"experiment": rec["id"], "hypothesis": rec["hypothesis"], "confirm": confirm,
                    **current_context,
                    **{key: rec[key] for key in ("proposal_trace_path", "proposal_trace_hash", "candidate_origin")},
                   "baseline_manifest_hash": rec.get("manifest_hash"),
                   "experiment_manifest_hash": rec.get("experiment_manifest_hash"),
                   "experiment_manifest_path": rec.get("experiment_manifest_path"),
                   "experiment_evidence_path": out.get("evidence_path"), "experiment_evidence_hash": out.get("evidence_hash"),
                  "ops": rec["ops"], "provenance": G.provenance(self._champ_g, rec["genome"]),
                  "diff_vs_champion": [list(x) for x in d],
                  "experiments_since_last_promotion": st["since_promotion"],
                   "search_seconds_total": round(st["search_seconds"], 1)}
            try:
                ev.update(readiness.pre_promotion(self, rec["genome"], src, ev))
            except (ValueError, RuntimeError, OSError) as exc:
                raise NeedsHuman("PRE_PROMOTION_FAILED: " + str(exc)) from exc
            name = self.store.promote(rec["genome"], src, ev, context=self)
            out["promoted_to"] = name
            st["since_promotion"] = 0
            st["plateau_meta_used"] = False
            st["research_used"] = False
            self._active_trials = None
            self.hist.add(rec["genome"], screen.get("cost_s"), screen["status"], rec["parent_cost"], rec["ops"])
            self.store.save_state(st)
            self.refresh_ref(src, check_drift=False)
            return "improved"
        self.store.append(out)
        self.hist.add(rec["genome"], screen.get("cost_s"), screen["status"], rec["parent_cost"], rec["ops"])
        self.store.save_state(st)
        line = f"{rec['id']} [{decision:>17}] {G.describe(rec['genome'])[:58]:<58} {reason[:70]}"
        self.log(line)
        return decision

    # -------------------------------------------------------------------- run
    def rollback(self, to_version, reason, *, _test_fault=None):
        from . import rollback
        result = {"status": "BLOCKED", "previous_current": None, "to_version": to_version,
                  "resulting_current": None, "event_id": None, "validations": "FAIL"}
        try:
            rollback.version(to_version)
            if not isinstance(reason, str) or not reason.strip():
                raise rollback.RollbackError("INVALID_REASON", "Rollback requires a non-empty operator reason")
        except (ValueError, rollback.RollbackError) as exc:
            return {**result, "code": getattr(exc, "code", "INVALID_DESTINATION"), "reason": str(exc)}
        # Deliberately not exclusive(): an existing campaign lock on this very
        # Engine is busy too, even if called by the same thread.
        try:
            self.store.lock()
        except (RuntimeError, OSError) as exc:
            return {**result, "code": "STATE_BUSY" if isinstance(exc, RuntimeError) else "STATE_UNAVAILABLE", "reason": str(exc)}
        try:
            self._rollback_in_progress = True
            result["previous_current"] = self.store.current_version()
            return rollback.perform(self, to_version, reason, _test_fault=_test_fault)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            try:
                result["resulting_current"] = self.store.current_version()
            except (OSError, ValueError):
                pass
            return {**result, "code": getattr(exc, "code", "ROLLBACK_BLOCKED"), "reason": str(exc)}
        finally:
            self._rollback_in_progress = False
            self.store.unlock()

    def run(self, until="improvement", minutes=None, max_experiments=None, meta=None):
        """until: 'improvement' (para al primera mejora verificada) | 'budget' (sigue)."""
        if getattr(self, "certification_only", False):
            self.log("CERTIFICATION_ONLY: run cannot use pipeline-certification state; use certify-pipeline")
            return "needs_human"
        if self.store.stop_requested():
            return "stopped"
        requirements = provenance.prerequisites(self)
        if not requirements["ok"]:
            self.log("MVP campaign BLOCKED: " + "; ".join(requirements["reasons"]))
            if requirements.get("state_schema") == "MVP_CPU_V1":
                try:
                    readiness.run_gates(self)  # Persist a fail-closed G0 report, never benchmark.
                except (OSError, ValueError, RuntimeError):
                    pass  # E.g. STATE_BUSY: preserve the original block, never bypass it.
                self._needs_human("; ".join(requirements["reasons"]))
            return "needs_human"
        self.store.lock()
        try:
            self.init()
            self._load()
            n_orph = self._recover()
            if n_orph:
                self.log(f"Recuperación: {n_orph} experimento(s) incompleto(s) marcados como abortados.")
            bad = integrity.verify(self.root, self.store.dir)
            if bad:
                raise NeedsHuman("Archivos protegidos modificados: " + ", ".join(bad) +
                                 ". Si el cambio es intencionado, borra state/ y reinicializa.")
            minutes = self.lim["max_total_minutes"] if minutes is None else minutes
            max_experiments = self.lim["max_experiments"] if max_experiments is None else max_experiments
            if minutes > self.lim["max_total_minutes"] or max_experiments > self.lim["max_experiments"]:
                raise NeedsHuman("ENVIRONMENT_MISMATCH: invocation exceeds certified budget caps")
            t_end = time.monotonic() + minutes * 60
            n_run = 0
            meta_on = self.cfg["meta"]["enabled"] if meta is None else meta
            self.invocation = {"until": until, "minutes": minutes, "max_experiments": max_experiments, "meta": meta_on}
            start_gates = readiness.run_gates(self)
            if start_gates["status"] != "READY_FOR_CAMPAIGN":
                raise NeedsHuman("GATES_BLOCKED: " + str([g["reason_codes"] for g in start_gates["gates"].values() if not g["ok"]]))
            _, champ_src = self.store.load_version()
            ref = self.refresh_ref(champ_src)
            self.log(f"Campeón {self.store.current_version()} · referencia {ref:.3f}s · "
                     f"objetivo de calidad {self.bench['calibrated']['main']['target']} · "
                     f"parada manual: crea el archivo STOP")
            if meta_on != self.cfg["meta"]["enabled"]:
                raise NeedsHuman("ENVIRONMENT_MISMATCH: meta flag differs from baseline configuration")
            self.invocation = {"until": until, "minutes": minutes, "max_experiments": max_experiments,
                               "meta": meta_on}
            while True:
                if self.store.stop_requested():
                    return "stopped"
                if time.monotonic() >= t_end or n_run >= max_experiments:
                    return "budget"
                if self.store.disk_mb() > self.lim["max_disk_mb"]:
                    raise NeedsHuman(f"Límite de disco superado ({self.store.disk_mb():.0f} MB).")
                if integrity.verify(self.root, self.store.dir):
                    raise NeedsHuman("Archivos protegidos modificados durante la ejecución.")
                est = (self.state["ref"]["cost"] * self.acc["screen_slack"] + 1.5)
                if time.monotonic() + est >= t_end:
                    return "budget"
                if n_run and n_run % self.cfg["stop"]["recalibrate_every"] == 0:
                    _, champ_src = self.store.load_version()
                    self.refresh_ref(champ_src)
                if meta_on and n_run and n_run % self.cfg["meta"]["every"] == 0:
                    self.meta_cycle()
                outcome = self.experiment()
                n_run += 1
                if outcome == "improved":
                    self._announce()
                    if until == "improvement":
                        return "improved"
                rc = self.cfg["research"]
                if (rc["enabled"] and self.state["since_promotion"] >= rc["trigger_after"]
                        and not self.state.get("research_used")):
                    self.state["research_used"] = True
                    self.store.save_state(self.state)
                    before_research = self.state["n_experiments"]
                    research_out = self.research_cycle(deadline=t_end,
                                                       max_experiments=max_experiments - n_run)
                    n_run += self.state["n_experiments"] - before_research
                    if research_out["improved"]:
                        self._announce()
                        if until == "improvement":
                            return "improved"
                        continue
                if self.state["since_promotion"] >= self.cfg["stop"]["plateau_experiments"]:
                    if meta_on and not self.state.get("plateau_meta_used"):
                        self.log("Meseta detectada: GAIA intenta mejorar su propia estrategia de búsqueda.")
                        self.state["plateau_meta_used"] = True
                        self.meta_cycle()
                        self.state["since_promotion"] = self.cfg["stop"]["plateau_experiments"] // 2
                        self.store.save_state(self.state)
                    else:
                        raise NeedsHuman(self._plateau_text())
        except NeedsHuman as e:
            self._needs_human(str(e))
            return "needs_human"
        finally:
            self.store.unlock()

    def _recover(self):
        """Tras una interrupción: cierra huérfanos, SINCRONIZA el contador con el ledger (los ids no se
        reutilizan nunca) y limpia directorios temporales de trials muertos (tenemos el lock)."""
        n = self.store.close_orphans(context=self)
        ids = [int(r["id"][1:]) for r in self.store.records()
               if r["type"] in ("start", "end") and str(r.get("id", "")).startswith("e")]
        top = max(ids, default=0)
        if top > self.state["n_experiments"]:
            self.state["n_experiments"] = top
            self.store.save_state(self.state)
            self.rng = np.random.default_rng(top * 7919 + 13)
        tmp = self.store.tmp
        if tmp.exists():
            for p in tmp.iterdir():
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        if n:
            self._load()  # Recovered accepted evidence must inform the existing search history now.
        return n

    def research_cycle(self, deadline=None, max_experiments=None):
        from . import research
        _, champ_src = self.store.load_version()
        self.refresh_ref(champ_src, check_drift=False)
        return research.cycle(self, deadline=deadline, max_experiments=max_experiments)

    def research_now(self):
        """Un ciclo de investigación bajo demanda (`gaia.py research`)."""
        requirements = provenance.prerequisites(self)
        if not requirements["ok"]:
            raise ValueError("MVP research blocked: " + "; ".join(requirements["reasons"]))
        self.store.lock()
        try:
            self.init()
            self._load()
            self._recover()
            res = self.research_cycle()
            if res["improved"]:
                self._announce()
            return res
        finally:
            self.store.unlock()

    def meta_cycle(self):
        from . import meta
        self.log("-- ciclo de metaoptimización (Nivel 4) --")
        res = meta.tune(self, rounds=self.cfg["meta"]["rounds"])
        self.log(f"   estrategia v{self.state['strategy'].get('version', 0)}: {res}")

    def _announce(self):
        v = self.store.current_version()
        ev = json.loads((self.store.stable / v / "evidence.json").read_text())
        c = ev["confirm"]
        self.log("\n*** MEJORA VERIFICADA ***")
        self.log(f"Nueva versión estable {v} (coste {c['ratio']:.3f}x del campeón anterior; "
                 f"IC95% sup. {c['ratio_upper95']:.3f}; {c['pairs']} pares; RAM {c.get('mem_ratio')}x)")
        self.log(f"Procedencia (según TODO lo que difiere del campeón anterior): {ev['provenance']}")
        for f, a, b, k in ev["diff_vs_champion"]:
            self.log(f"   {f}: {a} -> {b}  [{k}]")
        self.log(f"Genoma: {ev['hypothesis']['detail']}")

    def _plateau_text(self):
        recs = [r for r in self.store.records() if r["type"] == "end"][-self.cfg['stop']['plateau_experiments']:]
        ops = {}
        for r in recs:
            for o in r.get("ops", []):
                ops[o] = ops.get(o, 0) + 1
        rs = self.state.get("research_summary", "")
        return (rs + "\n\n" if rs else "") + (f"Meseta: {len(recs)} experimentos seguidos sin mejora verificada, incluso tras intentar mejorar "
                f"la estrategia de búsqueda. Operadores más usados: {sorted(ops.items(), key=lambda x: -x[1])[:6]}. "
                "Posibles causas a decidir por una persona: (a) el espacio de búsqueda está agotado, "
                "(b) el objetivo/benchmark ya no discrimina (ruido de medida), (c) hace falta ampliar el espacio "
                "(nuevos componentes en gaia/snippets.py) o subir los límites de gaia.json.")

    def _needs_human(self, msg):
        self.log("\n*** GAIA NECESITA AYUDA HUMANA ***\n" + msg)
        atomic_write(self.root / "NEEDS_HUMAN.md",
                     f"# GAIA necesita ayuda humana\n\n{msg}\n\nEstado: `python gaia.py status`. "
                     "Para continuar tras resolverlo: borra este archivo y ejecuta `python gaia.py run`.\n")
