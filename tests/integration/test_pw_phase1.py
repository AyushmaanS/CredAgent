"""D-078 phase 1 in real Chrome (opt-in: CREDAGENT_BROWSER_TESTS=1): Playwright session over CDP, snapshot, executor.

Exit checks: executor actions work on the fake site; the profile persists across a graceful close; a paused
run's Chrome can be re-attached from a new connection; secrets never appear in a snapshot or an inspect result.
"""

import asyncio
import os

import pytest
from fake_provider.app import FakeProvider, Scenario

from credagent.browser.executor import BrowserClosed, Executor, approved_values
from credagent.browser.pw_session import open_pw_session
from credagent.browser.snapshot import describe_change, take_snapshot
from credagent.browser.values import FieldValues
from credagent.secrets.masking import Masker

pytestmark = pytest.mark.skipif(os.environ.get("CREDAGENT_BROWSER_TESTS") != "1",
                                reason="set CREDAGENT_BROWSER_TESTS=1 to run real-browser tests")
HEADLESS = os.environ.get("CREDAGENT_HEADLESS", "1") == "1"
CB = "http://127.0.0.1:8976/callback"
VALUES = FieldValues.default(CB)
FORM = Scenario(require_signin=False, terms="none", cookie_banner="none", app_type_choice=True, scope_choice=True)


def find(snap, role, name):
    hits = [e for e in snap.elements if e.role == role and name.lower() in e.name.lower()]
    assert hits, f"no {role} named {name!r}; have: {[(e.role, e.name) for e in snap.elements][:20]}"
    return hits[0].ref


def run(coro):
    return asyncio.run(coro)


def test_profile_persists_across_graceful_close_and_reattach_works(tmp_path):
    async def go():
        with FakeProvider(Scenario(require_signin=False, terms="none", cookie_banner="reject")) as fp:
            profile = tmp_path / "profile"
            s1 = await open_pw_session(profile, headless=HEADLESS)
            assert not s1.reattached
            await s1.page.goto(fp.base_url + "/console")
            await s1.page.locator("xpath=//div[@id='cookie-banner']//button[@value='reject']").click()
            for _ in range(20):
                if fp.audit("cookie_choice"):
                    break
                await s1.page.wait_for_timeout(100)
            assert fp.audit("cookie_choice")
            await s1.page.goto(fp.base_url + "/docs")

            # A handoff is open: disconnect and leave Chrome running; a later connection re-attaches to it.
            rec, pid = s1.record(), s1.chrome.pid
            await s1.detach()
            assert s1.chrome.is_running()
            s2 = await open_pw_session(profile, headless=HEADLESS, existing=rec)
            assert s2.reattached and s2.chrome.pid == pid
            assert s2.page.url.endswith("/docs")  # the page the person was looking at

            assert await s2.close() == "graceful"  # profile flushed
            s3 = await open_pw_session(profile, headless=HEADLESS)  # fresh Chrome, same profile
            try:
                assert not s3.reattached and s3.chrome.pid != pid
                cookies = {c["name"]: c["value"] for c in await s3.context.cookies()}
                assert cookies.get("fp_consent") == "reject"  # survived the restart
            finally:
                await s3.close()
    run(go())


def test_domain_guard_blocks_off_domain_navigation_and_lifts(tmp_path):
    async def go():
        with FakeProvider(Scenario(require_signin=False, terms="none", cookie_banner="none")) as fp:
            s = await open_pw_session(tmp_path / "profile", headless=HEADLESS)
            try:
                await s.page.goto(fp.base_url + "/console")
                await s.set_allowed_domains(["127.0.0.1"])
                off = f"http://partner.elsewhere.localhost:{fp.port}/partner"
                with pytest.raises(Exception, match="ERR_BLOCKED_BY_CLIENT"):
                    await s.page.goto(off)
                await s.page.wait_for_timeout(600)  # Chrome shows its error page; let it settle
                # through the executor: a plain "blocked" result, and the tab is put back where it was
                from credagent.browser.executor import Executor
                ex = Executor(s.page, Masker())
                await s.page.goto(fp.base_url + "/console")
                r = await ex.navigate(off)
                assert not r.ok and r.error == "blocked: that address is outside the allowed sites"
                assert s.page.url.endswith("/console") and r.url.endswith("/console")
                assert (await ex.navigate(fp.base_url + "/docs")).ok  # allowed host: fine
                await s.set_allowed_domains(None)  # the person's handoff lifts it
                assert (await ex.navigate(off)).ok and "elsewhere.localhost" in s.page.url
            finally:
                await s.close()
    run(go())


