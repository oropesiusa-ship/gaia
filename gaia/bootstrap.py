"""Aprovisionamiento local, solo stdlib: debe poder arrancar sin NumPy instalado."""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
import platform
import sysconfig
import shutil
import subprocess
import sys
import time
import uuid
import urllib.request
import zipfile
import tempfile
from pathlib import Path


class BootstrapError(Exception):
    def __init__(self, stage, reason, remedy):
        super().__init__(reason)
        self.stage, self.remedy = stage, remedy


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def detect(root):
    """Datos estables de identidad separados de recursos disponibles variables."""
    info = _read("/proc/cpuinfo") or ""
    cpu = next((ln.split(":", 1)[1].strip() for ln in info.splitlines()
                if ln.startswith("model name")), platform.processor())
    mem = _read("/proc/meminfo") or ""
    memory = {ln.split(":")[0]: int(ln.split()[1]) // 1024 for ln in mem.splitlines()
              if ln.startswith(("MemTotal:", "MemAvailable:"))}
    total = memory.get("MemTotal", 0)
    # cgroup v2/v1: no presuponer que la RAM del host está disponible al contenedor.
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        value = _read(p)
        if value and value.isdigit():
            total = min(total, int(value) // 2**20) if total else int(value) // 2**20
    gpu = {"status": "not_detected", "devices": []}
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,uuid,driver_version,memory.total,compute_cap",
                 "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
            gpu["status"] = "detected" if result.returncode == 0 else "probe_failed"
            for line in result.stdout.splitlines() if result.returncode == 0 else []:
                fields = [v.strip() for v in line.split(",")]
                if len(fields) == 5:
                    gpu["devices"].append(dict(zip(
                        ("name", "uuid", "driver", "vram_mb", "compute_capability"), fields)))
            if result.returncode:
                gpu["error"] = result.stderr[-2000:]
        except (OSError, subprocess.TimeoutExpired) as exc:
            gpu.update(status="probe_failed", error=str(exc))
    machine_id = _read("/etc/machine-id") or platform.node()
    host = {"system": platform.system(), "machine": platform.machine(), "cpu": cpu,
            "cores": os.cpu_count(), "ram_mb": total, "gpu": gpu,
            "host_id": digest(machine_id)}
    return {"host": host, "python": list(sys.version_info[:3]),
            "implementation": platform.python_implementation(), "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
            "libc": list(platform.libc_ver()),
            "interpreter": sys.executable, "ram_available_mb": memory.get("MemAvailable"),
            "disk_free_mb": shutil.disk_usage(root).free // 2**20,
            "bwrap": shutil.which("bwrap")}


def select_profile(catalog, detected, workload="numpy_mlp", requested=None):
    h, py = detected["host"], detected["python"][:2]
    for profile in catalog["profiles"]:
        if requested and requested != profile["id"]:
            continue
        if (profile["workload"] == workload and h["system"] in profile["systems"]
                and h["machine"] in profile["machines"]
                and profile["python_min"] <= py <= profile["python_max"]):
            if profile.get("gpu_capabilities"):
                validate_cuda_host(profile, detected)
            for rule in profile["requirements"]:
                if rule["python_min"] <= py <= rule["python_max"]:
                    return {**profile, "packages": rule["packages"]}
    raise BootstrapError("profile", "No hay perfil compatible con este workload/SO/arquitectura/Python.",
                         "Revisar la detección y ampliar gaia/bootstrap_profiles.json con un perfil probado. "
                         "Detectar GPU no activa por sí solo otro workload.")


def version_tuple(value):
    return tuple(int(v) for v in value.split("."))


def validate_cuda_host(profile, detected):
    def fail(reason):
        raise BootstrapError("cuda-preflight", reason,
                             "Revisar detección, driver y perfil. No se modifican drivers ni se cambia a CPU silenciosamente.")
    if detected.get("implementation") != "CPython" or detected.get("free_threaded"):
        fail("El perfil CUDA requiere CPython estándar (no free-threaded).")
    libc = detected.get("libc", [])
    if len(libc) != 2 or libc[0] != "glibc" or version_tuple(libc[1]) < version_tuple(profile["min_glibc"]):
        fail("El perfil CUDA requiere glibc >= " + profile["min_glibc"])
    if detected["host"]["ram_mb"] < profile["min_ram_mb"]:
        fail("RAM insuficiente para el entorno Torch/CUDA.")
    for gpu in detected["host"]["gpu"]["devices"]:
        if (gpu.get("compute_capability") in profile["gpu_capabilities"]
                and version_tuple(gpu["driver"]) >= version_tuple(profile["min_driver"])
                and int(gpu["vram_mb"]) >= profile["min_vram_mb"]):
            return gpu
    fail("No hay GPU Pascal con VRAM y driver compatibles con el perfil CUDA 12.6.")


def local_config(user, detected, key, profile=None):
    cfg = json.loads(json.dumps(user))
    cfg.setdefault("workload", {}).update(state_dir=f"state_numpy_mlp_{key}",
                                          host_fingerprint=key, environment_profile="cpu-numpy")
    cfg["workload"].setdefault("id", "numpy_mlp")
    limits = cfg.setdefault("limits", {})
    ram = detected["host"]["ram_mb"]
    if ram < 1024:
        raise BootstrapError("resources", "Menos de 1 GiB de RAM disponible al sistema.",
                             "Ampliar recursos o diseñar un perfil de benchmark de baja memoria.")
    safe_ram = min(3000, int(ram * 0.4))
    limits["max_ram_mb"] = min(limits.get("max_ram_mb", safe_ram), safe_ram)
    limits.setdefault("worker_threads", 1)
    if limits["max_ram_mb"] < 768:
        cfg.setdefault("benchmark_profile", "easy")
    if profile and profile.get("environment_only"):
        gpu = validate_cuda_host(profile, detected)
        cfg["workload"].update(id=profile["workload"], state_dir=f"state_gaia_transformer_cuda_{key}",
                               environment_profile=profile["id"], contract=profile["contract"])
        cfg["cuda"] = {"device_uuid": gpu["uuid"], "deterministic": True, "dtype": "float32",
                       "cublas_workspace_config": ":4096:8", "allow_tf32": False, "cudnn_benchmark": False}
        limits["max_vram_mb"] = min(limits.get("max_vram_mb", 3000), 3000, int(int(gpu["vram_mb"]) * 0.6))
    return cfg


@contextlib.contextmanager
def locked(path):
    # El kernel libera flock también tras kill -9; no quedan bloqueos por PID reutilizado.
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BootstrapError("lock", "Otro bootstrap está trabajando en este proyecto.",
                                 "Esperar a que termine y volver a ejecutar.")
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Session:
    def __init__(self, root):
        self.root = Path(root)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.directory = self.root / ".gaia" / "reports" / f"{stamp}-{uuid.uuid4().hex[:8]}"
        self.directory.mkdir(parents=True)
        self.report = {"status": "running", "started": time.time(), "steps": []}

    def command(self, stage, args, env=None, timeout=300, live=False, text_errors="strict"):
        index = len(self.report["steps"])
        out, err = self.directory / f"{index:02d}-{stage}.stdout.log", self.directory / f"{index:02d}-{stage}.stderr.log"
        step = {"stage": stage, "command": [str(a) for a in args], "stdout": out.name,
                "stderr": err.name}
        self.report["steps"].append(step)
        self.save()
        print(f"[bootstrap] {stage}", flush=True)
        start = time.monotonic()
        try:
            with out.open("w") as stdout, err.open("w") as stderr:
                proc = subprocess.Popen(args, cwd=self.root, env=env, stdout=stdout, stderr=stderr,
                                        start_new_session=True)
                try:
                    if live:
                        with out.open(errors=text_errors) as output, err.open(errors=text_errors) as errors:
                            while True:
                                print(output.read(), end="", flush=True)
                                print(errors.read(), end="", file=sys.stderr, flush=True)
                                if proc.poll() is not None:
                                    print(output.read(), end="", flush=True)
                                    print(errors.read(), end="", file=sys.stderr, flush=True)
                                    break
                                if time.monotonic() - start >= timeout:
                                    raise subprocess.TimeoutExpired(args, timeout)
                                time.sleep(0.2)
                        rc = proc.returncode
                    else:
                        rc = proc.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    import signal
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                    raise
            step["returncode"] = rc
            if rc:
                raise BootstrapError(stage, f"El proceso terminó con código {rc}.",
                                     f"Revisar {out.name} y {err.name}; no se continúa con la campaña.")
        except subprocess.TimeoutExpired:
            step["timeout"] = timeout
            raise BootstrapError(stage, f"Tiempo límite de {timeout}s agotado.",
                                 "Revisar logs, conectividad y recursos antes de reintentar.")
        finally:
            step["seconds"] = round(time.monotonic() - start, 2)
            self.save()
        return out.read_text(errors=text_errors)

    def save(self):
        write_json(self.directory / "report.json", self.report)

    def finish(self, status, error=None):
        self.report.update(status=status, finished=time.time())
        if error:
            self.report["failure"] = {"stage": getattr(error, "stage", "bootstrap"),
                                      "reason": str(error), "remedy": getattr(error, "remedy", "Revisar informe y logs.")}
        self.save()
        lines = ["# Informe de aprovisionamiento GAIA", "", f"Estado: **{status}**", "",
                 "```json", json.dumps(self.report, indent=2, ensure_ascii=False), "```", "",
                 "Los logs completos de cada etapa están en este directorio."]
        (self.directory / "REPORT.md").write_text("\n".join(lines) + "\n")
        print(f"[bootstrap] {status}: {self.directory / 'REPORT.md'}", flush=True)
        if error:
            print(f"[bootstrap] {error}", flush=True)


PROBE = """
import json, sys, numpy as np
a = np.arange(16, dtype=float).reshape(4, 4)
assert np.isfinite(a @ a).all()
print(json.dumps({'python': sys.version.split()[0], 'executable': sys.executable,
                  'prefix': sys.prefix, 'numpy': np.__version__, 'numpy_file': np.__file__}))
"""


PREFLIGHT = """
import importlib.util, json
result = {}
for name in ('venv', 'ensurepip', 'ssl', 'zlib', 'ctypes', 'resource'):
    try:
        mod = __import__(name)
        if name == 'ensurepip':
            mod.version()
        result[name] = True
    except Exception as exc:
        result[name] = str(exc)
print(json.dumps(result))
"""


def preflight(session, env):
    checks = json.loads(session.command("preflight", [sys.executable, "-I", "-c", PREFLIGHT], env, 30))
    strategy = "venv" if checks["venv"] is True and checks["ensurepip"] is True else "virtualenv"
    session.report["preflight"] = {"checks": checks, "strategy": strategy,
                                   "needs_sudo": False, "network": "not_tested_until_needed"}
    missing = [name for name in ("ssl", "zlib", "ctypes", "resource") if checks[name] is not True]
    if missing:
        raise BootstrapError("preflight", "El intérprete carece de módulos necesarios: " + ", ".join(missing),
                             "Usar un Python completo para Linux con SSL, zlib, ctypes y resource.")
    return strategy


def verified_download(session, artifact):
    """La procedencia y el hash se fijan en el proyecto, no se confían a metadatos remotos."""
    cache = session.root / ".gaia" / "bootstrap-cache" / "wheels"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / artifact["url"].rsplit("/", 1)[1]
    record = {**artifact, "cache": str(target), "cached": False}
    session.report.setdefault("downloads", []).append(record)
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == artifact["sha256"]:
        record["cached"] = True
        return target
    tmp = target.with_suffix(".part")
    try:
        print(f"[bootstrap] download {target.name}", flush=True)
        request = urllib.request.Request(artifact["url"], headers={"User-Agent": "GAIA-bootstrap/1"})
        start = time.monotonic()
        with urllib.request.urlopen(request, timeout=30) as response, tmp.open("wb") as output:
            size = 0
            while chunk := response.read(128 * 1024):
                size += len(chunk)
                if size > 32 * 2**20 or time.monotonic() - start > 120:
                    raise ValueError("Descarga excede el tamaño o tiempo permitido")
                output.write(chunk)
        if hashlib.sha256(tmp.read_bytes()).hexdigest() != artifact["sha256"]:
            raise ValueError("SHA-256 no coincide con el artefacto declarado")
        tmp.replace(target)
        record["verified"] = True
        return target
    except Exception as exc:
        record["error"] = str(exc)
        raise BootstrapError("download", f"No se pudo obtener/verificar {target.name}: {exc}",
                             "Revisar red, certificados, espacio y URL/hash del catálogo. "
                             "Se puede precargar .gaia/bootstrap-cache/wheels con los wheels declarados; "
                             "o instalar opcionalmente python3-venv en el sistema.") from exc
    finally:
        tmp.unlink(missing_ok=True)
        session.save()


def create_environment(session, venv, env, strategy):
    if strategy == "venv":
        session.command("venv", [sys.executable, "-m", "venv", str(venv)], env, 120)
        return
    tools = json.loads((session.root / "gaia" / "bootstrap_tools.json").read_text())
    session.report["bootstrap_tools"] = tools
    # Completar/verificar todas las descargas antes de tocar el entorno de destino.
    wheels = [verified_download(session, item) for item in tools["artifacts"]]
    base = session.root / ".gaia" / "bootstrap-cache"
    with tempfile.TemporaryDirectory(prefix="virtualenv-", dir=base) as tmp:
        site = Path(tmp)
        for wheel in wheels:
            with zipfile.ZipFile(wheel) as archive:
                for name in archive.namelist():
                    if not (site / name).resolve().is_relative_to(site.resolve()):
                        raise BootstrapError("extract", "Ruta inválida en wheel de bootstrap.", "Revisar artefacto.")
                archive.extractall(site)
        runner = "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('virtualenv',run_name='__main__')"
        session.command("virtualenv", [sys.executable, "-I", "-S", "-c", runner, str(site),
                                        "--no-download", "--no-periodic-update", "--no-setuptools",
                                        "--app-data", str(base / "virtualenv-appdata"), str(venv)], env, 180)


def validate_cuda_results(results, profile, cfg):
    reference = results[0]
    for result in results:
        stable = {k: v for k, v in result.items() if k != "metrics"}
        if stable != {k: v for k, v in reference.items() if k != "metrics"}:
            raise BootstrapError("cuda-runtime", "El runtime o los resultados CUDA difieren entre procesos normal/aislados.",
                                 "Revisar los tres probes CUDA: runtime, flags, GPU y hashes numéricos.")
    torch = reference["runtime"]["torch"]
    policy = reference["policy"]
    gpu = reference["gpu"]
    if (reference.get("status") != "ok" or torch["version"] != profile["torch_version"]
            or torch["cuda"] != profile["cuda_version"]
            or str(gpu["uuid"]).lower().removeprefix("gpu-") != cfg["cuda"]["device_uuid"].lower().removeprefix("gpu-")
            or not policy["deterministic"] or not policy["cudnn_deterministic"]
            or policy["tf32_matmul"] or policy["tf32_cudnn"] or policy["cudnn_benchmark"]
            or policy["cublas_workspace_config"] != ":4096:8" or policy["dtype"] != "float32"):
        raise BootstrapError("cuda-policy", "El probe CUDA no cumple el perfil, GPU seleccionada o determinismo.",
                             "Revisar wheel, selección de GPU y flags antes de implementar GaiaTransformer.")


def diagnose_cuda(session, python, env, profile, cfg):
    probe = session.root / "gaia" / "cuda_probe.py"
    session.report["cuda_probe_sha256"] = hashlib.sha256(probe.read_bytes()).hexdigest()
    # Simula el entorno mínimo de un worker futuro; el worker MLP no se altera.
    minimal = {key: env[key] for key in (
        "PATH", "HOME", "CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER", "CUBLAS_WORKSPACE_CONFIG",
        "GAIA_PROBE_VRAM_MB", "GAIA_PROBE_RSS_MB", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"
    ) if key in env}
    results = []
    for stage, flags, child_env in (("cuda-parent", [], env), ("cuda-isolated", ["-I"], minimal),
                                     ("cuda-repeat", ["-I"], minimal)):
        result = json.loads(session.command(stage, [str(python), *flags, str(probe)], child_env, 120))
        results.append(result)
        session.report["cuda_probes"] = results
        session.save()
    validate_cuda_results(results, profile, cfg)
    session.report["cuda_status"] = "CUDA_ENVIRONMENT_READY"
    session.report["campaign_status"] = "NOT_ASSESSED: usar gaia-transformer-prepare para comprobar el estado de campaña"


def provision(session, requested=None, doctor=False, prepare=False, preflight_only=False, allow_environment_only=True):
    root = session.root
    detected = detect(root)
    session.report["detected"] = detected
    user_path = root / "gaia.json"
    user = json.loads(user_path.read_text()) if user_path.exists() else {}
    catalog = json.loads((root / "gaia" / "bootstrap_profiles.json").read_text())
    workload = user.get("workload", {}).get("id", "numpy_mlp")
    if requested:
        workload = next((p["workload"] for p in catalog["profiles"] if p["id"] == requested), workload)
    profile = select_profile(catalog, detected, workload, requested)
    if profile.get("environment_only") and not allow_environment_only:
        raise BootstrapError("workload", "El motor MLP no ejecuta campañas GaiaTransformer/CUDA.",
                             "Usar gaia-transformer-run/gaia-transformer-prepare o bootstrap/doctor --profile gaia-transformer-cuda-pascal. "
                             "No ejecutar una campaña MLP bajo identidad GaiaTransformer.")
    if profile.get("lockfile"):
        profile["lock_sha256"] = hashlib.sha256((root / profile["lockfile"]).read_bytes()).hexdigest()
        profile["interpreter_sha256"] = hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
    session.report.update(profile=profile["id"], packages=profile["packages"], catalog_version=catalog["version"],
                          selection_reason="Perfil compatible con workload, SO, arquitectura y Python" + (
                              "; GPU Pascal, driver, VRAM y glibc comprobados." if profile.get("environment_only")
                              else "; el workload NumPy no utiliza GPU."))
    if profile.get("lockfile"):
        session.report["lockfile"] = {"path": profile["lockfile"], "sha256": profile["lock_sha256"]}
        session.report["interpreter_sha256"] = profile["interpreter_sha256"]
    key = digest({"host": detected["host"], "python": detected["python"],
                  "profile": profile, "catalog_version": catalog["version"], "config": user})
    venv = root / ".gaia" / "venvs" / f"{profile['id']}-{key}"
    python = venv / "bin" / "python"
    cfg_path = root / ".gaia" / "configs" / f"{key}.json"
    cfg = local_config(user, detected, key, profile)
    session.report.update(environment=str(venv), config=str(cfg_path),
                          state_dir=cfg["workload"]["state_dir"], effective_config=cfg)
    # Modo diagnóstico no instala ni inicializa campañas.
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env.pop("GAIA_FP_TORCH", None)
    env.update(GAIA_LOCAL_CONFIG=str(cfg_path), GAIA_MANAGED="1", PYTHONNOUSERSITE="1", PYTHONUNBUFFERED="1")
    if profile.get("environment_only"):
        env.update(CUDA_VISIBLE_DEVICES=cfg["cuda"]["device_uuid"], CUDA_DEVICE_ORDER="PCI_BUS_ID",
                   CUBLAS_WORKSPACE_CONFIG=":4096:8", GAIA_PROBE_VRAM_MB=str(cfg["limits"]["max_vram_mb"]),
                   GAIA_PROBE_RSS_MB=str(cfg["limits"]["max_ram_mb"]),
                   OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    strategy = preflight(session, env)
    min_disk = profile.get("min_disk_mb", 1024)
    if detected["disk_free_mb"] < min_disk:
        raise BootstrapError("resources", f"Menos de {min_disk} MiB libres para entorno, caché y estado.",
                             "Liberar espacio y reintentar.")
    if preflight_only:
        session.report["preflight"]["environment_exists"] = python.exists()
        return python, env
    if doctor and not python.exists():
        raise BootstrapError("environment", "No existe el entorno local seleccionado.",
                             "Ejecutar python3 gaia.py bootstrap para crearlo y validarlo.")
    if not doctor:
        if not (venv / "gaia-venv-ready.json").exists():
            session.report["recovering_partial_environment"] = venv.exists()
            create_environment(session, venv, env, strategy)
            write_json(venv / "gaia-venv-ready.json", {"created": time.time(), "strategy": strategy})
        marker = venv / "gaia-installed.json"
        expected = {"packages": profile["packages"], "profile": profile["id"]}
        if profile.get("lockfile"):
            expected["lock_sha256"] = profile["lock_sha256"]
        if not marker.exists() or json.loads(marker.read_text()) != expected:
            requirements = ["--require-hashes", "-r", str(root / profile["lockfile"])] if profile.get("lockfile") else profile["packages"]
            session.command("install", [str(python), "-m", "pip", "--isolated", "install",
                                        "--disable-pip-version-check", "--only-binary=:all:",
                                        "--index-url", "https://pypi.org/simple", *requirements], env,
                            1800 if profile.get("lockfile") else 600, live=bool(profile.get("lockfile")))
            write_json(marker, expected)
        if cfg_path.exists() and json.loads(cfg_path.read_text()) != cfg:
            raise BootstrapError("config", "La configuración local existente no coincide.",
                                 "Revisar la configuración sin modificar una identidad congelada.")
        write_json(cfg_path, cfg)
    a = json.loads(session.command("probe-parent", [str(python), "-c", PROBE], env, 60))
    b = json.loads(session.command("probe-isolated", [str(python), "-I", "-c", PROBE], env, 60))
    if a != b or a["prefix"] != str(venv) or f"numpy=={a['numpy']}" not in profile["packages"]:
        raise BootstrapError("runtime", "Runtime distinto bajo -I o dependencia fuera del perfil.",
                             "Revisar los dos probes y reconstruir el entorno local.")
    session.report["runtime"] = a
    session.report["installed_packages"] = session.command(
        "inventory", [str(python), "-m", "pip", "--isolated", "freeze", "--all"], env, 60).splitlines()
    if profile.get("environment_only"):
        session.command("pip-check", [str(python), "-m", "pip", "--isolated", "check"], env, 60)
        diagnose_cuda(session, python, env, profile, cfg)
    elif prepare:
        session.command("selftest", [str(python), str(root / "gaia.py"), "selftest"], env, 600, live=True)
        session.command("prepare", [str(python), str(root / "gaia.py"), "prepare"], env, 1800, live=True)
    return python, env


def dispatch(root, args):
    """Devuelve None para el CLI normal, o código de salida si se gestionó el comando."""
    if not args or args[0] in ("-h", "--help"):
        return None
    if args[0] == "--no-bootstrap":
        del args[0]
        return None
    if args[0] in ("certify-pipeline", "verify-autonomous-mvp"):
        # Explicitly offline: no provisioning, pip, managed productive config,
        # calibration or other state is opened by this dispatch path.
        import importlib.util
        if importlib.util.find_spec("numpy") is None:
            print(json.dumps({"status": "BLOCKED", "pipeline_certified": False,
                              "autonomous_self_improvement_certified": False,
                              "reason": "Use an existing local Python with NumPy (e.g. the cpu-numpy venv); verification commands never install/download."}))
            return 40
        return None
    if args[0] == "appliance-bootstrap":
        from .appliance_bootstrap import main
        return main(root, args[1:])
    if args[0] == "appliance-rootfs":
        from .appliance_rootfs import main
        return main(root, args[1:])
    if args[0] == "appliance-image":
        from .appliance_image import main
        return main(root, args[1:])
    if args[0] == "appliance-verify":
        from .appliance_verify import main
        return main(root, args[1:])
    if args[0] == "appliance-recovery":
        from .appliance_recovery import main
        return main(root, args[1:])
    if args[0] == "appliance-nvidia":
        from .appliance_nvidia import main
        return main(root, args[1:])
    # La parada debe funcionar aunque no haya red, dependencias ni perfil compatible.
    if args == ["stop"]:
        (Path(root) / "STOP").write_text("stop\n")
        print("STOP creado: GAIA se detendrá antes del siguiente experimento.")
        return 0
    if args == ["resume"]:
        (Path(root) / "STOP").unlink(missing_ok=True)
        print("STOP eliminado.")
        return 0
    explicit = args[0] in ("bootstrap", "doctor", "gaia-transformer-baseline", "gaia-transformer-lab", "gaia-transformer-benchmark", "gaia-transformer-run", "gaia-transformer-prepare", "gaia-transformer-observe", "gaia-transformer-research", "gaia-transformer-meta")
    if os.environ.get("GAIA_MANAGED") == "1" and not explicit:
        return None
    if not explicit and args[0] not in ("run", "prepare", "status", "report", "audit", "meta", "prove", "research", "rollback", "stop", "resume", "selftest"):
        return None
    options = None
    if explicit:
        description = ("Compara estrategias en ajuste y tarea reservada GPU, con presupuestos equivalentes."
                       if args[0] == "gaia-transformer-meta" else
                       "Modo B GPU: hipótesis falsables, contrastes pareados y memoria sin promoción directa."
                       if args[0] == "gaia-transformer-research" else
                       "Perfila el campeón CUDA en observación separada y genera diagnóstico no promocional."
                       if args[0] == "gaia-transformer-observe" else
                       "Prepara puertas CUDA y ejecuta campaña GaiaTransformer sobre benchmark congelado."
                       if args[0] in ("gaia-transformer-run", "gaia-transformer-prepare") else
                       "Valida el laboratorio GPU con baseline, aislamiento y casos de fallo reales."
                       if args[0] == "gaia-transformer-lab" else
                       "Entrena la baseline GaiaTransformer CUDA fija y verifica causalidad, pérdida privada y repetibilidad."
                       if args[0] == "gaia-transformer-baseline" else
                       "Provisiona GAIA automáticamente o diagnostica su entorno local.")
        parser = argparse.ArgumentParser(description=description)
        parser.add_argument("--profile", help="perfil del catálogo, por defecto selección automática")
        if args[0] in ("gaia-transformer-baseline", "gaia-transformer-lab", "gaia-transformer-benchmark", "gaia-transformer-run", "gaia-transformer-prepare", "gaia-transformer-observe", "gaia-transformer-research", "gaia-transformer-meta"):
            parser.set_defaults(profile="gaia-transformer-cuda-pascal", preflight=False, no_prepare=False)
        if args[0] == "gaia-transformer-observe":
            parser.add_argument("--steps", type=int, default=100, help="pasos medidos después de 25 de calentamiento (10..300)")
        elif args[0] == "gaia-transformer-baseline":
            parser.add_argument("--steps", type=int, default=100, help="pasos de la baseline fija (20..10000)")
            parser.add_argument("--seed", type=int, default=9000)
            parser.add_argument("--repeats", type=int, default=2, help="repeticiones de la misma semilla (2..5), más una semilla distinta")
        elif args[0] == "gaia-transformer-research":
            parser.add_argument("--minutes", type=float, default=10, help="presupuesto de investigación (1..60)")
        elif args[0] in ("gaia-transformer-run", "gaia-transformer-prepare"):
            parser.add_argument("--minutes", type=float, default=15, help="presupuesto total incluidas puertas (1..60)")
            parser.add_argument("--max-experiments", type=int, default=1, help="experimentos nuevos (1..1000)")
            parser.add_argument("--research-after", type=int, default=40, help="disparar Modo B tras N experimentos sin mejora")
        elif args[0] not in ("gaia-transformer-lab", "gaia-transformer-benchmark", "gaia-transformer-meta"):
            parser.add_argument("--no-prepare", action="store_true", help="omitir selftest y calibración (bootstrap)")
            parser.add_argument("--preflight", action="store_true", help="solo comprobaciones previas, sin instalar ni calibrar")
        options = parser.parse_args(args[1:])
        if args[0] in ("gaia-transformer-baseline", "gaia-transformer-lab", "gaia-transformer-benchmark", "gaia-transformer-run", "gaia-transformer-prepare", "gaia-transformer-observe", "gaia-transformer-research", "gaia-transformer-meta"):
            if options.profile != "gaia-transformer-cuda-pascal" or options.preflight or options.no_prepare:
                parser.error("El comando requiere el perfil CUDA Pascal y ejecuta la verificación completa")
        if args[0] == "gaia-transformer-baseline":
            if not 20 <= options.steps <= 10000 or not 2 <= options.repeats <= 5 or not 0 <= options.seed < 2**31 - 1:
                parser.error("steps debe ser 20..10000, repeats 2..5 y seed 0..2**31-2")
        if args[0] in ("gaia-transformer-run", "gaia-transformer-prepare") and not (1 <= options.max_experiments <= 1000 and 1 <= options.minutes <= 60):
            parser.error("max-experiments debe ser 1..1000 y minutes 1..60")
        if args[0] == "gaia-transformer-observe" and not 10 <= options.steps <= 300:
            parser.error("steps debe ser 10..300")
        if args[0] in ("gaia-transformer-run", "gaia-transformer-prepare") and not 1 <= options.research_after <= 1000:
            parser.error("research-after debe ser 1..1000")
        if args[0] == "gaia-transformer-research" and not 1 <= options.minutes <= 60:
            parser.error("minutes debe ser 1..60")
    session = Session(root)
    session.report["request"] = {"command": args[0], "profile": options.profile if options else None}
    try:
        with locked(Path(root) / ".gaia" / "bootstrap.lock"):
            python, env = provision(session, options.profile if options else None,
                                    doctor=args[0] == "doctor",
                                    prepare=args[0] == "bootstrap" and not options.no_prepare and not options.preflight,
                                    preflight_only=bool(options and options.preflight), allow_environment_only=explicit)
        if args[0] == "gaia-transformer-baseline":
            suite = ("import sys,unittest;sys.path.insert(0,sys.argv[1]);"
                     "s=unittest.defaultTestLoader.discover(sys.argv[1]+'/tests',pattern='test_gaia_transformer_model.py');"
                     "sys.exit(0 if unittest.TextTestRunner(verbosity=2).run(s).wasSuccessful() else 1)")
            session.command("gaia-transformer-model-tests", [str(python), "-I", "-c", suite, str(root)], env, 120, live=True)
            runtime_limit = session.report["effective_config"].get("limits", {}).get("max_experiment_seconds", 20)
            raw = session.command("gaia-transformer-baseline", [str(python), "-I", str(Path(root) / "gaia/gaia_transformer/phase1.py"),
                                  "--config", env["GAIA_LOCAL_CONFIG"],
                                  "--bootstrap-report", str(session.directory / "report.json"),
                                  "--output", str(session.directory / "phase1"),
                                  "--steps", str(options.steps), "--seed", str(options.seed),
                                  "--repeats", str(options.repeats)], env,
                                  (options.repeats + 1) * (runtime_limit + 20) + 120, live=True)
            session.report["gaia_transformer_baseline"] = json.loads(raw)
            if session.report["gaia_transformer_baseline"].get("status") != "GAIA_TRANSFORMER_BASELINE_READY":
                raise BootstrapError("gaia-transformer-baseline", "La verificación no confirmó la baseline.",
                                     "Revisar phase1/result.json y los logs de los trials.")
        if args[0] == "gaia-transformer-lab":
            suite = ("import sys,unittest;sys.path.insert(0,sys.argv[1]);"
                     "s=unittest.defaultTestLoader.discover(sys.argv[1]+'/tests',pattern='test_gaia_transformer_lab.py');"
                     "sys.exit(0 if unittest.TextTestRunner(verbosity=2).run(s).wasSuccessful() else 1)")
            session.command("gaia-transformer-lab-tests", [str(python), "-I", "-c", suite, str(root)], env, 120, live=True)
            raw = session.command("gaia-transformer-lab", [str(python), "-I", str(Path(root) / "gaia/gaia_transformer/lab/validation.py"),
                                  "--config", env["GAIA_LOCAL_CONFIG"],
                                  "--bootstrap-report", str(session.directory / "report.json"),
                                  "--output", str(session.directory / "phase2")], env, 600, live=True)
            session.report["gaia_transformer_lab"] = json.loads(raw)
            if session.report["gaia_transformer_lab"].get("status") != "GPU_LAB_READY":
                raise BootstrapError("gaia-transformer-lab", "El laboratorio GPU no pasó su validación.", "Revisar phase2/result.json.")
        if args[0] == "gaia-transformer-benchmark":
            raw = session.command("gaia-transformer-benchmark", [str(python), "-I", str(Path(root) / "gaia/gaia_transformer/lab/calibration.py"),
                                  "--config", env["GAIA_LOCAL_CONFIG"],
                                  "--bootstrap-report", str(session.directory / "report.json"),
                                  "--output", str(session.directory / "phase3")], env, 2400, live=True)
            session.report["gaia_transformer_benchmark"] = json.loads(raw)
            if session.report["gaia_transformer_benchmark"].get("status") != "GPU_BENCHMARK_READY":
                raise BootstrapError("gaia-transformer-benchmark", "Benchmark no validado.", "Revisar phase3/result.json.")
        if args[0] in ("gaia-transformer-run", "gaia-transformer-prepare"):
            extra = ["--prepare-only"] if args[0] == "gaia-transformer-prepare" else []
            raw = session.command("gaia-transformer-campaign", [str(python), "-I", str(Path(root) / "gaia/gaia_transformer/campaign.py"),
                                  "--config", env["GAIA_LOCAL_CONFIG"], "--bootstrap-report", str(session.directory / "report.json"),
                                  "--output", str(session.directory / "campaign"),
                                  "--minutes", str(options.minutes), "--max-experiments", str(options.max_experiments),
                                  "--research-after", str(options.research_after), *extra],
                                  env, int(options.minutes * 60) + 180, live=True)
            session.report["gaia_transformer_campaign"] = json.loads(raw)
            if session.report["gaia_transformer_campaign"].get("status") not in ("READY_FOR_CAMPAIGN", "GPU_CAMPAIGN_COMPLETE", "STOPPED"):
                raise BootstrapError("gaia-transformer-campaign", "Campaña GPU incompleta.", "Revisar campaign/result.json.")
        if args[0] == "gaia-transformer-observe":
            raw = session.command("gaia-transformer-observe", [str(python), "-I", str(Path(root) / "gaia/gaia_transformer/observation.py"),
                                  "--config", env["GAIA_LOCAL_CONFIG"], "--bootstrap-report", str(session.directory / "report.json"),
                                  "--output", str(session.directory / "observation"), "--steps", str(options.steps)], env, 180, live=True)
            session.report["gaia_transformer_observation"] = json.loads(raw)
            if session.report["gaia_transformer_observation"].get("status") != "GPU_OBSERVATION_READY":
                raise BootstrapError("gaia-transformer-observe", "Observación GPU incompleta.", "Revisar observation/result.json.")
        if args[0] == "gaia-transformer-research":
            raw = session.command("gaia-transformer-research", [str(python), "-I", str(Path(root) / "gaia/gaia_transformer/research.py"),
                                  "--config", env["GAIA_LOCAL_CONFIG"], "--bootstrap-report", str(session.directory / "report.json"),
                                  "--output", str(session.directory / "research"), "--minutes", str(options.minutes)],
                                  env, int(options.minutes * 60) + 120, live=True)
            session.report["gaia_transformer_research"] = json.loads(raw)
            if session.report["gaia_transformer_research"].get("status") != "GPU_RESEARCH_COMPLETE":
                raise BootstrapError("gaia-transformer-research", "Investigación GPU incompleta.", "Revisar research/result.json.")
        if args[0] == "gaia-transformer-meta":
            raw = session.command("gaia-transformer-meta", [str(python), "-I", str(Path(root) / "gaia/gaia_transformer/metastudy.py"),
                                  "--config", env["GAIA_LOCAL_CONFIG"], "--bootstrap-report", str(session.directory / "report.json"),
                                  "--output", str(session.directory / "meta")], env, 1800, live=True)
            session.report["gaia_transformer_meta"] = json.loads(raw)
            if session.report["gaia_transformer_meta"].get("status") != "GPU_META_COMPLETE":
                raise BootstrapError("gaia-transformer-meta", "Estudio de transferencia incompleto.", "Revisar meta/result.json.")
        if options and options.preflight:
            status = "PREFLIGHT_READY"
        elif session.report.get("gaia_transformer_meta"):
            status = "GPU_META_COMPLETE"
        elif session.report.get("gaia_transformer_research"):
            status = "GPU_RESEARCH_COMPLETE"
        elif session.report.get("gaia_transformer_observation"):
            status = "GPU_OBSERVATION_READY"
        elif session.report.get("gaia_transformer_campaign"):
            status = session.report["gaia_transformer_campaign"]["status"]
        elif session.report.get("gaia_transformer_benchmark"):
            status = "GPU_BENCHMARK_READY"
        elif session.report.get("gaia_transformer_lab"):
            status = "GPU_LAB_READY"
        elif session.report.get("gaia_transformer_baseline"):
            status = "GAIA_TRANSFORMER_BASELINE_READY"
        elif session.report.get("cuda_status"):
            status = "CUDA_ENVIRONMENT_READY"
        elif args[0] == "bootstrap" and not options.no_prepare:
            status = "READY"
        else:
            status = "ENVIRONMENT_READY"
        session.finish(status)
    except KeyboardInterrupt as exc:
        session.finish("INTERRUPTED", exc)
        return 130
    except Exception as exc:
        session.finish("FAILED", exc)
        return 40
    if explicit:
        return 0
    # También se registra el fallo de las puertas en arranques automáticos.
    try:
        session.command("cli", [str(python), str(Path(root) / "gaia.py"), *args], env, 24 * 3600, live=True)
        session.finish("COMPLETED")
        return 0
    except BootstrapError as exc:
        rc = session.report["steps"][-1].get("returncode", 40)
        session.finish("STOPPED" if rc in (10, 20, 130) else "FAILED", exc)
        return rc
    except KeyboardInterrupt as exc:
        session.finish("INTERRUPTED", exc)
        return 130
