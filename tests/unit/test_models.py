import pytest
from pydantic import ValidationError

from credagent.state.models import (
    Blocker,
    CredentialPart,
    CredentialReference,
    Fact,
    Handoff,
    InvariantError,
    Run,
    StepRecord,
    VerificationResult,
    decide_outcome,
    new_run_id,
)

CRED = CredentialReference(kind="oauth_client", parts={
    "client_secret": CredentialPart(store_ref="file:r1/client_secret", masked_display="•••(40 chars)")})


def verified(limits=()):
    return VerificationResult(label="verified", test_description="token request",
                              observed_result="200 + access token", production_limitations=list(limits))


def run(**kw):
    return Run(id="r1", app_input="Fakeprov", **kw)


@pytest.mark.parametrize("label", ["client_recognized", "inconclusive", "invalid", "untested"])
def test_succeeded_impossible_without_verified(label):
    v = VerificationResult(label=label, test_description="t", observed_result="o")
    with pytest.raises(ValidationError):
        run(status="succeeded", credential=CRED, verification=v)
    r = run(credential=CRED, verification=v)
    with pytest.raises((InvariantError, ValidationError)):
        r.transition("succeeded")
    assert r.status == "running"


def test_succeeded_needs_credential_and_no_limitations():
    with pytest.raises(ValidationError):
        run(status="succeeded", verification=verified())
    with pytest.raises(ValidationError):
        run(status="succeeded", credential=CRED, verification=verified(["testing mode only"]))
    r = run(credential=CRED, verification=verified())
    r.transition("succeeded", "ok")
    assert r.status == r.actual_outcome == "succeeded"


@pytest.mark.parametrize(("kw", "expected"), [
    ({"credential_captured": True, "verification": None}, "partial"),
    ({"credential_captured": True, "verification": VerificationResult(
        label="client_recognized", test_description="t", observed_result="o")}, "partial"),
    ({"credential_captured": True, "verification": VerificationResult(
        label="invalid", test_description="t", observed_result="401")}, "failed"),
    ({"credential_captured": False, "verification": None, "provider_review_pending": True},
     "waiting_on_provider"),
    ({"credential_captured": False, "verification": None,
      "blocker": Blocker(kind="business_verification", description="needs company", who_must_act="owner")},
     "blocked"),
    ({"credential_captured": False, "verification": None, "error": "service unavailable"}, "failed"),
    ({"credential_captured": False, "verification": None}, "failed"),
])
def test_outcome_mapping(kw, expected):
    assert decide_outcome(**kw)[0] == expected


def test_outcome_mapping_verified():
    assert decide_outcome(credential_captured=True, verification=verified())[0] == "succeeded"
    out, reason = decide_outcome(credential_captured=True, verification=verified(["testing mode"]))
    assert out == "partial" and "testing mode" in reason


def test_transitions():
    r = run()
    r.transition("blocked", "needs business verification")
    with pytest.raises(InvariantError):
        r.transition("running")  # only via resume
    r.transition("running", resume=True)
    r.transition("failed", "service unavailable", resumable=False)
    with pytest.raises(InvariantError):
        r.transition("running", resume=True)
    r2 = run(); r2.transition("cancelled")  # noqa: E702
    with pytest.raises(InvariantError):
        r2.transition("running", resume=True)


def test_terminal_run_rejects_steps():
    r = run()
    r.transition("blocked", "x")
    with pytest.raises(InvariantError):
        r.add_step(StepRecord(action="click", actor="agent", outcome="done"))


def test_one_pending_handoff_and_decide_answers():
    r = run()
    h = r.open_handoff(Handoff(kind="DECIDE", reason="app type", completed_so_far="2 of 5",
                               person_instruction="Pick one", where="terminal",
                               expected_resume_action="select it", options=["web", "spa"]))
    with pytest.raises(InvariantError):
        r.open_handoff(Handoff(kind="DO", reason="x", completed_so_far="", person_instruction="",
                               where="browser", expected_resume_action=""))
    with pytest.raises(InvariantError):
        r.resolve_handoff(h.id, answer="desktop")
    r.resolve_handoff(h.id, answer="web")
    assert r.pending_handoff is None and r.handoffs[0].answer == "web"


def test_handoff_shape_rules():
    with pytest.raises(ValidationError):
        Handoff(kind="DECIDE", reason="x", completed_so_far="", person_instruction="", where="t",
                expected_resume_action="", options=["only one"])
    with pytest.raises(ValidationError):
        Handoff(kind="DO", reason="x", completed_so_far="", person_instruction="", where="b",
                expected_resume_action="", options=["a", "b"])


def test_runs_saved_before_d078_still_load():
    """The step-machine loop's bookkeeping fields and the plan step conditions are ignored, not an error."""
    r = run()
    data = r.model_dump()
    data.update({"replans_used": 1, "plan_cursor": 3, "loop": "legacy", "proofs": {"p1": {"checks": []}},
                 "bindings": {"app_id": "1"}})
    data["plan"]["revision"] = 1
    data["plan"]["steps"] = [{"id": "p1", "description": "d", "kind": "click", "where": [{"check": "at_page"}],
                              "done_when": [], "inferred": True}]
    loaded = Run.model_validate(data)
    assert loaded.plan.steps[0].id == "p1" and not hasattr(loaded, "proofs")


def test_sourced_fact_needs_url_and_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        Fact(statement="x", kind="sourced")
    Fact(statement="x", kind="unknown")
    with pytest.raises(ValidationError):
        CredentialReference(kind="api_key", parts={}, raw_value="nope")


def test_credential_part_requires_store_reference():
    with pytest.raises(ValidationError):
        CredentialPart(store_ref="sk_live_whatever", masked_display="x")  # secret-scan: allow


def test_run_id_is_store_safe():
    rid = new_run_id("Google Cloud (OAuth)!")
    assert len(rid) <= 64 and all(c.isalnum() or c in "-_." for c in rid)
