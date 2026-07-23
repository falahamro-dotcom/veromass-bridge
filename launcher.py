"""
Kills the last two manual steps in the "Process locally" flow: launching
the aligner GUI by hand, and keeping a terminal open running
`python bridge.py --watch`. Called from bridge.py's --scheme-launch —
after this, clicking the browser button is the only thing a scientist
ever has to do; everything else happens invisibly, the same way a
background agent works without someone babysitting a terminal.

Frozen vs. dev mode: this repo now ships as a real distributable, built
with PyInstaller (`--onefile --windowed`) into VeroMass_Bridge.exe, which
runs on a customer's machine with NO separate Python install required.
When frozen, `sys.frozen` is True and `sys.executable` IS the real
installed .exe (not python.exe) — its directory is the real install
folder a sibling VeroMass_Aligner.exe (built the same way) lives in
too. In dev mode (running `python bridge.py` from a source checkout),
neither of those is true, so this falls back to the original
python.exe + .py-script invocation and the VEROMASS_ALIGNER_DIR-
overridable dev path, exactly as before — nothing about local
development changed.
"""

import os
import subprocess
import sys
import time

import watch

FROZEN = getattr(sys, "frozen", False)

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_PY = os.path.join(BRIDGE_DIR, "bridge.py")


def _app_dir():
    """The real install folder — this exe's own directory when frozen,
    this repo's directory in dev mode. A sibling VeroMass_Aligner.exe
    (frozen) or the dev checkout (VEROMASS_ALIGNER_DIR) is expected here."""
    return os.path.dirname(sys.executable) if FROZEN else BRIDGE_DIR


def _child_env(extra=None):
    """Environment for a spawned child process — starts from this
    process's own os.environ (so PATH etc. carry over), but strips
    PyInstaller's internal _MEIPASS2 var. That var marks "onefile already
    extracted, reuse this temp dir" for the SAME running instance's own
    multiprocessing workers — inherited by an unrelated subprocess.Popen
    child (a fresh, independently-argsed launch of the same exe, not a
    multiprocessing fork), it makes the child try to reuse the parent's
    extraction directory instead of doing its own fresh one. Confirmed
    live: this is exactly what caused the frozen watcher/aligner children
    to crash with a DIFFERENT stdlib C-extension "module not found"
    error every run (select, then unicodedata, ...) — never in the
    parent process, only ever in a child spawned from within a running
    frozen parent. Stripping this one variable fixed it; every other
    env var still passes through unchanged."""
    env = dict(os.environ)
    env.pop("_MEIPASS2", None)
    if extra:
        env.update(extra)
    return env


# Dev-mode-only fallback — a real distribution never hits this branch,
# since ALIGNER_DIR is only read when NOT frozen (see launch_aligner).
_DEV_ALIGNER_DIR = os.environ.get(
    "VEROMASS_ALIGNER_DIR",
    r"C:\Users\Judie\Claude\Projects\MoleculeID\repos\veromass-aligner",
)

WATCH_LOG_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "VeroMassBridge", "watch.log",
)

HEARTBEAT_STALE_SECONDS = 10  # comfortably more than watch.POLL_SECONDS (2s)

