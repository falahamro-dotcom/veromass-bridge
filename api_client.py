"""
Thin wrapper around moleculeid-api's Workbench/Job endpoints
(see moleculeid-api/workbench_routes.py). Mirrors moleculeid-web's
apiFetch() call shape exactly (supabase.js): Bearer access token,
JSON body, FastAPI's `detail` error field surfaced as the exception message.
"""

import requests

API_BASE = "https://moleculeid-api.onrender.com"


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
    resp = requests.post(
        f"{API_BASE}/api/jobs/{job_id}/commit",
        headers={"Authorization": f"Bearer {access_token}",
                  "Content-Type": "application/json"},
        json={"package_uuid": package_uuid, **mode_body},
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
