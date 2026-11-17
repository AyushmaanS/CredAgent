"""Checkable steps: the closed check vocabulary (design §5)."""

import asyncio
import json
import re

import pytest
from pydantic import ValidationError

from credagent.browser.candidates import FieldValues
from credagent.browser.observe import Observation
from credagent.steps.checks import Check, Context, FieldRef, evaluate, evaluate_all, path_regex

CB = "http://127.0.0.1:8976/callback"
V = FieldValues.default(CB)


class FakePage:
    """Answers the in-page equality test from a map of xpath -> value (the value never leaves this object)."""

    def __init__(self, values):
        self.values = values

    async def evaluate(self, js):
        xs = json.loads(re.search(r"const xs = (\[.*?\]), want", js).group(1))
        want = json.loads(re.search(r"want = (\".*?\");", js).group(1))
        return any(self.values.get(x, "").strip() == want for x in xs)


def box(xpath, label="", section="", value=""):
    return {"xpath": xpath, "tag": "input", "type": "text", "name": "", "id": "", "label": label, "section": section,
            "required": False, "checked": False, "readonly": False, "autocomplete": "", "value_len": len(value),
            "value_secretlike": False, "options": [], "form": None}


def obs(url="https://discord.com/developers/applications/123456789012345678/oauth2", **kw):
    return Observation(url=url, title="t", text=kw.pop("text", ""), url_masked=url, **kw)


def ctx(**kw):
    return Context(values=V, allowed_domains=["discord.com", "docs.discord.com"], **kw)


def run(check, o, c=None, page=None):
    return asyncio.run(evaluate(check, page or FakePage({}), o, c or ctx()))


def test_vocabulary_is_closed_and_validated():
    with pytest.raises(ValidationError):
        Check(check="run_javascript")
    with pytest.raises(ValidationError):
        Check(check="at_page", path="/apps/{user}/x")  # unknown placeholder
    with pytest.raises(ValidationError):
        Check(check="field_holds", field=FieldRef(label="Redirects"), value="anything")  # not an approved value
    with pytest.raises(ValidationError):
        Check(check="field_holds", field=FieldRef(label="Client secret"), value="redirect_uri")  # never on secrets
    with pytest.raises(ValidationError):
        Check(check="element_present", role="button")  # needs a name


def test_at_page_binds_app_id_and_never_matches_docs():
    c = Check(check="at_page", path="/developers/applications/{app_id}/oauth2")
    bound = {}
    assert asyncio.run(evaluate(c, FakePage({}), obs(), ctx(), new_bindings=bound)) and bound == {
        "app_id": "123456789012345678"}
    assert not run(c, obs(), ctx(bindings={"app_id": "999"}))  # bound to another app
    docs = obs("https://docs.discord.com/developers/applications/123/oauth2")
    assert not run(c, docs)  # D-070: the docs never complete a console step
    assert not run(c, obs("https://evil.example/developers/applications/1/oauth2"))
    assert path_regex("/apps/*/x", {}).match("/apps/abc/x") and not path_regex("/apps/*/x", {}).match("/apps/a/b/x")


def test_element_present_and_absent():
    o = obs(buttons=[{"xpath": "/b", "text": "Save Changes", "type": "", "name": "", "value": "", "disabled": False,
                      "form": None, "in_dialog": False}],
            links=[{"xpath": "/a", "text": "OAuth2", "href": "x"}], headings=["Redirects"])
    assert run(Check(check="element_present", role="link", name="oauth2", match="exact"), o)
    assert run(Check(check="element_present", role="heading", name="Redirects"), o)
    assert not run(Check(check="element_absent", role="button", name="Save Changes"), o)
    assert run(Check(check="element_absent", role="button", name="Reset Secret"), o)


def test_field_holds_is_an_equality_test_d071():
    o = obs(inputs=[box("/r0", label="Select redirect URI", section="Redirects", value=CB + ".")])
    holds = Check(check="field_holds", field=FieldRef(section="Redirects"), value="redirect_uri")
    assert not run(holds, o, page=FakePage({"/r0": CB + "."}))  # the stray full stop: not the callback
    o2 = obs(inputs=[box("/r0", label="Select redirect URI", section="Redirects", value=CB)])
    assert run(holds, o2, page=FakePage({"/r0": CB}))
    other = "http://127.0.0.1:8976/callbacx"  # same length, different value: still false
    assert not run(holds, obs(inputs=[box("/r0", section="Redirects", value=other)]), page=FakePage({"/r0": other}))


def test_app_exists_and_credential_shown():
    o = obs(text="credagent-demo app")
    assert not run(Check(check="app_exists"), o)  # nothing created by this run
    assert run(Check(check="app_exists"), o, ctx(created=True, app_name="credagent-demo"))
    assert run(Check(check="app_exists"), obs(), ctx(created=True, bindings={"app_id": "123456789012345678"}))
    cs = Check(check="credential_shown", parts=["client_id", "client_secret"])
    assert not run(cs, o, ctx(credential_parts={"client_id"}))  # D-061: an ID alone is not the credential
    assert run(cs, o, ctx(credential_parts={"client_id", "client_secret"}))


def test_evaluate_all_reports_each_check():
    o = obs(inputs=[box("/r0", section="Redirects", value=CB)])
    res, bound = asyncio.run(evaluate_all([
        Check(check="at_page", path="/developers/applications/{app_id}/oauth2"),
        Check(check="field_holds", field=FieldRef(section="Redirects"), value="redirect_uri"),
        Check(check="element_absent", role="button", name="Save Changes"),
    ], FakePage({"/r0": CB}), o, ctx()))
    assert [r.ok for r in res] == [True, True, True] and bound["app_id"] == "123456789012345678"
    assert res[1].line().startswith("[✓]")
