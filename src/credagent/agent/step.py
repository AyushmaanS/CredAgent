"""The step contract (D-078 §2): what the LLM may return, and what code checks before anything runs.

The model returns ONE action per turn as strict JSON. Code then, in this order:
  1. parses it (pydantic, extra fields refused);
  2. validates it against the live snapshot (`validate_step`): the ref exists and suits the action, typed text is
     an approved value *key* (never free text), a dropdown option exists, an address is on an allowed site and is
     not documentation, a handoff request is well formed;
  3. turns it into a policy input (`to_proposed`) for the existing hard stops and policy order.
A step that fails 2 is rejected with a message written for the model, and counts against the step budget.
Nothing here executes anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin, urlparse

from pydantic import BaseModel, ConfigDict

from credagent.browser.snapshot import Element, Snapshot
from credagent.policy.engine import ProposedAction
from credagent.policy.hard_checks import host_allowed
from credagent.steps.checks import APPROVED_VALUES, is_docs_host

ACTIONS = ["click", "type", "select", "navigate", "scroll", "inspect", "back", "wait", "ask_person", "done",
           "give_up"]
DIRECTIONS = ["down", "up", "top", "bottom"]
PERSON_KINDS = ["DO", "DECIDE"]
READ_ONLY_ACTIONS = ("scroll", "inspect", "back", "wait")


def _nullable(t: str, **extra: Any) -> dict[str, Any]:
    return {"type": [t, "null"], **extra}


def _nenum(values: list[str]) -> dict[str, Any]:
    return {"type": ["string", "null"], "enum": [*values, None]}


# Flat on purpose (no nested objects): every property required, nullable where it does not apply.
STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "ref", "value_key", "option", "url", "direction", "wait_ms", "person_kind", "person_why",
                 "person_options", "reason", "expected"],
    "properties": {
        "action": {"type": "string", "enum": ACTIONS},
        "ref": _nullable("string"),
        "value_key": _nenum(list(APPROVED_VALUES)),
        "option": _nullable("string"),
        "url": _nullable("string"),
        "direction": _nenum(DIRECTIONS),
        "wait_ms": _nullable("integer"),
        "person_kind": _nenum(PERSON_KINDS),
        "person_why": _nullable("string"),
        "person_options": {"type": ["array", "null"], "items": {"type": "string"}},
        "reason": {"type": "string"},
        "expected": {"type": "string"},
    },
}


class AgentStep(BaseModel):
    """The model's answer, parsed. Only shape is checked here; `validate_step` checks it against the page."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["click", "type", "select", "navigate", "scroll", "inspect", "back", "wait", "ask_person",
                    "done", "give_up"]
    ref: str | None = None
    value_key: Literal["app_name", "homepage_url", "redirect_uri", "description"] | None = None
    option: str | None = None
    url: str | None = None
    direction: Literal["down", "up", "top", "bottom"] | None = None
    wait_ms: int | None = None
    person_kind: Literal["DO", "DECIDE"] | None = None
    person_why: str | None = None
    person_options: list[str] | None = None
    reason: str
    expected: str = ""


