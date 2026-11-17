"""D-078 phase 3: code-assigned risk (the owner's rule, 2026-11-17) and the ported handoff helpers."""

import pytest

from credagent.agent.handoff import still_needed, terms_instruction, terms_submit_text
from credagent.browser.snapshot import build_snapshot
from credagent.policy.engine import ProposedAction, evaluate
from credagent.policy.hard_checks import check
from credagent.policy.risk import assess_risk
from credagent.secrets.masking import Masker
from tests.unit.test_snapshot import el, raw

ALLOWED = ["127.0.0.1"]


def act(method, label, href=None):
    return ProposedAction(method, "/x", label, href=href)


@pytest.mark.parametrize("action,created,risk", [
    (act("navigate", "navigate to /apps", href="http://127.0.0.1/apps"), False, "read_only"),
    (act("click", "link 'OAuth2'", href="http://127.0.0.1/oauth2"), False, "read_only"),
    (act("fill", "text field 'Name'"), False, "reversible"),
    (act("click", "button 'Save Changes'"), False, "reversible"),
    (act("click", "button 'Add Redirect'"), False, "reversible"),
    (act("click", "button 'Next'"), False, "reversible"),
    (act("click", "button 'Yes, do it!'"), False, "reversible"),  # the provider's own confirm, after a reset the
    #                                                              person approved
    (act("click", "button 'Create app'"), False, "reversible"),  # the one consented create
    (act("click", "button 'Reset Secret'"), False, "hard_to_undo"),
    (act("click", "button 'Regenerate secret'"), False, "hard_to_undo"),
    (act("click", "button 'Generate a new token'"), False, "hard_to_undo"),
    (act("click", "button 'Transfer ownership'"), False, "hard_to_undo"),
    (act("click", "button 'Publish'"), False, "hard_to_undo"),
    (act("click", "button 'Confirm'"), False, "hard_to_undo"),
    (act("click", "button 'Disable'"), False, "hard_to_undo"),
])
def test_risk_is_assigned_by_code_from_what_the_control_is(action, created, risk):
    assert assess_risk(action, already_created=created) == risk


def snap_with(*elements, **kw):
    return build_snapshot(raw(list(elements), url="http://127.0.0.1:1/x", **kw), Masker())


def verdict(label, created=False, method="click", href=None):
    s = snap_with(el("/x", "button", "b", tag="button"))
    a = ProposedAction(method, "/x", label, href=href)
    return evaluate(a, s.obs, check(s.obs, ALLOWED), ALLOWED, risk=assess_risk(a, already_created=created),
                    risk_uncertain=False, already_created=created)


def test_the_owner_rule_in_the_policy_engine():
    # no repeated "New Application?" questions: the first create click goes ahead (consent covered it)
    assert verdict("button 'New Application'").decision == "allow"
    assert verdict("button 'Create'").decision == "allow"
    assert verdict("button 'Save Changes'").decision == "allow"
    # a second create is denied before risk is read
    assert verdict("button 'Create app'", created=True).category == "already_created"
    # consequence verbs ask the person; the secret-rotation rule asks too
    assert verdict("button 'Transfer ownership'").decision == "DECIDE"
    assert verdict("button 'Reset Secret'").decision == "DECIDE"
    # and the hard stops stay hard whatever the risk
    for label in ("button 'Delete app'", "button 'Submit for review'", "button 'Upgrade to Pro'",
                  "button 'Verify your business'", "button 'Sign out'"):
        assert verdict(label).decision == "deny", label


# ------------------------------------------------------------------ the ported handoff helpers

def terms_page(checked=False, url="http://127.0.0.1:1/apps/new"):
    inputs = [{"xpath": "/c", "tag": "input", "type": "checkbox", "name": "", "id": "", "required": True,
               "checked": checked, "readonly": False, "autocomplete": "", "value_len": 0, "value_secretlike": False,
               "options": [], "form": "/form[1]", "section": "",
               "label": "I have read and agree to the Developer Terms"},
              {"xpath": "/n", "tag": "input", "type": "text", "name": "", "id": "", "required": True,
               "checked": False, "readonly": False, "autocomplete": "", "value_len": 0, "value_secretlike": False,
               "options": [], "form": "/form[1]", "section": "", "label": "Application name"}]
    buttons = [{"xpath": "/b", "text": "Create app", "type": "submit", "name": "", "value": "", "disabled": False,
                "form": "/form[1]", "in_dialog": False}]
    return build_snapshot(raw([el("/b", "button", "Create app", tag="button")], url=url, inputs=inputs,
                              buttons=buttons, text="Terms"), Masker())


def test_the_terms_card_names_the_box_the_button_and_what_is_left():
    s = terms_page()
    gates = check(s.obs, ALLOWED)
    text, missing = terms_instruction(s.obs, gates)
    assert "tick “I have read and agree to the Developer Terms”" in text and "click “Create app”" in text
    assert "first fill the required field(s) the agent could not: “Application name”" in text
    assert missing.startswith("tick “I have read")
    assert terms_submit_text(s.obs, gates) == "Create app"
    ticked = terms_page(checked=True)
    assert "is ticked, but the form is not submitted yet" in terms_instruction(ticked.obs, check(ticked.obs, ALLOWED))[0]


def test_still_needed_after_enter():
    before = terms_page()
    same = terms_page()
    assert "tick" in still_needed(same, before, "terms", ALLOWED)  # nothing happened: still needed
    moved = terms_page(url="http://127.0.0.1:1/apps/42")
    assert still_needed(moved, before, "terms", ALLOWED) is None  # the page moved on: resolved
    quiet = snap_with(el("/b", "button", "OK", tag="button"))
    assert still_needed(quiet, quiet, "unexpected", ALLOWED) == "nothing has changed on the page yet"
    changed = snap_with(el("/b", "button", "OK", tag="button"), el("/c", "link", "Next", tag="a"))
    assert still_needed(changed, quiet, "unexpected", ALLOWED) is None
