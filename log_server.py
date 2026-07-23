"""
Tiny loopback-only HTTP server that lets app.veromass.com show the
aligner's own live log while a "Process locally" run is in progress —
without touching Supabase/the shared DB at all. The background watcher
(already a long-lived process — see launcher.py/watch.py) starts this once;
Workbench.jsx polls it directly from the browser while a job is
waiting_for_desktop.

Read-only, GET-only, bound to 127.0.0.1 — never reachable off this machine.
Serves the tail of veromass-aligner's own alignment_log.txt
(VeroMass_Aligner.py:run_alignment's `flog`), which already lives at
<watch_dir>/<job_id>/alignment_log.txt now that the output folder is
auto-filled to a per-job subfolder of watch.DEFAULT_DIR (see
launcher.launch_aligner's output_dir param). Nothing here can affect the
actual commit/matching path — it only reads a text file.
"""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

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
    import re
    return bool(re.fullmatch(r"[0-9a-fA-F-]{36}", s))


class _LogHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence default stderr request logging — this polls every ~3s

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
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

        body = json.dumps({"lines": [ln.rstrip("\n") for ln in lines]}).encode("utf-8")
        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