# The run's approved values are passed to every snapshot, as the agent loop does: the app name looks like a token
# and is exempt from the credential scan only because it is a known value (D-076, D-086).
NS = list(approved_values(VALUES).values())


def test_executor_actions_on_the_create_form(tmp_path):
    async def go():
        with FakeProvider(FORM) as fp:
            s = await open_pw_session(tmp_path / "profile", headless=HEADLESS)
            m = Masker()
            ex = Executor(s.page, m, approved=approved_values(VALUES))
            try:
                assert (await ex.navigate(fp.base_url + "/apps/new")).ok
                snap = await take_snapshot(ex.page, m, NS)
                name_ref = find(snap, "field", "Application name")

                # type: ok, and the value is never echoed back
                r = await ex.type(snap, name_ref, VALUES.app_name)
                assert r.ok and VALUES.app_name not in r.summary() and "typed into field" in r.detail
                after = await take_snapshot(ex.page, m, NS)
                assert "field “Application name” is now filled" in describe_change(snap, after)

                # inspect a field: only whether it holds an approved value (never the value itself)
                r = await ex.inspect(after, find(after, "field", "Application name"))
                assert r.ok and "holds the approved value: app_name" in r.text and VALUES.app_name not in r.text
                await ex.type(after, find(after, "field", "Description"), "something else entirely")
                again = await take_snapshot(ex.page, m, NS)
                r = await ex.inspect(again, find(again, "field", "Description"))
                assert "not one of the approved values" in r.text and "something else" not in r.text
                r = await ex.inspect(again, find(again, "field", "Homepage"))
                assert r.ok and "is empty" in r.text

                # select: a real option works, a made-up one lists the real ones
                kind = find(again, "select", "Application type")
                bad = await ex.select(again, kind, "Quantum app")
                assert not bad.ok and "is not one of:" in bad.error and "Web app" in bad.error
                good = await ex.select(again, kind, "Web app (confidential: can keep a client secret)")
                assert good.ok and "chose" in good.detail
                assert not (await ex.select(again, name_ref, "x")).ok  # not a dropdown

                # click a checkbox: the change is described
                scope = find(again, "checkbox", "read:profile")
                before = await take_snapshot(ex.page, m, NS)
                assert (await ex.click(before, scope)).ok
                assert "is now checked" in describe_change(before, await take_snapshot(ex.page, m, NS))

                # scroll, wait, back
                assert (await ex.scroll("down")).ok and (await ex.scroll("top")).ok
                assert not (await ex.scroll("sideways")).ok
                assert (await ex.wait(300)).ok and (await ex.wait(999_999)).detail == "waited 5000 ms"
                await ex.navigate(fp.base_url + "/docs")
                r = await ex.back()
                assert r.ok and r.url.endswith("/apps/new")

                # click the submit button: navigates to the new app's page
                snap = await take_snapshot(ex.page, m, NS)
                await ex.type(snap, find(snap, "field", "Authorization callback URL"), VALUES.redirect_uri)
                snap = await take_snapshot(ex.page, m, NS)
                r = await ex.click(snap, find(snap, "button", "Create app"))
                assert r.ok and "/apps/" in r.url
                assert "navigated to /apps/" in describe_change(snap, await take_snapshot(ex.page, m, NS))
                assert [a["event"] for a in fp.audit() if a["event"] == "app_created"] == ["app_created"]
            finally:
                await s.close()
    run(go())


