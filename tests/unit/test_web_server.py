"""The local server's security rules (D-089): who may call it, and what it will and will not do."""

import http.client
import json
import threading

import pytest

from credagent.config.settings import load_settings
from credagent.web.controller import Service
from credagent.web.server import COOKIE, UiServer


@pytest.fixture
def ui():
    httpd = UiServer(("127.0.0.1", 0), Service(load_settings(), headless=True))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def call(httpd, method, path, *, body=None, headers=None, cookie=True, xheader=True, raw=False):
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
    h = dict(headers or {})
    if cookie:
        h["Cookie"] = f"{COOKIE}={httpd.session}"
    if xheader:
        h["X-CredAgent"] = "1"
    data = body if raw else (json.dumps(body) if body is not None else None)
    if data is not None:
        h.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=h)
    r = conn.getresponse()
    payload = r.read()
    conn.close()
    try:
        return r.status, json.loads(payload) if payload else None, r
    except ValueError:
        return r.status, payload, r


def test_the_page_is_served_and_the_token_is_exchanged_for_a_strict_cookie(ui):
    status, body, r = call(ui, "GET", "/", cookie=False, xheader=False)
    assert status == 200 and b"<title>CredAgent</title>" in body
    assert r.getheader("Cache-Control") == "no-store" and "default-src 'self'" in r.getheader("Content-Security-Policy")
    assert call(ui, "GET", "/?t=wrong", cookie=False, xheader=False)[0] == 403
    status, _, r = call(ui, "GET", f"/?t={ui.launch_token}", cookie=False, xheader=False)
    cookie = r.getheader("Set-Cookie")
    assert status == 302 and "HttpOnly" in cookie and "SameSite=Strict" in cookie and ui.launch_token not in cookie


def test_the_api_needs_the_cookie_and_the_custom_header(ui):
    assert call(ui, "GET", "/api/config", cookie=False)[0] == 401
    assert call(ui, "GET", "/api/config", xheader=False)[0] == 401
    status, body, _ = call(ui, "GET", "/api/config")
    assert status == 200 and body["product"] == "CredAgent" and body["keys"] == {"llm": False, "research": False}
    assert call(ui, "GET", "/api/config", headers={"Cookie": f"{COOKIE}=forged"}, cookie=False)[0] == 401


def test_other_hosts_and_other_origins_are_refused(ui):
    assert call(ui, "GET", "/api/config", headers={"Host": "evil.example"})[0] == 403          # DNS rebinding
    assert call(ui, "GET", "/api/config", headers={"Origin": "http://evil.example"})[0] == 403  # another site's page
    port = ui.server_address[1]
    assert call(ui, "GET", "/api/config", headers={"Origin": f"http://127.0.0.1:{port}"})[0] == 200
    assert "Access-Control-Allow-Origin" not in call(ui, "GET", "/api/config")[2].headers


def test_static_files_cannot_escape_their_folder(ui):
    for path in ("/../../../../etc/hosts", "/js/../../../../pyproject.toml", "/..%2f..%2fREADME.md", "/nope.js"):
        assert call(ui, "GET", path, cookie=False, xheader=False)[0] == 404, path
    status, body, r = call(ui, "GET", "/js/main.js", cookie=False, xheader=False)
    assert status == 200 and r.getheader("Content-Type").startswith("application/javascript") and b"import" in body


def test_bad_requests_get_plain_errors_not_tracebacks(ui):
    for app in ("", "   ", "two\nlines", "x" * 101):
        status, body, _ = call(ui, "POST", "/api/runs", body={"app": app})
        assert status == 400 and body["error"]["message"] and "Traceback" not in json.dumps(body)
    assert call(ui, "POST", "/api/runs", body={"app": "Acme"})[1]["error"]["code"] == "no_keys"  # no keys in tests
    assert call(ui, "POST", "/api/runs", body={"app": "A", "mode": "fake", "scenario": "nope"})[1]["error"]["code"] == "bad_scenario"
    assert call(ui, "POST", "/api/runs", body=b"{not json", raw=True)[1]["error"]["code"] == "bad_json"
    assert call(ui, "POST", "/api/runs", body=b"[1]", raw=True)[1]["error"]["code"] == "bad_json"
    assert call(ui, "POST", "/api/runs", body=b"x" * 20000, raw=True)[0] == 413
    assert call(ui, "GET", "/api/runs/does-not-exist")[0] == 404
    assert call(ui, "GET", "/api/nothing")[0] == 404
    assert call(ui, "GET", "/api/runs/r1/answer")[0] == 405


def test_a_value_is_never_revealed_without_an_explicit_confirm(ui):
    status, body, _ = call(ui, "POST", "/api/runs/r1/secrets/client_secret/reveal", body={})
    assert status == 400 and body["error"]["code"] == "no_confirm"
    assert call(ui, "POST", "/api/runs/r1/secrets/client_secret/reveal", body={"confirm": "yes"})[0] == 400
    assert call(ui, "POST", "/api/runs/r1/secrets/client_secret/reveal", body={"confirm": True})[0] == 404  # no such run


def test_questions_that_are_not_open_are_refused(ui):
    for path, payload in (("consent", {"account": "me", "confirm": True}), ("continue", {"handoff_id": "h-1"}),
                          ("answer", {"handoff_id": "h-1", "option": 0}), ("stop", {})):
        status, body, _ = call(ui, "POST", f"/api/runs/r1/{path}", body=payload)
        assert status in (404, 409), (path, status, body)  # nothing is running, so nothing can be answered
