"""Fakeprov in a real Chrome, through CredAgent's ChromeProcess + Stagehand.

Opt-in (launches Chrome): CREDAGENT_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/integration
Headed by default so a person can watch; set CREDAGENT_HEADLESS=1 to hide the window.
No model API is called: Stagehand gets a recording callback with canned replies.
"""

import asyncio
import json
import os
import shutil

import httpx
import pytest
from fake_provider.app import FakeProvider, Scenario
from fake_provider.app.server import TEST_EMAIL, TEST_PASSWORD

from credagent.browser.chrome import ChromeProcess
from credagent.secrets.masking import Masker

pytestmark = pytest.mark.skipif(os.environ.get("CREDAGENT_BROWSER_TESTS") != "1",
                                reason="set CREDAGENT_BROWSER_TESTS=1 to run real-browser tests")
HEADLESS = os.environ.get("CREDAGENT_HEADLESS") == "1"


def minimal(schema, defs=None):
    defs = defs if defs is not None else schema.get("$defs", {})
    if "$ref" in schema:
        return minimal(defs[schema["$ref"].split("/")[-1]], defs)
    for k in ("anyOf", "oneOf", "allOf"):
        if k in schema:
            return minimal(schema[k][0], defs)
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type")
    t = next((x for x in t if x != "null"), None) if isinstance(t, list) else t
    if t == "object":
        props = schema.get("properties", {})
        return {k: minimal(props[k], defs) for k in schema.get("required", []) if k in props}
    return {"array": [], "string": "", "number": 0, "integer": 0, "boolean": False}.get(t)


class Recorder:
    def __init__(self):
        self.calls = []

    async def generate(self, params):
        from stagehand._generated.models import LLMStructuredGenerateResult
        d = params.model_dump(mode="json", by_alias=True)
        self.calls.append(d)
        out = minimal(d["response_format"]["schema"])
        return LLMStructuredGenerateResult.model_validate({
            "role": "assistant", "content": {"type": "text", "text": json.dumps(out)},
            "output_format": "json_schema", "structured_content": out})


async def attach(chrome, rec):
    from stagehand import Stagehand, local_browser
    browser = await local_browser.connect(cdp_url=chrome.cdp_url)
    sh = await Stagehand.create(browser=browser, model=rec.generate)
    page = await browser.context.active_page() or (await browser.context.pages())[0]
    return browser, sh, page


async def as_person(page, fn):
    """Simulate the human: requests carry X-Fakeprov-Actor: person while fn runs."""
    await page.set_extra_http_headers({"X-Fakeprov-Actor": "person"})
    try:
        await fn()
    finally:
        await page.set_extra_http_headers({})


