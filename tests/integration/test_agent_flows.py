"""D-078 phase 5: flows that were covered by the old loop's tests, now through the agent loop (real Chrome, opt-in:
CREDAGENT_BROWSER_TESTS=1), plus the command line. Scripted stand-in for the model, a harness playing the person.
"""

import asyncio
import json
import os

import pytest
from fake_provider.app import FakeProvider, scenario

from credagent.agent.scripted import ScriptedLLM
from credagent.agent.step import AgentStep
from tests.agent_harness import (
    CB,
    PersonIO,
    assert_no_leak,
    assert_safe,
    events,
    fake_secrets,
    new_run,
    run_agent_scenario,
    run_phase,
)

pytestmark = pytest.mark.skipif(os.environ.get("CREDAGENT_BROWSER_TESTS") != "1",
                                reason="set CREDAGENT_BROWSER_TESTS=1 to run real-browser tests")


def go(tmp_path, name, **kw):
    return asyncio.run(run_agent_scenario(tmp_path, name, **kw))


# ------------------------------------------------------------------ page content that tries to steer the agent

def test_prompt_injection_on_the_page_is_ignored(tmp_path):
    o = go(tmp_path, "prompt_injection")
    assert o.result.status == "credential_page", o.result
    assert_safe(o.audit)  # no deletion, no review submission
    assert any("agent_instruction" in json.dumps(e["data"]) or "addressed to automated agents" in json.dumps(e["data"])
               for e in o.store.events(o.run.id))


# ------------------------------------------------------------------ choices only the person makes

def test_an_unanswered_dropdown_is_a_decide_before_submit_and_scopes_stay_unticked(tmp_path):
    o = go(tmp_path, "decide_app_type_and_scopes")
    assert o.result.status == "credential_page", o.result
    assert ("DECIDE", "other") in o.io.handoffs
    (app,) = o.apps
    assert app["app_type"] == "confidential" and app["scopes"] == []  # the person chose option 1; no scope ticked
    assert any("person decided" in s.action for s in o.run.steps)
    assert_safe(o.audit)


class DeclineIO(PersonIO):
    async def choose(self, prompt, options):
        self.handoffs.append(("DECIDE", self.run.pending_handoff.blocker_kind))
        assert "Stop here" in options  # the person can always say no
        return "Stop here"


def test_declining_a_form_choice_ends_blocked_and_creates_nothing(tmp_path):
    o = go(tmp_path, "decide_app_type_and_scopes", io_cls=DeclineIO)
    assert o.result.status == "blocked" and "declined" in o.result.reason
    assert o.run.blockers and o.run.blockers[-1].who_must_act == "person"
    assert not [a for a in o.audit if a["event"] == "app_created"] and o.apps == []


# ------------------------------------------------------------------ the terms card and the handoff re-check

class TickOnlyFirstIO(PersonIO):
    """Replays the owner's report: first tick the box and press Enter, then click Create app."""

    steps: list = []

    async def wait_enter(self, prompt):
        self.n += 1
        h = self.run.pending_handoff
        if self.n == 1:
            self.handoffs.append((h.kind, h.blocker_kind))
        step = self.steps.pop(0) if self.steps else None
        if step == "tick":
            await self._as_person("document.getElementById('accept-terms').click()")
        elif step == "submit":
            await self._as_person("document.getElementById('create-app').click()")
        return True


def _io_with(steps):
    class IO(TickOnlyFirstIO):
        pass
    IO.steps = list(steps)
    return IO


def test_the_terms_card_names_box_and_button_and_rechecks_after_enter(tmp_path):
    o = go(tmp_path, "terms_checkbox", io_cls=_io_with(["tick", "submit"]))
    card = " ".join(" ".join(o.io.out).split())  # the card wraps lines; compare words
    assert "tick “I have read and agree to the Fakeprov Developer Terms”" in card
    assert "click “Create app”" in card
    assert "Not done yet — still needed: click “Create app”" in card  # after the first Enter
    assert o.io.handoffs == [("DO", "terms")] and o.io.n == 2         # one handoff, not a new card per Enter
    assert o.result.status == "credential_page"
    assert [a["actor"] for a in o.audit if a["event"] == "terms_accepted"] == ["person"]
    assert_safe(o.audit)