def test_executor_refuses_stale_unknown_disabled_password_and_non_http(tmp_path):
    async def go():
        with FakeProvider(Scenario(require_signin=True, terms="none", cookie_banner="none")) as fp:
            s = await open_pw_session(tmp_path / "profile", headless=HEADLESS)
            m = Masker()
            ex = Executor(s.page, m, approved=approved_values(VALUES))
            try:
                await ex.navigate(fp.base_url + "/login")
                snap = await take_snapshot(ex.page, m)
                pw = find(snap, "field", "Password")
                r = await ex.type(snap, pw, "hunter2")
                assert not r.ok and "never typed by the agent" in r.error
                r = await ex.inspect(snap, pw)
                assert not r.ok and "never read" in r.error
                assert not (await ex.click(snap, "e999")).ok  # unknown ref
                assert "unknown ref" in (await ex.click(snap, "e999")).error
                assert not (await ex.navigate("file:///etc/passwd")).ok
                assert not (await ex.navigate("javascript:alert(1)")).ok

                link = find(snap, "link", "Create an account")
                await ex.navigate(fp.base_url + "/docs")  # the page moved: the old refs are stale
                r = await ex.click(snap, link)
                assert not r.ok and r.error.startswith("stale ref")
            finally:
                await s.close()
    run(go())


def test_snapshot_hides_credentials_and_inspect_cannot_reveal_them(tmp_path):
    async def go():
        with FakeProvider(Scenario(require_signin=False, terms="none", cookie_banner="none",
                                   secret_shown_once=True)) as fp:
            app = fp.state._new_app(VALUES.app_name, CB)  # its page shows the secret on first view
            s = await open_pw_session(tmp_path / "profile", headless=HEADLESS)
            m = Masker()
            ex = Executor(s.page, m, approved=approved_values(VALUES))
            try:
                await ex.navigate(f"{fp.base_url}/apps/{app.id}")
                # a read-only box holding a credential, as some portals render it
                await ex.page.evaluate("""(v) => document.body.insertAdjacentHTML('beforeend',
                    '<label>Client secret <input readonly value="' + v + '"></label>')""", app.client_secret)
                snap = await take_snapshot(ex.page, m)
                out = snap.render()
                assert app.client_secret not in out and snap.secret_count >= 1
                assert "[SECRET-ELEMENT]" in out
                assert not [e for e in snap.elements if "client secret" in e.name.lower() and e.role == "field"]
                # the visible action is still offered, so the agent can see what it could do
                regen = find(snap, "button", "Regenerate secret")
                r = await ex.inspect(snap, regen)
                assert r.ok and app.client_secret not in (r.text or "") + r.summary()
                # text containing a token is masked even if it comes through inspect
                m.register(app.client_secret, "client_secret")
                await ex.page.evaluate("""(v) => { document.querySelector('button').innerText = 'copy ' + v; }""",
                                       app.client_secret)
                snap2 = await take_snapshot(ex.page, m)
                r2 = await ex.inspect(snap2, find(snap2, "button", "copy"))
                assert app.client_secret not in (r2.text or "") and "REDACTED" in (r2.text or "")
            finally:
                await s.close()
    run(go())


def test_new_tab_is_adopted_and_a_closed_browser_raises(tmp_path):
    async def go():
        with FakeProvider(Scenario(require_signin=False, terms="none", cookie_banner="none")) as fp:
            s = await open_pw_session(tmp_path / "profile", headless=HEADLESS)
            m = Masker()
            ex = Executor(s.page, m)
            await ex.navigate(fp.base_url + "/console")
            await ex.page.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
                '<a href="/docs" target="_blank">Open the docs in a new tab</a>')""")
            snap = await take_snapshot(ex.page, m)
            r = await ex.click(snap, find(snap, "link", "Open the docs"))
            assert r.ok and r.new_tab and r.url.endswith("/docs") and ex.page.url.endswith("/docs")

            snap = await take_snapshot(ex.page, m)
            ref = find(snap, "link", "Console")
            await s.chrome.graceful_close()  # the person closed the window / Chrome went away
            with pytest.raises(BrowserClosed):
                await ex.click(snap, ref)
            await s.playwright.stop()
    run(go())
