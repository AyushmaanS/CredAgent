"""Sprint 5 in real Chrome (opt-in: CREDAGENT_BROWSER_TESTS=1): capture → live test → outcome, shown-once and
hidden secrets, resume after the browser closed or while it stayed open, in-doubt clicks, and leak scans.

Offline deciders, a harness playing the person (X-Fakeprov-Actor: person). After every run the test collects
every secret the fake site ever issued (client secrets and access tokens) and asserts none of them appears in
run state, the event log, the reports or anything printed to the terminal.
"""

import asyncio
import json
import os

import httpx
import pytest
from fake_provider.app import FakeProvider, scenario

from credagent.decisions.client import RuleJev
from credagent.orchestrator import (
    BrowserDeps,
    Orchestrator,
    execute_browser_phase,
    fake_provider_plan,
    resume_browser_phase,
)
from credagent.secrets.capture import load_into_masker
from credagent.secrets.masking import Masker
from credagent.secrets.store import SecretFileStore
from credagent.state.models import Run
from credagent.state.store import RunStore
from tests.integration.test_browser_loop_fake import HEADLESS, PersonIO, assert_safe

pytestmark = pytest.mark.skipif(os.environ.get("CREDAGENT_BROWSER_TESTS") != "1",
                                reason="set CREDAGENT_BROWSER_TESTS=1 to run real-browser tests")
CB = "http://127.0.0.1:8976/callback"


class Person(PersonIO):
    """PersonIO plus: regenerate a hidden secret; optionally refuse (close the terminal) at handoff N."""

    def __init__(self, page, *, quit_at=None, choose=None):
        super().__init__(page, choose)
        self.quit_at = quit_at
        self.n = 0

    async def wait_enter(self, prompt):
        self.n += 1
        if self.quit_at is not None and self.n >= self.quit_at:
            h = self.run.pending_handoff
            self.handoffs.append((h.kind, h.blocker_kind))
            return False  # the person closed the terminal
        h = self.run.pending_handoff
        if h.blocker_kind == "secret_hidden":
            self.handoffs.append((h.kind, h.blocker_kind))
            await self._as_person("Array.from(document.querySelectorAll('button')).find(b => "
                                  "b.innerText.includes('Regenerate')).click()")
            return True
        return await super().wait_enter(prompt)


def deps_for(tmp_path, *, ephemeral=True):
    return BrowserDeps(jev=RuleJev(), reasoner=None, llm_model=None, model_callback=None,
                       secret_store=SecretFileStore(tmp_path / "secrets"), profile_dir=tmp_path / "profile",
                       redirect_uri=CB, headless=HEADLESS, allow_dcr=False, ephemeral_profile=ephemeral)


class LateIO:
    """Binds a Person to the page once the orchestrator has opened the browser."""

    def __init__(self, **kw):
        self.kw = kw
        self.person = None
        self.out = []
        self.run = None

    def _p(self):
        return self.person

    def say(self, text):
        self.out.append(text)

    async def wait_enter(self, prompt):
        return await self.person.wait_enter(prompt)

    async def choose(self, prompt, options):
        return await self.person.choose(prompt, options)


def fake_secrets(fp):
    with fp.state.lock:
        return [a.client_secret for a in fp.state.apps.values()] + list(fp.state.tokens)


def assert_no_leak(tmp_path, run_id, secrets_, printed):
    assert secrets_, "nothing to look for"
    run_dir = tmp_path / "runs" / run_id
    for f in run_dir.rglob("*"):
        if f.is_file():
            body = f.read_text(encoding="utf-8", errors="replace")
            assert not any(s in body for s in secrets_), f"secret leaked into {f.name}"
    joined = "\n".join(printed)
    assert not any(s in joined for s in secrets_), "secret leaked into terminal output"


async def _phase(tmp_path, fp, run, deps, io, *, resume=False, in_doubt=None, masker=None):
    m = masker or Masker()
    store = RunStore(tmp_path / "runs", m)
    o = Orchestrator(store, m, None, io)

    # Bind the harness person to the page the orchestrator opens: patch open_session to capture the page.
    import credagent.browser.session as sess

    real_open = sess.open_session

    async def spy(*a, **kw):
        s = await real_open(*a, **kw)
        io.person = Person(s.page, **io.kw)
        io.person.run = run
        return s

    sess.open_session = spy
    try:
        if resume:
            return await resume_browser_phase(o, run, deps, io, in_doubt), store
        if not (tmp_path / "runs" / run.id).exists():
            store.create(run)
        return await execute_browser_phase(o, run, deps, fp.base_url + "/", io), store
    finally:
        sess.open_session = real_open


def new_run(fp, name):
    return Run(id=f"t5-{name}", app_input="Fakeprov", provider="Fakeprov (local)",
               plan=fake_provider_plan(fp.base_url))


