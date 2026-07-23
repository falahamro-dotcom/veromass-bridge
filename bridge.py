"""
VeroMass Bridge — Phase 1 MVP spike entry point.

Three ways to run:
  python bridge.py --job <job_id> --mode targeted --xlsx <path>
      Manual, one-shot — you already know the job_id (e.g. for testing).
  python bridge.py --watch [--dir <path>]
      Watches a handoff folder for veromass-aligner's .ready marker and
      auto-matches finished output to a pending Job. Checks for a
      pre-stamped pending-job hint first (see --scheme-launch below); falls
      back to polling for jobs in status=="waiting_for_desktop" only when
      no hint is present (jobs.py, watch.py — see README.md).
  python bridge.py --scheme-launch <veromass://job?workbench=X&job=Y>
      Not meant to be typed by hand — this is what a registered
      veromass:// URL launches (see register_scheme.py and
      moleculeid-web/Workbench.jsx's "Process locally" button). Parses the
      real workbench_id/job_id the browser already knows, writes them as a
      pending-job hint for the next --watch run to pick up, THEN (see
      launcher.py) launches the real aligner GUI and makes sure a --watch
      loop is already running in the background — starting one silently if
      not. Clicking "Process locally" in the browser is meant to be the
      only thing a scientist ever has to do; everything else here happens
      invisibly, the same way a background agent works unattended.

Every invocation (any mode above) first checks GitHub Releases for a newer
version and, if found, downloads + applies it + restarts itself running the
new code BEFORE doing anything else (updater.py) — relaunching is what
performs an update, never a silent hot-swap of an already-running process.

--workbench is optional in the manual path (never sent to the API — the
commit call only needs --job) and is now purely informational: Workbench.jsx
(moleculeid-web) polls its own already-open tab and auto-refreshes once a
commit lands, so process_one() no longer opens a browser tab itself — an
earlier version did, which meant a redundant second tab/window popped up on
every commit even when app.veromass.com was already open and about to show
the same result on its own.
"""

import argparse
import os
import sys
import urllib.parse
import uuid

import auth
import api_client
import jobs
import mapping


