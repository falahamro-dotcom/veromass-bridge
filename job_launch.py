"""
Shared "launch a job for local processing" logic — invoked from TWO places:
  1. bridge.py's --scheme-launch (the OS-level veromass:// handoff — kept
     as a legacy path, still works for anyone whose registration is intact)
  2. log_server.py's POST /launch (the NEW, reliable HTTP-based handoff —
     see moleculeid-web/Workbench.jsx's pre-flight GET /health check + a
     real "Process locally" button that POSTs here and shows the actual
     result, replacing the old bare veromass:// link. A real user hit
     "clicked it, nothing happened" with zero feedback and no way to even
     tell whether Bridge was installed — the browser gives NO error for an
     unregistered custom URL scheme. HTTP gives a real response either way.)

One implementation, so the two invocation paths can never drift apart.
"""
import os

import auth
import api_client
import jobs
import launcher
import watch


def launch_job(workbench_id, job_id):
    """Pre-stamp `job_id` as pending, launch the aligner GUI linked to it,
    and make sure a --watch loop is running. Returns a small result dict
    with display info; never raises for expected failure modes (network/
    auth hiccups fetching display names are non-fatal, same as the
    original bridge.py behavior) — only propagates a truly unexpected
    error (e.g. the aligner exe itself is missing), which callers turn
    into a real error response instead of a silent success."""
    jobs.write_pending_hint(workbench_id, job_id)

    workbench_name = job_name = None
    try:
        access_token = auth.get_access_token()
        workbench_name = api_client.get_workbench(workbench_id, access_token).get("name")
        job_name = api_client.get_job(job_id, access_token).get("name")
    except Exception as e:
        print(f"Could not fetch workbench/job name for display (non-fatal): {e}")

    # Same per-job subfolder convention as the original --scheme-launch
    # handling: uses watch.py's primary detection path, can't collide with
    # another job's run, and the scientist never has to know/type a path.
    output_dir = os.path.join(watch.DEFAULT_DIR, job_id)
    launcher.launch_aligner(
        workbench_name=workbench_name, job_name=job_name,
        workbench_id=workbench_id, job_id=job_id,
        output_dir=output_dir,
    )

    watcher_started = False
    if not launcher.is_watcher_alive():
        launcher.spawn_background_watcher()
        watcher_started = True

    return {
        "workbench_name": workbench_name,
        "job_name": job_name,
        "watcher_started": watcher_started,
    }
