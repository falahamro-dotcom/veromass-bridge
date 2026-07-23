"""
Watches a handoff folder for veromass-aligner's .ready marker
(VeroMass_Aligner.py, written atomically right after the Excel output is
fully written) and auto-matches each finished run to a pending Job via
jobs.py, instead of requiring a manually-typed --job.

Matching precedence: a pending-job HINT (written by bridge.py's
--scheme-launch, from the browser's "Process locally" button) is checked
FIRST and consumed exactly once — real pre-stamped IDs, zero ambiguity.
Only falls back to the poll-based "guess which job is waiting" heuristic
(jobs.match_one_pending_job) when no hint is present.

Two supported layouts under <watch_dir> — a scientist will naturally do
either, so both are handled rather than requiring one:
    <watch_dir>/<run-name>/aligned_features.xlsx + .ready   (a per-run subfolder)
    <watch_dir>/aligned_features.xlsx + .ready              (aligner's output
                                                              folder pointed
                                                              straight at
                                                              <watch_dir> itself)

Once a run is handled (committed or given up on), its `.ready` marker is
renamed to `.done` or `.failed` FIRST — a small, never-locked rename — so a
restarted Bridge never reprocesses it, before attempting best-effort
archiving into `processed/`/`failed/` (moves the whole subfolder for the
first layout; moves just that run's own files for the second, since
<watch_dir> itself can't be moved — it's what's being watched). Windows can
still hold aligned_features.xlsx open briefly after the aligner GUI exits,
and a locked file must never crash the loop or cause a re-commit — the
marker rename is what actually prevents reprocessing, archiving is cleanup.
"""

import os
import shutil
import time

import jobs
import log_server
import updater

POLL_SECONDS = 2
UPDATE_CHECK_SECONDS = 15 * 60  # coarse — not worth checking every 2s poll
DEFAULT_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "VeroMassBridge", "incoming",
)

# Touched once per poll iteration so launcher.py can tell "a --watch loop is
# alive" from "the last one crashed/was closed" without fragile PID checks.
HEARTBEAT_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "VeroMassBridge", "watch.heartbeat",
)


def _touch_heartbeat():
    os.makedirs(os.path.dirname(HEARTBEAT_PATH), exist_ok=True)
    with open(HEARTBEAT_PATH, "w") as f:
        f.write(str(time.time()))


def _looks_like_auth_error(exc):
    """api_client.py's RuntimeError messages are "<status>: <detail>" —
    a 401 here means the token went stale, which is retriable (once
    refreshed), not a genuine commit failure to give up on."""
    return "401" in str(exc)


_ARCHIVE_SUBFOLDERS = ("processed", "failed")


def _find_ready_runs(watch_dir):
    """Returns run directories with a .ready marker — either immediate
    subfolders of watch_dir (the recommended layout), or watch_dir itself
    (when the aligner's output folder was pointed straight at the watched
    folder rather than a subfolder inside it — a natural thing to do,
    handled rather than treated as user error)."""
    if not os.path.isdir(watch_dir):
        return []
    runs = []
    if os.path.exists(os.path.join(watch_dir, ".ready")):
        runs.append(watch_dir)
    for name in os.listdir(watch_dir):
        if name in _ARCHIVE_SUBFOLDERS:
            continue
        path = os.path.join(watch_dir, name)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, ".ready")):
            runs.append(path)
    return runs


def _find_xlsx(run_dir):
    for name in os.listdir(run_dir):
        if name.lower().endswith(".xlsx"):
            return os.path.join(run_dir, name)
    return None


def _mark(run_dir, suffix):
    """Rename .ready -> .done/.failed. This is the actual "don't reprocess"
    signal — a small marker file, never locked by Windows the way the
    xlsx workbook can briefly be right after the aligner GUI exits."""
    os.replace(os.path.join(run_dir, ".ready"), os.path.join(run_dir, suffix))


def _archive_best_effort(watch_dir, run_dir, subfolder):
    """Best-effort cleanup only — the marker rename above already prevents
    reprocessing, so a locked file here must just warn, never crash or
    trigger a retry/re-commit."""
    if os.path.normpath(run_dir) == os.path.normpath(watch_dir):
        _archive_top_level_files(watch_dir, subfolder)
        return

    dest = os.path.join(watch_dir, subfolder, os.path.basename(run_dir))
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(run_dir, dest)
        print(f"  Moved to {dest}")
    except OSError as e:
        print(f"  Note: couldn't archive {run_dir} to {subfolder}/ ({e}) — "
              f"already marked so it won't be reprocessed; safe to move by "
              f"hand once Windows releases the file.")


def _archive_top_level_files(watch_dir, subfolder):
    """When the aligner's output folder IS the watched folder itself, there
    is no per-run subfolder to move — watch_dir can't be moved, it's what's
    being watched. Instead move just this run's own files (the renamed
    marker, the xlsx, the log, etc.) into a freshly-named subfolder."""
    dest = os.path.join(watch_dir, subfolder, f"run-{int(time.time())}")
    try:
        os.makedirs(dest, exist_ok=True)
        moved = 0
        for name in os.listdir(watch_dir):
            if name in _ARCHIVE_SUBFOLDERS:
                continue
            src = os.path.join(watch_dir, name)
            if os.path.isfile(src):
                shutil.move(src, os.path.join(dest, name))
                moved += 1
        print(f"  Moved {moved} file(s) to {dest}")
    except OSError as e:
        print(f"  Note: couldn't archive this run's files ({e}) — already "
              f"marked so it won't be reprocessed; safe to move by hand "
              f"once Windows releases the file.")


