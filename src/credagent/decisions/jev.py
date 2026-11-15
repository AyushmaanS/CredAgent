"""Jev: exactly five closed decisions per page, asked in one systemone request.

PRD §8. The answer sets are written here in code; Jev only picks among them.
Thresholds are provisional (Sprint 0) and get calibrated on the fake provider.
Fallback handling (what happens when a decision is uncertain) lives in the
browser loop / policy layer (Sprint 4); this module only reports certainty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

DECISION_KEYS = (
    "element_selection",
    "action_selection",
    "blocker_detection",
    "risk_assessment",
    "completion_detection",
)
ACTIONS = ("proceed", "step_complete", "wait", "go_back", "stuck")
RISK_LEVELS = ("read_only", "reversible", "hard_to_undo", "irreversible")
NONE_OPTION = "none"

# Provisional thresholds — see docs/DECISIONS.md D-011.
CHOICE_MIN_CONFIDENCE = 0.6
NOUL_YES = 0.8  # p >= this → confident "yes"
NOUL_NO = 0.2   # p <= this → confident "no"; in between → uncertain


class Candidate(BaseModel):
    id: str = Field(pattern=r"^c\d{1,3}$")
    description: str
    method: str = ""


class PageState(BaseModel):
    """Everything Jev sees. Built from already-masked page observations."""

    step_goal: str
    url: str
    title: str = ""
    visible_text: str = Field(default="", max_length=6000)
    candidates: list[Candidate] = Field(default_factory=list, max_length=60)


def build_questions(state: PageState) -> dict[str, Any]:
    element_criteria: dict[str, Any] = {
        c.id: f"{c.description} ({c.method})" if c.method else c.description
        for c in state.candidates
    }
    element_criteria[NONE_OPTION] = "None of these candidates does what the current step needs."
    return {
        "element_selection": {
            "type": "choice",
            "instructions": (
                "Which candidate element on this page should be used next to accomplish the "
                "step goal? Choose 'none' if no candidate fits."
            ),
            "criteria": element_criteria,
        },
        "action_selection": {
            "type": "choice",
            "instructions": "Given the step goal and the page, what should the agent do now?",
            "criteria": {
                "proceed": "Act on the page to make progress on the step goal.",
                "step_complete": "The step goal is already achieved on this page.",
                "wait": "The page is loading or processing; wait and look again.",
                "go_back": "This page is the wrong place for the step goal; go back.",
                "stuck": "No sensible way forward from this page.",
            },
        },
        "blocker_detection": {
            "type": "noul",
            "instructions": (
                "Does a human need to act on this page before the agent can continue? Human-only "
                "actions: signing in or creating an account, entering an email/phone code or 2FA, "
                "solving a CAPTCHA or bot check, identity or business verification, payment, "
                "accepting terms or any agreement (including 'by clicking ... you agree' wording)."
            ),
            "criteria": {
                "true": "The page requires one of those human-only actions now.",
                "false": "The agent can continue without a human on this page.",
            },
        },
        "risk_assessment": {
            "type": "score",
            "instructions": (
                "How risky is the most likely next action on this page toward the step goal?"
            ),
            "criteria": [
                "Read-only: navigating or viewing, nothing changes.",
                "Reversible: changes something that can easily be edited or undone.",
                "Hard to undo: creates or changes something that is difficult to reverse.",
                "Irreversible: deletes, submits for review, pays, or cannot be undone.",
            ],
        },
        "completion_detection": {
            "type": "noul",
            "instructions": (
                "Has the credential (client ID/secret, API key or token) been created and is it "
                "currently shown on this page?"
            ),
            "criteria": {
                "true": "A newly created credential is displayed on the page.",
                "false": "No created credential is displayed.",
            },
        },
    }


@dataclass(frozen=True)
class Decision:
    key: str
    value: Any            # choice string, risk level, or bool for noul
    confidence: float     # choice/score: model confidence; noul: distance-based certainty
    uncertain: bool
    raw: dict[str, Any]


@dataclass(frozen=True)
class JevDecisions:
    decisions: dict[str, Decision]
    model: str | None
    latency_ms: int | None

    def __getitem__(self, key: str) -> Decision:
        return self.decisions[key]

    @property
    def all_uncertain(self) -> bool:
        return all(d.uncertain for d in self.decisions.values())


def _uncertain(key: str, raw: dict[str, Any] | None = None) -> Decision:
    return Decision(key=key, value=None, confidence=0.0, uncertain=True, raw=raw or {})


def _parse_choice(key: str, ans: dict[str, Any], allowed: set[str]) -> Decision:
    choice = ans.get("choice")
    conf = float(ans.get("confidence") or 0.0)
    if choice not in allowed:
        return _uncertain(key, ans)
    return Decision(key, choice, conf, conf < CHOICE_MIN_CONFIDENCE, ans)


def _parse_noul(key: str, ans: dict[str, Any]) -> Decision:
    p = ans.get("noul")
    if not isinstance(p, int | float) or not 0.0 <= p <= 1.0:
        return _uncertain(key, ans)
    certain = p >= NOUL_YES or p <= NOUL_NO
    return Decision(key, p >= 0.5, abs(p - 0.5) * 2, not certain, ans)


def _parse_risk(ans: dict[str, Any]) -> Decision:
    key = "risk_assessment"
    probs = ans.get("probabilities")
    conf = float(ans.get("confidence") or 0.0)
    if not isinstance(probs, dict) or not probs:
        return _uncertain(key, ans)
    try:
        level = max(probs, key=lambda k: probs[k])
        idx = int(level)
    except (ValueError, TypeError):
        return _uncertain(key, ans)
    if not 0 <= idx < len(RISK_LEVELS):
        return _uncertain(key, ans)
    return Decision(key, RISK_LEVELS[idx], conf, conf < CHOICE_MIN_CONFIDENCE, ans)


def parse_response(state: PageState, response: dict[str, Any]) -> JevDecisions:
    """Validate a systemone response. Missing/malformed answers become uncertain."""
    answers = response.get("answers") if isinstance(response, dict) else None
    answers = answers if isinstance(answers, dict) else {}
    element_ids = {c.id for c in state.candidates} | {NONE_OPTION}
    out: dict[str, Decision] = {}
    for key in DECISION_KEYS:
        ans = answers.get(key)
        if not isinstance(ans, dict):
            out[key] = _uncertain(key)
        elif key == "element_selection":
            out[key] = _parse_choice(key, ans, element_ids)
        elif key == "action_selection":
            out[key] = _parse_choice(key, ans, set(ACTIONS))
        elif key == "risk_assessment":
            out[key] = _parse_risk(ans)
        else:
            out[key] = _parse_noul(key, ans)
    return JevDecisions(out, response.get("model"), response.get("latency_ms"))


def all_uncertain(state: PageState) -> JevDecisions:
    """Result used after a failed retry (PRD §8 Jev-failure rule)."""
    return JevDecisions({k: _uncertain(k) for k in DECISION_KEYS}, None, None)
