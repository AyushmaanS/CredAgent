#!/usr/bin/env python3
"""Sprint 0 spike: FastRouter LLM + Jev, and Stagehand's model routed via FastRouter.

Needs FASTROUTER_API_KEY in .env.local. Never prints the key.
Usage: .venv/bin/python scripts/spikes/spike_fastrouter.py [--jev-trials 5] [--no-stagehand]
Writes docs/spikes/fastrouter.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import httpx  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from credagent.config.settings import load_settings  # noqa: E402
from credagent.decisions.jev import Candidate, PageState, build_questions, parse_response  # noqa: E402
from credagent.reasoning.fastrouter import (  # noqa: E402
    FastRouterClient,
    ModelCallError,
    ServiceUnavailable,
)
from credagent.secrets.masking import Masker  # noqa: E402

OUT = REPO / "docs" / "spikes" / "fastrouter.json"


def stats(ms: list[int]) -> dict:
    if not ms:
        return {}
    s = sorted(ms)
    return {"n": len(s), "min": s[0], "p50": round(statistics.median(s)), "max": s[-1],
            "p90": s[min(len(s) - 1, int(0.9 * len(s)))]}


def err(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:300]}"


# ------------------------------------------------------------------ models

def check_models(settings) -> dict:
    # httpx (certifi CA bundle); stdlib urllib fails TLS on this python.org build.
    r = httpx.get(f"{settings.fastrouter_base_url}/models", timeout=30)
    r.raise_for_status()
    data = {m["id"]: m for m in r.json()["data"]}
    out = {}
    for role, mid in (("llm", settings.llm_model), ("stagehand", settings.stagehand_model),
                      ("jev", settings.jev_model)):
        m = data.get(mid)
        out[role] = {"id": mid, "listed": m is not None, "active": bool(m and m.get("is_active")),
                     "structured_params": sorted(set(m.get("supported_parameters") or []) &
                                                 {"response_format", "structured_outputs"}) if m else []}
    return out


# ---------------------------------------------------------------- LLM

class PlanProbe(BaseModel):
    app_name: str
    credential_type: Literal["oauth_client", "api_key", "token", "sandbox_key", "other", "unknown"]
    console_url: str
    sourced_facts: list[str]
    unknowns: list[str]


PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["app_name", "credential_type", "console_url", "sourced_facts", "unknowns"],
    "properties": {
        "app_name": {"type": "string"},
        "credential_type": {"type": "string", "enum": ["oauth_client", "api_key", "token",
                                                       "sandbox_key", "other", "unknown"]},
        "console_url": {"type": "string"},
        "sourced_facts": {"type": "array", "items": {"type": "string"}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
}


def llm_checks(client: FastRouterClient, trials: int) -> dict:
    plain, structured = [], []
    for _ in range(trials):
        try:
            r = client.chat([{"role": "user", "content": "Reply with exactly the word OK."}],
                            max_tokens=10)
            plain.append({"ok": r["content"].strip().strip(".") == "OK", "latency_ms": r["latency_ms"],
                          "served_model": r["model"]})
        except Exception as exc:
            plain.append({"error": err(exc)})
    for strict in (True, False):
        for _ in range(trials):
            try:
                r = client.chat(
                    [{"role": "system", "content": "You fill in a JSON plan skeleton. Use 'unknown' "
                      "and list unknowns rather than guessing. You have no sources in this test."},
                     {"role": "user", "content": "App: 'Acme Widgets' (fictional). Draft the skeleton."}],
                    json_schema=PLAN_SCHEMA, schema_name="plan_probe", strict=strict, max_tokens=600)
                try:
                    PlanProbe.model_validate(r["parsed"])
                    valid = True
                except ValidationError:
                    valid = False
                structured.append({"strict": strict, "valid": valid, "latency_ms": r["latency_ms"],
                                   "served_model": r["model"]})
            except Exception as exc:
                structured.append({"strict": strict, "error": err(exc)})
    return {
        "plain": plain, "plain_latency": stats([x["latency_ms"] for x in plain if "latency_ms" in x]),
        "structured": structured,
        "structured_latency": stats([x["latency_ms"] for x in structured if "latency_ms" in x]),
    }


# ---------------------------------------------------------------- Jev

STATES = {
    "sign_in_wall": (PageState(
        step_goal="Open the developer console's app list",
        url="https://console.example-provider.test/login", title="Sign in",
        visible_text="Sign in to Example Developer Console. Email. Password. Sign in. "
                     "Forgot password? Create account.",
        candidates=[Candidate(id="c0", description="Email textbox", method="fill"),
                    Candidate(id="c1", description="Password textbox", method="fill"),
                    Candidate(id="c2", description="Sign in button", method="click")]),
        {"blocker": True, "completion": False}),
    "create_form": (PageState(
        step_goal="Fill in the application name field",
        url="https://console.example-provider.test/apps/new", title="Register a new OAuth app",
        visible_text="Register a new OAuth application. Application name. Homepage URL. "
                     "Authorization callback URL. Register application.",
        candidates=[Candidate(id="c0", description="Application name textbox", method="fill"),
                    Candidate(id="c1", description="Homepage URL textbox", method="fill"),
                    Candidate(id="c2", description="Register application button", method="click"),
                    Candidate(id="c3", description="Docs link", method="click")]),
        {"blocker": False, "completion": False, "element": "c0", "action": "proceed"}),
    "implied_terms": (PageState(
        step_goal="Submit the create-app form",
        url="https://console.example-provider.test/apps/new", title="Create app",
        visible_text="App name: demo. By clicking Create, you agree to the Developer Terms of "
                     "Service and the API Policy. Create.",
        candidates=[Candidate(id="c0", description="Create button", method="click"),
                    Candidate(id="c1", description="Developer Terms of Service link", method="click")]),
        {"blocker": True, "completion": False}),
    "credential_shown": (PageState(
        step_goal="Capture the newly created client secret",
        url="https://console.example-provider.test/apps/123", title="demo app",
        visible_text="Client ID: [REDACTED:id]. Client secret (shown only once, copy it now): "
                     "[REDACTED:high_entropy]. Copy. Done.",
        candidates=[Candidate(id="c0", description="Copy button", method="click"),
                    Candidate(id="c1", description="Done button", method="click")]),
        {"blocker": False, "completion": True}),
    "captcha": (PageState(
        step_goal="Continue to the developer console",
        url="https://console.example-provider.test/challenge", title="Just a moment",
        visible_text="Verify you are human. I'm not a robot. Checking your browser.",
        candidates=[Candidate(id="c0", description="I'm not a robot checkbox", method="click")]),
        {"blocker": True, "completion": False}),
}


def jev_checks(client: FastRouterClient, trials: int) -> dict:
    out: dict = {"per_state": {}, "latencies": [], "served_models": set(), "errors": []}
    for name, (state, expect) in STATES.items():
        rows = []
        for _ in range(trials):
            try:
                resp = client.systemone(state.model_dump(), build_questions(state))
            except (ServiceUnavailable, ModelCallError) as exc:
                out["errors"].append(err(exc))
                continue
            d = parse_response(state, resp)
            out["latencies"].append(resp["latency_ms"])
            out["served_models"].add(resp.get("model"))
            answers = resp.get("answers", {})
            shape_ok = all(k in answers for k in build_questions(state))
            rows.append({
                "shape_ok": shape_ok,
                "element": (d["element_selection"].value, round(d["element_selection"].confidence, 2)),
                "action": (d["action_selection"].value, round(d["action_selection"].confidence, 2)),
                "blocker_p": answers.get("blocker_detection", {}).get("noul"),
                "risk": (d["risk_assessment"].value, round(d["risk_assessment"].confidence, 2)),
                "completion_p": answers.get("completion_detection", {}).get("noul"),
                "uncertain": [k for k, v in d.decisions.items() if v.uncertain],
                "matches_expected": {
                    k: (d["blocker_detection"].value == v if k == "blocker" else
                        d["completion_detection"].value == v if k == "completion" else
                        d["element_selection"].value == v if k == "element" else
                        d["action_selection"].value == v)
                    for k, v in expect.items()},
            })
        out["per_state"][name] = rows
    out["latency"] = stats(out.pop("latencies"))
    out["served_models"] = sorted(m for m in out["served_models"] if m)
    return out


def failure_mapping(settings, masker) -> dict:
    res = {}
    c = FastRouterClient(settings, masker)
    try:
        c.chat([{"role": "user", "content": "x"}], model="typesafe/does-not-exist", max_tokens=5)
        res["unknown_model"] = "no error (unexpected)"
    except Exception as exc:
        res["unknown_model"] = type(exc).__name__
    down = FastRouterClient(replace(settings, fastrouter_base_url="http://127.0.0.1:9"), masker,
                            timeout_s=3)
    try:
        down.systemone("x", {})
        res["unreachable"] = "no error (unexpected)"
    except Exception as exc:
        res["unreachable"] = type(exc).__name__
    return res


# ------------------------------------------------------ Stagehand via FastRouter

FORM = b"""<!doctype html><title>Fake Console - Apps</title><h1>Your apps (fake)</h1>
<a href="/docs">Documentation</a> <button id="delete">Delete selected app</button>
<button id="new">Create new app</button> <a href="/billing">Billing</a>"""


async def stagehand_live(client: FastRouterClient, model: str) -> dict:
    from stagehand import Stagehand, local_browser

    from credagent.browser.chrome import ChromeProcess
    from credagent.browser.stagehand_llm import make_generate

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(FORM)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    settings = load_settings()
    chrome = ChromeProcess.launch(settings.profiles_dir / "spike-fastrouter")
    results = {}
    try:
        for strict in (False, True):
            browser = await local_browser.connect(cdp_url=chrome.cdp_url)
            sh = await Stagehand.create(browser=browser, model=make_generate(client, model, strict=strict))
            try:
                page = await browser.context.active_page() or (await browser.context.pages())[0]
                await page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
                t0 = time.monotonic()
                obs = await sh.observe("find the button that creates a new app")
                results[f"strict_{strict}"] = {
                    "latency_ms": round((time.monotonic() - t0) * 1000),
                    "actions": [{"selector": a.selector, "description": a.description} for a in obs.data],
                    "picked_create": any("new" in a.selector or "Create" in a.description
                                         for a in obs.data[:1]),
                }
            except Exception as exc:
                results[f"strict_{strict}"] = {"error": err(exc)}
            finally:
                await browser.disconnect()
    finally:
        await chrome.graceful_close()
        srv.shutdown()
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--jev-trials", type=int, default=5)
    ap.add_argument("--no-stagehand", action="store_true")
    args = ap.parse_args()
    settings = load_settings()
    if not settings.fastrouter_api_key:
        print("FASTROUTER_API_KEY missing — see README 'Local environment'.")
        return 1
    masker = Masker()
    client = FastRouterClient(settings, masker)
    summary = {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "base_url": settings.fastrouter_base_url}
    steps = [("models", lambda: check_models(settings)),
             ("llm", lambda: llm_checks(client, args.trials)),
             ("jev", lambda: jev_checks(client, args.jev_trials)),
             ("failure_mapping", lambda: failure_mapping(settings, masker))]
    if not args.no_stagehand:
        steps.append(("stagehand_via_fastrouter",
                      lambda: asyncio.run(stagehand_live(client, settings.stagehand_model))))
    for name, fn in steps:
        print(f"... {name}", flush=True)
        try:
            summary[name] = fn()
        except Exception as exc:
            summary[name] = {"error": err(exc)}
    text = masker.mask_text(json.dumps(summary, indent=2, default=str))
    assert settings.fastrouter_api_key not in text
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