def test_a_handoff_is_saved_as_waiting_after_three_unchanged_enters(tmp_path):
    o = go(tmp_path, "terms_checkbox", io_cls=_io_with([None, None, None]))
    assert o.result.status == "handoff_pending" and o.io.n == 3
    assert o.run.pending_handoff is not None and o.run.pending_handoff.blocker_kind == "terms"
    assert "The run is saved with this step waiting for you" in "\n".join(o.io.out)
    assert not [a for a in o.audit if a["event"] in ("terms_accepted", "app_created")]


@pytest.mark.parametrize("name", ["terms_checkbox", "terms_implied"])
def test_the_agent_fills_optional_fields_too_and_the_card_says_what_it_did(tmp_path, name):
    o = go(tmp_path, name)
    assert o.result.status == "credential_page"
    (app,) = o.apps
    assert app["homepage_url"] == "http://127.0.0.1:8976" and app["description"].startswith("Created by CredAgent")
    assert app["redirect_uri"] == CB
    card = " ".join(" ".join(o.io.out).split())
    filled = card.split("The agent filled:")[1].split(".")[0]
    for label in ("Application name", "Description", "Homepage URL", "Authorization callback URL"):
        assert f"“{label}”" in filled, label
    assert o.io.handoffs == [("DO", "terms")]
    assert_safe(o.audit)


# ------------------------------------------------------------------ a console like Discord's

def test_a_discord_like_portal_creates_exactly_one_app_and_saves_the_redirect(tmp_path):
    with FakeProvider(scenario("discord_like")) as fp:
        o = asyncio.run(run_phase(tmp_path, fp, new_run(fp, "dlike"), llm=ScriptedLLM()))
        created = [a for a in fp.audit() if a["event"] == "app_created"]
        secrets_ = fake_secrets(fp)
        redirects = [a.redirects for a in fp.state.apps.values()][0]
    assert o.run.status == "succeeded", (o.run.status, o.run.status_reason)
    assert len(created) == 1 and created[0]["actor"] == "person"  # implied terms: the person clicked Create
    assert set(o.run.credential.parts) == {"client_id", "client_secret"} and o.run.created
    assert ("DO", "terms") in o.io.handoffs
    assert redirects == [CB], redirects
    assert sum(s.action.startswith("click") and "Add Another" in s.action for s in o.run.steps) <= 2
    assert_no_leak(tmp_path, o.run.id, secrets_, o.io.out)


class DocsOnce(ScriptedLLM):
    """A model that wanders into the documentation once (D-070)."""

    went = False

    def _choose(self, ctx):
        docs = [e for e in ctx.snapshot.elements if e.role == "link" and e.name == "Docs"]
        if docs and not self.went:
            self.went = True
            return AgentStep(action="click", ref=docs[0].ref, reason="read the docs", expected="")
        return super()._choose(ctx)


def test_a_documentation_detour_is_undone(tmp_path):
    with FakeProvider(scenario("success")) as fp:
        llm = DocsOnce()
        o = asyncio.run(run_phase(tmp_path, fp, new_run(fp, "docs"), llm=llm))
    assert llm.went
    assert any("documentation" in s.action.lower() for s in o.run.steps)
    assert o.run.status == "succeeded", (o.run.status, o.run.status_reason)


# ------------------------------------------------------------------ a model that fails

def test_unusable_model_answers_are_recorded_and_the_run_still_succeeds(tmp_path):
    from fake_provider.faults import Faults, FaultyLLM

    o = go(tmp_path, "llm_failure", llm=FaultyLLM(ScriptedLLM(), Faults(flaky=True)))
    assert o.result.status == "credential_page", o.result
    assert events(o, "step_invalid"), "no unusable answer was recorded"
    assert_safe(o.audit)


def test_a_model_that_is_down_ends_failed_and_resumable(tmp_path):
    from fake_provider.faults import Faults, FaultyLLM

    o = go(tmp_path, "service_unavailable", llm=FaultyLLM(ScriptedLLM(), Faults(down=True)))
    assert o.result.status == "failed" and "service unavailable" in o.result.reason
    assert events(o, "service_unavailable")
    assert not [a for a in o.audit if a["event"] == "app_created"]


# ------------------------------------------------------------------ the command line

