"""Mandatory CPU bwrap boundary, minimal bundle and verified isolation protocol.

Only /work and a private /tmp are writable. This module is also copied into
the read-only bundle so the trusted worker can report isolation before loading
any candidate. No candidate or evaluation target is used by the handshake.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import socket
import subprocess
import sys
import sysconfig

NAMESPACES = ("user", "pid", "net", "ipc", "uts")
POLICY_SCHEMA = "cpu_bwrap_policy_v1"
POLICY = {"writable": ["/work", "/tmp"], "bundle": "/lab:read-only",
          "runtime": "read-only", "host_home": False, "host_workspace": False}


class SandboxError(RuntimeError):
    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _hash(contents):
    return hashlib.sha256(contents).hexdigest()


def namespaces(pid="self"):
    return {name: os.stat(f"/proc/{pid}/ns/{name}").st_ino for name in NAMESPACES}


def environment(threads):
    return {"HOME": "/work", "TMPDIR": "/tmp", "PATH": "/usr/bin:/bin",
            "PYTHONHASHSEED": "0", "OMP_NUM_THREADS": str(threads),
            "OPENBLAS_NUM_THREADS": str(threads), "MKL_NUM_THREADS": str(threads)}


def rlimit_policy(limits):
    cpu_s = int(limits["max_experiment_seconds"] + 10)
    return {"RLIMIT_CPU": [cpu_s, cpu_s + 2],
            "RLIMIT_AS": [limits["max_ram_mb"] * 2**20] * 2,
            "RLIMIT_FSIZE": [64 * 2**20] * 2, "RLIMIT_CORE": [0, 0]}


def policy(limits):
    return {"policy_schema": POLICY_SCHEMA, "backend": "bwrap", "namespaces": list(NAMESPACES),
            "network_isolated": True, "filesystem": json.loads(json.dumps(POLICY)),
            "rlimits": rlimit_policy(limits), "environment": environment(limits.get("worker_threads", 1))}


def command(bundle, work, entrypoint, arguments=()):
    binary = shutil.which("bwrap")
    if not binary:
        raise SandboxError("SANDBOX_UNAVAILABLE", "bwrap not found")
    import numpy
    executable = Path(sys.executable).absolute()
    real = executable.resolve()
    args = [binary, "--die-with-parent", "--cap-drop", "ALL"]
    args += [f"--unshare-{name}" for name in NAMESPACES]
    # System shared objects / stdlib. No /usr/bin directory, home, sysfs,
    # workspace, host sockets or devices are exposed.
    for path in ("/usr/lib", "/lib", "/lib64"):
        if Path(path).exists():
            args += ["--ro-bind", path, path]
    args += ["--ro-bind", str(real), str(real)]
    if executable != real:
        args += ["--symlink", str(real), str(executable)]
    if Path(sys.prefix, "pyvenv.cfg").exists():
        path = str(Path(sys.prefix, "pyvenv.cfg"))
        args += ["--ro-bind", path, path]
    stdlib = sysconfig.get_path("stdlib")
    if not Path(stdlib).is_relative_to("/usr/lib"):
        args += ["--ro-bind", stdlib, stdlib]
    numpy_dir = Path(numpy.__file__).parent
    args += ["--ro-bind", str(numpy_dir), str(numpy_dir)]
    numpy_libs = numpy_dir.parent / "numpy.libs"
    if numpy_libs.exists():
        args += ["--ro-bind", str(numpy_libs), str(numpy_libs)]
    if Path("/etc/ld.so.cache").exists():
        args += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache"]
    args += ["--proc", "/proc", "--remount-ro", "/proc", "--dev", "/dev", "--remount-ro", "/dev",
             "--ro-bind", str(bundle), "/lab", "--bind", str(work), "/work",
             "--tmpfs", "/tmp", "--chdir", "/work", "--remount-ro", "/",
             str(executable), "-I", f"/lab/{entrypoint}", "/work", *map(str, arguments)]
    return args


def bundle_files(directory, worker, source, data):
    """Only worker, runtime, handshake helper, candidate and public inputs."""
    directory = Path(directory)
    directory.mkdir()
    files = {"worker.py": Path(worker).read_bytes(), "runtime.py": Path(__file__).with_name("runtime.py").read_bytes(),
             "sandbox.py": Path(__file__).read_bytes(), "trainer.py": source.encode(), "data.npz": Path(data).read_bytes()}
    for name, contents in files.items():
        (directory / name).write_bytes(contents)
    return {name: _hash(contents) for name, contents in sorted(files.items())}


def _write_probe(path, create=False):
    try:
        fd = os.open(path, os.O_WRONLY | (os.O_CREAT | os.O_EXCL if create else 0), 0o600)
    except OSError:
        return False
    else:
        os.close(fd)
        if create:
            os.unlink(path)
        return True


def _read_only(path):
    return os.path.isfile(path) and bool(os.statvfs(path).f_flag & os.ST_RDONLY) and not _write_probe(path)


def worker_handshake():
    """Runs before importing trainer.py. Parent verifies independently then sends GO."""
    request = json.loads(Path("/lab/isolation.json").read_text())
    limits = {name: list(resource.getrlimit(getattr(resource, name))) for name in request["limits"]}
    evidence = {"pid": os.getpid(), "namespaces": namespaces(), "home": os.environ.get("HOME"),
                "environment": {key: os.environ.get(key) for key in request["environment"]},
                "tmpdir": os.environ.get("TMPDIR"), "cwd": os.getcwd(),
                "work_writable": _write_probe("/work/.isolation-write-probe", True),
                "outside_write_denied": not _write_probe("/.isolation-write-probe", True),
                "runtime_read_only": all(_read_only(path) for path in request["runtime_paths"]),
                "bundle_read_only": all(_read_only(f"/lab/{name}") for name in request["bundle_hashes"]),
                "hidden_paths": [{"path": path, "visible": os.path.exists(path),
                                  "write_denied": not _write_probe(path)} for path in request["hidden_paths"]],
                "limits": limits,
                "bundle_hashes": {name: _hash(Path("/lab", name).read_bytes()) for name in request["bundle_hashes"]}}
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        evidence["parent_loopback_unreachable"] = probe.connect_ex(("127.0.0.1", request["probe_port"])) != 0
    print("ISOLATED " + json.dumps(evidence, sort_keys=True), flush=True)
    if sys.stdin.readline().strip() != "GO":
        raise RuntimeError("SANDBOX_VIOLATION: parent did not authorize execution")


def _descendants(pid):
    pending, found = [pid], set()
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        try:
            pending.extend(map(int, Path(f"/proc/{current}/task/{current}/children").read_text().split()))
        except (OSError, ValueError):
            pass
    return found


class Session:
    def __init__(self, proc, request, command_line):
        self.proc, self.request = proc, request
        self.evidence = {"validated": False, "timestamp": datetime.now(timezone.utc).isoformat(),
                         "backend": "bwrap", "filesystem_policy": POLICY, "command": command_line,
                         "active_limits": request["limits"],
                         "bundle_hashes": request["bundle_hashes"],
                         "bundle_sha256": _hash(json.dumps(request["bundle_hashes"], sort_keys=True).encode()),
                         "worker_sha256": request["bundle_hashes"]["worker.py"],
                         "candidate_sha256": request["bundle_hashes"]["trainer.py"]}

    def verify(self, channel, timeout):
        try:
            line = channel.recv(timeout)
        except (OSError, EOFError, TimeoutError) as exc:
            raise SandboxError("SANDBOX_UNAVAILABLE", "CPU worker isolation startup failed: " + str(exc)) from exc
        try:
            if not line.startswith("ISOLATED "):
                raise ValueError("Missing CPU isolation handshake: " + line[:200])
            report = json.loads(line[len("ISOLATED "):])
            checks = {name: report["namespaces"][name] != self.request["parent_namespaces"][name]
                      for name in NAMESPACES}
            worker_pid = None
            for pid in _descendants(self.proc.pid):
                try:
                    status = Path(f"/proc/{pid}/status").read_text()
                    inner_pid = next(int(line.split()[-1]) for line in status.splitlines()
                                     if line.startswith("NSpid:"))
                    if namespaces(pid) == report["namespaces"] and inner_pid == report["pid"]:
                        worker_pid = pid
                        break
                except (OSError, StopIteration, ValueError):
                    pass
            checks.update({"parent_observed_namespaces": worker_pid is not None,
                           "pid_isolated": 0 < report["pid"] <= 2,
                           "home": report["home"] == "/work", "tmpdir": report["tmpdir"] == "/tmp",
                           "cwd": report["cwd"] == "/work", "work_writable": report["work_writable"] is True,
                           "outside_write_denied": report["outside_write_denied"] is True,
                           "runtime_read_only": report["runtime_read_only"] is True,
                           "bundle_read_only": report["bundle_read_only"] is True,
                           "hidden_paths": report["hidden_paths"] == [
                               {"path": p, "visible": False, "write_denied": True} for p in self.request["hidden_paths"]],
                           "loopback_unreachable": report["parent_loopback_unreachable"] is True,
                           "rlimits": report["limits"] == self.request["limits"],
                           "environment": report["environment"] == self.request["environment"],
                           "bundle_hashes": report["bundle_hashes"] == self.request["bundle_hashes"]})
            self.evidence.update(handshake=report, checks=checks, worker_host_pid=worker_pid)
            if not all(checks.values()):
                raise ValueError("Isolation checks failed: " + str([k for k, value in checks.items() if not value]))
            self.evidence["validated"] = True
            channel.send("GO")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise SandboxError("SANDBOX_VIOLATION", str(exc)) from exc
        return self.evidence


def terminate(proc):
    if proc is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    finally:
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()


@contextmanager
def launch(bundle, work, hashes, limits, limiter, *, arguments=(), hidden_paths=()):
    """Owns process, local network probe and stderr descriptor on every exit."""
    cpu_s = int(limits["max_experiment_seconds"] + 10)
    import numpy
    request = {"parent_namespaces": namespaces(), "bundle_hashes": hashes,
               "environment": environment(limits.get("worker_threads", 1)),
               "runtime_paths": [str(Path(sys.executable).resolve()), numpy.__file__,
                                 str(Path(sysconfig.get_path("stdlib"), "os.py"))],
               "hidden_paths": list(map(str, hidden_paths)),
               "limits": rlimit_policy(limits)}
    proc = None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        probe.listen(1)
        request["probe_port"] = probe.getsockname()[1]
        (Path(bundle) / "isolation.json").write_text(json.dumps(request))
        for path in Path(bundle).iterdir():
            path.chmod(0o444)
        args = command(bundle, work, "worker.py", arguments)
        try:
            with (Path(work).parent / "stderr.txt").open("wb") as err:
                try:
                    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                            cwd=work, env=environment(limits.get("worker_threads", 1)),
                                            preexec_fn=limiter(limits["max_ram_mb"], cpu_s))
                except OSError as exc:
                    raise SandboxError("SANDBOX_UNAVAILABLE", str(exc)) from exc
                yield Session(proc, request, args)
        finally:
            terminate(proc)