@pytest.mark.parametrize("name", ["success", "shown_once_secret", "terms_checkbox", "secret_behind_reveal"])
def test_capture_and_live_test_succeed_without_leaks(tmp_path, name):
    with FakeProvider(scenario(name)) as fp:
        io = LateIO()
        run, store = asyncio.run(_phase(tmp_path, fp, new_run(fp, name), deps_for(tmp_path), io))
        secrets_ = fake_secrets(fp)
        audit = fp.audit()
    assert run.status == "succeeded", (run.status, run.status_reason)
    assert run.verification.label == "verified" and set(run.credential.parts) == {"client_id", "client_secret"}
    stored = SecretFileStore(tmp_path / "secrets").get(run.credential.parts["client_secret"].store_ref)
    assert stored in secrets_  # the value captured is the one the provider issued
    assert_safe(audit)
    assert_no_leak(tmp_path, run.id, secrets_, io.out)
    assert not (tmp_path / "profile").exists()  # fake run ended: profile removed


def test_shown_once_secret_is_captured_on_first_view(tmp_path):
    with FakeProvider(scenario("shown_once_secret")) as fp:
        io = LateIO()
        run, _ = asyncio.run(_phase(tmp_path, fp, new_run(fp, "once"), deps_for(tmp_path), io))
        (app,) = fp.state.apps.values()
        # the page was not reloaded after the capture: a second view would show it hidden
        r = httpx.get(f"{fp.base_url}/apps/{app.id}")
    assert run.status == "succeeded" and app.secret_unviewed is False
    assert "client-secret-hidden" in r.text  # it really was shown only once


def test_hidden_secret_hands_off_regeneration_to_the_person(tmp_path):
    with FakeProvider(scenario("shown_once_secret")) as fp:
        app = fp.state._new_app("credagent-demo-old", CB)
        httpx.get(f"{fp.base_url}/apps/{app.id}")  # someone viewed it earlier: the secret is now hidden
        old = app.client_secret
        io = LateIO()
        run = new_run(fp, "hidden")
        m = Masker()
        store = RunStore(tmp_path / "runs", m)
        store.create(run)

        async def go():
            o = Orchestrator(store, m, None, io)
            import credagent.browser.session as sess
            real = sess.open_session

            async def spy(*a, **kw):
                s = await real(*a, **kw)
                io.person = Person(s.page)
                io.person.run = run
                return s
            sess.open_session = spy
            try:
                return await execute_browser_phase(o, run, deps_for(tmp_path), f"{fp.base_url}/apps/{app.id}", io)
            finally:
                sess.open_session = real
        run = asyncio.run(go())
        secrets_ = fake_secrets(fp) + [old]
        audit = fp.audit()
    assert ("DO", "secret_hidden") in io.person.handoffs
    assert [a["actor"] for a in audit if a["event"] == "secret_regenerated"] == ["person"]
    assert run.status == "succeeded" and run.verification.label == "verified"
    assert_no_leak(tmp_path, run.id, secrets_, io.out)


def test_testing_mode_is_partial_with_the_observed_limitation(tmp_path):
    with FakeProvider(scenario("partial_testing_mode")) as fp:
        io = LateIO()
        run, _ = asyncio.run(_phase(tmp_path, fp, new_run(fp, "testing"), deps_for(tmp_path), io))
    assert run.status == "partial" and run.verification.label == "verified"
    assert any("testing mode" in x for x in run.verification.production_limitations)


def _reload(tmp_path, run_id):
    m = Masker()
    store = RunStore(tmp_path / "runs", m)
    loaded = store.load(run_id)
    load_into_masker(loaded.run.credential, SecretFileStore(tmp_path / "secrets"), m)
    return loaded, m


def test_resume_after_terminal_and_browser_closed(tmp_path):
    """Flow D: the person closes the terminal at the sign-in card; the browser closes too. Later, resume
    relaunches Chrome with the saved profile, re-checks the page, shows the card again, and finishes."""
    with FakeProvider(scenario("signin_resume")) as fp:
        io1 = LateIO(quit_at=1)
        run, _ = asyncio.run(_phase(tmp_path, fp, new_run(fp, "resume"), deps_for(tmp_path), io1))
        assert run.status == "running" and run.pending_handoff and run.pending_handoff.blocker_kind == "sign_in"
        assert (tmp_path / "profile").exists()  # kept for resume
        loaded, m = _reload(tmp_path, run.id)
        io2 = LateIO()
        run2, store = asyncio.run(_phase(tmp_path, fp, loaded.run, deps_for(tmp_path), io2, resume=True, masker=m))
        secrets_ = fake_secrets(fp)
        audit = fp.audit()
    assert run2.status == "succeeded", (run2.status_reason, run2.verification)
    assert any("resumed: re-checking" in s.action for s in run2.steps)
    assert io2.person.handoffs[0] == ("DO", "sign_in")  # re-checked: still needed, so asked again
    assert [a["actor"] for a in audit if a["event"] == "signed_in"] == ["person"]
    assert len([a for a in audit if a["event"] == "app_created"]) == 1
    assert_no_leak(tmp_path, run2.id, secrets_, io1.out + io2.out)


