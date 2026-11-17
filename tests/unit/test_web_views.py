"""The UI's view model (D-089): what the page shows is derived from recorded backend facts, and never holds a secret."""

import json

from credagent.state.models import (
    Blocker,
    BrowserSession,
    CredentialPart,
    CredentialReference,
    Evidence,
    Handoff,
    Identification,
    Plan,
    Run,
    VerificationResult,
)
from credagent.web.views import build_view, latest_activity, plain, public_event, summary

SECRET = "Zk93-fake-secret-value-for-tests-1234"  # fake; secret-scan: allow


def run_with(**kw) -> Run:
    plan = Plan(identification=Identification(canonical_name="Acme", provider="Acme Inc.", confidence="high"),
                credential_kind="oauth_client", console_url="https://dev.acme.example/apps",
                allowed_domains=["acme.example"])
    return Run(id="r1", app_input="acme", app_name="Acme", provider="Acme Inc.", plan=plan, phase="browser", **kw)


def handoff(kind="DO", blocker="sign_in", **kw) -> Handoff:
    base = dict(kind=kind, reason="This page asks for a password.", blocker_kind=blocker,
                completed_so_far="3 actions by the agent, 0 by you",
                person_instruction="Sign in in the CredAgent browser window. When you are done, press Enter.",
                where="the CredAgent Chrome window", expected_resume_action="Re-check the page.",
                evidence=[Evidence(kind="observed", text="password field")])
    if kind == "DECIDE":
        base |= dict(where="this terminal", options=["Yes, do it", "No, stop here"], person_instruction="Pick one.")
    return Handoff(**(base | kw))


def live(**kw):
    return {"alive": True, "stage": "browser", "error": None, "pending": None, "consent": None, "consented": True} | kw


def ev(seq, type_, **data):
    return {"seq": seq, "at": f"2026-11-17T10:00:{seq:02d}+00:00", "type": type_, "data": data, "status": "running"}


def test_a_running_run_with_no_open_question_is_running():
    v = build_view(run_with(), [ev(1, "browser_opened")], live())
    assert v["state"] == "running" and v["attention"] is None
    ids = [m["id"] for m in v["milestones"]]
    assert ids == ["identified", "portal", "type", "consent", "browser", "registered", "captured", "verified"]
    status = {m["id"]: m["status"] for m in v["milestones"]}
    assert status["identified"] == status["portal"] == status["type"] == status["consent"] == status["browser"] == "done"
    assert status["registered"] == "current" and status["captured"] == status["verified"] == "pending"


def test_a_pending_do_handoff_needs_attention_and_speaks_plainly():
    r = run_with()
    r.open_handoff(handoff())
    v = build_view(r, [ev(1, "browser_opened")], live(pending="enter"))
    a = v["attention"]
    assert v["state"] == "attention" and a["type"] == "do" and a["title"] == "Your attention is needed"
    assert a["headline"] == "Sign in to continue" and a["handoff_id"]
    assert "Enter" not in a["instruction"] and "terminal" not in a["instruction"] and a["instruction"].startswith("Sign in")
    assert a["where"] == "the agent's Chrome window" and "Identified" not in a["done_so_far"]
    assert "Application identified" in a["done_milestones"]
    assert [m["status"] for m in v["milestones"] if m["status"] in ("blocked", "current")] == ["blocked"]


def test_a_decide_handoff_offers_its_options_and_no_terminal_words():
    r = run_with()
    r.open_handoff(handoff("DECIDE", "other"))
    a = build_view(r, [], live(pending="choose", options=["Yes, do it", "No, stop here"]))["attention"]
    assert a["type"] == "decide" and a["options"] == ["Yes, do it", "No, stop here"]


def test_consent_is_shown_while_the_controller_waits_for_it():
    consent = {"provider": "Acme Inc.", "app": "Acme", "terms": {"finding": "unclear"}}
    r = run_with()
    r.phase = "planned"
    v = build_view(r, [], live(pending="consent", consent=consent, consented=False, stage="awaiting_consent"))
    assert v["state"] == "attention" and v["attention"]["type"] == "consent" and v["attention"]["terms"]["finding"] == "unclear"
    assert next(m for m in v["milestones"] if m["id"] == "consent")["status"] == "blocked"


def test_without_a_live_controller_a_running_run_is_paused_and_resumable():
    v = build_view(run_with(), [], None)
    assert v["state"] == "paused" and v["paused"]["can_resume"] and not v["live"]["alive"]
    v2 = build_view(run_with(), [], {"alive": False, "stage": "stopped", "error": {"kind": "browser_closed", "message": "closed"},
                                     "pending": None, "consent": None, "consented": False})
    assert v2["paused"]["error"]["message"] == "closed"


