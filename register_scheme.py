"""
One-time setup: registers the veromass:// URI scheme for THIS Windows user
(HKEY_CURRENT_USER\\Software\\Classes\\veromass — no admin rights needed,
unlike HKEY_CLASSES_ROOT). After this, clicking a veromass://job?... link
in the browser (Workbench.jsx's "Process locally" button) launches either:

  Frozen (real distribution — VeroMass_Bridge.exe, built with PyInstaller
  --onefile --windowed):
    "<full path to VeroMass_Bridge.exe>" --scheme-launch "<url>"
  No Python interpreter reference at all — the exe IS the interpreter+app.

  Dev mode (running from a source checkout):
    "<pythonw.exe>" "<full path to bridge.py>" --scheme-launch "<url>"

Callable two ways:
  - `python bridge.py --register-scheme` (dev) or
    `VeroMass_Bridge.exe --register-scheme` (frozen, e.g. from an
    installer's post-install step) — bridge.py's argparse wires this up.
  - `python register_scheme.py` directly (dev only — the historical way,
    kept working unchanged).

Safe to re-run (idempotent — just overwrites the same keys/values).
"""

import sys
import os
import winreg

FROZEN = getattr(sys, "frozen", False)
BRIDGE_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge.py")


def _pythonw():
    """Dev-mode only. The windowless launcher living next to whatever
    python.exe ran this script — Windows invokes the registered command
    directly (there is no parent console to inherit), so registering
    python.exe here flashed a visible console on every "Process locally"
    click. pythonw.exe is a real, windowed-subsystem Python build: no
    console, but bridge.py's own Tkinter-launching code still works
    identically (see launcher.py, which made the same switch for
    launch_aligner()). Falls back to sys.executable if pythonw.exe is
    somehow missing next to it."""
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def register():
    if FROZEN:
        # sys.executable IS the real installed VeroMass_Bridge.exe when
        # frozen — no interpreter to reference separately, and no console
        # question at all: a --windowed build has none for any argument.
        command = f'"{sys.executable}" --scheme-launch "%1"'
    else:
        command = f'"{_pythonw()}" "{BRIDGE_PY}" --scheme-launch "%1"'

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\veromass") as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:VeroMass Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, r"Software\Classes\veromass\shell\open\command"
    ) as key:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)

    print("Registered veromass:// for this Windows user.")
    print(f"  Command: {command}")


def read_back():
    """Used by tests/verification — not called during normal registration."""
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Software\Classes\veromass\shell\open\command"
    ) as key:
        value, _ = winreg.QueryValueEx(key, "")
        return value


if __name__ == "__main__":
    register()
