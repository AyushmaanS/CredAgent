"""D-078 phase 4 in real Chrome (opt-in: CREDAGENT_BROWSER_TESTS=1): the agent loop through the full orchestrator
phase: capture → live test → outcome; shown-once and hidden secrets, reset with confirmation, resume after the
browser closed or while it stayed open, in-doubt clicks, and leak scans.

Offline scripted stand-in for the model, a harness playing the person (X-Fakeprov-Actor: person). After every run
the test collects every secret the fake site ever issued (client secrets and access tokens) and asserts none of
them appears in run state, the event log, the reports or anything printed to the terminal.
"""

import asyncio
import functools
import json
import os

import httpx
import pytest
from fake_provider.app import FakeProvider, scenario
from fake_provider.app.server import TEST_EMAIL, TEST_PASSWORD

from credagent.agent.scripted import ScriptedLLM
from credagent.browser.pw_session import open_pw_session
from credagent.metadata.discovery import discover
from credagent.secrets.capture import load_into_masker
from credagent.secrets.masking import Masker
from credagent.secrets.store import SecretFileStore
from credagent.state.store import RunStore
from tests.agent_harness import (
    CB,
    HEADLESS,
    PersonIO,
    assert_no_leak,
    assert_safe,
    fake_secrets,
    new_run,
    run_phase,
)

pytestmark = pytest.mark.skipif(os.environ.get("CREDAGENT_BROWSER_TESTS") != "1",
                                reason="set CREDAGENT_BROWSER_TESTS=1 to run real-browser tests")


