"""The actual page, driven like a person would (opt-in: CREDAGENT_BROWSER_TESTS=1): enter an app name, follow the
progress, answer a handoff, see the masked credential, reveal and copy it, refresh mid-run, and a phone-sized screen.
Backed by the real server and orchestrator with the fake provider and the offline model stand-in.
"""

import asyncio
import os
import re

import pytest
from playwright.async_api import async_playwright, expect

from credagent.browser.chrome import MAC_CHROME
from credagent.secrets.store import SecretFileStore
from tests.web_harness import Ui

pytestmark = pytest.mark.skipif(os.environ.get("CREDAGENT_BROWSER_TESTS") != "1",
                                reason="set CREDAGENT_BROWSER_TESTS=1 to run real-browser tests")
TERMS = ("(() => { const t = document.getElementById('accept-terms'); if (t) t.click();"
         " document.getElementById('create-app').click(); })()")


@pytest.fixture
def ui():
    u = Ui()
    yield u
    u.settle()
    u.close()


async def open_page(p, ui, *, width=1000, height=900):
    browser = await p.chromium.launch(executable_path=str(MAC_CHROME), headless=True)
    ctx = await browser.new_context(viewport={"width": width, "height": height})
    await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=f"http://127.0.0.1:{ui.httpd.server_address[1]}")
    page = await ctx.new_page()
    logs, urls = [], []
    page.on("console", lambda m: logs.append(m.text))
    page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"))
    page.on("request", lambda r: urls.append(r.url))
    await page.goto(ui.url)
    return browser, page, logs, urls


async def start_test_run(page, ui, scenario, name="Test app"):
    """The page starts real applications only; a test run on the local test site is started through the API (as a
    script or the CLI would) and then followed in the page by its link."""
    await expect(page.get_by_role("heading", name="Get access to any app.")).to_be_visible()
    run_id = ui.start(scenario)
    await page.evaluate(f"location.hash = '#/run/{run_id}'")
    return run_id


def test_the_whole_journey_in_the_page(ui):
    async def go():
        async with async_playwright() as p:
            browser, page, logs, urls = await open_page(p, ui)
            try:
                await expect(page).to_have_title("CredAgent")
                await expect(page.get_by_role("button", name="GitHub")).to_be_visible()  # suggestions fill the input only
                await page.get_by_role("button", name="Linear").click()
                assert await page.input_value("#app-name") == "Linear"
                # one name and one button: nothing else on the landing page
                assert await page.locator("details, select, [aria-label='Recent runs']").count() == 0
                # no research keys in the test environment, so starting is refused up front and the page says why
                await expect(page.get_by_role("button", name="Get credentials")).to_be_disabled()
                await expect(page.get_by_text("add FASTROUTER_API_KEY and TAVILY_API_KEY")).to_be_visible()
                await start_test_run(page, ui, "terms_checkbox")

                # Running → needs attention, with a plain explanation and a way to continue
                await expect(page.locator(".attn-title")).to_contain_text("Your attention is needed", timeout=90_000)
                await expect(page.get_by_role("heading", name=re.compile("Review and accept"))).to_be_visible()
                await expect(page.get_by_role("list", name="Progress")).to_be_visible()
                await expect(page.get_by_role("button", name="I've done this")).to_be_enabled()
                await expect(page).to_have_title(re.compile("Your attention is needed"))
                assert "press Enter" not in (await page.inner_text("#app")).lower()

                # A refresh does not lose the run: the state is read back from the backend
                await page.reload()
                await expect(page.locator(".attn-title")).to_contain_text("Your attention is needed", timeout=30_000)
                run_id = re.search(r"#/run/([\w.-]+)", page.url).group(1)

                # The person acts in the agent's window, then continues here
                await ui.aperson(run_id, TERMS)
                await page.get_by_role("button", name="I've done this").click()
                await expect(page.get_by_role("heading", name="Credentials verified")).to_be_visible(timeout=90_000)
                await expect(page.locator(".pill.ok")).to_have_text("Verified")

                # Masked by default; revealed only on a click; hidden again; copyable; never stored or logged
                secret = SecretFileStore(ui.settings.secrets_dir).get(
                    ui.service.read_store.load(run_id).run.credential.parts["client_secret"].store_ref)
                body = await page.content()
                assert secret not in body
                row = page.locator(".cred", has_text="Client secret")
                await expect(row.locator(".val")).to_have_text(re.compile(r"…? ?\(\d+ chars\)"))  # the backend's masked display
                await row.get_by_role("button", name="Reveal Client secret").click()
                await expect(row.locator(".val")).to_have_text(secret)
                await row.get_by_role("button", name="Hide Client secret").click()
                await expect(row.locator(".val")).not_to_have_text(secret)
                assert secret not in await page.content()
                await row.get_by_role("button", name="Copy Client secret").click()
                await expect(row.locator(".toast")).to_contain_text("Copied")
                assert await page.evaluate("navigator.clipboard.readText()") == secret
                assert await page.evaluate("[localStorage.length, sessionStorage.length]") == [0, 0]
                assert not any(secret in x for x in logs + urls)
                assert not any(secret in c["value"] for c in await page.context.cookies())
                assert not [x for x in logs if x.startswith("pageerror")], logs
            finally:
                await browser.close()
    asyncio.run(go())