def run(watch_dir, get_access_token, process_one):
    """Poll indefinitely. `process_one` is bridge.process_one, passed in
    rather than imported at module load, so watch.py has no import-time
    dependency on bridge.py (bridge.py imports watch.py, not the reverse).

    `get_access_token` is a zero-arg callable (auth.get_access_token), NOT
    a fixed token string — this loop is meant to run for hours in the
    background (launcher.py's whole point), and a Supabase access token
    lives ~1h. Calling it fresh each iteration lets auth.py's own
    cache/refresh logic silently renew it; a real crash was observed live
    when a fixed token went stale mid-run and an uncaught 401 killed the
    entire loop — never fetch it once and hold onto it."""
    watch_dir = watch_dir or DEFAULT_DIR
    os.makedirs(watch_dir, exist_ok=True)
    print(f"Watching {watch_dir} for finished aligner runs (Ctrl+C to stop)...")

    # Best-effort local log server so app.veromass.com can show the
    # aligner's live log for a running job — never allowed to affect the
    # actual watch loop below if it fails to start for any reason.
    try:
        log_server.start_in_background(watch_dir)
    except Exception as e:
        print(f"  Note: local log server did not start ({e}) — live log "
              f"tailing in the browser won't be available this run.")

    # Set whenever an API call fails this iteration — forces a real refresh
    # attempt next time instead of trusting the same (possibly wrong) local
    # expiry math that produced the bad token in the first place.
    force_refresh = False
    last_update_check = 0.0

    while True:
        _touch_heartbeat()

        if time.time() - last_update_check > UPDATE_CHECK_SECONDS:
            last_update_check = time.time()
            # Was updater.check_for_update_notice() — print-only, meant for
            # a human to read "close and relaunch to update" and act on it.
            # Now that launcher.py starts this loop windowless (pythonw.exe,
            # no console — see the console-flash fix), that notice only
            # ever reached watch.log, which nobody watches; a background
            # watcher would silently run stale code forever, exactly what
            # happened live: log_server.py/name-linking/output-dir-autofill
            # all shipped in later releases while an already-running
            # watcher from before those releases kept serving old code,
            # since nothing ever told IT to restart. apply_update_if_available()
            # actually applies + os.execv-restarts the process when a newer
            # release exists — called here, right after touching the
            # heartbeat and before _find_ready_runs() below, i.e. only at an
            # idle poll boundary with no run in progress, so this can never
            # interrupt an in-progress commit.
            updater.apply_update_if_available()

        try:
            access_token = get_access_token(force_refresh=force_refresh)
            force_refresh = False
        except Exception as e:
            print(f"  Couldn't refresh access token this poll ({e}) — retrying next poll.")
            force_refresh = True
            time.sleep(POLL_SECONDS)
            continue

        for run_dir in _find_ready_runs(watch_dir):
            xlsx_path = _find_xlsx(run_dir)
            if not xlsx_path:
                print(f"  {run_dir}: .ready marker present but no .xlsx found — skipping")
                continue

            print(f"Detected finished run: {run_dir}")

            hint = jobs.peek_pending_hint()
            if hint is not None:
                workbench_id, job_id = hint
                try:
                    match = jobs.resolve_hint(workbench_id, job_id, access_token)
                    jobs.consume_pending_hint()
                    print(f"  Pre-stamped job found (via 'Process locally') — "
                          f"no ambiguity check needed: {job_id}")
                except Exception as e:
                    # Leave the hint in place — could be a transient auth
                    # glitch, not proof the hint itself is bad. Falls back
                    # to the poll heuristic for THIS run; the hint stays
                    # available for the next poll to retry with a fresh token.
                    print(f"  Pending hint pointed at job {job_id}, but "
                          f"couldn't be resolved right now ({e}) — falling "
                          f"back to the poll-based match instead; the hint "
                          f"is kept for the next poll to retry.")
                    force_refresh = True
                    match = None
            else:
                match = None

            if match is None:
                try:
                    match = jobs.match_one_pending_job(access_token)
                except jobs.AmbiguousJobError as e:
                    print(f"  {e}\n  Leaving this run for the next poll — resolve the "
                          f"ambiguity above, then it will be picked up automatically.")
                    continue
                except Exception as e:
                    # Any other failure while checking for a pending job
                    # (network hiccup, transient API error, etc.) must not
                    # crash a loop meant to run unattended for hours —
                    # leave this run for the next poll instead.
                    print(f"  Couldn't check for a pending job this poll ({e}) — "
                          f"leaving this run for the next poll.")
                    force_refresh = True
                    continue

            if match is None:
                print("  No job is currently waiting for the desktop — "
                      "create one at app.veromass.com/workbench, then it will "
                      "be picked up on the next poll.")
                continue

            workbench, job = match
            try:
                process_one(job["id"], job["mode"], xlsx_path, access_token,
                            workbench_id=workbench["id"])
            except Exception as e:
                if _looks_like_auth_error(e):
                    # Don't give up permanently on a run that could well
                    # succeed with a fresh token — leave it for the next
                    # poll instead of archiving it as a genuine failure.
                    print(f"  Commit failed with what looks like a stale "
                          f"token ({e}) — retrying next poll instead of "
                          f"giving up.")
                    force_refresh = True
                    continue
                # A genuine commit failure (e.g. a misconfigured workbench)
                # must never take down the whole watch loop — it has to
                # keep running for whatever the scientist runs next.
                print(f"  Commit failed, marking as failed instead of "
                      f"retrying forever: {e}")
                _mark(run_dir, ".failed")
                _archive_best_effort(watch_dir, run_dir, "failed")
                continue

            _mark(run_dir, ".done")
            _archive_best_effort(watch_dir, run_dir, "processed")

        time.sleep(POLL_SECONDS)
