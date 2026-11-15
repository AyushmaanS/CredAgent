#!/usr/bin/env python3
"""Sprint 0 spike: Stagehand v4 (Python) feasibility. Needs no API keys.

Checks:
  A. Headed local Chrome launches with a persistent user_data_dir.
  B. Cookie + localStorage survive a full *process* restart.
  C. What page content reaches Stagehand's model: a recording LLM callback captures
     every llm.generate request while observe() runs on a page holding FAKE secrets.
     Repeated with ignore_locators covering the secret panel.
  D. act() with an Action from observe() — does it make any model call?
  E. Network: Chrome is pointed at a local deny-all proxy that logs every off-machine
     host it tries to reach.

Usage: .venv/bin/python scripts/spikes/spike_stagehand.py [--headless]
Writes a summary to docs/spikes/stagehand.json (no secrets; fake values only, and
those are reported only as found/not-found).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets as pysecrets
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from stagehand import Stagehand, local_browser  # noqa: E402
from stagehand._generated.models import LLMStructuredGenerateResult  # noqa: E402

from credagent.browser.chrome import ChromeProcess  # noqa: E402
from credagent.config.settings import load_settings  # noqa: E402
from credagent.secrets.store import ensure_private_dir  # noqa: E402

OUT = REPO / "docs" / "spikes" / "stagehand.json"

# ---------------------------------------------------------------- local site

FAKE = {
    "code_text": "FAKECS_" + pysecrets.token_hex(12),
    "readonly_input": "FAKEKEY_" + pysecrets.token_hex(12),
    "password_input": "FAKEPW_" + pysecrets.token_hex(12),
    "outside_input": "FAKEOUT_" + pysecrets.token_hex(12),
}

SECRET_PAGE = f"""<!doctype html><html><head><title>Fake Console — App created</title></head>
<body>
<h1>Spike Test Console (fake)</h1>
<nav><a href="/docs">Docs</a> <a href="/apps">My apps</a></nav>
<button id="create">Create new app</button>
<button id="delete">Delete app</button>
<section id="cred-panel">
  <h2>Your credentials (shown once)</h2>
  <p>Client secret: <code id="client-secret">{FAKE["code_text"]}</code></p>
  <label>API key <input id="api-key" readonly value="{FAKE["readonly_input"]}"></label>
  <label>Password <input id="pw" type="password" value="{FAKE["password_input"]}"></label>
  <button id="copy">Copy</button>
</section>
<label>Other field <input id="other" value="{FAKE["outside_input"]}"></label>
</body></html>"""

PERSIST_PAGE = """<!doctype html><html><head><title>persist</title></head><body>
<script>
const p = new URLSearchParams(location.search);
if (p.get('set')) {
  document.cookie = 'spike=' + p.get('set') + '; Max-Age=86400; Path=/; SameSite=Lax';
  localStorage.setItem('spike', p.get('set'));
}
</script><p>persist test</p></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/persist"):
            body = PERSIST_PAGE
        elif self.path.startswith("/secret"):
            body = SECRET_PAGE
        else:
            body = "<!doctype html><title>other</title><p>other page</p>"
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def serve(port: int = 0) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ------------------------------------------------------------ deny-all proxy

class DenyProxy:
    """Logs CONNECT/absolute-URL targets and refuses them all."""

    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.server: asyncio.base_events.Server | None = None
        self.port = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        try:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode(errors="replace")
            parts = line.split()
            if len(parts) >= 2:
                target = parts[1]
                host = target.split("//")[-1].split("/")[0]
                self.hosts.append(host)
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        except Exception:  # noqa: S110
            pass
        finally:
            writer.close()

    async def stop(self) -> None:
        if self.server:
            self.server.close()


# --------------------------------------------------------- recording callback