def test_a_choice_is_made_with_a_radio_and_a_confirm_button(ui):
    async def go():
        async with async_playwright() as p:
            browser, page, _logs, _urls = await open_page(p, ui)
            try:
                await start_test_run(page, ui, "decide_app_type_and_scopes")
                await expect(page.get_by_text("Your decision")).to_be_visible(timeout=90_000)
                confirm = page.get_by_role("button", name="Confirm choice")
                await expect(confirm).to_be_disabled()
                await page.get_by_role("radio").first.check()
                await expect(confirm).to_be_enabled()
                await confirm.click()
                await expect(page.get_by_role("heading", name="Credentials verified")).to_be_visible(timeout=90_000)
            finally:
                await browser.close()
    asyncio.run(go())


def test_save_and_stop_then_resume_from_the_page(ui):
    async def go():
        async with async_playwright() as p:
            browser, page, _logs, _urls = await open_page(p, ui)
            try:
                await start_test_run(page, ui, "terms_checkbox")
                await expect(page.locator(".attn-title")).to_contain_text("Your attention is needed", timeout=90_000)
                run_id = re.search(r"#/run/([\w.-]+)", page.url).group(1)
                await page.get_by_role("button", name="Save and stop").click()
                await expect(page.get_by_role("heading", name="This run is saved and waiting")).to_be_visible(timeout=30_000)
                ui.settle()
                await page.get_by_role("button", name="Resume", exact=True).click()
                await expect(page.locator(".attn-title")).to_contain_text("Your attention is needed", timeout=90_000)
                await ui.aperson(run_id, TERMS)
                await page.get_by_role("button", name="I've done this").click()
                await expect(page.get_by_role("heading", name="Credentials verified")).to_be_visible(timeout=90_000)
            finally:
                await browser.close()
    asyncio.run(go())


def test_a_failure_says_what_happened_and_offers_resume(ui):
    async def go():
        async with async_playwright() as p:
            browser, page, _logs, _urls = await open_page(p, ui)
            try:
                await start_test_run(page, ui, "service_unavailable")
                await expect(page.get_by_role("heading", name="The run stopped, and it can continue")).to_be_visible(timeout=90_000)
                await expect(page.get_by_text("Recoverable")).to_be_visible()
                await expect(page.get_by_role("button", name="Resume this run")).to_be_enabled()
                await expect(page.get_by_text("What you can do")).to_be_visible()
            finally:
                await browser.close()
    asyncio.run(go())


def test_the_page_works_on_a_phone_sized_screen(ui):
    async def go():
        async with async_playwright() as p:
            browser, page, _logs, _urls = await open_page(p, ui, width=375, height=812)
            try:
                assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                await start_test_run(page, ui, "success")
                await expect(page.get_by_role("heading", name="Credentials verified")).to_be_visible(timeout=90_000)
                assert await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                for name in ("Reveal Client secret", "Copy Client secret"):
                    box = await page.get_by_role("button", name=name).bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 375
            finally:
                await browser.close()
    asyncio.run(go())


def test_without_the_launch_link_the_page_explains_how_to_sign_in(ui):
    async def go():
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=str(MAC_CHROME), headless=True)
            page = await (await browser.new_context()).new_page()
            try:
                await page.goto(f"http://127.0.0.1:{ui.httpd.server_address[1]}/")  # no token, so no cookie
                await expect(page.get_by_role("heading", name="Open CredAgent from its link")).to_be_visible(timeout=10_000)
            finally:
                await browser.close()
    asyncio.run(go())


def test_a_missing_console_address_is_asked_for_in_the_page(ui):
    from tests.web_harness import run_waiting_for_the_console

    _ctl, got = run_waiting_for_the_console(ui)

    async def go():
        async with async_playwright() as p:
            browser, page, _logs, _urls = await open_page(p, ui)
            try:
                await page.evaluate("location.hash = '#/run/r-console'")
                await expect(page.get_by_role("heading", name="Where is the developer console?")).to_be_visible(timeout=15_000)
                await expect(page.get_by_text("Research could not find the address")).to_be_visible()
                await expect(page.get_by_role("button", name="Continue")).to_be_disabled()
                await page.get_by_label("Developer console address").fill("console.acme.example")
                await page.get_by_role("button", name="Continue").click()
                await expect(page.get_by_text("Use the full address")).to_be_visible()  # refused, with the reason
                await page.get_by_label("Developer console address").fill("https://console.acme.example/apps")
                await page.get_by_role("button", name="Continue").click()
            finally:
                await browser.close()
    asyncio.run(go())
    assert got == ["https://console.acme.example/apps"]