def _is_uuid(s):
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def parse_scheme_url(url):
    """veromass://job?workbench=<uuid>&job=<uuid> -> (workbench_id, job_id).
    Raises ValueError with a clear message on anything malformed — never
    silently proceed with a bad ID."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "veromass":
        raise ValueError(f"Not a veromass:// URL: {url!r}")
    params = urllib.parse.parse_qs(parsed.query)
    workbench_id = (params.get("workbench") or [None])[0]
    job_id = (params.get("job") or [None])[0]
    if not workbench_id or not job_id:
        raise ValueError(f"Missing workbench or job param in: {url!r}")
    if not (_is_uuid(workbench_id) and _is_uuid(job_id)):
        raise ValueError(f"workbench/job must be UUIDs, got: {workbench_id!r}, {job_id!r}")
    return workbench_id, job_id


def process_one(job_id, mode, xlsx_path, access_token, workbench_id=None):
    """Map + commit one finished aligner workbook against one Job. Shared by
    both the manual --job path and the watch loop (watch.py) — the commit
    logic must only ever exist once.

    Does NOT open a browser tab on completion. For the "Process locally"
    flow, the scientist's own click on that link is what opened
    app.veromass.com in the first place — Workbench.jsx now polls and
    auto-refreshes that already-open tab once the commit lands (see
    moleculeid-web), and "Remind me when done" covers the case where
    they've since switched away from it. An earlier version of this
    function called webbrowser.open() here unconditionally, which meant a
    NEW tab/window popped up on every single commit on top of the one
    already open and about to show the same result on its own — removed as
    redundant, not as a regression."""
    print(f"Mapping {xlsx_path} for a {mode} job...")
    mode_body = mapping.build_commit_payload(xlsx_path, mode)
    n = len(mode_body.get("features") or mode_body.get("feature_matrix") or [])
    print(f"  -> {n} {'features' if mode == 'targeted' else 'matrix rows'}")

    package_uuid = str(uuid.uuid4())
    print(f"Committing job {job_id} (package_uuid={package_uuid})...")
    result = api_client.commit_job(job_id, package_uuid, mode_body, access_token)
    print(f"  -> status: {result.get('status')}")
    return result


def _ensure_stdio():
    """The registered veromass:// protocol handler (register_scheme.py) now
    invokes pythonw.exe so clicking "Process locally" doesn't flash a
    console window — but under pythonw.exe, sys.stdout/stderr are None, and
    every print() in this file would crash with AttributeError. Redirect to
    a log file in that case, same convention as launcher.py's watch.log. A
    normal console invocation (python.exe — manual --job/--watch use) is
    untouched, since sys.stdout is a real stream there."""
    if sys.stdout is None or sys.stderr is None:
        log_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "VeroMassBridge"
        )
        os.makedirs(log_dir, exist_ok=True)
        log = open(os.path.join(log_dir, "scheme_launch.log"), "a", buffering=1)
        sys.stdout = log
        sys.stderr = log


def main():
    _ensure_stdio()

    import updater
    updater.apply_update_if_available()  # relaunch-to-update: see updater.py

    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true",
                         help="watch a handoff folder instead of processing one file")
    parser.add_argument("--dir", default=None,
                         help="handoff folder to watch (only with --watch); "
                              "defaults to %%LOCALAPPDATA%%\\VeroMassBridge\\incoming")
    parser.add_argument("--scheme-launch", default=None, metavar="URL",
                         help="internal — invoked by the registered veromass:// "
                              "protocol handler (register_scheme.py), not typed by hand")
    parser.add_argument("--workbench", required=False, default=None,
                         help="workbench_id from the browser (optional — only used to "
                              "annotate the closing message, never sent to the API)")
    parser.add_argument("--job", required=False, help="job_id from the browser")
    parser.add_argument("--mode", required=False, choices=["targeted", "untargeted"])
    parser.add_argument("--xlsx", required=False, help="path to aligned_features.xlsx")
    args = parser.parse_args()

    if args.scheme_launch:
        try:
            workbench_id, job_id = parse_scheme_url(args.scheme_launch)
        except ValueError as e:
            print(f"Ignoring malformed veromass:// launch: {e}")
            return
        jobs.write_pending_hint(workbench_id, job_id)
        print(f"Job {job_id} pre-stamped — the next finished aligner run "
              f"will be matched to it automatically.")

        # Best-effort: fetch the real names the scientist sees in the
        # browser so the aligner GUI can show "linked to <name>" instead of
        # just launching blind. Never blocks the launch on failure (a
        # transient auth/network hiccup here shouldn't stop the aligner
        # from opening) — falls back to no name shown, IDs still work.
        workbench_name = job_name = None
        try:
            access_token = auth.get_access_token()
            workbench_name = api_client.get_workbench(workbench_id, access_token).get("name")
            job_name = api_client.get_job(job_id, access_token).get("name")
        except Exception as e:
            print(f"Could not fetch workbench/job name for display (non-fatal): {e}")

        # Pre-fill the aligner's output folder with a per-job subfolder of
        # the Bridge's own watched folder (watch.py's DEFAULT_DIR) so the
        # scientist never has to know/type that path for "Process locally"
        # to work — the folder-requirement question a user asked about
        # directly. A per-job subfolder (not the watched folder's own top
        # level) uses watch.py's primary, more-robust detection path rather
        # than its top-level fallback, and can't collide with another
        # job's run. Manual (`--job`/`--xlsx`) runs are unaffected — this
        # only applies to the scheme-launch flow.
        import watch
        output_dir = os.path.join(watch.DEFAULT_DIR, job_id)

        import launcher
        launcher.launch_aligner(
            workbench_name=workbench_name, job_name=job_name,
            workbench_id=workbench_id, job_id=job_id,
            output_dir=output_dir,
        )
        print("Launched the VeroMass Aligner.")

        if launcher.is_watcher_alive():
            print("A Bridge watcher is already running in the background.")
        else:
            launcher.spawn_background_watcher()
            print("Started a Bridge watcher in the background "
                  f"(log: {launcher.WATCH_LOG_PATH}).")
        return

    if args.watch:
        import watch
        print("Authenticating...")
        auth.get_access_token()  # surface any login prompt now, up front
        watch.run(args.dir, auth.get_access_token, process_one)
        return

    if not (args.job and args.mode and args.xlsx):
        parser.error("--job, --mode, and --xlsx are required unless --watch is given")

    print("Authenticating...")
    access_token = auth.get_access_token()
    process_one(args.job, args.mode, args.xlsx, access_token, workbench_id=args.workbench)


if __name__ == "__main__":
    main()
