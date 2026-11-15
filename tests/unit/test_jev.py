from credagent.decisions.jev import (
    DECISION_KEYS,
    Candidate,
    PageState,
    all_uncertain,
    build_questions,
    parse_response,
)


def state():
    return PageState(
        step_goal="Open the create-app form",
        url="http://127.0.0.1/apps",
        candidates=[Candidate(id="c0", description="New app button", method="click"),
                    Candidate(id="c1", description="Docs link", method="click")],
    )


def test_exactly_five_questions_with_closed_answer_sets():
    q = build_questions(state())
    assert tuple(q) == DECISION_KEYS
    assert set(q["element_selection"]["criteria"]) == {"c0", "c1", "none"}
    assert set(q["action_selection"]["criteria"]) == {
        "proceed", "step_complete", "wait", "go_back", "stuck"}
    assert q["blocker_detection"]["type"] == "noul"
    assert q["risk_assessment"]["type"] == "score" and len(q["risk_assessment"]["criteria"]) == 4
    assert q["completion_detection"]["type"] == "noul"


def good_response():
    return {"model": "jev-1.13.0", "answers": {
        "element_selection": {"type": "choice", "choice": "c0", "confidence": 0.9},
        "action_selection": {"type": "choice", "choice": "proceed", "confidence": 0.85},
        "blocker_detection": {"type": "noul", "noul": 0.05},
        "risk_assessment": {"type": "score", "score": 0.2, "confidence": 0.8,
                            "probabilities": {"0": 0.8, "1": 0.2, "2": 0.0, "3": 0.0}},
        "completion_detection": {"type": "noul", "noul": 0.02},
    }}


def test_parse_confident_response():
    d = parse_response(state(), good_response())
    assert d["element_selection"].value == "c0" and not d["element_selection"].uncertain
    assert d["blocker_detection"].value is False and not d["blocker_detection"].uncertain
    assert d["risk_assessment"].value == "read_only"
    assert d.model == "jev-1.13.0"


def test_middle_probability_is_uncertain():
    r = good_response()
    r["answers"]["blocker_detection"]["noul"] = 0.5
    assert parse_response(state(), r)["blocker_detection"].uncertain


def test_unknown_choice_or_missing_answer_is_uncertain():
    r = good_response()
    r["answers"]["element_selection"]["choice"] = "c9"
    del r["answers"]["completion_detection"]
    d = parse_response(state(), r)
    assert d["element_selection"].uncertain and d["element_selection"].value is None
    assert d["completion_detection"].uncertain


def test_garbage_response_all_uncertain():
    assert parse_response(state(), {"oops": 1}).all_uncertain
    assert all_uncertain(state()).all_uncertain
