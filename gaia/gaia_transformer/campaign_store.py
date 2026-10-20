"""Ledger persistente y publicación atómica de versiones GPU completas."""
import json
import hashlib
import os
from pathlib import Path
import shutil
import uuid

from gaia.atomic_publish import publish
from gaia.store import Store, atomic_write
from . import genome as G


class CampaignStore(Store):
    def rollback(self):
        # Preserve the pre-existing GPU behavior; CPU uses Engine.rollback.
        versions = self.versions()
        index = versions.index(self.current_version())
        if index == 0:
            raise RuntimeError("ya estás en la línea base")
        atomic_write(self.stable / "CURRENT", versions[index - 1])
        return versions[index - 1]

    # El llamador mantiene flock durante toda la campaña/preparación.
    def append(self, record):
        if self.ledger.exists() and self.ledger.stat().st_size:
            with self.ledger.open("rb+") as stream:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    stream.seek(0, os.SEEK_END)
                    stream.write(b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
        super().append(record)

    def publish(self, genome, source, evidence, allow_baseline=False):
        G.validate(genome)
        if allow_baseline:
            if self.current_version() is not None or genome != G.BASE:
                raise ValueError("La baseline solo se publica una vez")
        else:
            from .lab.calibration import decide, SPEC
            confirmation = evidence["comparison"]["confirmation"]
            actual = decide(confirmation["champion"], confirmation["candidate"], SPEC["confirm_seeds"])
            if actual["decision"] != "accepted" or evidence["parent"] != self.current_version():
                raise ValueError("Promoción sin evidencia válida o campeón cambió")
            parent_source = self.load_version(evidence["parent"])[1]
            for group, expected_source in (("candidate", source), ("champion", parent_source)):
                expected_hash = hashlib.sha256(expected_source.encode()).hexdigest()
                if any(t.get("candidate_sha256") != expected_hash for t in confirmation[group]):
                    raise ValueError("La evidencia no corresponde a las fuentes comparadas")
        if source != G.render(genome):
            raise ValueError("Fuente no corresponde al genoma")
        self.stable.mkdir(exist_ok=True)
        numbers = [int(name[1:]) for name in self.versions()]
        name = f"v{max(numbers, default=-1) + 1:04d}"
        prefix = ".pending-" + uuid.uuid4().hex + "-"
        artifacts = {"genome.json": (json.dumps(genome, indent=2, ensure_ascii=False) + "\n").encode(),
                     "trainer.py": source.encode(),
                     "evidence.json": (json.dumps(evidence, indent=2, ensure_ascii=False) + "\n").encode()}

        try:
            publish(self.stable, name, artifacts, lambda directory: None, self.current_version(),
                    staging_prefix=prefix, artifact_mode=None)
        finally:
            for staging in self.stable.glob(prefix + "*"):
                shutil.rmtree(staging)
        return name

    def verify_versions(self):
        current = self.current_version()
        if current is None:
            return
        if current not in self.versions():
            raise RuntimeError("CURRENT apunta a versión ausente")
        for name in self.versions():
            g, source = self.load_version(name)
            if source != G.render(g):
                raise RuntimeError("Fuente estable modificada: " + name)
            evidence = json.loads((self.stable / name / "evidence.json").read_text())
            if name != "v0000":
                from .lab.calibration import decide, SPEC
                comparison = evidence["comparison"]["confirmation"]
                if decide(comparison["champion"], comparison["candidate"], SPEC["confirm_seeds"])["decision"] != "accepted":
                    raise RuntimeError("Versión sin confirmación aceptada: " + name)
                parent = evidence["parent"]
                if parent not in self.versions() or parent >= name:
                    raise RuntimeError("Linaje de versión inválido: " + name)
                for key, expected_source in (("candidate", source), ("champion", self.load_version(parent)[1])):
                    if any(t.get("candidate_sha256") != hashlib.sha256(expected_source.encode()).hexdigest()
                           for t in comparison[key]):
                        raise RuntimeError("Evidencia de fuente distinta: " + name)

    def recover(self):
        self.verify_versions()
        # Solo temporales del laboratorio dentro de este estado; no se barre /tmp global.
        removed = 0
        if self.tmp.exists():
            for path in self.tmp.glob("gaia-gpu-*"):
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                    removed += 1
        for path in self.stable.glob(".pending-*"):
            shutil.rmtree(path)
        records = self.records()
        ended = {r["id"] for r in records if r["type"] == "end"}
        count = 0
        current = self.current_version()
        evidence = json.loads((self.stable / current / "evidence.json").read_text()) if current else {}
        for record in records:
            if record["type"] == "start" and record["id"] not in ended:
                committed = evidence.get("experiment_id") == record["id"]
                self.append({"type": "end", "id": record["id"], "operator": record["operator"],
                             "decision": "accepted" if committed else "aborted", "recovered": True,
                             "version": current if committed else None})
                count += 1
        if removed:
            self.append({"type": "cleanup", "removed_trial_directories": removed})
        next_id = max([int(r["id"][1:]) for r in records if "id" in r], default=0) + 1
        return count, next_id
