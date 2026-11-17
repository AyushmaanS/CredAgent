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
                                  "/Regenerate|Reset/.test(b.innerText)).click()")
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


def new_run(fp, name, *, oauth_step=False):
    plan = fake_provider_plan(fp.base_url)
    if oauth_step:  # as in Discord's real plan: after creating, open the OAuth2 page from the app's sidebar
        from credagent.state.models import PlanStep

        steps = list(plan.steps)
        from credagent.steps.checks import Check, FieldRef, Target

        oauth2 = Check(check="at_page", path="/apps/{app_id}/oauth2")
        steps[5:5] = [  # as research will write them for Discord (design §4)
            PlanStep(id="p5b", kind="navigate", description="In the left sidebar of the application, open the OAuth2 "
                     "page.", expected_page="/oauth2", target=Target(role="link", name="OAuth2"), done_when=[oauth2]),
            PlanStep(id="p5c", kind="fill", description="Under Redirects, click 'Add Redirect', enter the exact "
                     "callback URL, and save.", where=[oauth2], value="redirect_uri",
                     target=Target(role="button", name="Add Redirect"),
                     done_when=[Check(check="field_holds", field=FieldRef(section="Redirects"), value="redirect_uri"),
                                Check(check="element_absent", role="button", name="Save Changes")]),
            PlanStep(id="p5d", kind="click", description="On the OAuth2 page, click 'Reset Secret' to generate a new "
                     "client secret.", where=[oauth2], target=Target(role="button", name="Reset Secret"),
                     done_when=[Check(check="credential_shown", parts=["client_secret"])]),
        ]
        plan = plan.model_copy(update={"steps": steps})
    return Run(id=f"t5-{name}", app_input="Fakeprov", provider="Fakeprov (local)", plan=plan)


@pytest.mark.parametrize("name", ["success", "shown_once_secret", "terms_checkbox", "secret_behind_reveal", "numeric_client_id", "decoy_token"])
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


def test_unlabelled_token_before_creation_does_not_end_the_run(tmp_path):
    """Discord run 20261116-164345: an unlabelled ID on the app list ended the run as blocked (D-061)."""
    with FakeProvider(scenario("decoy_token")) as fp:
        io = LateIO()
        run, _ = asyncio.run(_phase(tmp_path, fp, new_run(fp, "decoy"), deps_for(tmp_path), io))
    assert any("nothing labelled to capture; continuing" in s.action for s in run.steps)
    assert run.status == "succeeded" and run.verification.label == "verified"


class CreateAgainJev:
    """Replays real run 20261116-171020 (D-063): after the app exists, the decider goes back to the create
    form and keeps proposing to create another app, confidently and as read-only."""

    def __init__(self):
        import re

        self.create = re.compile(r"create app|new app|new application", re.I)
        self.went_back = 0
        self.proposed_again = 0

    def decide(self, state, log):
        import re

        from credagent.decisions.jev import Decision, JevDecisions

        base = RuleJev().decide(state, log).decisions
        on_app = re.search(r"/apps/\d+$", state.url)
        if on_app and self.went_back == 0:
            self.went_back = 1
            base["action_selection"] = Decision("action_selection", "go_back", 0.99, False, {})
            return JevDecisions(base, "create-again", 0)
        hit = [c for c in state.candidates if self.create.search(c.description)]
        if hit and self.went_back == 1:
            self.proposed_again += 1
            base["element_selection"] = Decision("element_selection", hit[0].id, 0.99, False, {})
            base["action_selection"] = Decision("action_selection", "proceed", 0.99, False, {})
            base["risk_assessment"] = Decision("risk_assessment", "read_only", 0.99, False, {})
            return JevDecisions(base, "create-again", 0)
        if "/apps/new" in state.url and self.went_back == 1:
            self.went_back = 2
            base["action_selection"] = Decision("action_selection", "go_back", 0.99, False, {})
        return JevDecisions(base, "create-again", 0)