async def scenario_flow(tmp_path):
    profile = tmp_path / "profile"
    results = {}
    with FakeProvider(Scenario(require_signin=True, terms="checkbox", cookie_banner="reject")) as fp:
        chrome = ChromeProcess.launch(profile, headless=HEADLESS)
        rec = Recorder()
        try:
            browser, sh, page = await attach(chrome, rec)
            await page.goto(fp.base_url + "/console")
            results["redirected_to_login"] = "/login" in await page.url()

            # Agent: choose the limited cookie option with a plain click.
            # A single click right after load occasionally has no effect in headless Chrome (observed in Sprint 5:
            # banner still shown, no cookie). The agent's loop re-observes and clicks again; do the same here.
            for _ in range(3):
                await page.locator("xpath=//div[@id='cookie-banner']//button[@value='reject']").click()
                for _ in range(10):
                    if fp.audit("cookie_choice"):
                        break
                    await page.wait_for_timeout(100)
                if fp.audit("cookie_choice"):
                    break
            results["cookie_choice"] = [a["choice"] for a in fp.audit("cookie_choice")]

            # Person: sign in (DO handoff in the real flow).
            async def sign_in():
                await page.locator("xpath=//input[@name='email']").fill(TEST_EMAIL)
                await page.locator("xpath=//input[@name='password']").fill(TEST_PASSWORD)
                await page.locator("xpath=//button[@type='submit']").click()
                await page.wait_for_timeout(500)
            await as_person(page, sign_in)
            results["signed_in"] = "/console" in await page.url()
            await browser.disconnect()
        finally:
            results["first_close"] = await chrome.graceful_close()

        # Restart Chrome on the same profile: sign-in must persist.
        chrome = ChromeProcess.launch(profile, headless=HEADLESS)
        try:
            browser, sh, page = await attach(chrome, rec)
            await page.goto(fp.base_url + "/console")
            results["still_signed_in_after_restart"] = "/console" in await page.url()
            results["cookie_banner_gone"] = await page.evaluate(
                "document.getElementById('cookie-banner') === null")

            # Agent fills non-terms fields; person ticks terms and submits.
            await page.goto(fp.base_url + "/apps/new")
            await page.locator("xpath=//input[@name='name']").fill("credagent-demo")
            await page.locator("xpath=//input[@name='redirect_uri']").fill(
                "http://127.0.0.1:8976/callback")
            results["terms_unticked_by_agent"] = not await page.locator("#accept-terms").is_checked()

            async def accept_and_create():
                await page.locator("#accept-terms").click()
                await page.locator("#create-app").click()
                await page.wait_for_timeout(600)
            await as_person(page, accept_and_create)

            # Agent: observe the credential page with the credentials panel excluded.
            before = len(rec.calls)
            await sh.observe("find the Done or Back to console link",
                             ignore_locators=[page.locator("#credentials")])
            sent = json.dumps(rec.calls[before:])
            results["observe_model_calls"] = len(rec.calls) - before
            results["model_saw_page"] = "Credentials" not in sent and "credagent-demo" in sent

            # Agent: read the shown-once secret by plain code only.
            cid = await page.evaluate("document.getElementById('client-id').textContent")
            secret = await page.evaluate(
                "(document.getElementById('client-secret')||{}).textContent || null")
            results["secret_captured"] = bool(secret and secret.startswith("fpcs_"))
            results["secret_not_sent_to_model"] = bool(secret) and secret not in sent and cid not in sent
            results["masker_would_mask_it"] = secret not in Masker([secret]).mask_text(f"x {secret} y")

            await page.reload()
            await page.wait_for_timeout(300)
            results["hidden_after_reload"] = await page.evaluate(
                "document.getElementById('client-secret') === null")

            # Live test of the captured credential against the mock token endpoint.
            r = httpx.post(fp.base_url + "/oauth/token", data={"grant_type": "client_credentials"},
                           auth=(cid, secret), timeout=5)
            tok = r.json().get("access_token", "")
            me = httpx.get(fp.base_url + "/api/me", headers={"Authorization": f"Bearer {tok}"}, timeout=5)
            results["live_test_passed"] = r.status_code == 200 and me.status_code == 200
            await browser.disconnect()
        finally:
            results["second_close"] = await chrome.graceful_close()

        audit = fp.audit()
        results["terms_only_by_person"] = all(
            a["actor"] == "person" for a in audit if a["event"] == "terms_accepted")
        results["terms_accepted_count"] = len([a for a in audit if a["event"] == "terms_accepted"])
        results["forbidden_events"] = [a["event"] for a in audit if a["event"] in {
            "app_deleted", "submitted_for_review", "payment_entered", "secret_regenerated"}]
    shutil.rmtree(profile, ignore_errors=True)
    return results


def test_fake_provider_end_to_end_in_real_chrome(tmp_path):
    r = asyncio.run(scenario_flow(tmp_path))
    print(json.dumps(r, indent=2))
    assert r["redirected_to_login"]
    assert r["cookie_choice"] == ["reject"]
    assert r["signed_in"]
    assert r["first_close"] == "graceful" and r["second_close"] == "graceful"
    assert r["still_signed_in_after_restart"], "sign-in must survive a Chrome restart"
    assert r["cookie_banner_gone"]
    assert r["terms_unticked_by_agent"]
    assert r["secret_captured"]
    assert r["observe_model_calls"] >= 1, "observe must call the model for the leak check to mean anything"
    assert r["model_saw_page"], "the model request should contain the page minus the excluded panel"
    assert r["secret_not_sent_to_model"]
    assert r["masker_would_mask_it"]
    assert r["hidden_after_reload"]
    assert r["live_test_passed"]
    assert r["terms_only_by_person"] and r["terms_accepted_count"] == 1
    assert r["forbidden_events"] == []
