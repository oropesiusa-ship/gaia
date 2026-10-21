"""Campaign wall watchdog in the controller main thread, preserving cleanup handlers."""
from contextlib import contextmanager
import signal
import threading
from .policy import BudgetExceeded


@contextmanager
def wall_deadline(seconds):
    if threading.current_thread()is not threading.main_thread():raise ValueError('CONTROLLER_MAIN_THREAD_REQUIRED')
    previous=signal.getsignal(signal.SIGALRM);prior_timer=signal.getitimer(signal.ITIMER_REAL)
    if prior_timer[0]:raise ValueError('ACTIVE_PROCESS_TIMER_CONFLICT')
    def expire(signum,frame):raise BudgetExceeded('STOPPED_BUDGET')
    signal.signal(signal.SIGALRM,expire);signal.setitimer(signal.ITIMER_REAL,max(.001,seconds))
    try:yield
    finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