def minimal_instance(schema: dict, defs: dict | None = None):
    """Smallest JSON value that satisfies a JSON schema (enough for canned replies)."""
    defs = defs if defs is not None else schema.get("$defs", schema.get("definitions", {}))
    if "$ref" in schema:
        return minimal_instance(defs[schema["$ref"].split("/")[-1]], defs)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            return minimal_instance(schema[key][0], defs)
    if "allOf" in schema:
        return minimal_instance(schema["allOf"][0], defs)
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t == "object":
        props = schema.get("properties", {})
        return {k: minimal_instance(props[k], defs) for k in schema.get("required", []) if k in props}
    if t == "array":
        n = schema.get("minItems", 0)
        return [minimal_instance(schema.get("items", {}), defs) for _ in range(n)]
    if t == "string":
        return ""
    if t in ("number", "integer"):
        return schema.get("minimum", 0)
    if t == "boolean":
        return False
    return None


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate(self, params):
        dumped = params.model_dump(mode="json", by_alias=True)
        self.calls.append(dumped)
        schema = (dumped.get("response_format") or dumped.get("responseFormat") or {}).get("schema")
        if schema is None:
            raise RuntimeError("spike recorder only handles structured requests")
        structured = minimal_instance(schema)
        return LLMStructuredGenerateResult.model_validate({
            "role": "assistant",
            "content": {"type": "text", "text": json.dumps(structured)},
            "output_format": "json_schema",
            "structured_content": structured,
        })

    def text(self) -> str:
        return json.dumps(self.calls)


def leak_report(blob: str) -> dict[str, bool]:
    return {name: value in blob for name, value in FAKE.items()}


# ---------------------------------------------------------------- phases

async def launch(profile: Path, headless: bool, proxy_port: int | None):
    kwargs = {"headless": headless, "user_data_dir": str(profile)}
    if proxy_port:
        kwargs["proxy_server"] = f"http://127.0.0.1:{proxy_port}"
    return await local_browser.launch(**kwargs)


async def persist_set(profile: Path, port: int, token: str, headless: bool) -> dict:
    browser = await launch(profile, headless, None)
    rec = Recorder()
    sh = await Stagehand.create(browser=browser, model=rec.generate)
    try:
        page = await browser.context.active_page() or (await browser.context.pages())[0]
        await page.goto(f"http://127.0.0.1:{port}/persist?set={token}")
        await page.wait_for_timeout(500)
        cookie = await page.evaluate("document.cookie")
        ls = await page.evaluate("localStorage.getItem('spike')")
    finally:
        await sh.close()
        await browser.close()
    return {"cookie_set": f"spike={token}" in str(cookie), "localstorage_set": ls == token,
            "model_calls": len(rec.calls)}


async def persist_check(profile: Path, port: int, token: str, headless: bool) -> dict:
    browser = await launch(profile, headless, None)
    sh = await Stagehand.create(browser=browser, model=Recorder().generate)
    try:
        page = await browser.context.active_page() or (await browser.context.pages())[0]
        await page.goto(f"http://127.0.0.1:{port}/persist")
        await page.wait_for_timeout(500)
        cookie = await page.evaluate("document.cookie")
        ls = await page.evaluate("localStorage.getItem('spike')")
    finally:
        await sh.close()
        await browser.close()
    return {"cookie_survived": f"spike={token}" in str(cookie), "localstorage_survived": ls == token,
            "profile_dir_exists_after_close": profile.exists()}


