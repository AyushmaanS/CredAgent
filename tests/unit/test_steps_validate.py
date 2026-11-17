"""Checkable steps: validator, model-output converter, position rules and the Jev request block (D-075)."""

import asyncio

from credagent.browser.candidates import FieldValues
from credagent.browser.loop import BrowserLoop
from credagent.browser.observe import Observation
from credagent.secrets.masking import Masker
from credagent.state.models import Plan, PlanStep, Run
from credagent.steps.checks import Check, FieldRef
from credagent.steps.convert import to_plan_step
from credagent.steps.validate import has_checks, validate_steps

CB = "http://127.0.0.1:8976/callback"


def test_converter_keeps_valid_conditions_and_drops_invalid_ones():
    notes = []
    raw = {"where_path": "/developers/applications/{app_id}/oauth2", "target_role": "button",
           "target_name": "Add Redirect", "value": "redirect_uri",
           "done_when": [
               {"check": "field_holds", "field_section": "Redirects", "value": "redirect_uri", "path": None,
                "role": None, "name": None, "field_label": None, "parts": None},
               {"check": "element_absent", "role": "button", "name": "Save Changes", "path": None,
                "field_label": None, "field_section": None, "value": None, "parts": None},
               {"check": "field_holds", "field_label": "Client secret", "value": "redirect_uri", "path": None,
                "role": None, "name": None, "field_section": None, "parts": None},  # never on secrets: dropped
           ]}
    st = to_plan_step("s4", "Add the callback under Redirects and save.", "fill", raw, notes)
    assert [c.check for c in st.done_when] == ["field_holds", "element_absent"]
    assert st.where[0].path.endswith("/oauth2") and st.target.name == "Add Redirect"
    assert any("invalid and dropped" in n for n in notes)
    bad = to_plan_step("s5", "x", "navigate", {"where_path": "/apps/{user}", "done_when": []}, notes)
    assert bad.where == []


def test_validator_adds_app_exists_to_the_last_create_step_and_marks_inferred():
    steps = [
        PlanStep(id="a", kind="click", description="Open the form to create a new app",
                 done_when=[Check(check="at_page", path="/apps/new")]),
        PlanStep(id="b", kind="click", description="Submit the form to create the app (Create app button)"),
        PlanStep(id="c", kind="navigate", description="Open the settings page"),
        PlanStep(id="d", kind="capture", description="capture", done_when=[Check(check="app_exists")]),
    ]
    notes = []
    out = validate_steps(steps, ["example.com"], notes)
    assert [c.check for c in out[1].done_when] == ["app_exists"]  # the step that actually creates
    assert [c.check for c in out[0].done_when] == ["at_page"]
    assert out[2].inferred and any("no checkable condition" in n for n in notes)
    assert out[3].done_when == []  # code-owned steps carry no model conditions
    assert has_checks(out)
    assert not has_checks([PlanStep(id="x", kind="click", description="Click it")])  # legacy plans


class NullStore:
    def checkpoint(self, *a, **k):
        return 0


def loop_with(run):
    lp = BrowserLoop(NullStore(), Masker(), None, None, FieldValues.default(CB))
    lp._proof, lp._jev_note, lp._recent, lp._asked_replace = True, "", [], set()
    lp._run_ref = run
    return lp


class Page:
    async def evaluate(self, js):
        return True  # every field equality test passes


def test_position_is_the_first_unproven_step_and_a_later_proof_implies_earlier_ones():
    oauth = Check(check="at_page", path="/apps/{app_id}/oauth2")
    steps = [
        PlanStep(id="s1", kind="fill", description="Fill the app name", value="app_name",
                 done_when=[Check(check="field_holds", field=FieldRef(label="Application name"), value="app_name")]),
        PlanStep(id="s2", kind="click", description="Create the app", done_when=[Check(check="app_exists")]),
        PlanStep(id="s3", kind="navigate", description="Open OAuth2", done_when=[oauth]),
        PlanStep(id="s4", kind="capture", description="capture"),
    ]
    run = Run(id="r", app_input="x", plan=Plan(steps=steps, allowed_domains=["127.0.0.1"]), created=["an app"])
    lp = loop_with(run)
    lp._allowed = ["127.0.0.1"]
    o = Observation(url="http://127.0.0.1:1/apps/42/oauth2", title="t", text=f"{lp.values.app_name} OAuth2",
                    url_masked="x")
    asyncio.run(lp._prove(run, Page(), o))
    # the form of s1 is gone, but the app exists (s2) and OAuth2 is open (s3): s1 is implied, s2/s3 proven
    assert run.proofs["s1"]["by"].startswith("implied by step")
    assert run.proofs["s2"]["by"] == "code checks" and "s3" in run.proofs
    assert run.plan_cursor == 3 and run.bindings == {"app_id": "42"}


def test_jev_block_carries_progress_checks_next_steps_and_recent_actions():
    steps = [PlanStep(id=f"s{i}", kind="navigate", description=f"Step number {i}") for i in range(4)]
    run = Run(id="r", app_input="x", plan=Plan(steps=steps), plan_cursor=1, proofs={"s0": {"by": "code checks"}})
    lp = loop_with(run)
    lp._last_results = []
    lp._recent = ["click button 'Add Another' → no change"]
    lp._jev_note = "You said this step is done, but these checks are not true yet: [✗] x"
    block = lp._jev_block(run, "Step number 1")
    assert block.startswith("Current step (2 of 4): Step number 1")
    assert "Already done: Step number 0 ✓" in block and "Next: Step number 2 · Step number 3" in block
    assert "no change" in block and "not true yet" in block and len(block) <= 1500
