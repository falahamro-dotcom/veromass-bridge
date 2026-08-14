"""
Tiny loopback-only local control server for the Bridge. Bound to
127.0.0.1, never reachable off this machine. Started once a --watch loop
is running (watch.py). Three routes:

  GET  /health        -> {"status":"ok","version":"<bridge version>"}
      Lets app.veromass.com detect "is a Bridge actually running on this
      machine" BEFORE the scientist clicks anything — see
      moleculeid-web/Workbench.jsx.

  POST /launch         body {"workbench_id":"<uuid>","job_id":"<uuid>"}
      Replaces the old bare `<a href="veromass://...">` link. That custom
      URL scheme gives the browser ZERO feedback when it fails to resolve
      (Bridge never installed, registration silently skipped/broken, or a
      stale registry entry) — a real user hit exactly this ("clicked
      Process locally, nothing happened") with no way to even tell why.
      A plain HTTP POST gives a real response either way: 200 on success,
      a real error body on failure. veromass:// is kept as a legacy
      fallback (register_scheme.py, bridge.py --scheme-launch) for anyone
      whose registration still works, but this is now the PRIMARY path.

  GET  /log/<job_id>   (unchanged) — tails veromass-aligner's own
      alignment_log.txt for a running job, read-only.

Nothing here can affect the actual commit/matching path except /launch,
which does exactly what the veromass:// handler already did (job_launch.py
— ONE shared implementation, not two that can drift apart).
"""

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import version

PORT = 58765
TAIL_LINES = 300


def _log_path_for(watch_dir, job_id):
    # Only ever read a path built from a job_id we validate as a plain
    # UUID-shaped path component below — never trust the URL's raw segment
    # as a filesystem path.
    return os.path.join(watch_dir, job_id, "alignment_log.txt")


def _is_safe_job_id(s):
    """Job ids are always real UUIDs (see bridge.py's parse_scheme_url) —
    reject anything else so a request can never walk outside watch_dir via
    "..", separators, etc."""
    return bool(re.fullmatch(r"[0-9a-fA-F-]{36}", s))


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class _LogHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence default stderr request logging — this polls every ~3s

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path.strip("/") == "health":
            self._json(200, {"status": "ok", "version": version.__version__})
            return

        parts = self.path.strip("/").split("/")
        if len(parts) != 2 or parts[0] != "log" or not _is_safe_job_id(parts[1]):
            self.send_response(404)
            self._cors_headers()
            self.end_headers()
            return

        job_id = parts[1]
        watch_dir = self.server.watch_dir
        log_path = _log_path_for(watch_dir, job_id)

        lines = []
        if os.path.isfile(log_path):
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()[-TAIL_LINES:]
            except OSError:
                lines = []

        self._json(200, {"lines": [ln.rstrip("\n") for ln in lines]})

    def do_POST(self):
        if self.path.strip("/") != "launch":
            self._json(404, {"error": "Unknown endpoint."})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._json(400, {"error": "Malformed request body."})
            return

        workbench_id = body.get("workbench_id")
        job_id = body.get("job_id")
        if not (workbench_id and job_id and _UUID_RE.match(workbench_id) and _UUID_RE.match(job_id)):
            self._json(400, {"error": "workbench_id and job_id must both be UUIDs."})
            return

        try:
            import job_launch
            result = job_launch.launch_job(workbench_id, job_id)
        except Exception as e:
            # A real failure here (e.g. the aligner exe is missing, or the
            # install is otherwise broken) — the whole point of this
            # endpoint over the old veromass:// link is that this becomes a
            # real error the page can show, not a silent no-op.
            self._json(500, {"error": str(e)})
            return

        self._json(200, {
            "status": "ok",
            "workbench_name": result.get("workbench_name"),
            "job_name": result.get("job_name"),
        })


class _LogServer(HTTPServer):
    def __init__(self, watch_dir):
        super().__init__(("127.0.0.1", PORT), _LogHandler)
        self.watch_dir = watch_dir


def start_in_background(watch_dir):
    """Best-effort — never raises. If the port's already taken (a prior
    watcher instance still holds it, or something else on the machine),
    assume that instance is already serving the same data and move on;
    this is a nice-to-have, not something that should ever take down the
    real watch loop if it fails."""
    try:
        server = _LogServer(watch_dir)
    except OSError:
        return None
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server
