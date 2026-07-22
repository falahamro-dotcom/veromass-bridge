"""
Finds which real Job a finished aligner output belongs to.

Two ways, checked in this order by watch.py:
  1. A pending-job HINT — real pre-stamped IDs written by
     bridge.py's --scheme-launch (browser's "Process locally" button opens
     veromass://job?workbench=X&job=Y, which the registered scheme handler
     turns into a --scheme-launch call). No ambiguity possible: the
     scientist told us exactly which job before the aligner even ran, per
     the architecture doc's real design.
  2. The poll-based fallback (list_pending_jobs/match_one_pending_job) —
     loops the already-working GET /api/workbenches and
     GET /api/workbenches/{id}/jobs, filtering to status ==
     "waiting_for_desktop". Used when no hint is present (a scientist who
     ran the aligner without clicking "Process locally" first) — still
     refuses to guess if more than one job is pending.
"""

import json
import os
import time

import api_client

PENDING_STATUS = "waiting_for_desktop"
HINT_MAX_AGE_SECONDS = 3600  # a stale hint from an abandoned job must not
                              # silently attach to some unrelated later run

HINT_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "VeroMassBridge", "pending_hint.json",
)


def write_pending_hint(workbench_id, job_id):
    """Called by bridge.py's --scheme-launch, right after parsing a real
    veromass://job?workbench=...&job=... URL."""
    os.makedirs(os.path.dirname(HINT_PATH), exist_ok=True)
    with open(HINT_PATH, "w") as f:
        json.dump({
            "workbench_id": workbench_id,
            "job_id": job_id,
            "written_at": time.time(),
        }, f)


def peek_pending_hint():
    """Returns (workbench_id, job_id) or None — does NOT delete the hint.
    An expired hint IS deleted here (it can never be validly retried), but
    a hint that's still fresh is left in place until consume_pending_hint()
    confirms it was actually used. This split exists because a transient
    failure while resolving the hint (e.g. an access-token refresh glitch,
    observed live) must not permanently lose a real pre-stamped match —
    only a hint that's genuinely used or genuinely expired should ever be
    thrown away."""
    if not os.path.exists(HINT_PATH):
        return None
    with open(HINT_PATH) as f:
        hint = json.load(f)

    age = time.time() - hint.get("written_at", 0)
    if age > HINT_MAX_AGE_SECONDS:
        os.remove(HINT_PATH)
        return None
    return hint["workbench_id"], hint["job_id"]


def consume_pending_hint():
    """Call once a peeked hint has actually been used (or definitively
    can't ever be, e.g. the job/workbench no longer exists) — never on a
    merely transient failure, or a real match gets thrown away for good."""
    if os.path.exists(HINT_PATH):
        os.remove(HINT_PATH)


def resolve_hint(workbench_id, job_id, access_token):
    """Fetch the real workbench/job dicts for a hint, in the same
    (workbench, job) shape match_one_pending_job returns."""
    workbench = api_client.get_workbench(workbench_id, access_token)
    job = api_client.get_job(job_id, access_token)
    return workbench, job


def list_pending_jobs(access_token, mode=None):
    """Returns [(workbench_dict, job_dict), ...] for every job still waiting
    on the desktop, optionally filtered to a specific mode."""
    pending = []
    for workbench in api_client.list_workbenches(access_token):
        jobs = api_client.list_jobs_for_workbench(workbench["id"], access_token)
        for job in jobs:
            if job.get("status") != PENDING_STATUS:
                continue
            if mode is not None and job.get("mode") != mode:
                continue
            pending.append((workbench, job))
    return pending


class AmbiguousJobError(RuntimeError):
    """More than one pending job matched — refuse to guess which one a
    finished file belongs to. Silently picking wrong would attach real
    results to the wrong study."""

    def __init__(self, candidates):
        self.candidates = candidates
        lines = [
            f"  - workbench '{w['name']}' ({w['id']}) / job "
            f"'{j.get('name') or j['id']}' ({j['id']}, mode={j['mode']})"
            for w, j in candidates
        ]
        super().__init__(
            "Multiple jobs are waiting for the desktop — can't tell which one "
            "this file belongs to:\n" + "\n".join(lines) +
            "\nFinish or cancel the others, or re-run with an explicit --job."
        )


def match_one_pending_job(access_token):
    """Zero pending -> returns None (caller should keep polling).
    Exactly one -> returns (workbench, job).
    More than one -> raises AmbiguousJobError."""
    pending = list_pending_jobs(access_token)
    if not pending:
        return None
    if len(pending) > 1:
        raise AmbiguousJobError(pending)
    return pending[0]
