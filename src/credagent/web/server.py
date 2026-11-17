"""The local HTTP server for the web UI (D-089): static files plus a small JSON API, standard library only.

This server can reveal stored credentials and drive a signed-in browser, so it is deliberately strict:
  * it binds 127.0.0.1 only, and `Host` must be that address (blocks DNS rebinding);
  * a random one-time launch token in the printed URL is exchanged for an HttpOnly, SameSite=Strict session cookie;
    every API call needs that cookie and a custom `X-CredAgent` header, and `Origin`, if sent, must be this server;
  * no CORS headers, `no-store` on everything, a restrictive Content-Security-Policy;
  * no access log (paths and bodies are never written anywhere), and unexpected errors return a generic message.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import re
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from credagent.web.controller import ApiError, Service

STATIC = Path(__file__).resolve().parent / "static"
COOKIE = "credagent_session"
MAX_BODY = 16_384
CSP = ("default-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
ROUTE = re.compile(r"^/api/runs/([A-Za-z0-9_.-]{1,64})(?:/([a-z]+)(?:/([A-Za-z0-9_.-]{1,64})(?:/([a-z]+))?)?)?$")


class UiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr: tuple[str, int], service: Service) -> None:
        super().__init__(addr, Handler)
        self.service = service
        self.launch_token = secrets.token_urlsafe(24)
        self.session = secrets.token_urlsafe(32)

    @property
    def hosts(self) -> set[str]:
        port = self.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/?t={self.launch_token}"


class Handler(BaseHTTPRequestHandler):
    server: UiServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - never log paths or bodies
        return

    # ---------------------------------------------------------------- plumbing
    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: object, extra: dict[str, str] | None = None) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _error(self, status: int, message: str, code: str = "error") -> None:
        self._json(status, {"error": {"code": code, "message": message}})

    def _cookie_ok(self) -> bool:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE and hmac.compare_digest(v, self.server.session):
                return True
        return False

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in self.server.hosts}

    def _guard(self, api: bool) -> bool:
        if (self.headers.get("Host") or "") not in self.server.hosts:
            self._error(403, "Unexpected Host header.", "bad_host")
            return False
        if not self._origin_ok():
            self._error(403, "Unexpected Origin.", "bad_origin")
            return False
        if api:
            if self.headers.get("X-CredAgent") != "1" or not self._cookie_ok():
                self._error(401, "Open the link printed by `credagent ui` to use this page.", "unauthorized")
                return False
        return True

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Bad request.", "bad_length") from None
        if n > MAX_BODY:
            raise ApiError(413, "The request is too large.", "too_large")
        if n == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "The request body is not valid JSON.", "bad_json") from None
        if not isinstance(data, dict):
            raise ApiError(400, "The request body must be a JSON object.", "bad_json")
        return data

    # ------------------------------------------------------------------ routes
    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            return self._api("GET", url)
        if not self._guard(False):
            return
        if url.path == "/" and "t" in parse_qs(url.query):
            tok = parse_qs(url.query)["t"][0]
            if hmac.compare_digest(tok, self.server.launch_token):  # exchange the one-time token for a cookie
                return self._send(HTTPStatus.FOUND, b"", "text/plain", {
                    "Location": "/",
                    "Set-Cookie": f"{COOKIE}={self.server.session}; HttpOnly; SameSite=Strict; Path=/"})
            return self._error(403, "That link is not valid. Use the one printed by `credagent ui`.", "bad_token")
        self._static(url.path)

    def do_POST(self) -> None:  # noqa: N802
        self._api("POST", urlparse(self.path))

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (STATIC / rel).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            return self._error(404, "Not found.", "not_found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".js":
            ctype = "application/javascript"
        self._send(200, target.read_bytes(), ctype if "charset" in ctype else f"{ctype}; charset=utf-8")

    def _api(self, method: str, url) -> None:  # noqa: ANN001
        if not self._guard(True):
            return
        svc = self.server.service
        try:
            self._json(200, self._dispatch(svc, method, url))
        except ApiError as exc:
            self._error(exc.status, exc.message, exc.code)
        except Exception as exc:  # noqa: BLE001 - generic message out; only the class name goes to stderr
            print(f"ui: unexpected {type(exc).__name__} in {method} API call", file=sys.stderr)
            self._error(500, "Something went wrong in the local server.", "internal")

    def _dispatch(self, svc: Service, method: str, url) -> object:  # noqa: ANN001
        p = url.path
        if method == "GET" and p == "/api/config":
            return svc.config()
        if method == "GET" and p == "/api/runs":
            return {"runs": svc.list_runs()}
        if method == "POST" and p == "/api/runs":
            return svc.start_run(self._body())
        m = ROUTE.match(p)
        if not m:
            raise ApiError(404, "Not found.", "not_found")
        run_id, action, arg, sub = m.groups()
        if method == "GET" and action is None:
            return svc.view(run_id)
        if method == "GET" and action == "events":
            after = parse_qs(url.query).get("after", ["0"])[0]
            return {"events": svc.events(run_id, int(after) if after.isdigit() else 0)}
        if method != "POST":
            raise ApiError(405, "Method not allowed.", "method")
        body = self._body()
        if action == "consent":
            svc.give_consent(run_id, body.get("account"), body.get("confirm"))
        elif action == "answer":
            svc.answer(run_id, body.get("handoff_id"), body.get("option"))
        elif action == "continue":
            svc.done(run_id, body.get("handoff_id"))
        elif action == "stop":
            svc.stop(run_id)
        elif action == "resume":
            return svc.resume(run_id)
        elif action == "verify":
            return svc.verify(run_id)
        elif action == "browser" and arg == "focus":
            return svc.focus_browser(run_id)
        elif action == "secrets" and sub == "reveal" and arg:
            if body.get("confirm") is not True:
                raise ApiError(400, "Revealing a value needs an explicit click.", "no_confirm")
            return {"value": svc.reveal(run_id, arg)}
        else:
            raise ApiError(404, "Not found.", "not_found")
        return {"ok": True}


def serve(service: Service, port: int, *, open_browser: bool = True, echo=print) -> None:  # noqa: ANN001
    try:
        httpd = UiServer(("127.0.0.1", port), service)
    except OSError:
        raise SystemExit(f"Port {port} is in use. Choose another with: credagent ui --port <number>") from None
    echo(f"CredAgent is running at {httpd.url()}")
    echo("Open that exact link (it signs this browser in once). Press Ctrl+C to stop; saved runs can be resumed later.")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(httpd.url())).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        echo("\nStopped. Runs are saved; resume them from this page or with `credagent resume <run-id>`.")
    finally:
        httpd.server_close()
