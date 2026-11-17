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


# ------------------------------------------------- the console address, when research found none (D-092)

def _run_waiting_for_the_console(ui, run_id="r-console"):
    import time

    from credagent.state.models import Identification, Plan, Run
    from credagent.state.store import RunStore
    from credagent.web.controller import RunController

    run = Run(id=run_id, app_input="Acme", app_name="Acme", provider="Acme Inc.", phase="planned",
              plan=Plan(identification=Identification(canonical_name="Acme", provider="Acme Inc.", confidence="high"),
                        credential_kind="oauth_client", console_url=None, allowed_domains=["acme.example"]))
    RunStore(ui.service.settings.runs_dir, ui.service.new_masker()).create(run)
    ctl = RunController(ui.service, run_id)
    ctl.thread = threading.Thread(target=lambda: time.sleep(5), daemon=True)
    ctl.thread.start()
    ui.service.controllers[run_id] = ctl
    got = []
    threading.Thread(target=lambda: got.append(ctl.io.wait_console()), daemon=True).start()
    for _ in range(100):
        if ctl.io.snapshot():
            break
        time.sleep(0.02)
    return ctl, got


def test_a_plan_without_a_console_address_asks_for_one_instead_of_dead_ending(ui):
    _run_waiting_for_the_console(ui)
    status, view, _ = call(ui, "GET", "/api/runs/r-console")
    a = view["attention"]
    assert status == 200 and view["state"] == "attention" and a["type"] == "console"
    assert a["headline"] == "Where is the developer console?" and a["allowed"] == ["acme.example"]
    assert next(m for m in view["milestones"] if m["id"] == "portal")["status"] == "blocked"


def test_the_console_address_is_validated_before_it_is_accepted(ui):
    ctl, got = _run_waiting_for_the_console(ui)
    for bad in ("", "console.acme.example", "http://console.acme.example/", "https://user:pw@console.acme.example/",
                "https://10.0.0.1/apps", "https://two words.example/", "https://localhost/x"):
        status, body, _ = call(ui, "POST", "/api/runs/r-console/console", body={"url": bad})
        assert status == 400 and body["error"]["code"] == "bad_console_url" and body["error"]["message"], bad
    assert not got  # nothing was delivered to the waiting run
    status, _body, _ = call(ui, "POST", "/api/runs/r-console/console", body={"url": "https://console.acme.example/apps"})
    assert status == 200
    ctl.thread.join(0) if False else None
    import time
    for _ in range(100):
        if got:
            break
        time.sleep(0.02)
    assert got == ["https://console.acme.example/apps"]
    assert call(ui, "POST", "/api/runs/r-console/console", body={"url": "https://console.acme.example/x"})[0] == 409


def test_a_console_address_for_a_run_that_is_not_active_is_refused(ui):
    assert call(ui, "POST", "/api/runs/none/console", body={"url": "https://console.acme.example/"})[0] in (404, 409)
