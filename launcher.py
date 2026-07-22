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


def launch_aligner():
    """Detached launch of the real aligner GUI — keeps its own visible
    window (Tkinter needs a real console-capable process to reliably show
    one, so this uses python.exe, not pythonw.exe, unlike the watcher)."""
    subprocess.Popen(
        [sys.executable, ALIGNER_PY],
        cwd=ALIGNER_DIR,
        creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
        close_fds=True,
    )