def sync(fn):
    """Run an async test body to completion (the suite's other real-Chrome tests use asyncio.run the same way)."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))
    return wrapper


class RegeneratingPerson(PersonIO):
    """The person also resets a hidden secret (clicks the provider's Regenerate button) when asked."""

    async def wait_enter(self, prompt):
        h = self.run.pending_handoff
        if h.blocker_kind == "secret_hidden" and not (self.quit_at and self.n + 1 >= self.quit_at):
            self.n += 1
            self.handoffs.append((h.kind, h.blocker_kind))
            await self._as_person("Array.from(document.querySelectorAll('button')).find(b => "
                                  "/Regenerate|Reset/.test(b.innerText)).click()")
            return True
        return await super().wait_enter(prompt)


def _reload(tmp_path, run_id):
    m = Masker()
    loaded = RunStore(tmp_path / "runs", m).load(run_id)
    load_into_masker(loaded.run.credential, SecretFileStore(tmp_path / "secrets"), m)
    return loaded, m


@sync
@pytest.mark.parametrize("name", ["success", "shown_once_secret", "terms_checkbox", "secret_behind_reveal",
                                  "numeric_client_id", "decoy_token"])
async def test_capture_and_live_test_succeed_without_leaks(tmp_path, name):
    with FakeProvider(scenario(name)) as fp:
        o = await run_phase(tmp_path, fp, new_run(fp, name), llm=ScriptedLLM())
        secrets_ = fake_secrets(fp)
        audit = fp.audit()
    run = o.run
    assert run.status == "succeeded", (run.status, run.status_reason)
    assert run.verification.label == "verified" and set(run.credential.parts) == {"client_id", "client_secret"}
    stored = SecretFileStore(tmp_path / "secrets").get(run.credential.parts["client_secret"].store_ref)
    assert stored in secrets_  # the value captured is the one the provider issued
    assert_safe(audit)
    assert len([a for a in audit if a["event"] == "app_created"]) == 1
    assert_no_leak(tmp_path, run.id, secrets_, o.io.out)
    assert not (tmp_path / "profile").exists()  # a fake run ended: profile removed


@sync
async def test_shown_once_secret_is_captured_on_first_view(tmp_path):
    with FakeProvider(scenario("shown_once_secret")) as fp:
        o = await run_phase(tmp_path, fp, new_run(fp, "once"), llm=ScriptedLLM())
        (app,) = fp.state.apps.values()
        # the page was not reloaded after the capture: a second view would show it hidden
        r = httpx.get(f"{fp.base_url}/apps/{app.id}")
    assert o.run.status == "succeeded" and app.secret_unviewed is False
    assert "client-secret-hidden" in r.text  # it really was shown only once


@sync
async def test_hidden_secret_hands_off_regeneration_to_the_person(tmp_path):
    """The secret was shown once earlier and is now hidden. The model can only say done; code finds nothing to
    capture, tells it, and after three misses asks the person to regenerate. Only the person regenerates."""
    with FakeProvider(scenario("shown_once_secret")) as fp:
        app = fp.state._new_app("credagent-demo-old", CB)
        httpx.get(f"{fp.base_url}/apps/{app.id}")  # someone viewed it earlier: the secret is now hidden
        old = app.client_secret
        run = new_run(fp, "hidden")
        m = Masker()
        RunStore(tmp_path / "runs", m).create(run)
        # the model sits on the app page that shows the hidden secret: a stand-in that insists it is done
        llm = ScriptedLLM()
        llm.need_secret = False
        from credagent.agent.step import AgentStep
        done = AgentStep(action="done", reason="the page shows the credential", expected="")
        llm._choose = lambda ctx: done  # type: ignore[method-assign]
        import tests.agent_harness as h
        orig = h.PersonIO
        h.PersonIO = RegeneratingPerson  # type: ignore[misc]
        try:
            o = await run_phase(tmp_path, fp, run, llm=llm, masker=m, start_url=f"{fp.base_url}/apps/{app.id}")
        finally:
            h.PersonIO = orig  # type: ignore[misc]
        secrets_ = fake_secrets(fp) + [old]
        audit = fp.audit()
    assert ("DO", "secret_hidden") in o.io.handoffs
    assert [a["actor"] for a in audit if a["event"] == "secret_regenerated"] == ["person"]
    assert o.run.status == "succeeded" and o.run.verification.label == "verified", o.run.status_reason
    assert_no_leak(tmp_path, run.id, secrets_, o.io.out)


@sync
async def test_testing_mode_is_partial_with_the_observed_limitation(tmp_path):
    with FakeProvider(scenario("partial_testing_mode")) as fp:
        o = await run_phase(tmp_path, fp, new_run(fp, "testing"), llm=ScriptedLLM())
    assert o.run.status == "partial" and o.run.verification.label == "verified"
    assert any("testing mode" in x for x in o.run.verification.production_limitations)


@sync
async def test_secret_behind_reset_with_confirm_dialog_asks_the_person_first(tmp_path):
    """Discord-like: the secret is hidden behind "Reset Secret" and a provider confirm prompt. The agent clicks
    reset: code classifies it as hard to undo, the person decides, and only then the prompt is confirmed."""
    with FakeProvider(scenario("discord_like")) as fp:
        o = await run_phase(tmp_path, fp, new_run(fp, "reset"), llm=ScriptedLLM())
        regen = [a for a in fp.audit() if a["event"] == "secret_regenerated"]
        secrets_ = fake_secrets(fp)
    assert ("DECIDE", "other") in o.io.handoffs
    assert len(regen) == 1  # one reset, after the person said yes
    assert o.run.status == "succeeded" and o.run.verification.label == "verified", (o.run.status, o.run.status_reason)
    assert_no_leak(tmp_path, o.run.id, secrets_, o.io.out)


@sync
async def test_declining_the_reset_leaves_the_secret_alone(tmp_path):
    with FakeProvider(scenario("discord_like")) as fp:
        o = await run_phase(tmp_path, fp, new_run(fp, "noreset"), llm=ScriptedLLM(),
                            choose=lambda opts: opts[-1])
        regen = [a for a in fp.audit() if a["event"] == "secret_regenerated"]
    assert regen == []
    assert o.run.status != "succeeded"


@sync
async def test_resume_after_terminal_and_browser_closed(tmp_path):
    """The person closes the terminal at the sign-in card; the browser closes too. Later, resume relaunches Chrome
    with the saved profile, re-checks the page, shows the card again, and finishes."""
    with FakeProvider(scenario("signin_resume")) as fp:
        o1 = await run_phase(tmp_path, fp, new_run(fp, "resume"), llm=ScriptedLLM(), quit_at=1)
        run = o1.run
        assert run.status == "running" and run.pending_handoff and run.pending_handoff.blocker_kind == "sign_in"
        assert (tmp_path / "profile").exists()  # kept for resume
        loaded, m = _reload(tmp_path, run.id)
        o2 = await run_phase(tmp_path, fp, loaded.run, llm=ScriptedLLM(), masker=m, resume=True)
        secrets_ = fake_secrets(fp)
        audit = fp.audit()
    run2 = o2.run
    assert run2.status == "succeeded", (run2.status_reason, run2.verification)
    assert any("resumed: re-checking" in s.action for s in run2.steps)
    assert o2.io.handoffs[0] == ("DO", "sign_in")  # re-checked: still needed, so asked again
    assert [a["actor"] for a in audit if a["event"] == "signed_in"] == ["person"]
    assert len([a for a in audit if a["event"] == "app_created"]) == 1
    assert_no_leak(tmp_path, run2.id, secrets_, o1.io.out + o2.io.out)


@sync
async def test_resume_reattaches_to_open_browser_and_sees_the_person_already_acted(tmp_path):
    """Chrome stays open at the handoff. The person signs in while CredAgent is not running. Resume reattaches to
    the same Chrome, re-checks, finds the sign-in done, and asks nothing."""
    with FakeProvider(scenario("signin_resume")) as fp:
        o1 = await run_phase(tmp_path, fp, new_run(fp, "reattach"), llm=ScriptedLLM(), quit_at=1, ephemeral=False)
        run = o1.run
        pid = run.browser.chrome_pid
        assert run.pending_handoff and run.pending_handoff.blocker_kind == "sign_in"

        sess = await open_pw_session(tmp_path / "profile", headless=HEADLESS, existing=run.browser)
        assert sess.chrome.pid == pid
        page = sess.page
        await page.set_extra_http_headers({"X-Fakeprov-Actor": "person"})
        await page.evaluate(f"(() => {{ document.querySelector('input[name=email]').value = "
                            f"{json.dumps(TEST_EMAIL)}; document.querySelector('input[name=password]').value = "
                            f"{json.dumps(TEST_PASSWORD)}; document.querySelector('form').submit(); }})()")
        await page.wait_for_timeout(800)
        await page.set_extra_http_headers({})
        await sess.detach()

        loaded, m = _reload(tmp_path, run.id)
        o2 = await run_phase(tmp_path, fp, loaded.run, llm=ScriptedLLM(), masker=m, resume=True, ephemeral=False,
                             existing=loaded.run.browser)
        audit = fp.audit()
    assert o2.run.status == "succeeded", (o2.run.status_reason, o2.run.verification)
    assert o2.run.browser.chrome_pid == pid  # same Chrome, re-attached
    assert o2.io.handoffs == []              # nothing asked: the page showed sign-in was done
    assert [a["actor"] for a in audit if a["event"] == "signed_in"] == ["person"]


@sync
@pytest.mark.parametrize("answer,status", [(0, "succeeded"), (-1, "blocked")])
async def test_in_doubt_click_is_never_repeated_without_asking(tmp_path, answer, status):
    """As if a run was interrupted right after it started clicking "Create app" (no recorded result)."""
    with FakeProvider(scenario("success")) as fp:
        run = new_run(fp, f"doubt{answer}")
        m = Masker()
        RunStore(tmp_path / "runs", m).create(run)
        with httpx.Client() as http:
            run.metadata_check = discover(run.plan, http, base_urls=[fp.base_url]).summary()
        run.browser = None
        run.plan = run.plan.model_copy(update={"console_url": fp.base_url + "/"})
        doubt = {"action": "click", "target": 'button "Create app"'}
        o = await run_phase(tmp_path, fp, run, llm=ScriptedLLM(), masker=m, resume=True, in_doubt=doubt,
                            choose=lambda opts: opts[answer])
        created = [a for a in fp.audit() if a["event"] == "app_created"]
    assert o.run.status == status, o.run.status_reason
    assert ("DECIDE", "unexpected") in o.io.handoffs
    assert len(created) == (1 if status == "succeeded" else 0)


@sync
async def test_agent_run_leaves_no_secret_in_the_events_or_report(tmp_path):
    with FakeProvider(scenario("discord_like")) as fp:
        o = await run_phase(tmp_path, fp, new_run(fp, "scan"), llm=ScriptedLLM())
        secrets_ = fake_secrets(fp)
    run_dir = tmp_path / "runs" / o.run.id
    assert (run_dir / "events.jsonl").exists()
    assert_no_leak(tmp_path, o.run.id, secrets_, o.io.out)


# ------------------------------------------------------------------ Discord run #6 (D-086)

@sync
async def test_ids_and_secrets_in_unlabelled_text_fields_are_captured(tmp_path):
    """Discord run #6: the OAuth2 page showed the ID and the new secret in fields whose heading is above them. The
    page scan found nothing, so "done" was refused and the secret was lost. Now both are found and stored."""
    with FakeProvider(scenario("discord_inputs")) as fp:
        o = await run_phase(tmp_path, fp, new_run(fp, "inputs"), llm=ScriptedLLM())
        secrets_ = fake_secrets(fp)
        audit = fp.audit()
    assert o.run.status == "succeeded" and o.run.verification.label == "verified", (o.run.status, o.run.status_reason)
    assert set(o.run.credential.parts) == {"client_id", "client_secret"}
    stored = SecretFileStore(tmp_path / "secrets").get(o.run.credential.parts["client_secret"].store_ref)
    assert stored in secrets_
    assert len([a for a in audit if a["event"] == "secret_regenerated"]) == 1
    assert_safe(audit, allow=("secret_regenerated",))
    assert_no_leak(tmp_path, o.run.id, secrets_, o.io.out)


class ResetTwice(ScriptedLLM):
    """A model that clicks Reset Secret whenever it can, as run #6's model did after it lost the first secret."""

    def _choose(self, ctx):
        from credagent.agent.step import AgentStep

        yes = next((e for e in ctx.snapshot.elements if e.in_dialog and e.role == "button"
                    and e.name.startswith("Yes")), None)
        if yes is not None:  # the provider's "are you sure" prompt (the person already said yes to the reset)
            return AgentStep(action="click", ref=yes.ref, reason="confirm the prompt", expected="")
        btn = next((e for e in ctx.snapshot.elements if e.role == "button" and e.name == "Reset Secret"
                    and not e.in_dialog and e.xpath not in ctx.snapshot.refused), None)
        if btn is not None and ctx.created and "/oauth2" in ctx.snapshot.url:
            return AgentStep(action="click", ref=btn.ref, reason="reset the secret", expected="")
        return super()._choose(ctx)


@sync
async def test_a_second_secret_reset_is_asked_with_a_warning(tmp_path):
    answers = iter([0, -1])  # yes to the first reset, no to the second

    with FakeProvider(scenario("discord_inputs")) as fp:
        o = await run_phase(tmp_path, fp, new_run(fp, "twice"), llm=ResetTwice(),
                            choose=lambda opts: opts[next(answers)])
        resets = [a for a in fp.audit() if a["event"] == "secret_regenerated"]
    reasons = [h.reason for h in o.run.handoffs if h.kind == "DECIDE"]
    assert len(reasons) == 2 and "already reset" not in reasons[0] and "already reset" in reasons[1], \
        (reasons, o.run.status, o.run.status_reason, o.io.handoffs)
    assert len(resets) == 1  # the second one was declined
    assert o.run.status == "blocked"