class StepRejected(Exception):
    """The step is not acceptable here. `message` is written for the model: it appears in its next turn."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Validated:
    step: AgentStep
    action: str
    element: Element | None = None
    value: str | None = None  # the approved value for `type`, resolved from its key
    option: str | None = None  # the dropdown option's exact label
    url: str | None = None  # absolute address for `navigate`
    direction: str = "down"
    ms: int = 1500

    def target(self) -> str:
        """A short label for logs and history: never a value."""
        e = self.element
        if e is not None:
            return f'{e.role} "{e.name[:50]}"' if e.name else e.role
        if self.action == "navigate" and self.url:
            p = urlparse(self.url)
            return (p.path or "/")[:80]
        return ""


def approved_map(values: Any) -> dict[str, str]:
    return {k: v for k in APPROVED_VALUES if (v := getattr(values, k, None))}


def _ref_element(step: AgentStep, snap: Snapshot) -> Element:
    if not step.ref:
        raise StepRejected("missing_ref", f"{step.action} needs a ref (e1, e2, …) from the current snapshot.")
    el = snap.element(step.ref)
    if el is None:
        raise StepRejected("unknown_ref", f"{step.ref!r} is not in the current snapshot. Refs are valid only for "
                           "the snapshot they appear in; look at the elements listed now.")
    return el


def validate_step(step: AgentStep, snap: Snapshot, *, values: Any, allowed_domains: list[str]) -> Validated:
    reason = (step.reason or "").strip()
    if len(reason) < 3:
        raise StepRejected("empty_reason", "Give a short reason for the action.")
    act = step.action

    if act == "click":
        el = _ref_element(step, snap)
        if el.disabled:
            raise StepRejected("disabled", f'{el.role} "{el.name[:40]}" is disabled; do what it needs first.')
        if el.is_field and el.role != "checkbox":
            raise StepRejected("wrong_element", f'"{el.name[:40]}" is a {el.role}: use type or select, not click.')
        return Validated(step, act, el)

    if act == "type":
        el = _ref_element(step, snap)
        if el.role != "field":
            raise StepRejected("wrong_element", f'{el.role} "{el.name[:40]}" is not a text field.')
        if el.type == "password" or el.readonly or el.disabled:
            raise StepRejected("wrong_element", f'"{el.name[:40]}" cannot be typed into by the agent (password, '
                               "read-only or disabled): ask_person if it is needed.")
        if not step.value_key:
            raise StepRejected("bad_value_key", "type needs value_key: one of " + ", ".join(APPROVED_VALUES)
                               + ". You cannot write other text into fields.")
        value = getattr(values, step.value_key, None)
        if not value:
            raise StepRejected("bad_value_key", f"There is no approved value for {step.value_key!r}.")
        return Validated(step, act, el, value=value)

    if act == "select":
        el = _ref_element(step, snap)
        if el.role != "select":
            raise StepRejected("wrong_element", f'{el.role} "{el.name[:40]}" is not a dropdown.')
        want = (step.option or "").strip().lower()
        match = next((o for o in el.options if o.strip().lower() == want), None)
        if not match:
            raise StepRejected("bad_option", f'"{(step.option or "")[:40]}" is not one of: '
                               + " | ".join(el.options[:10]) + ". If the choice is the person's, use ask_person "
                               "with kind DECIDE.")
        return Validated(step, act, el, option=match)

    if act == "inspect":
        el = _ref_element(step, snap)
        if el.type == "password":
            raise StepRejected("wrong_element", "password fields are never read.")
        return Validated(step, act, el)

    if act == "navigate":
        if not step.url:
            raise StepRejected("missing_url", "navigate needs a url.")
        url = urljoin(snap.url, step.url.strip())
        if urlparse(url).scheme not in ("http", "https"):
            raise StepRejected("bad_url", "Only http and https addresses can be opened.")
        if not host_allowed(url, allowed_domains):
            raise StepRejected("off_domain", "That address is outside the allowed sites: "
                               + ", ".join(allowed_domains) + ".")
        if is_docs_host(url):
            raise StepRejected("docs_page", "Documentation pages are not part of the console steps; stay in the "
                               "console.")
        return Validated(step, act, url=url)

    if act == "scroll":
        return Validated(step, act, direction=step.direction or "down")

    if act == "wait":
        return Validated(step, act, ms=max(200, min(step.wait_ms or 1500, 5000)))

    if act == "ask_person":
        if not step.person_kind or not (step.person_why or "").strip():
            raise StepRejected("bad_person", "ask_person needs person_kind (DO or DECIDE) and person_why.")
        opts = [o.strip() for o in (step.person_options or []) if o and o.strip()]
        if step.person_kind == "DECIDE" and not 2 <= len(opts) <= 5:
            raise StepRejected("bad_person", "A DECIDE needs 2 to 5 short options for the person to choose from.")
        return Validated(step, act)

    if act == "give_up" and len(reason) < 10:
        raise StepRejected("empty_reason", "give_up needs a clear reason: what is blocking and why.")

    return Validated(step, act)  # back, done, give_up: nothing to check against the page (code judges "done")


_ROLE_WORDS = {"link": "link", "button": "button", "tab": "button", "menuitem": "button", "field": "text field",
               "select": "dropdown", "checkbox": "checkbox", "radio": "checkbox", "switch": "checkbox"}


def policy_description(el: Element) -> str:
    """The label policy rules read: `button 'Create'`, `link 'OAuth2'`, `text field 'Name'` (unchanged format)."""
    return f"{_ROLE_WORDS.get(el.role, el.role)} '{el.name}'"


def to_proposed(v: Validated) -> ProposedAction | None:
    """The policy input for an action that changes the page; None for read-only actions and handoffs."""
    el = v.element
    if v.action == "click" and el is not None:
        method = "check" if el.role in ("checkbox", "radio", "switch") else "click"
        return ProposedAction(method=method, xpath=el.xpath, description=policy_description(el),
                              href=el.href or None)
    if v.action == "type" and el is not None:
        return ProposedAction(method="fill", xpath=el.xpath, description=policy_description(el),
                              field_key=v.step.value_key, value=v.value)
    if v.action == "select" and el is not None:
        return ProposedAction(method="select", xpath=el.xpath, description=policy_description(el))
    if v.action == "navigate" and v.url:
        return ProposedAction(method="navigate", xpath=None, description=f"navigate to {urlparse(v.url).path or '/'}",
                              href=v.url)
    return None
