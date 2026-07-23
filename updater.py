"""
Claude-Code-style auto-update: never hot-swap a running process — always
apply + restart via os.execv, never a live in-place patch. Two call sites,
both idle-safe:
  - bridge.py's main(), the very first thing any invocation does, before
    any real work begins.
  - watch.py's long-running loop, once per UPDATE_CHECK_SECONDS, called
    right after touching the heartbeat and before checking for finished
    runs — i.e. only at an idle poll boundary, never mid-commit.
An earlier version of the watch-loop call only printed a "close and
relaunch to update" notice instead of actually applying it, on the
assumption a human would see and act on it — broken once launcher.py
started running this loop windowless (pythonw.exe, no console): the
notice went to watch.log, which nobody watches, so an already-running
background watcher would silently serve stale code indefinitely. Both
call sites now go through the same apply_update_if_available().

Hosting: GitHub Releases on a dedicated repo (this one). All persistent
Bridge state (token.dat, hint files, heartbeat, logs) lives under
%LOCALAPPDATA%\\VeroMassBridge — NOT inside this repo directory — so
overwriting this directory's contents during an update is safe by
construction, not by luck.
"""

import io
import os
import re
import sys
import zipfile

import requests

import version

REPO = os.environ.get("VEROMASS_BRIDGE_REPO", "falahamro-dotcom/veromass-bridge")
BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))

_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _parse_tag(tag):
    m = _TAG_RE.match(tag.strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def is_newer(tag, current=version.__version__):
    """True if `tag` (e.g. "v0.2.0") is a strictly newer version than
    `current` (e.g. "0.1.0"). Malformed tags are never considered newer —
    a bad tag on the release page must never trigger an update."""
    parsed_tag = _parse_tag(tag)
    parsed_current = _parse_tag(current)
    if parsed_tag is None or parsed_current is None:
        return False
    return parsed_tag > parsed_current


def get_latest_release():
    """Returns (tag, zipball_url) or None on ANY failure (network, bad
    JSON, no releases yet, whatever) — an update check must never raise
    and never block normal operation."""
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=5,
        )
        if not resp.ok:
            return None
        data = resp.json()
        tag = data.get("tag_name")
        zipball_url = data.get("zipball_url")
        if not tag or not zipball_url:
            return None
        return tag, zipball_url
    except Exception:
        return None


def apply_update_if_available():
    """Called once, as the very first thing bridge.py's main() does.
    Downloads and applies a newer release if one exists, then restarts
    this same process running the new code. Any failure at any step must
    fall through to running the CURRENT version — never block startup."""
    try:
        latest = get_latest_release()
        if latest is None:
            return
        tag, zipball_url = latest
        if not is_newer(tag):
            return

        print(f"Updating VeroMass Bridge to {tag}...")
        sys.stdout.flush()  # see the flush before execv below — applies here too
        resp = requests.get(zipball_url, timeout=30)
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            # GitHub zipballs wrap everything in one top-level
            # "<owner>-<repo>-<sha>/" folder — strip it so files land
            # directly in BRIDGE_DIR, not one level too deep.
            names = zf.namelist()
            if not names:
                return
            root_prefix = names[0].split("/")[0] + "/"
            for name in names:
                if not name.startswith(root_prefix) or name == root_prefix:
                    continue
                rel_path = name[len(root_prefix):]
                if not rel_path:
                    continue
                dest = os.path.join(BRIDGE_DIR, rel_path)
                if name.endswith("/"):
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(name) as src, open(dest, "wb") as out:
                        out.write(src.read())

        print(f"Updated to {tag} — restarting...")
        sys.stdout.flush()  # execv wipes this process's memory (buffered
        sys.stderr.flush()  # output included) before it's written — must
                             # flush explicitly or these messages vanish
                             # when stdout is piped/redirected (confirmed
                             # live: they were silently lost without this).
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as e:
        print(f"Update check failed ({e}) — continuing with the current version.")