# Detached: outlives this process. Dev mode combines DETACHED_PROCESS with
# CREATE_NO_WINDOW (pythonw.exe running bridge.py — no console either way,
# this is belt-and-suspenders). Frozen: DETACHED_PROCESS ONLY — verified
# live that adding CREATE_NO_WINDOW here breaks a --windowed-built onefile
# PyInstaller exe spawning ANOTHER instance of itself: the child's own
# bootstrap corrupts partway through extraction, surfacing as a random
# stdlib C-extension "module not found" (select, unicodedata, a different
# one each time) deep in an unrelated import chain — never in the parent
# invocation, only ever in this specific detached-child spawn. A
# --windowed exe never has a console for any argument combination
# regardless, so CREATE_NO_WINDOW was always redundant here; removing it
# for the frozen case fixed the crash (heartbeat file confirmed updating
# in real time after the fix, none of it before).
_DETACHED_NO_WINDOW = (
    (subprocess.DETACHED_PROCESS
     if getattr(sys, "frozen", False)
     else subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
    if sys.platform == "win32" else 0
)


def _pythonw():
    """Dev-mode only. The windowless launcher living next to whatever
    python.exe is running this — falls back to sys.executable if it's
    somehow missing (still works, just not console-free). Not used when
    frozen — a --windowed-built exe has no console for ANY argument
    combination, so there's no python.exe/pythonw.exe distinction left
    to make once distributed."""
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def is_watcher_alive():
    """A --watch loop touches watch.HEARTBEAT_PATH once per poll — alive
    means that file exists and was touched recently, not a fragile
    PID-liveness check."""
    path = watch.HEARTBEAT_PATH
    if not os.path.exists(path):
        return False
    return (time.time() - os.path.getmtime(path)) < HEARTBEAT_STALE_SECONDS


def spawn_background_watcher():
    """Detached, windowless `--watch` instance — output goes to watch.log
    since there's no console to print to. Frozen: re-launches the SAME
    installed exe (sys.executable) with --watch, since a --windowed build
    has no console for any argument combination — no separate
    python.exe/pythonw.exe needed at all. Dev mode: unchanged, python.exe
    running bridge.py directly."""
    os.makedirs(os.path.dirname(WATCH_LOG_PATH), exist_ok=True)
    log = open(WATCH_LOG_PATH, "a")
    cmd = [sys.executable, "--watch"] if FROZEN else [_pythonw(), BRIDGE_PY, "--watch"]
    subprocess.Popen(
        cmd,
        cwd=_app_dir(),
        env=_child_env(),
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        creationflags=_DETACHED_NO_WINDOW,
        close_fds=True,
    )


def launch_aligner(workbench_name=None, job_name=None, workbench_id=None, job_id=None, output_dir=None):
    """Detached launch of the real aligner GUI. Frozen: runs the sibling
    VeroMass_Aligner.exe directly, no interpreter involved at all. Dev
    mode: pythonw.exe — a real, windowed-subsystem Python build meant
    exactly for this: no console attached, but Tkinter's own GUI window
    still renders normally, since Tkinter draws its own window rather
    than needing a console. (An earlier version used python.exe here on
    the mistaken assumption pythonw.exe wouldn't reliably show the GUI —
    that flashed a console window on every "Process locally" click,
    fixed once this was confirmed live on a real machine.)

    workbench_name/job_name/*_id (all optional): the exact name/id the
    scientist already sees in app.veromass.com for the job this launch is
    pre-stamped for — passed through env vars so VeroMass_Aligner.py can
    show "linked to" in its own title/header, making the desktop run
    visibly the same job the browser is waiting on, not just silently
    linked by a UUID underneath (the commit path already guarantees that
    part via the pending-hint match in jobs.py/watch.py)."""
    extra = {}
    if workbench_name:
        extra["VEROMASS_WORKBENCH_NAME"] = workbench_name
    if job_name:
        extra["VEROMASS_JOB_NAME"] = job_name
    if workbench_id:
        extra["VEROMASS_WORKBENCH_ID"] = workbench_id
    if job_id:
        extra["VEROMASS_JOB_ID"] = job_id
    if output_dir:
        extra["VEROMASS_OUTPUT_DIR"] = output_dir
    # VeroMass_Aligner.exe is its own separate frozen onefile build (not a
    # multiprocessing child of THIS one), so it must do its own fresh
    # extraction — _child_env() strips the parent's _MEIPASS2, same fix as
    # spawn_background_watcher's below.
    env = _child_env(extra)

    if FROZEN:
        cmd = [os.path.join(_app_dir(), "VeroMass_Aligner.exe")]
        cwd = _app_dir()
    else:
        cmd = [_pythonw(), os.path.join(_DEV_ALIGNER_DIR, "VeroMass_Aligner.py")]
        cwd = _DEV_ALIGNER_DIR

    subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
        close_fds=True,
    )
