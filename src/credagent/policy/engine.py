"""Policy engine: the last word before every browser action (spec §6.6). Code only.

Order (fixed): hard-stop categories → terms → navigation allow-list → field rules → risk.
A model (Jev or LLM) proposes; this module disposes. Nothing here can be overridden by
model output: the model's choice is an input, never a permission.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from credagent.browser.observe import Observation
from credagent.policy.hard_checks import Gate, host_allowed

DENY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("delete", re.compile(r"\b(delete|remove|destroy|revoke|deactivate|uninstall)\b", re.I)),
    (
        "provider_review",
        re.compile(
            r"submit (for|to) (review|verification|approval)|request (review|approval)|"
            r"\bpublish\b|go live|submit (app|application) for",
            re.I,
        ),
    ),
    (
        "payment",
        re.compile(
            r"\b(pay|purchase|buy|upgrade|subscribe|checkout|add (a )?(payment|card)|"
            r"start (a )?(free )?trial|billing)\b",
            re.I,
        ),
    ),
    (
        "business_verification",
        re.compile(
            r"\b(verify|start verification|submit for verification)\b.*"
            r"(business|identity|organi[sz]ation)|business verification",
            re.I,
        ),
    ),
    (
        "account_security",
        re.compile(
            r"\b(sign out|log ?out|change password|two[- ]factor|2fa|security settings|"
            r"recovery (codes?|email)|sessions?)\b",
            re.I,
        ),
    ),
]
DECIDE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "secret_rotation",
        re.compile(
            r"\b(regenerate|rotate|reset)\b.*\b(secret|key|token)\b|"
            r"\b(secret|key|token)\b.*\b(regenerate|rotate|reset)\b",
            re.I,
        ),
    ),
    ("overwrite", re.compile(r"\b(overwrite|replace (the )?existing|replace app)\b", re.I)),
]
HUMAN_ONLY_FIELDS = re.compile(
    r"password|passcode|verification code|one[- ]time|otp|card|cvc|cvv|iban|ssn|"
    r"passport|tax id|date of birth|\bemail\b|e-mail|phone|username",
    re.I,
)
ACCOUNT_CREATION = re.compile(r"\b(sign up|create (an |your )?account|register (an |your )?account|join now)\b", re.I)
SIGN_IN = re.compile(r"^(sign in|log ?in|continue with [a-z]+)$", re.I)
RISK_ORDER = ("read_only", "reversible", "hard_to_undo", "irreversible")
# Controls that create a new app/client/project. One run creates at most one (D-063).
CREATE_RE = re.compile(
    r"\b(new|create|add|register)\b[^\n']{0,20}\b(app|apps|application|project|client(?![\s_-]*secret)|"
    r"integration|api key|oauth app)\b|'(create|new)'",
    re.I,
)


@dataclass(frozen=True)
class ProposedAction:
    method: Literal["click", "fill", "select", "check", "navigate"]
    xpath: str | None
    description: str
    href: str | None = None
    field_key: str | None = None  # for fill: which code-owned value
    value: str | None = None


@dataclass(frozen=True)
class Verdict:
    decision: Literal["allow", "deny", "DO", "DECIDE"]
    reason: str
    category: str = ""


def bump(risk: str | None) -> str:
    """PRD §8: an uncertain risk assessment assumes the next higher level."""
    if risk not in RISK_ORDER:
        return "hard_to_undo"
    return RISK_ORDER[min(RISK_ORDER.index(risk) + 1, len(RISK_ORDER) - 1)]


def evaluate(
    action: ProposedAction,
    obs: Observation,
    gates: list[Gate],
    allowed: list[str],
    *,
    risk: str | None,
    risk_uncertain: bool,
    already_created: bool = False,
) -> Verdict:
    label = action.description or ""
    # 1. Hard-stop categories (never, whatever any model says)
    for cat, rx in DENY_PATTERNS:
        if rx.search(label):
            return Verdict(
                "deny", f"'{label[:80]}' is a {cat.replace('_', ' ')} action; the agent never does this.", cat
            )
    if already_created and action.method == "click" and CREATE_RE.search(label):
        return Verdict(
            "deny", f"'{label[:80]}' would create another app, and this run already created one. The agent never "
            "creates a second one (D-063).", "already_created"
        )
    if ACCOUNT_CREATION.search(label):
        return Verdict("DO", "Account creation is the person's step.", "account_creation")
    if action.method == "click" and SIGN_IN.match(label.strip()):
        return Verdict("DO", "Signing in is the person's step.", "sign_in")

    # 2. Terms: the control and any submit that carries agreement belong to the person
    for g in gates:
        if g.kind != "terms":
            continue
        if g.target_xpath and action.xpath == g.target_xpath:
            return Verdict("DO", "Accepting terms is always the person's action.", "terms")
        if action.method == "click" and (_is_submit(action, obs, g.form_xpath) or _named_in_agreement(label, g)):
            return Verdict(
                "DO",
                "Submitting this form accepts terms (checkbox or implied wording); the person reviews and submits.",
                "terms",
            )
    if (
        action.method in ("check", "click")
        and re.search(r"\b(i agree|accept( all)?|agree)\b", label, re.I)
        and not re.search(r"cookie", label, re.I)
    ):
        return Verdict("DO", "Agreeing to anything is the person's action.", "terms")

    # 3. Navigation allow-list
    if action.href and not host_allowed(action.href, allowed):
        # A hard stop, not a handoff: the agent simply never follows it and keeps working (D-052).
        return Verdict(
            "deny", f"The link leads outside the allowed domains ({action.href[:80]}); the agent never follows it.",
            "off_allow_list",
        )

    # 4. Field rules: only code-owned values, never human-only fields; choices belong to the person
    if action.method in ("fill", "select", "check") and HUMAN_ONLY_FIELDS.search(label):
        return Verdict("DO", f"'{label[:60]}' is a field only the person fills.", "human_field")
    if action.method == "select":
        return Verdict("DECIDE", f"Choosing '{label[:60]}' (e.g. an app type) is the person's decision.", "choice")
    if action.method == "check":
        return Verdict(
            "DECIDE", f"Ticking '{label[:60]}' (e.g. a permission/scope) is the person's decision.", "permission"
        )
    if action.method == "fill" and (not action.field_key or action.value is None):
        return Verdict("deny", f"No code-approved value for the field '{label[:60]}'.", "no_value")

    # 5. Decide-categories and risk
    for cat, rx in DECIDE_PATTERNS:
        if rx.search(label):
            return Verdict("DECIDE", f"'{label[:80]}' is hard to undo; the person decides.", cat)
    if action.method == "fill":
        return Verdict("allow", "typing into a field without submitting is reversible (code rule)")
    if action.href and not _is_button(action, obs):
        return Verdict("allow", "following a link within the allowed domains changes nothing (code rule)")
    effective = bump(risk) if risk_uncertain else (risk or "hard_to_undo")
    if effective == "irreversible":
        # Not a named hard-stop category (those were denied above), so the person decides (D-045).
        return Verdict(
            "DECIDE",
            "Assessed as irreversible"
            + (" (risk uncertain, assumed one level higher)" if risk_uncertain else "")
            + ". The agent will not do this unless you say so.",
            "irreversible",
        )
    if effective == "hard_to_undo":
        return Verdict(
            "DECIDE",
            "The risk of this action could not be assessed, so the agent assumes it is hard to undo; you decide."
            if risk_uncertain and risk not in RISK_ORDER
            else "Assessed as hard to undo"
            + (" (risk uncertain, assumed one level higher)" if risk_uncertain else "")
            + "; you decide.",
            "hard_to_undo",
        )
    return Verdict("allow", f"risk {effective}")


_AGREE_BY = re.compile(r"by (clicking|selecting|tapping|pressing) [“\"'‘]?([A-Za-z][\w &-]{0,30}?)[”\"'’]?[,.]?\s+"
                       r"you (agree|accept|consent)", re.I)


def _named_in_agreement(label: str, g: Gate) -> bool:
    """A control named in the agreement wording ("By clicking Create, you agree…") carries the agreement, even
    when the page has no <form> to tie it to the terms (Discord's create dialog, D-069)."""
    m = label.lower()
    for text in g.evidence:
        found = _AGREE_BY.search(text)
        if found:
            name = found.group(2).strip().lower()
            if name and (f"'{name}'" in m or f"[{name}]" in m or m.endswith(name) or f"“{name}”" in m):
                return True
    return False


def _is_button(action: ProposedAction, obs: Observation) -> bool:
    return any(b["xpath"] == action.xpath for b in obs.buttons)


def _is_submit(action: ProposedAction, obs: Observation, form_xpath: str | None) -> bool:
    for b in obs.buttons:
        if b["xpath"] != action.xpath:
            continue
        is_submit = b["type"] in ("submit", "") and b["form"] is not None
        return is_submit and (form_xpath is None or b["form"] == form_xpath)
    return False
