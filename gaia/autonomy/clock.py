"""Clocks for budgets and telemetry: monotonic intervals within a boot, UTC for traceability, boot ID for restarts."""
from datetime import datetime,timezone
import resource
import time

BOOT_ID_PATH='/proc/sys/kernel/random/boot_id'


def boot_id():
    try:
        with open(BOOT_ID_PATH)as f:return f.read().strip()or None
    except OSError:return None


def cpu_seconds():
    """CPU time of this process and its finished children (user + system)."""
    own,children=resource.getrusage(resource.RUSAGE_SELF),resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime+own.ru_stime+children.ru_utime+children.ru_stime


def stamp():
    return {'utc':datetime.now(timezone.utc).isoformat(),'wall':time.time(),'monotonic':time.monotonic(),'boot_id':boot_id(),'cpu_s':cpu_seconds()}


def interval(a,b):
    """Seconds between two stamps: monotonic within one boot, wall across a reboot (flagged); never negative."""
    if a.get('boot_id')and a.get('boot_id')==b.get('boot_id'):return max(0.,b['monotonic']-a['monotonic']),False
    return max(0.,b['wall']-a['wall']),True


def elapsed(state,now=None):
    """Campaign elapsed time for budgets. Conservative: the larger of the wall and the same-boot monotonic interval,
    so a backwards wall-clock step can neither stop a campaign early nor extend its budget."""
    if state.get('started_at')is None:return 0.
    wall=(time.time()if now is None else now)-state['started_at']
    start=state.get('started_clock')
    if now is None and start and start.get('boot_id')and start['boot_id']==boot_id():return max(wall,time.monotonic()-start['monotonic'])
    return wall
