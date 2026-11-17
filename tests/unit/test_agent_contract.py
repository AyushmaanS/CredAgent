"""D-078 phase 2: the step contract, validation against the snapshot, and the path into the policy rules."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from credagent.agent.step import (
    ACTIONS,
    STEP_SCHEMA,
    AgentStep,
    StepRejected,
    to_proposed,
    validate_step,
)
from credagent.browser.candidates import FieldValues
from credagent.browser.snapshot import build_snapshot
from credagent.policy.engine import evaluate
from credagent.policy.hard_checks import check
from credagent.secrets.masking import Masker
from credagent.steps.checks import APPROVED_VALUES
from tests.unit.test_snapshot import el, raw

CB = "http://127.0.0.1:8976/callback"
VALUES = FieldValues.default(CB)
ALLOWED = ["127.0.0.1"]
BASE = "http://127.0.0.1:1"


def page(extra_inputs=(), extra_buttons=(), **kw):
    """A console page: sidebar link, fields, dropdown, scope checkbox, buttons (one carries the terms)."""
    elements = [
        el("/a[1]", "link", "OAuth2", tag="a", href=BASE + "/apps/42/oauth2"),
        el("/i[1]", "field", "Application name", tag="input", type="text"),
        el("/i[2]", "field", "Email", tag="input", type="text"),
        el("/i[3]", "field", "Password", tag="input", type="password"),
        el("/i[4]", "field", "Client ID", tag="input", type="text", readonly=True, value_len=3),
        el("/s[1]", "select", "App type", tag="select", options=["Web app", "Single-page app"]),
        el("/c[1]", "checkbox", "identify", tag="input", type="checkbox"),
        el("/c[2]", "checkbox", "I agree to the Terms", tag="input", type="checkbox"),
        el("/b[1]", "button", "Create", tag="button"),
        el("/b[2]", "button", "Delete app", tag="button"),
        el("/b[3]", "button", "Reset Secret", tag="button"),
        el("/b[4]", "button", "Save Changes", tag="button", disabled=True),
        el("/b[5]", "button", "Add Redirect", tag="button"),
    ]
    inputs = [
        {"xpath": "/c[2]", "tag": "input", "type": "checkbox", "name": "", "id": "", "required": False,
         "checked": False, "readonly": False, "autocomplete": "", "value_len": 0, "value_secretlike": False,
         "options": [], "form": None, "label": "By clicking Create, you agree to the Developer Terms",
         "section": ""},
        {"xpath": "/i[2]", "tag": "input", "type": "text", "name": "", "id": "", "required": False, "checked": False,
         "readonly": False, "autocomplete": "", "value_len": 0, "value_secretlike": False, "options": [],
         "form": None, "label": "Email", "section": ""},
    ]
    buttons = [{"xpath": x, "text": t, "type": "button", "name": "", "value": "", "disabled": False, "form": None,
                "in_dialog": False} for x, t in (("/b[1]", "Create"), ("/b[2]", "Delete app"),
                                                 ("/b[3]", "Reset Secret"), ("/b[5]", "Add Redirect"))]
    return build_snapshot(raw(elements, url=BASE + "/apps/42", inputs=inputs, buttons=buttons,
                              text="By clicking Create, you agree to the Developer Terms.", **kw), Masker())


def step(**kw):
    base = {"action": "click", "reason": "because the step needs it", "expected": "something changes"}
    base.update(kw)
    return AgentStep.model_validate(base)


def ok(snap, **kw):
    return validate_step(step(**kw), snap, values=VALUES, allowed_domains=ALLOWED)


def refused(snap, code, **kw):
    with pytest.raises(StepRejected) as e:
        ok(snap, **kw)
    assert e.value.code == code, (e.value.code, e.value.message)
    return e.value.message


# ------------------------------------------------------------------ the schema and the model

def test_schema_is_strict_flat_and_matches_the_model():
    props = STEP_SCHEMA["properties"]
    assert STEP_SCHEMA["additionalProperties"] is False and STEP_SCHEMA["required"] == list(props)
    assert set(props) == set(AgentStep.model_fields)
    assert props["action"]["enum"] == ACTIONS
    assert set(props["value_key"]["enum"]) == {*APPROVED_VALUES, None}
    assert all(p.get("type") != "object" for p in props.values())  # flat: no nested objects


@pytest.mark.parametrize("bad", [
    {"action": "run_javascript", "reason": "x"},
    {"action": "click", "reason": "x", "extra": 1},
    {"action": "type", "reason": "x", "value_key": "password"},
    {"action": "scroll", "reason": "x", "direction": "sideways"},
    {"action": "ask_person", "reason": "x", "person_kind": "MAYBE"},
])
def test_parsing_refuses_anything_outside_the_contract(bad):
    with pytest.raises(ValidationError):
        AgentStep.model_validate(bad)


# ------------------------------------------------------------------ validation against the page

def test_click_checks():
    s = page()
    v = ok(s, ref="e1")
    assert v.element.name == "OAuth2" and v.target() == 'link "OAuth2"'
    assert ok(s, ref="e7").element.role == "checkbox"  # a checkbox is clicked
    assert "not in the current snapshot" in refused(s, "unknown_ref", ref="e99")
    refused(s, "missing_ref")
    refused(s, "disabled", ref="e12")
    assert "use type or select" in refused(s, "wrong_element", ref="e2")
    refused(s, "empty_reason", ref="e1", reason=" ")


def test_type_only_approved_values_by_key_and_only_into_plain_fields():
    s = page()
    v = ok(s, action="type", ref="e2", value_key="app_name")
    assert v.value == VALUES.app_name and "typed" not in v.target()
    assert "one of" in refused(s, "bad_value_key", action="type", ref="e2")
    refused(s, "wrong_element", action="type", ref="e4", value_key="app_name")  # password
    refused(s, "wrong_element", action="type", ref="e5", value_key="app_name")  # read-only
    refused(s, "wrong_element", action="type", ref="e1", value_key="app_name")  # a link
    no_desc = SimpleNamespace(app_name="x", homepage_url="http://h", redirect_uri=CB, description="")
    with pytest.raises(StepRejected, match="no approved value"):
        validate_step(step(action="type", ref="e2", value_key="description"), s, values=no_desc,
                      allowed_domains=ALLOWED)


def test_select_resolves_the_exact_option_or_lists_the_real_ones():
    s = page()
    assert ok(s, action="select", ref="e6", option="web APP").option == "Web app"
    msg = refused(s, "bad_option", action="select", ref="e6", option="Quantum")
    assert "Web app | Single-page app" in msg and "DECIDE" in msg
    refused(s, "wrong_element", action="select", ref="e2", option="x")


def test_navigate_scroll_wait_inspect_back():
    s = page()
    assert ok(s, action="navigate", url="/apps/42/oauth2").url == BASE + "/apps/42/oauth2"  # relative
    refused(s, "off_domain", action="navigate", url="https://evil.example/x")
    refused(s, "bad_url", action="navigate", url="file:///etc/passwd")
    refused(s, "bad_url", action="navigate", url="javascript:alert(1)")
    refused(s, "missing_url", action="navigate")
    refused(s, "docs_page", action="navigate", url="http://127.0.0.1:1/docs")
    assert ok(s, action="scroll").direction == "down" and ok(s, action="scroll", direction="top").direction == "top"
    assert ok(s, action="wait", wait_ms=999_999).ms == 5000 and ok(s, action="wait", wait_ms=10).ms == 200
    assert ok(s, action="inspect", ref="e1").element is not None
    refused(s, "wrong_element", action="inspect", ref="e4")
    assert ok(s, action="back").action == "back" and ok(s, action="done").action == "done"


def test_ask_person_and_give_up_need_substance():
    s = page()
    assert ok(s, action="ask_person", person_kind="DO", person_why="Sign in to the console").action == "ask_person"
    refused(s, "bad_person", action="ask_person", person_kind="DO")
    refused(s, "bad_person", action="ask_person", person_kind="DECIDE", person_why="Which type?",
            person_options=["only one"])
    assert ok(s, action="ask_person", person_kind="DECIDE", person_why="Which type?",
              person_options=["Web app", "SPA", "Stop"]).action == "ask_person"
    refused(s, "empty_reason", action="give_up", reason="stuck")
    assert ok(s, action="give_up", reason="The console needs business verification first.").action == "give_up"


# ------------------------------------------------------------------ into the existing policy rules

def verdict(s, already_created=False, **kw):
    v = ok(s, **kw)
    proposed = to_proposed(v)
    assert proposed is not None
    gates = check(s.obs, ALLOWED)
    return evaluate(proposed, s.obs, gates, ALLOWED, risk="reversible", risk_uncertain=False,
                    already_created=already_created)


def test_policy_still_has_the_last_word_on_what_the_model_proposes():
    s = page()
    # the control named in the agreement wording is the person's, whatever the model thinks
    v = verdict(s, ref="e9")
    assert v.decision == "DO" and v.category == "terms"
    assert verdict(s, ref="e8").category == "terms"  # the terms checkbox itself
    assert verdict(s, ref="e10").decision == "deny"  # Delete app: a hard stop
    assert verdict(s, ref="e11").decision == "DECIDE"  # Reset Secret: the person decides
    assert verdict(s, ref="e7").decision == "DECIDE"  # a permission is the person's choice
    # one app per run: once an app exists, creating another is refused before anything else
    again = verdict(s, already_created=True, ref="e9")
    assert again.decision == "deny" and again.category == "already_created"
    assert verdict(s, already_created=True, ref="e13").decision == "allow"  # "Add Redirect" is not creating


def test_fields_a_person_fills_stay_the_persons_even_with_an_approved_key():
    s = page()
    v = verdict(s, action="type", ref="e3", value_key="app_name")  # a field labelled "Email"
    assert v.decision == "DO" and v.category == "human_field"
    assert verdict(s, action="type", ref="e2", value_key="app_name").decision == "allow"  # "Application name"
    assert verdict(s, action="navigate", url="/apps/42/oauth2").decision == "allow"


def test_read_only_actions_and_handoffs_have_no_policy_input():
    s = page()
    for kw in ({"action": "scroll"}, {"action": "back"}, {"action": "wait"}, {"action": "inspect", "ref": "e1"},
               {"action": "done"}, {"action": "ask_person", "person_kind": "DO", "person_why": "sign in"}):
        assert to_proposed(ok(s, **kw)) is None
    p = to_proposed(ok(s, action="type", ref="e2", value_key="redirect_uri"))
    assert p.method == "fill" and p.field_key == "redirect_uri" and p.value == VALUES.redirect_uri
    assert p.description == "text field 'Application name'"
    assert to_proposed(ok(s, ref="e7")).method == "check"
