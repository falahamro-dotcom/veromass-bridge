"""
Kills the last two manual steps in the "Process locally" flow: launching
the aligner GUI by hand, and keeping a terminal open running
`python bridge.py --watch`. Called from bridge.py's --scheme-launch —
after this, clicking the browser button is the only thing a scientist
ever has to do; everything else happens invisibly, the same way a
background agent works without someone babysitting a terminal.

Portability note: ALIGNER_DIR below is hardcoded to this machine's real
path (overridable via VEROMASS_ALIGNER_DIR) — this is still a spike, not
an installer that knows where it put things on someone else's machine.
"""

import os
import subprocess
import sys
import time

import watch

ALIGNER_DIR = os.environ.get(
    "VEROMASS_ALIGNER_DIR",
    r"C:\Users\Judie\Claude\Projects\MoleculeID\repos\veromass-aligner",
)
ALIGNER_PY = os.path.join(ALIGNER_DIR, "VeroMass_Aligner.py")

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIDGE_PY = os.path.join(BRIDGE_DIR, "bridge.py")

WATCH_LOG_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "VeroMassBridge", "watch.log",
)

HEARTBEAT_STALE_SECONDS = 10  # comfortably more than watch.POLL_SECONDS (2s)

# Detached: outlives this process. No console window at all (for the
# background watcher — the aligner keeps its own window, that's the point).
_DETACHED_NO_WINDOW = (
    subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    if sys.platform == "win32" else 0
)


def _pythonw():
    """The windowless launcher living next to whatever python.exe is
    running this — falls back to sys.executable if it's somehow missing
    (still works, just not console-free)."""
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
    """Detached, windowless `python bridge.py --watch` — output goes to
    watch.log since there's no console to print to."""
    os.makedirs(os.path.dirname(WATCH_LOG_PATH), exist_ok=True)
    log = open(WATCH_LOG_PATH, "a")
    subprocess.Popen(
        [_pythonw(), BRIDGE_PY, "--watch"],
        cwd=BRIDGE_DIR,
        stdout=log, stderr=subprocess.STDOUT,
        creationflags=_DETACHED_NO_WINDOW,
        close_fds=True,
    )


def launch_aligner(workbench_name=None, job_name=None, workbench_id=None, job_id=None):
    """Detached launch of the real aligner GUI. Uses pythonw.exe — a real,
    windowed-subsystem Python build meant exactly for this: it has no
    console attached, but Tkinter's own GUI window still renders normally,
    since Tkinter draws its own window rather than needing a console. The
    earlier version used python.exe (console-attached) here on the mistaken
    assumption pythonw.exe wouldn't reliably show the GUI — that flashed a
    console window on every "Process locally" click. Confirmed on this real
    machine that pythonw.exe exists alongside python.exe before switching.

    workbench_name/job_name/*_id (all optional): the exact name/id the
    scientist already sees in app.veromass.com for the job this launch is
    pre-stamped for — passed through env vars so VeroMass_Aligner.py can
    show "linked to" in its own title/header, making the desktop run
    visibly the same job the browser is waiting on, not just silently
    linked by a UUID underneath (the commit path already guarantees that
    part via the pending-hint match in jobs.py/watch.py)."""
    env = dict(os.environ)
    if workbench_name:
        env["VEROMASS_WORKBENCH_NAME"] = workbench_name
    if job_name:
        env["VEROMASS_JOB_NAME"] = job_name
    if workbench_id:
        env["VEROMASS_WORKBENCH_ID"] = workbench_id
    if job_id:
        env["VEROMASS_JOB_ID"] = job_id

    subprocess.Popen(
        [_pythonw(), ALIGNER_PY],
        cwd=ALIGNER_DIR,
        env=env,
        creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
        close_fds=True,
    )