def test_discord_like_portal_creates_exactly_one_app(tmp_path):
    with FakeProvider(scenario("discord_like")) as fp:
        io = LateIO()
        run, _ = asyncio.run(_phase(tmp_path, fp, new_run(fp, "dlike", oauth_step=True), deps_for(tmp_path), io))
        created = [a for a in fp.audit() if a["event"] == "app_created"]
        secrets_ = fake_secrets(fp)
        app_redirects = [a.redirects for a in fp.state.apps.values()][0]
    assert run.status == "succeeded", (run.status, run.status_reason)
    assert len(created) == 1 and created[0]["actor"] == "person"  # implied terms: the person clicked Create
    assert set(run.credential.parts) == {"client_id", "client_secret"} and run.created
    assert_no_leak(tmp_path, run.id, secrets_, io.out)
    # D-069: the formless Create button was handed to the person (never clicked by the agent after a DECIDE);
    # the unlabelled redirect box was filled with the callback and saved; "Add Another" was not clicked on and on.
    assert ("DO", "terms") in io.person.handoffs
    assert app_redirects == [CB], app_redirects
    assert sum(s.action.startswith("click") and "Add Another" in s.action for s in run.steps) <= 2


def test_eager_decider_cannot_create_a_second_app(tmp_path):
    with FakeProvider(scenario("discord_like")) as fp:
        io = LateIO()
        deps = deps_for(tmp_path)
        jev = CreateAgainJev()
        deps.jev = jev
        run, store = asyncio.run(_phase(tmp_path, fp, new_run(fp, "again", oauth_step=True), deps, io))
        created = [a for a in fp.audit() if a["event"] == "app_created"]
    assert jev.proposed_again >= 1, "the replay never proposed a second app; the test would prove nothing"
    assert len(created) == 1, f"{len(created)} apps created"
    assert any("would create another app" in json.dumps(e["data"]) for e in store.events(run.id) if e["type"] == "policy")
    # (Where the replay then wanders is the replay's doing; what matters is that no second app was created.)


def test_navigator_opens_the_app_from_the_list_when_the_step_target_is_elsewhere(tmp_path):
    """Discord run 20261116-171020 (D-068): on the app list, the step "open the OAuth2 page" had no matching
    element; Jev said stuck. The navigator is asked once for the click that leads there (open the app)."""
    from credagent.browser.candidates import FieldValues
    from credagent.decisions.client import RuleLLM

    class Navigator(RuleLLM):
        def __init__(self):
            self.asked = 0

        def chat(self, messages, *, json_schema=None, schema_name="result", **kw):
            if schema_name != "toward_goal":
                return super().chat(messages, json_schema=json_schema, schema_name=schema_name, **kw)
            self.asked += 1
            info = json.loads(messages[-1]["content"].split("\n<<<PAGE>>>")[0])
            mine = [c["id"] for c in info["candidates"] if "(the app this run created)" in c["description"]]
            return {"parsed": {"element": mine[0] if mine else "none", "reason": "open the app first"}}

    class StuckOffList(RuleJev):
        def decide(self, state, log):
            d = super().decide(state, log)
            if state.url.endswith("/console"):
                from credagent.decisions.jev import Decision
                d.decisions["action_selection"] = Decision("action_selection", "stuck", 0.99, False, {})
            return d

    with FakeProvider(scenario("discord_like")) as fp:
        name = FieldValues.default(CB).app_name
        fp.state._new_app(name, CB)
        run = new_run(fp, "nav", oauth_step=True)
        run.plan = run.plan.model_copy(update={"console_url": fp.base_url + "/console"})
        run.created = ["an app (created earlier)"]
        from credagent.metadata.discovery import discover

        with httpx.Client() as http:  # as recorded by the first session of a real run
            run.metadata_check = discover(run.plan, http, base_urls=[fp.base_url]).summary()
        run.plan_cursor = [i for i, st in enumerate(run.plan.steps) if st.id == "p5b"][0]
        m = Masker()
        RunStore(tmp_path / "runs", m).create(run)
        nav = Navigator()
        deps = deps_for(tmp_path)
        deps.jev, deps.reasoner = StuckOffList(), nav
        io = LateIO()
        run, store = asyncio.run(_phase(tmp_path, fp, run, deps, io, resume=True, masker=m))
        created = [a for a in fp.audit() if a["event"] == "app_created"]
    assert nav.asked >= 1
    assert any(e["type"] == "toward_goal" and e["data"]["element"] for e in store.events(run.id))
    assert run.status == "succeeded", (run.status, run.status_reason)
    assert created == []  # the existing app was used; nothing new was created