def test_resume_reattaches_to_open_browser_and_sees_the_person_already_acted(tmp_path):
    """Real-provider style: Chrome stays open at the handoff. The person signs in while CredAgent is not
    running. Resume reattaches to the same Chrome, re-checks, finds the sign-in done, and asks nothing."""
    with FakeProvider(scenario("signin_resume")) as fp:
        io1 = LateIO(quit_at=1)
        run, _ = asyncio.run(_phase(tmp_path, fp, new_run(fp, "reattach"), deps_for(tmp_path, ephemeral=False), io1))
        pid = run.browser.chrome_pid
        assert run.pending_handoff and run.pending_handoff.blocker_kind == "sign_in"

        async def person_signs_in():
            from fake_provider.app.server import TEST_EMAIL, TEST_PASSWORD

            from credagent.browser.session import open_session
            sess = await open_session(tmp_path / "profile", headless=HEADLESS, existing=run.browser)
            assert sess.chrome.pid == pid
            page = sess.page
            await page.set_extra_http_headers({"X-Fakeprov-Actor": "person"})
            await page.evaluate(f"(() => {{ document.querySelector('input[name=email]').value = "
                                f"{json.dumps(TEST_EMAIL)}; document.querySelector('input[name=password]').value = "
                                f"{json.dumps(TEST_PASSWORD)}; document.querySelector('form').submit(); }})()")
            await page.wait_for_timeout(800)
            await page.set_extra_http_headers({})
            await sess.detach()
        asyncio.run(person_signs_in())
        loaded, m = _reload(tmp_path, run.id)
        io2 = LateIO()
        run2, _ = asyncio.run(_phase(tmp_path, fp, loaded.run, deps_for(tmp_path, ephemeral=False), io2,
                                     resume=True, masker=m))
        audit = fp.audit()
    assert run2.status == "succeeded", (run2.status_reason, run2.verification)
    assert run2.browser.chrome_pid == pid  # same Chrome, re-attached
    assert io2.person.handoffs == []       # nothing asked: the page showed sign-in was done
    assert [a["actor"] for a in audit if a["event"] == "signed_in"] == ["person"]


@pytest.mark.parametrize("answer,status", [(0, "succeeded"), (-1, "blocked")])
def test_in_doubt_click_is_never_repeated_without_asking(tmp_path, answer, status):
    with FakeProvider(scenario("success")) as fp:
        run = new_run(fp, f"doubt{answer}")
        m = Masker()
        RunStore(tmp_path / "runs", m).create(run)
        io = LateIO(choose=lambda opts: opts[answer])
        doubt = {"action": "click", "target": "button 'Create app'"}
        run, _ = asyncio.run(_resume_from_start(tmp_path, fp, run, io, doubt, m))
        created = [a for a in fp.audit() if a["event"] == "app_created"]
    assert run.status == status, run.status_reason
    assert ("DECIDE", "unexpected") in io.person.handoffs or ("DECIDE", "other") in io.person.handoffs
    assert len(created) == (1 if status == "succeeded" else 0)


async def _resume_from_start(tmp_path, fp, run, io, doubt, m):
    """As if a run was interrupted right after it started clicking "Create app" (no recorded result)."""
    from credagent.metadata.discovery import discover

    with httpx.Client() as http:
        run.metadata_check = discover(run.plan, http, base_urls=[fp.base_url]).summary()
    run.browser = None
    run.plan = run.plan.model_copy(update={"console_url": fp.base_url + "/"})
    return await _phase(tmp_path, fp, run, deps_for(tmp_path), io, resume=True, in_doubt=doubt, masker=m)


def test_cli_get_then_resume_from_a_new_process(tmp_path):
    """`get` pauses at the sign-in card (terminal closed). `resume` in a new process restarts the fake site on
    the same port with its saved state, reopens the browser with the saved profile and re-checks the page."""
    from click.testing import CliRunner

    from credagent.cli.main import cli

    r1 = CliRunner().invoke(cli, ["get", "Fakeprov", "--fake-provider", "signin_resume", "--offline", "--headless"],
                            input="")
    assert r1.exit_code == 0, r1.output
    home = tmp_path / "credagent-home"
    (run_dir,) = (home / "runs").iterdir()
    assert "credagent resume" in r1.output and "running" in r1.output
    port = json.loads((run_dir / "run.json").read_text())["plan"]["console_url"].split(":")[2].split("/")[0]
    r2 = CliRunner().invoke(cli, ["resume", run_dir.name], input="")
    assert r2.exit_code == 0, r2.output
    assert f"Fakeprov restarted at http://127.0.0.1:{port}" in r2.output
    assert "ACTION NEEDED IN THE BROWSER (DO)" in r2.output  # sign-in re-checked: still needed
    events = [json.loads(x)["type"] for x in (run_dir / "events.jsonl").read_text().splitlines()]
    assert "resumed" in events and events.count("browser_opened") == 2
    state = json.loads((home / "fakeprov" / run_dir.name / "state.json").read_text())
    assert state["audit"] == [] or all(a["event"] != "app_created" for a in state["audit"])
    mode = oct((home / "fakeprov" / run_dir.name / "state.json").stat().st_mode & 0o777)
    assert mode == "0o600"
