# veromass-bridge (Phase 1 spike)

Proves the desktop-Bridge loop described in the "VeroMass Desktop
Integration — Architecture" doc: take a completed `veromass-aligner`
workbook, authenticate as the signed-in VeroMass user, and commit the
result to an already-created Workbench/Job via the real, live
`moleculeid-api` (`POST /api/jobs/{job_id}/commit`).

This is **not** the production Bridge. It is a spike to validate the loop
before committing to a final stack (.NET/C# vs. otherwise).

## Usage

```
pip install requests openpyxl
```

**Manual, one-shot** (you already know the job_id — e.g. for testing):
```
python bridge.py --job <job_id> --mode targeted --xlsx aligned_features.xlsx
```
`job_id` comes from a Workbench/Job already created at
`app.veromass.com/workbench` — this spike does not create them.

**Watch mode** (no manual IDs — the normal way a scientist would run this):
```
python bridge.py --watch
```
Watches `%LOCALAPPDATA%\VeroMassBridge\incoming` (override with `--dir`) for
`veromass-aligner` output. `VeroMass_Aligner.py` now writes a `.ready` marker
next to its `aligned_features.xlsx` the moment a run finishes; the Bridge
picks that up and matches it to a Job in one of two ways (see next section).

**One-time setup — after this, "Process locally" is the only thing you
ever do:**
```
python register_scheme.py
```
Registers `veromass://` for your Windows user (`HKEY_CURRENT_USER`, no admin
needed). After this, clicking **"Process locally"** next to a job at
`app.veromass.com/workbench` (`Workbench.jsx`):
1. Pre-stamps that job's real ID (no ambiguity, ever, for that run).
2. **Launches the real Aligner GUI** (`launcher.py`) — pick your files
   there, same as always.
3. **Makes sure a `--watch` loop is already running in the background**,
   silently starting one (windowless, logging to
   `%LOCALAPPDATA%\VeroMassBridge\watch.log`) if none is — detected via a
   heartbeat file `watch.py` touches once per poll, not a fragile
   PID-liveness check.

No terminal, no typed commands, nothing to keep open by hand — click the
button, the aligner pops up, walk away, the result shows up in the browser.
Safe to re-run `register_scheme.py` any time.

**Matching precedence:**
1. **Pre-stamped hint** — if you clicked "Process locally" first, the next
   finished run is matched to that exact job, consumed once. This is the
   architecture doc's real design: the browser hands the ID to the desktop
   before the aligner even runs.
2. **Poll-based fallback** — if no hint is present (you just ran the
   aligner without clicking that button first), the Bridge polls for jobs
   sitting in `status == "waiting_for_desktop"` (`jobs.py`, no new backend
   endpoint). If more than one is pending, it refuses to guess — it prints
   every candidate and waits for you to finish/cancel the others (or use
   the manual `--job` path). Silently attaching a result to the wrong study
   is a correctness bug, not just an inconvenience — this safety net stays
   even now that the hint path exists, since a scientist can always skip
   the button.

## Known simplifications vs. the architecture doc (must close before production)

- **Auth**: `auth.py` opens the system browser to `app.veromass.com/authorize`
  (`moleculeid-web/Authorize.jsx`) and receives the resulting session over a
  `state`-nonce-protected loopback listener — the password never touches this
  process, matching the architecture doc's actual security goal. This is
  *not* a byte-for-byte RFC 7636 PKCE code_verifier/code_challenge exchange
  (Supabase's session here isn't obtained via an authorization-code grant,
  so there's no "code" to protect that way) — it's the same trust model as
  e.g. `gh auth login`'s local OAuth handoff: an OS-assigned ephemeral
  loopback port + a random state only this process and the browser tab know.
- **Token storage**: `%LOCALAPPDATA%\VeroMassBridge\token.dat` is DPAPI-sealed
  (`dpapi.py`, `CryptProtectData`/`CryptUnprotectData`) — encrypted to this
  Windows user, useless to anyone else on the machine or if copied
  elsewhere. This gap is now closed.
- **Trigger**: closed. `veromass://job?workbench=X&job=Y` is registered
  (`register_scheme.py`) and real (`bridge.py --scheme-launch`, wired to
  `moleculeid-web/Workbench.jsx`'s "Process locally" button) — the browser
  really does stamp the IDs into the desktop before the aligner runs, per
  the architecture doc. The poll-based fallback still exists for the
  scientist-skips-the-button case, with its ambiguity-refusal safety net.
  Also closed: `--scheme-launch` now auto-launches the real Aligner GUI and
  auto-starts a background `--watch` loop if none is running
  (`launcher.py`) — zero manual terminal commands anywhere in the flow.
  Not done: no browser-side file picker hands back a real filesystem path
  (browsers can't, for security reasons) — the scientist still picks input
  files in the aligner's own native dialog, same as always. Also not done:
  no way to stop a background watcher from the browser — it just keeps
  running (check Task Manager for a lingering `pythonw.exe`, or Ctrl+C a
  manually-started `--watch` — same as before this slice).
- **Upload**: the mapped feature data goes straight in the JSON commit body
  (matching the current `/api/jobs/{id}/commit` contract, which does not yet
  accept file uploads) — no TUS resumable upload to Supabase Storage.
- **Deep link**: closed — `/workbench/:workbenchId/job/:jobId` exists in
  `moleculeid-web/App.jsx`, and the Bridge opens straight to it whenever a
  `workbench_id` is known.
- **Packaging**: a plain Python script, not an MSIX-signed installer.
  `register_scheme.py` is a one-time manual setup step, not something an
  installer runs automatically.

## Files

- `mapping.py` — `aligned_features.xlsx` → commit body (`features` or
  `feature_matrix`), pure function, no I/O beyond the file read.
- `dpapi.py` — ctypes wrapper around Windows DPAPI (`CryptProtectData`/
  `CryptUnprotectData`), no `pywin32` dependency.
- `auth.py` — browser-mediated loopback session handoff + DPAPI-sealed
  local token cache.
- `api_client.py` — `commit_job` / `get_job` / `list_workbenches` /
  `list_jobs_for_workbench` against `moleculeid-api`.
- `jobs.py` — matches a finished run to a pending Job: pre-stamped hint
  first, poll-based 0/1/many fallback second.
- `watch.py` — polls a handoff folder for `.ready` markers and drives the
  auto-match + commit loop.
- `register_scheme.py` — one-time setup: registers `veromass://` for this
  Windows user (run by hand, not automatically).
- `launcher.py` — auto-launches the Aligner GUI and auto-starts a
  background `--watch` loop (heartbeat-based liveness check) from
  `--scheme-launch`, so clicking "Process locally" is the only manual step.
- `bridge.py` — CLI entry point: manual `--job` path, `--watch` mode, or
  `--scheme-launch` (invoked by the registered protocol) — all funnelling
  through the same `process_one()` for the actual commit.
