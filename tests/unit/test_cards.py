import pytest

from credagent.handoff.cards import render_card
from credagent.secrets.masking import Masker
from credagent.state.models import Evidence, Handoff, Plan, PlanStep, Run, StepRecord


def sample_run():
    r = Run(id="r1", app_input="Fakeprov", plan=Plan(steps=[
        PlanStep(id=f"p{i}", description="x", kind="click") for i in range(6)]))
    r.add_step(StepRecord(plan_step_id="p0", action="open console", actor="agent", outcome="done"))
    r.add_step(StepRecord(plan_step_id="p1", action="fill name", actor="agent", outcome="done"))
    return r


DO = dict(kind="DO", reason="The create form contains a terms checkbox (terms are always yours).",
          blocker_kind="terms",
          evidence=[Evidence(kind="observed", text='Checkbox: "I agree to the Developer Terms"',
                             url="http://127.0.0.1:8765/apps/new")],
          completed_so_far="2 of 6",
          person_instruction="Read the terms, tick the box if you agree, then click 'Create app'.",
          where="the CredAgent Chrome window",
          expected_resume_action="Re-check the page, then capture the new client secret.")


@pytest.mark.parametrize("kind", ["DO", "DECIDE"])
def test_card_has_all_six_fields(kind):
    kw = dict(DO)
    if kind == "DECIDE":
        kw.update(kind="DECIDE", options=["Web app (confidential)", "Single-page app (public)"],
                  where="this terminal")
    card = render_card(sample_run(), Handoff(**kw))
    for label in ["1. Done so far", "2. Blocking", "3. What to do", "4. Then I will",
                  "5. To resume", "6. Do not"]:
        assert label in card
    assert "2 actions by the agent, 0 by you" in card
    assert "r1" in card and "resume" in card
    if kind == "DECIDE":
        assert "Option 1" in card and "Option 2" in card
    else:
        assert "Do not close the CredAgent browser window" in card


def test_card_masks_secrets():
    secret = "Hq3-fake-registered-secret-zz9"  # fake; secret-scan: allow
    kw = dict(DO, reason=f"page shows {secret}")
    card = render_card(sample_run(), Handoff(**kw), Masker([secret]))
    assert secret not in card


def test_run_id_never_split_across_lines():
    from credagent.state.models import Run
    rid = "20261115-181141-fakeprov-terms-check-8866"
    run = Run(id=rid, app_input="x")
    card = render_card(run, Handoff(**DO))
    assert rid in card  # appears unbroken on one line


def test_progress_counts_what_was_done_not_plan_steps():
    r = sample_run()
    for i in range(9):
        r.add_step(StepRecord(plan_step_id="p2", action=f"fill field {i}", actor="agent", outcome="done"))
    r.add_step(StepRecord(action="signed in", actor="person", outcome="done"))
    r.created = ["an app named credagent-demo"]
    card = render_card(r, Handoff(**DO))
    assert "11 actions by the agent, 1 by you; created: an app named credagent-demo" in " ".join(card.split())