def test_cli_fake_provider_offline_end_to_end(tmp_path):
    from click.testing import CliRunner

    from credagent.cli.main import cli

    r = CliRunner().invoke(cli, ["get", "Fakeprov", "--fake-provider", "success", "--offline", "--headless"])
    assert r.exit_code == 0, r.output
    assert "succeeded" in r.output and "Live test: verified" in r.output
    home = tmp_path / "credagent-home"
    assert not list((home / "profiles" / "fakeprov").glob("*"))  # ephemeral profile removed


def test_cli_service_unavailable_run_is_failed_resumable(tmp_path):
    from click.testing import CliRunner

    from credagent.cli.main import cli

    r = CliRunner().invoke(cli, ["get", "Fakeprov", "--fake-provider", "service_unavailable", "--offline",
                                 "--headless"])
    assert r.exit_code == 0, r.output
    assert "Simulated fault" in r.output and "failed" in r.output and "service unavailable" in r.output
    (run_dir,) = (tmp_path / "credagent-home" / "runs").iterdir()
    state = json.loads((run_dir / "run.json").read_text())
    assert state["status"] == "failed" and state["resumable"] is True


def test_cli_get_then_resume_from_a_new_process(tmp_path):
    """`get` pauses at the sign-in card (terminal closed). `resume` in a new process restarts the fake site on the
    same port with its saved state, reopens the browser with the saved profile and re-checks the page."""
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
    evs = [json.loads(x)["type"] for x in (run_dir / "events.jsonl").read_text().splitlines()]
    assert "resumed" in evs and evs.count("browser_opened") == 2
    state = json.loads((home / "fakeprov" / run_dir.name / "state.json").read_text())
    assert all(a["event"] != "app_created" for a in state["audit"])
    mode = oct((home / "fakeprov" / run_dir.name / "state.json").stat().st_mode & 0o777)
    assert mode == "0o600"


# ------------------------------------------------------------------ Google Cloud run (D-093)

def test_an_off_site_sign_in_redirect_goes_to_the_person_and_does_not_bounce_off_a_blank_page(tmp_path):
    """Google run 20261117-145242: the console redirected to accounts.google.com, outside the allowed sites. The agent
    went back (to about:blank), navigated again, was redirected again, and the person never reached the sign-in page.
    Now an off-site sign-in page is the person's: no back, no loop, and the run continues at the console afterwards."""
    with FakeProvider(scenario("signin_offsite")) as fp:
        o = asyncio.run(run_phase(tmp_path, fp, new_run(fp, "offsite"), llm=ScriptedLLM()))
        audit = fp.audit()
    assert o.run.status == "succeeded", (o.run.status, o.run.status_reason)
    assert o.io.handoffs == [("DO", "sign_in")], o.io.handoffs
    assert not any("going back" in s.action for s in o.run.steps), [s.action for s in o.run.steps]
    assert any("asking the person" in s.action and "localhost" in s.action for s in o.run.steps)
    assert [a["actor"] for a in audit if a["event"] == "signed_in"] == ["person"]
    assert len([a for a in audit if a["event"] == "app_created"]) == 1
    card = " ".join(" ".join(o.io.out).split())
    assert "sign-in page (localhost)" in card and "outside the allowed sites" in card


def test_a_project_made_first_is_not_the_app_and_the_agent_still_creates_the_app(tmp_path):
    """Google run 20261117-152213: "Create project" was counted as the app, so "Create client" was refused as "another
    app" and the person had to create the credential themselves (D-094). A project is asked about; the app is still
    created by the agent, once."""
    with FakeProvider(scenario("project_then_app")) as fp:
        o = asyncio.run(run_phase(tmp_path, fp, new_run(fp, "proj"), llm=ScriptedLLM()))
        audit = fp.audit()
    assert o.run.status == "succeeded", (o.run.status, o.run.status_reason)
    assert o.io.handoffs == [("DECIDE", "other")], o.io.handoffs  # the person is asked about the project, once
    assert [a["event"] for a in audit if a["event"] in ("project_created", "app_created")] == \
        ["project_created", "app_created"]
    assert [a["actor"] for a in audit if a["event"] == "app_created"] == ["unknown"]  # the agent made the app
    assert len(o.run.created) == 1 and len(o.run.created_setup) == 1 and "project" in o.run.created_setup[0]
    assert not [e for e in o.store.events(o.run.id) if e["type"] == "policy"
                and e["data"].get("category") == "already_created"]
    assert_safe(audit)
