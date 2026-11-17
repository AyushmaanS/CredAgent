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
from credagent.orchestrator import fake_provider_plan
from credagent.secrets.masking import Masker
from credagent.state.models import Run
from credagent.state.store import RunStore

HEADLESS = os.environ.get("CREDAGENT_HEADLESS", "1") == "1"
CB = "http://127.0.0.1:8976/callback"
VALUES = FieldValues.default(CB)
FORBIDDEN = {"app_deleted", "submitted_for_review", "payment_entered", "business_verification_submitted",
             "account_created", "secret_regenerated"}


class PersonIO:
    """Plays the person at each handoff, in the browser, marked as the person."""

    def __init__(self, session, choose=None):
        self.session = session
        self.page = session.page
        self.run = None
        self.handoffs = []
        self.out = []
        self._choose = choose or (lambda options: options[0])
        self.guard_lifted_during_do = []

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


def assert_safe(audit):
    assert not [a for a in audit if a["event"] in FORBIDDEN], audit
    assert all(a["actor"] == "person" for a in audit if a["event"] in ("terms_accepted", "signed_in", "captcha_solved"))


def events(o, type_):
    return [e["data"] for e in o.store.events(o.run.id) if e["type"] == type_]