async def exposure(profile: Path, port: int, headless: bool) -> dict:
    proxy = DenyProxy()
    await proxy.start()
    browser = await launch(profile, headless, proxy.port)
    rec = Recorder()
    sh = await Stagehand.create(browser=browser, model=rec.generate)
    result: dict = {}
    try:
        page = await browser.context.active_page() or (await browser.context.pages())[0]
        await page.goto(f"http://127.0.0.1:{port}/secret")
        await page.wait_for_timeout(500)

        t0 = time.monotonic()
        obs = await sh.observe("find the button that creates a new app")
        result["observe_plain"] = {
            "model_calls": len(rec.calls),
            "latency_ms_excluding_model": round((time.monotonic() - t0) * 1000),
            "fake_secret_seen_by_model": leak_report(rec.text()),
            "returned_actions": len(obs.data),
            "request_keys": sorted(rec.calls[0].keys()) if rec.calls else [],
        }
        # Save one raw request locally (git-ignored) so a human can inspect the format.
        raw_dir = REPO / "docs" / "spikes" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "stagehand_observe_request.json").write_text(json.dumps(rec.calls[:1], indent=2))

        before = len(rec.calls)
        await sh.observe(
            "find the button that creates a new app",
            ignore_locators=[page.locator("#cred-panel")],
        )
        ignored_blob = json.dumps(rec.calls[before:])
        result["observe_with_ignore_locators"] = {
            "model_calls": len(rec.calls) - before,
            "fake_secret_seen_by_model": leak_report(ignored_blob),
        }

        before = len(rec.calls)
        scoped = await sh.observe("find the button", locator=page.locator("nav"))
        result["observe_scoped_to_nav"] = {
            "model_calls": len(rec.calls) - before,
            "fake_secret_seen_by_model": leak_report(json.dumps(rec.calls[before:])),
            "returned_actions": len(scoped.data),
        }

        # D. Deterministic act with an explicit Action (no instruction text).
        from stagehand._generated.models import Action
        before = len(rec.calls)
        clicked_marker = await page.evaluate(
            "document.getElementById('create').addEventListener('click',"
            "()=>{window.__clicked=true}); true")
        act_err = None
        try:
            await sh.act(Action.model_validate({
                "selector": "#create", "description": "Create new app button", "method": "click",
                "arguments": []}))
        except Exception as exc:  # record, don't crash the spike
            act_err = f"{type(exc).__name__}: {str(exc)[:200]}"
        result["act_with_action"] = {
            "model_calls": len(rec.calls) - before,
            "clicked": bool(await page.evaluate("window.__clicked === true")) if clicked_marker else None,
            "error": act_err,
        }

        # Plain browser code read of the secret (the path CredAgent will use).
        before = len(rec.calls)
        val = await page.evaluate("document.getElementById('client-secret').textContent")
        result["plain_code_read"] = {"model_calls": len(rec.calls) - before,
                                     "value_matches": val == FAKE["code_text"]}
    finally:
        await sh.close()
        await browser.close()
        await proxy.stop()
    result["offmachine_hosts_attempted_via_proxy"] = sorted(set(proxy.hosts))
    return result


# ------------------------------------------- CredAgent-owned Chrome (D-012)

async def _attach(port: int):
    browser = await local_browser.connect(cdp_url=f"http://127.0.0.1:{port}")
    sh = await Stagehand.create(browser=browser, model=Recorder().generate)
    page = await browser.context.active_page() or (await browser.context.pages())[0]
    return browser, sh, page


async def _read_state(page, port: int) -> tuple[str, str]:
    await page.goto(f"http://127.0.0.1:{port}/persist")
    await page.wait_for_timeout(300)
    return str(await page.evaluate("document.cookie")), await page.evaluate(
        "localStorage.getItem('spike')")


async def owned_phase(args) -> dict:
    profile = Path(args.profile)
    if args.phase in ("owned-set", "owned-set-detach"):
        chrome = ChromeProcess.launch(profile, headless=args.headless)
        browser, sh, page = await _attach(chrome.port)
        await page.goto(f"http://127.0.0.1:{args.port}/persist?set={args.token}")
        await page.wait_for_timeout(300)
        await browser.disconnect()
        if args.phase == "owned-set":
            ended = await chrome.graceful_close()
            return {"chrome_close": ended}
        return {"chrome_pid": chrome.pid, "chrome_port": chrome.port, "left_running": chrome.is_running()}
    if args.phase == "owned-reattach":
        chrome = ChromeProcess(pid=args.pid, port=args.chrome_port, profile_dir=profile)
        running = chrome.is_running()
        browser, sh, page = await _attach(chrome.port)
        cookie, ls = await _read_state(page, args.port)
        await browser.disconnect()
        ended = await chrome.graceful_close()
        return {"was_running_after_python_exit": running,
                "cookie_present": f"spike={args.token}" in cookie,
                "localstorage_present": ls == args.token, "chrome_close": ended}
    # owned-check: fresh Chrome on the same profile
    chrome = ChromeProcess.launch(profile, headless=args.headless)
    browser, sh, page = await _attach(chrome.port)
    cookie, ls = await _read_state(page, args.port)
    await browser.disconnect()
    ended = await chrome.graceful_close()
    return {"cookie_survived": f"spike={args.token}" in cookie,
            "localstorage_survived": ls == args.token, "chrome_close": ended}


