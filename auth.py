"""
Auth for the Bridge — browser-mediated loopback session handoff.

The password never touches this process. Flow:
  1. Generate a random `state` and start a single-request local HTTP server
     on 127.0.0.1:<OS-assigned free port>.
  2. Open the system browser to moleculeid-web's /authorize page
     (Authorize.jsx), passing that state + this loopback's redirect_uri.
  3. The user signs in on that page, in the real app, same as any other
     login. Once signed in, the page POSTs the fresh session's
     access_token/refresh_token/expires_in + the same `state` back to our
     loopback listener.
  4. We verify `state` matches what we generated (only this process knows
     it — that plus the loopback-only, OS-assigned ephemeral port is what
     makes this safe without a full RFC 7636 code_verifier/code_challenge
     exchange, which doesn't apply here anyway since Supabase's session
     isn't obtained via an authorization-code grant). Same trust model as
     e.g. `gh auth login`'s local OAuth handoff.

The token cache is DPAPI-sealed (dpapi.py, CryptProtectData/
CryptUnprotectData) — encrypted to this Windows user, so the file on disk
is useless to anyone but this OS account on this machine, matching the
architecture doc's "Windows DPAPI token vault" requirement.
"""

import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

import dpapi

# Override with VEROMASS_APP_BASE for local dev-server testing
# (e.g. http://localhost:5173) before Authorize.jsx is deployed.
APP_BASE = os.environ.get("VEROMASS_APP_BASE", "https://app.veromass.com")
SUPABASE_URL = "https://ufnyuccqnbdkwdroyggo.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_HtSCh-aE1EQuOniVKrzqvw_8jlhs5pz"

LOGIN_TIMEOUT_SECONDS = 300  # 5 minutes to complete the browser sign-in

# .dat, not .json — the contents are DPAPI-sealed ciphertext, not plaintext
# JSON anymore. (An old plaintext token.json from before this change may
# still be sitting alongside it; it's simply never read.)
_TOKEN_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "VeroMassBridge", "token.dat",
)


def _token_endpoint(grant_type):
    return f"{SUPABASE_URL}/auth/v1/token?grant_type={grant_type}"


def _headers():
    return {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}


def _save_token(data):
    os.makedirs(os.path.dirname(_TOKEN_PATH), exist_ok=True)
    data = dict(data)
    data["_obtained_at"] = time.time()
    sealed = dpapi.protect(json.dumps(data).encode("utf-8"))
    with open(_TOKEN_PATH, "wb") as f:
        f.write(sealed)


def _load_cached_token():
    if not os.path.exists(_TOKEN_PATH):
        return None
    with open(_TOKEN_PATH, "rb") as f:
        sealed = f.read()
    try:
        return json.loads(dpapi.unprotect(sealed).decode("utf-8"))
    except OSError:
        # Sealed to a different Windows user/machine, or the file predates
        # DPAPI sealing and isn't valid ciphertext — either way, this cache
        # is unusable; treat it the same as "no cache" and re-login.
        return None


def _refresh(refresh_token):
    resp = requests.post(
        _token_endpoint("refresh_token"),
        headers=_headers(),
        json={"refresh_token": refresh_token},
    )
    resp.raise_for_status()
    data = resp.json()
    _save_token(data)
    return data["access_token"]


class _CallbackServer(HTTPServer):
    """Single-request loopback listener for the /authorize handoff."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _CallbackHandler)
        self.state = secrets.token_urlsafe(24)
        self.result = None  # set by the handler once a valid callback lands
        self.error = None

    @property
    def redirect_uri(self):
        return f"http://127.0.0.1:{self.server_port}/callback"


class _CallbackHandler(BaseHTTPRequestHandler):
    """Authorize.jsx runs on a different origin (the web app's own host/port)
    than this loopback listener, so the browser sends a CORS preflight
    (OPTIONS) before the real POST, and every response here needs
    Access-Control-Allow-Origin or the browser's fetch() rejects it outright
    with an opaque "Failed to fetch" — no server-side detail available."""

    def log_message(self, *args):
        pass  # silence default stderr request logging

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_POST(self):
        server: _CallbackServer = self.server
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            body = {}

        if body.get("state") != server.state:
            server.error = "state mismatch — rejecting callback (not from our /authorize request)"
            self.send_response(400)
            self._cors_headers()
            self.end_headers()
            return

        missing = [k for k in ("access_token", "refresh_token") if not body.get(k)]
        if missing:
            server.error = f"callback body missing: {', '.join(missing)}"
            self.send_response(400)
            self._cors_headers()
            self.end_headers()
            return

        server.result = {
            "access_token": body["access_token"],
            "refresh_token": body["refresh_token"],
            "expires_in": body.get("expires_in", 3600),
        }
        self.send_response(200)
        self._cors_headers()
        self.end_headers()


def _serve_until_done(server, deadline):
    """The browser sends a CORS preflight (OPTIONS) before the real POST —
    two separate requests — so handle_request() once isn't enough. Keep
    serving until we have a result/error or run out of time."""
    server.timeout = 1.0  # handle_request() gives up and returns after this long
    while server.result is None and server.error is None and time.time() < deadline:
        server.handle_request()


def _browser_login():
    import webbrowser

    server = _CallbackServer()
    deadline = time.time() + LOGIN_TIMEOUT_SECONDS
    thread = threading.Thread(target=_serve_until_done, args=(server, deadline), daemon=True)
    thread.start()

    url = f"{APP_BASE}/authorize?state={server.state}&redirect_uri={server.redirect_uri}"
    print(f"Opening {url} — sign in there to connect this Bridge.")
    webbrowser.open(url)

    thread.join(timeout=LOGIN_TIMEOUT_SECONDS + 2)
    server.server_close()

    if server.error:
        raise RuntimeError(f"Browser sign-in failed: {server.error}")
    if server.result is None:
        raise TimeoutError(
            f"No sign-in completed within {LOGIN_TIMEOUT_SECONDS}s — "
            "reopen the browser tab and sign in, or run again."
        )

    _save_token(server.result)
    return server.result["access_token"]


def get_access_token(force_refresh=False):
    """Return a valid Supabase access token, refreshing or re-prompting for
    browser sign-in as needed. This is the only function api_client.py
    should call.

    force_refresh=True skips the local expires_in-based shortcut entirely.
    This matters because the local clock math can be wrong relative to the
    server's real notion of the token's lifetime (observed live: the cache
    said a token was good for ~20 more minutes while the API had already
    started rejecting it with 401 "Signature has expired") — a caller that
    just got a 401 should force a real refresh attempt instead of trusting
    the same stale math that produced the bad token in the first place."""
    cached = _load_cached_token()
    if cached and not force_refresh:
        obtained_at = cached.get("_obtained_at", 0)
        expires_in = cached.get("expires_in", 0)
        if time.time() < obtained_at + expires_in - 60:
            return cached["access_token"]
    if cached:
        refresh_token = cached.get("refresh_token")
        if refresh_token:
            try:
                return _refresh(refresh_token)
            except requests.HTTPError:
                pass  # refresh token expired/invalid — fall through to a fresh login
    return _browser_login()