def test_a_verified_credential_is_a_completed_result_with_only_masked_values():
    r = run_with()
    r.credential = CredentialReference(kind="oauth_client", parts={
        "client_id": CredentialPart(store_ref="file:r1/client_id", masked_display="••• (19 chars)"),
        "client_secret": CredentialPart(store_ref="file:r1/client_secret", masked_display="Zk93… (32 chars)")})
    r.verification = VerificationResult(label="verified", tested_at="2026-11-17T10:05:00+00:00",
                                        test_description="Client-credentials token request",
                                        observed_result="HTTP 200: the provider issued an access token")
    r.status = "succeeded"
    r.created = ["an app (created by the person)"]
    v = build_view(r, [ev(1, "consent_given"), ev(2, "browser_opened"), ev(3, "credential_captured")], None)
    res = v["result"]
    assert v["state"] == "completed" and v["headline"] == "Credentials verified" and not res["partial"]
    assert [p["label"] for p in res["parts"]] == ["Client ID", "Client secret"]
    assert res["parts"][1]["masked"] == "Zk93… (32 chars)" and res["verification"]["label"] == "verified"
    assert res["completed_at"] == "2026-11-17T10:05:00+00:00" and res["permissions"] is None
    assert all(m["status"] == "done" for m in v["milestones"])
    assert SECRET not in json.dumps(v) and "store_ref" not in json.dumps(v) and "file:" not in json.dumps(v)


def test_a_captured_but_unverified_credential_is_not_shown_as_success():
    r = run_with()
    r.credential = CredentialReference(kind="oauth_client", parts={
        "client_id": CredentialPart(store_ref="file:r1/client_id", masked_display="•••")})
    r.verification = VerificationResult(label="inconclusive", test_description="t", observed_result="HTTP 400 (invalid_scope)",
                                        tested_at="2026-11-17T10:05:00+00:00")
    r.status = "partial"
    v = build_view(r, [], None)
    assert v["state"] == "completed" and v["result"]["partial"] and v["headline"].startswith("Credentials captured, not fully")
    assert next(m for m in v["milestones"] if m["id"] == "verified")["status"] == "blocked"


def test_failures_are_classified_from_status_and_resumable():
    r = run_with()
    r.transition("failed", "service unavailable: FastRouter", resumable=True)
    f = build_view(r, [], None)["failure"]
    assert f["kind"] == "recoverable" and f["can_resume"] and "service unavailable" in f["reason"]
    r2 = run_with()
    r2.add_blocker(Blocker(kind="business_verification", description="Business verification required.",
                           who_must_act="person", next_steps=["Complete verification at the provider."]))
    r2.transition("blocked", "business verification", resumable=True)
    f2 = build_view(r2, [], None)["failure"]
    assert f2["kind"] == "needs_you" and f2["next_steps"] == ["Complete verification at the provider."]
    r3 = run_with()
    r3.transition("blocked", "the app could not be identified", resumable=False)
    f3 = build_view(r3, [], None)["failure"]
    assert f3["kind"] == "unrecoverable" and not f3["can_resume"]


def test_plain_replaces_terminal_wording_without_changing_facts():
    assert plain("Fill the field yourself in the browser window, then press Enter.") == \
        "Fill the field yourself in the browser window."
    assert plain("If you agree, click “Create”. If you do not agree, press Ctrl+C: nothing is submitted and the run is saved.") \
        == "If you agree, click “Create”. If you do not agree, choose “Save and stop”: nothing is submitted and the run is saved."
    assert plain("Answer in this terminal.") == "Answer in this page."
    assert plain("It stays 5 characters long.") == "It stays 5 characters long."


def test_latest_activity_is_the_newest_meaningful_event():
    r = run_with()
    events = [ev(1, "research_started"), ev(2, "page_observed", url="x"), ev(3, "agent_step", reason="Click the OAuth2 link", action="click"),
              ev(4, "action_started", action="click"), ev(5, "page_observed", url="y")]
    assert latest_activity(r, events)["text"] == "Click the OAuth2 link"
    assert latest_activity(r, [ev(1, "page_observed")]) is None


def test_the_log_and_the_list_carry_no_page_data_or_secrets():
    e = public_event(ev(7, "page_observed", url="https://x", hints=[{"len": 32}]))
    assert set(e) == {"seq", "at", "type", "text"} and "hints" not in e["text"]
    r = run_with()
    r.browser = BrowserSession(chrome_pid=123, cdp_port=9222, profile_dir="profile")
    assert summary(r)["state"] == "paused" and "profile" not in json.dumps(summary(r))
