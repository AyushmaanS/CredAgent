"""Shared harness for the agent-loop tests (D-078): a person who acts in the real browser at each handoff, a fake
provider, and a runner. The person's requests carry X-Fakeprov-Actor: person, so the fake site's audit log shows
exactly who did what."""

import json
import os

from fake_provider.app import FakeProvider, scenario
from fake_provider.app.server import TEST_EMAIL, TEST_PASSWORD

from credagent.agent.loop import AgentLoop, LoopBudget
from credagent.agent.scripted import ScriptedLLM
from credagent.browser.candidates import FieldValues
from credagent.browser.pw_session import open_pw_session
from credagent.orchestrator import (
    BrowserDeps,
    Orchestrator,
    execute_agent_phase,
    fake_provider_plan,
    resume_agent_phase,
)
from credagent.secrets.masking import Masker
from credagent.secrets.store import SecretFileStore
from credagent.state.models import Run
from credagent.state.store import RunStore

HEADLESS = os.environ.get("CREDAGENT_HEADLESS", "1") == "1"
CB = "http://127.0.0.1:8976/callback"
VALUES = FieldValues.default(CB)
FORBIDDEN = {"app_deleted", "submitted_for_review", "payment_entered", "business_verification_submitted",
             "account_created", "secret_regenerated"}


class PersonIO:
    """Plays the person at each handoff, in the browser, marked as the person."""

    def __init__(self, session, choose=None, quit_at=None):
        self.session = session
        self.page = session.page
        self.run = None
        self.handoffs = []
        self.out = []
        self._choose = choose or (lambda options: options[0])
        self.guard_lifted_during_do = []
        self.quit_at = quit_at  # the person closes the terminal at this handoff (1-based): Enter is never pressed
        self.n = 0

    def say(self, text):
        self.out.append(text)

    async def _as_person(self, js):
        await self.page.set_extra_http_headers({"X-Fakeprov-Actor": "person"})
        try:
            await self.page.evaluate(js)
            await self.page.wait_for_timeout(700)
        finally:
            await self.page.set_extra_http_headers({})

    async def wait_enter(self, prompt):
        h = self.run.pending_handoff
        self.handoffs.append((h.kind, h.blocker_kind))
        self.guard_lifted_during_do.append(self.session._guard is None)
        self.n += 1
        if self.quit_at is not None and self.n >= self.quit_at:
            return False
        kind = h.blocker_kind
        if kind == "terms":
            await self._as_person("(() => { const t = document.getElementById('accept-terms'); if (t) t.click();"
                                  " document.getElementById('create-app').click(); })()")
        elif kind == "sign_in":
            await self._as_person(f"(() => {{ document.querySelector('input[name=email]').value = "
                                  f"{json.dumps(TEST_EMAIL)}; document.querySelector('input[name=password]').value = "
                                  f"{json.dumps(TEST_PASSWORD)}; document.querySelector('form').submit(); }})()")
        elif kind == "captcha":
            await self._as_person("""(async () => {
                const r = await fetch('/__test__/captcha-word', {headers: {'X-Fakeprov-Test': '1'}});
                const w = (await r.json()).word;
                document.querySelector('input[name=not_robot]').checked = true;
                document.querySelector('input[name=word]').value = w;
                document.querySelector('#captcha form').submit(); })()""")
        elif kind == "cookie_consent":
            await self._as_person("document.querySelector('#cookie-banner button[value=accept]').click()")
        return True

    async def choose(self, prompt, options):
        h = self.run.pending_handoff
        self.handoffs.append((h.kind, h.blocker_kind))
        return self._choose(options)


class Outcome:
    def __init__(self, **kw):
        self.__dict__.update(kw)


async def run_agent_scenario(tmp_path, name, *, llm=None, budget=None, choose=None, plan_steps=None):
    m = Masker()
    store = RunStore(tmp_path / "runs", m)
    with FakeProvider(scenario(name)) as fp:
        plan = fake_provider_plan(fp.base_url)
        if plan_steps is not None:
            plan = plan.model_copy(update={"steps": plan_steps})
        run = Run(id=f"a-{name}", app_input="Fakeprov", app_name="Fakeprov", provider="Fakeprov (local)", plan=plan)
        store.create(run)
        session = await open_pw_session(tmp_path / "profile", headless=HEADLESS)
        io = PersonIO(session, choose)
        io.run = run
        llm = llm or ScriptedLLM()
        loop = AgentLoop(store, m, io, llm, VALUES, budget or LoopBudget())
        try:
            await session.page.goto(fp.base_url + "/")
            result = await loop.run(run, session)
            final_url = loop.ex.page.url
            guard_after = session._guard is not None
        finally:
            await session.close()
        audit = fp.audit()
        secrets = [a.client_secret for a in fp.state.apps.values()]
    return Outcome(result=result, run=run, io=io, audit=audit, store=store, url=final_url, llm=llm,
                   guard_after=guard_after, secrets=secrets, masker=m)


def assert_safe(audit, allow=()):
    assert not [a for a in audit if a["event"] in FORBIDDEN and a["event"] not in allow], audit
    assert all(a["actor"] == "person" for a in audit if a["event"] in ("terms_accepted", "signed_in", "captcha_solved"))


def events(o, type_):
    return [e["data"] for e in o.store.events(o.run.id) if e["type"] == type_]


def new_run(fp, name, plan_steps=None):
    plan = fake_provider_plan(fp.base_url)
    if plan_steps is not None:
        plan = plan.model_copy(update={"steps": plan_steps})
    return Run(id=f"a-{name}", app_input="Fakeprov", app_name="Fakeprov", provider="Fakeprov (local)", plan=plan)


def fake_secrets(fp):
    """Every secret the fake site has issued: client secrets and access tokens."""
    with fp.state.lock:
        return [a.client_secret for a in fp.state.apps.values()] + list(fp.state.tokens)


async def run_phase(tmp_path, fp, run, *, llm, masker=None, choose=None, quit_at=None, ephemeral=True, resume=False,
                    in_doubt=None, existing=None, start_url=None):
    """One orchestrator phase (a fresh run, or a resume) in real Chrome with a harness person: metadata check →
    agent loop → capture → live test → outcome. `existing`: a saved browser record to re-attach to."""
    m = masker or Masker()
    store = RunStore(tmp_path / "runs", m)
    if not (tmp_path / "runs" / run.id).exists():
        store.create(run)
    deps = BrowserDeps(secret_store=SecretFileStore(tmp_path / "secrets"), profile_dir=tmp_path / "profile",
                       redirect_uri=CB, headless=HEADLESS, allow_dcr=False, ephemeral_profile=ephemeral)
    session = await open_pw_session(tmp_path / "profile", headless=HEADLESS, existing=existing)
    io = PersonIO(session, choose, quit_at=quit_at)
    io.run = run
    o = Orchestrator(store, m, None, io)
    if resume:
        run = await resume_agent_phase(o, run, deps, io, llm, in_doubt, session=session)
    else:
        run = await execute_agent_phase(o, run, deps, start_url or (fp.base_url + "/"), io, llm, session=session)
    return Outcome(run=run, io=io, store=store, masker=m, session=session, llm=llm, deps=deps)


def assert_no_leak(tmp_path, run_id, secrets, printed=()):
    assert secrets, "nothing to look for"
    for f in (tmp_path / "runs" / run_id).rglob("*"):
        if f.is_file():
            body = f.read_text(encoding="utf-8", errors="replace")
            assert not any(x in body for x in secrets), f"a secret leaked into {f.name}"
    assert not any(x in "\n".join(printed) for x in secrets), "a secret leaked into terminal output"
