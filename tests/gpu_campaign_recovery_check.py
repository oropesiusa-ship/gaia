"""Prueba manual real: mata SOLO la campaña hija tras start y verifica recuperación.

Invocar con el Python CUDA: --config <config> --bootstrap-report <report> --output <nuevo-dir>.
Requiere benchmark local ya calibrado. Consume trials de puertas; deja un experimento
aborted legítimo en el ledger. No simula resultados ni modifica el campeón.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gaia.bootstrap import locked, write_json
from gaia.gaia_transformer.campaign_store import CampaignStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--bootstrap-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--previous-report", type=Path, help="limpiar únicamente fixture temporal verificado de un ensayo previo")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cfg = json.loads(args.config.read_text())
    if args.previous_report:
        previous = json.loads(args.previous_report.read_text())
        if previous.get("status") != "RECOVERY_VERIFIED":
            raise ValueError("Informe previo no es una prueba de recuperación verificada")
        old_pid = previous["killed_pid"]
        if Path(f"/proc/{old_pid}").exists():
            raise RuntimeError("El PID anterior todavía existe; no limpiar automáticamente")
        for path in Path("/tmp").glob("gaia-gpu-*/work/runtime.json"):
            request = json.loads(path.read_text())
            hidden = request.get("hidden_files", [])
            expected = str(args.previous_report.parent.resolve() / "interrupted")
            if request.get("parent_host_pid") == old_pid and any(str(value).startswith(expected + "/trial-") for value in hidden):
                shutil.rmtree(path.parents[1])
    store = CampaignStore(ROOT, cfg["workload"]["state_dir"])
    before = store.current_version()
    old_starts = {r["id"] for r in store.records() if r["type"] == "start"}
    env = os.environ.copy()
    env.update(CUDA_VISIBLE_DEVICES=cfg["cuda"]["device_uuid"], CUBLAS_WORKSPACE_CONFIG=":4096:8",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    proc = None
    report = {"status": "RUNNING"}
    try:
        with (args.output / "campaign.stdout.log").open("w") as stdout, (args.output / "campaign.stderr.log").open("w") as stderr:
            proc = subprocess.Popen([sys.executable, "-I", str(ROOT / "gaia/gaia_transformer/campaign.py"),
                                     "--config", str(args.config.resolve()), "--bootstrap-report", str(args.bootstrap_report.resolve()),
                                     "--output", str(args.output.resolve() / "interrupted"), "--minutes", "15", "--max-experiments", "1"],
                                    env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            new = [r for r in store.records() if r["type"] == "start" and r["id"] not in old_starts]
            if new:
                experiment = new[-1]
                time.sleep(.25)  # El trial hijo entra en arranque; no alcanza confirmación/promoción.
                os.kill(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
                break
            if proc.poll() is not None:
                raise RuntimeError("Campaña terminó antes de start; revisar sus logs")
            time.sleep(.05)
        else:
            raise TimeoutError("No apareció un experimento nuevo")
        # flock se libera tras SIGKILL, y recuperar no realiza mediciones ni acepta un trial parcial.
        with locked(store.dir / "calibration.lock"), locked(store.dir / "campaign.lock"):
            partial = list(store.tmp.glob("gaia-gpu-*"))
            recovered, next_id = store.recover()
            end = [r for r in store.records() if r["type"] == "end" and r["id"] == experiment["id"]]
            if recovered != 1 or len(end) != 1 or end[0]["decision"] != "aborted":
                raise RuntimeError("Recuperación no marcó exactamente un huérfano aborted")
            if next_id <= int(experiment["id"][1:]) or store.current_version() != before:
                raise RuntimeError("Se reutiliza ID o cambió campeón tras interrupción")
            if store.recover()[0] != 0:
                raise RuntimeError("Recuperación no es idempotente")
            if list(store.tmp.glob("gaia-gpu-*")):
                raise RuntimeError("Temporales del trial interrumpido no se limpiaron")
        report.update(status="RECOVERY_VERIFIED", interrupted_id=experiment["id"], next_id=next_id,
                      champion_before=before, champion_after=store.current_version(), killed_pid=proc.pid,
                      child_returncode=proc.returncode, recovered=recovered, partial_directories_removed=len(partial))
    except BaseException as exc:
        report.update(status="FAILED", reason=str(exc))
        raise
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        write_json(args.output / "result.json", report)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