def test_docs_detour_is_undone_d070(tmp_path):
    """Discord run #4: the navigator led into the docs, where Jev declared 'open OAuth2' complete."""

    class DocsOnceJev(RuleJev):
        went = False

        def decide(self, state, log):
            d = super().decide(state, log)
            docs = [c for c in state.candidates if c.description == "link 'Docs'"]
            if docs and not DocsOnceJev.went:
                from credagent.decisions.jev import Decision
                DocsOnceJev.went = True
                d.decisions["element_selection"] = Decision("element_selection", docs[0].id, 0.99, False, {})
                d.decisions["action_selection"] = Decision("action_selection", "proceed", 0.99, False, {})
            return d

    with FakeProvider(scenario("success")) as fp:
        deps = deps_for(tmp_path)
        deps.jev = DocsOnceJev()
        io = LateIO()
        run, _ = asyncio.run(_phase(tmp_path, fp, new_run(fp, "docs"), deps, io))
    assert DocsOnceJev.went
    assert any("documentation page is not part of the console steps" in s.action for s in run.steps)
    assert run.status == "succeeded", (run.status, run.status_reason)


def test_redirect_with_a_stray_character_is_noticed_and_replaced_d071(tmp_path):
    """Discord run #4: the person typed the callback with a trailing full stop; the agent could not tell and kept
    clicking. Code now compares the value's length and asks before replacing it."""
    from credagent.browser.candidates import FieldValues

    with FakeProvider(scenario("discord_like")) as fp:
        app = fp.state._new_app(FieldValues.default(CB).app_name, CB)
        app.redirects = [CB + "."]
        run = new_run(fp, "stray", oauth_step=True)
        run.plan = run.plan.model_copy(update={"console_url": f"{fp.base_url}/apps/{app.id}/oauth2"})
        run.created = ["an app (created earlier)"]
        run.plan_cursor = [i for i, st in enumerate(run.plan.steps) if st.id == "p5c"][0]
        from credagent.metadata.discovery import discover

        with httpx.Client() as http:
            run.metadata_check = discover(run.plan, http, base_urls=[fp.base_url]).summary()
        m = Masker()
        RunStore(tmp_path / "runs", m).create(run)
        io = LateIO()
        run, _ = asyncio.run(_phase(tmp_path, fp, run, deps_for(tmp_path), io, resume=True, masker=m))
        saved = list(app.redirects)
    assert any(k == "DECIDE" for k, _ in io.person.handoffs)  # asked before replacing
    assert saved == [CB], saved
    assert run.status == "succeeded", (run.status, run.status_reason)


def test_legacy_plan_without_conditions_still_runs_d075(tmp_path):
    """Runs saved before checkable steps (no conditions) keep today's behaviour."""
    with FakeProvider(scenario("success")) as fp:
        run = new_run(fp, "legacy")
        run.plan = run.plan.model_copy(update={"steps": [s.model_copy(update={"where": [], "done_when": [],
                                                                             "target": None, "inferred": False})
                                                         for s in run.plan.steps]})
        io = LateIO()
        run, store = asyncio.run(_phase(tmp_path, fp, run, deps_for(tmp_path), io))
    assert run.status == "succeeded" and run.proofs == {}
    assert not any(e["type"] == "step_proven" for e in store.events(run.id))


def test_jev_cannot_complete_a_step_without_proof_d075(tmp_path):
    """Jev says "done" on the console for the step "open the form" (/apps/new): code's check disagrees."""

    class LiesOnce(RuleJev):
        lied = False

        def decide(self, state, log):
            d = super().decide(state, log)
            if "Open the form" in state.step_goal and state.url.endswith("/console") and not LiesOnce.lied:
                from credagent.decisions.jev import Decision
                LiesOnce.lied = True
                d.decisions["action_selection"] = Decision("action_selection", "step_complete", 0.99, False, {})
            return d

    with FakeProvider(scenario("success")) as fp:
        deps = deps_for(tmp_path)
        deps.jev = LiesOnce()
        io = LateIO()
        run, store = asyncio.run(_phase(tmp_path, fp, new_run(fp, "lie"), deps, io))
    ev = store.events(run.id)
    assert LiesOnce.lied and any(e["type"] == "jev_complete_rejected" for e in ev)
    assert run.proofs["p2"]["by"] == "code checks" and "on page /apps/new" in run.proofs["p2"]["checks"][0]
    assert run.status == "succeeded"