def run_phase(phase: str, port: int, profile: Path, token: str, headless: bool, **extra) -> dict:
    cmd = [sys.executable, __file__, "--phase", phase, "--profile", str(profile), "--token", token,
           "--port", str(port)] + (["--headless"] if headless else [])
    for k, v in extra.items():
        cmd += [f"--{k.replace('_', '-')}", str(v)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": (proc.stderr or proc.stdout)[-600:]}


def python_offmachine_connections() -> list[str]:
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(os.getpid()), "-i", "-n", "-P"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ["lsof unavailable"]
    return [ln for ln in out.splitlines()[1:] if "127.0.0.1" not in ln and "[::1]" not in ln
            and "localhost" not in ln]


async def main_async(args) -> int:
    settings = load_settings()
    profiles = ensure_private_dir(settings.profiles_dir)
    profile = profiles / f"spike-{int(time.time())}"
    if args.phase == "check":  # uses the parent process's server
        print(json.dumps(await persist_check(Path(args.profile), args.port, args.token, args.headless)))
        return 0
    if args.phase.startswith("owned-"):
        print(json.dumps(await owned_phase(args)))
        return 0
    srv = serve(0)
    port = srv.server_address[1]

    summary: dict = {"stagehand_version": __import__("importlib.metadata").metadata.version("stagehand"),
                     "headless": args.headless, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    token = pysecrets.token_hex(8)
    t0 = time.monotonic()
    summary["persist_set"] = await persist_set(profile, port, token, args.headless)
    summary["launch_and_close_s"] = round(time.monotonic() - t0, 1)
    # Restart: a brand-new Python process re-opens the same profile.
    proc = subprocess.run(
        [sys.executable, __file__, "--phase", "check", "--profile", str(profile), "--token", token,
         "--port", str(port)] + (["--headless"] if args.headless else []),
        capture_output=True, text=True, timeout=180)
    try:
        summary["persist_after_process_restart"] = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        summary["persist_after_process_restart"] = {"error": proc.stderr[-500:]}
    # Owned Chrome, graceful close, then relaunch in a new process.
    p1, t1 = profiles / f"spike-owned-{int(time.time())}", pysecrets.token_hex(8)
    summary["owned_graceful"] = {
        "set": run_phase("owned-set", port, p1, t1, args.headless),
        "after_relaunch": run_phase("owned-check", port, p1, t1, args.headless),
    }
    # Owned Chrome left open while the Python process exits (terminal closed mid-handoff).
    p2, t2 = profiles / f"spike-detach-{int(time.time())}", pysecrets.token_hex(8)
    setr = run_phase("owned-set-detach", port, p2, t2, args.headless)
    summary["owned_detach"] = {"set": setr}
    if "chrome_pid" in setr:
        summary["owned_detach"]["reattach_new_process"] = run_phase(
            "owned-reattach", port, p2, t2, args.headless, pid=setr["chrome_pid"],
            chrome_port=setr["chrome_port"])
        summary["owned_detach"]["after_relaunch"] = run_phase("owned-check", port, p2, t2, args.headless)
    summary["profile_dir_mode"] = oct(profile.stat().st_mode & 0o777) if profile.exists() else None

    summary["exposure"] = await exposure(profiles / f"spike-exposure-{int(time.time())}", port,
                                         args.headless)
    summary["python_offmachine_connections_at_end"] = python_offmachine_connections()
    srv.shutdown()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--phase", default="all", choices=[
        "all", "check", "owned-set", "owned-set-detach", "owned-reattach", "owned-check"])
    ap.add_argument("--pid", type=int)
    ap.add_argument("--chrome-port", type=int)
    ap.add_argument("--profile")
    ap.add_argument("--token")
    ap.add_argument("--port", type=int, default=0)
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
