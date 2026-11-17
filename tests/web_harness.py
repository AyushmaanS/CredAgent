"""Shared helpers for the web UI tests: a running UI server on a free port, and a harness that plays the person in the
agent's own Chrome window (its requests carry X-Fakeprov-Actor: person, so the fake site's audit log shows who did what)."""

import http.client
import json
import threading
import time

from playwright.async_api import async_playwright

from credagent.config.settings import load_settings
from credagent.web.controller import Service
from credagent.web.server import COOKIE, UiServer


class Ui:
    def __init__(self):
        self.settings = load_settings()
        self.service = Service(self.settings, headless=True)
        self.httpd = UiServer(("127.0.0.1", 0), self.service)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=20)
        headers = {"Cookie": f"{COOKIE}={self.httpd.session}", "X-CredAgent": "1"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = conn.getresponse()
        data = json.loads(r.read() or b"null")
        conn.close()
        return r.status, data

    def start(self, scenario, offline=True):
        status, data = self.call("POST", "/api/runs", {"app": "Test app", "mode": "fake", "scenario": scenario,
                                                       "offline": offline})
        assert status == 200, data
        return data["run_id"]

    def view(self, run_id):
        status, data = self.call("GET", f"/api/runs/{run_id}")
        assert status == 200, data
        return data

    def wait(self, run_id, pred, timeout=120):
        end = time.time() + timeout
        v = None
        while time.time() < end:
            v = self.view(run_id)
            if pred(v):
                return v
            time.sleep(0.3)
        raise AssertionError(f"timed out; last view state={v['state']} headline={v['headline']} "
                             f"attention={v['attention'] and v['attention']['type']}, reason={v['reason']}")

    def settle(self):
        """Wait until no worker thread is alive (so the next start is not refused as busy)."""
        end = time.time() + 30
        while time.time() < end and self.service._busy():
            time.sleep(0.2)

    async def aperson(self, run_id, js):
        """The person acts in the agent's Chrome window (requests are marked as the person)."""
        port = self.service.read_store.load(run_id).run.browser.cdp_port
        async with async_playwright() as p:
            b = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            page = next(pg for c in b.contexts for pg in c.pages if pg.url.startswith("http://127.0.0.1"))
            await page.set_extra_http_headers({"X-Fakeprov-Actor": "person"})
            await page.evaluate(js)
            await page.wait_for_timeout(700)
            await page.set_extra_http_headers({})
            await b.close()

    def person(self, run_id, js):
        import asyncio

        asyncio.run(self.aperson(run_id, js))

    @property
    def url(self):
        return self.httpd.url()

    def fake_state(self, run_id):
        f = self.settings.home / "fakeprov" / run_id / "state.json"
        return json.loads(f.read_text())

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
