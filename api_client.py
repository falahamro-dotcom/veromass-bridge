"""
Thin wrapper around moleculeid-api's Workbench/Job endpoints
(see moleculeid-api/workbench_routes.py). Mirrors moleculeid-web's
apiFetch() call shape exactly (supabase.js): Bearer access token,
JSON body, FastAPI's `detail` error field surfaced as the exception message.
"""

import gzip
import json as _json

import requests

API_BASE = "https://moleculeid-api.onrender.com"

# Render's edge proxy rejects request bodies above roughly 50-90MB with a
# 502/503 before the request ever reaches the app (confirmed empirically --
# no trace in app logs, no CPU/memory spike on the server). Untargeted-mode
# commits carry feature_matrix/feature_meta/chromatograms, which can cross
# that ceiling as raw JSON even when the intermediate columnar store is
# small (float arrays serialize far less compactly as JSON text). gzip the
# body once it's large enough that compression is worth the CPU cost;
# main.py's GZipRequestMiddleware decompresses it server-side.
_GZIP_THRESHOLD_BYTES = 1_000_000


def _raise_for_detail(resp):
    if resp.ok:
        return
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    raise RuntimeError(f"{resp.status_code}: {detail}")


def commit_job(job_id, package_uuid, mode_body, access_token):
    """mode_body: {"features": [...]} or {"feature_matrix": {...}} —
    see mapping.build_commit_payload."""
    body = _json.dumps({"package_uuid": package_uuid, **mode_body}).encode("utf-8")
    headers = {"Authorization": f"Bearer {access_token}",
               "Content-Type": "application/json"}
    if len(body) > _GZIP_THRESHOLD_BYTES:
        body = gzip.compress(body)
        headers["Content-Encoding"] = "gzip"
    resp = requests.post(
        f"{API_BASE}/api/jobs/{job_id}/commit",
        headers=headers,
        data=body,
    )
    _raise_for_detail(resp)
    return resp.json()


def get_job(job_id, access_token):
    resp = requests.get(
        f"{API_BASE}/api/jobs/{job_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    _raise_for_detail(resp)
    return resp.json()


def get_workbench(workbench_id, access_token):
    resp = requests.get(
        f"{API_BASE}/api/workbenches/{workbench_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    _raise_for_detail(resp)
    return resp.json()


def list_workbenches(access_token):
    resp = requests.get(
        f"{API_BASE}/api/workbenches",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    _raise_for_detail(resp)
    return resp.json()


def list_jobs_for_workbench(workbench_id, access_token):
    resp = requests.get(
        f"{API_BASE}/api/workbenches/{workbench_id}/jobs",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    _raise_for_detail(resp)
    return resp.json()
