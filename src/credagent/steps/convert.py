"""Model output → checkable plan steps. Shared by research and re-planning (design §8).

The model only fills a fixed JSON shape (schema below). Every condition is validated by `Check`; an invalid
one is dropped with a note, never repaired by guessing.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from credagent.state.models import PlanStep
from credagent.steps.checks import APPROVED_VALUES, Check, FieldRef, Target

CHECKS = ["at_page", "element_present", "element_absent", "field_holds", "field_empty", "checked", "app_exists",
          "credential_shown"]
ROLES = ["button", "link", "field", "heading", "dialog", "checkbox"]
_NSTR = {"type": ["string", "null"]}
_NENUM = lambda vals: {"type": ["string", "null"], "enum": [*vals, None]}  # noqa: E731

CHECK_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["check", "path", "role", "name", "field_label", "field_section", "value", "parts"],
    "properties": {
        "check": {"type": "string", "enum": CHECKS},
        "path": _NSTR, "role": _NENUM(ROLES), "name": _NSTR, "field_label": _NSTR, "field_section": _NSTR,
        "value": _NENUM(list(APPROVED_VALUES)), "parts": {"type": ["array", "null"], "items": {"type": "string"}},
    },
}
STEP_CONDITION_PROPS: dict[str, Any] = {
    "where_path": _NSTR,
    "target_role": _NENUM(ROLES),
    "target_name": _NSTR,
    "value": _NENUM(list(APPROVED_VALUES)),
    "done_when": {"type": "array", "items": CHECK_SCHEMA},
}

GUIDANCE = (
    "For every console step (navigate, click, fill, check) also say how code can check it on the live page, using "
    "ONLY these checks: at_page (path, e.g. /developers/applications/{app_id}/oauth2; {app_id} is the new app's id in "
    "the URL), element_present / element_absent (role: button|link|field|heading|dialog|checkbox, name: the visible "
    "text), field_holds (field_label or field_section, value: one of app_name|homepage_url|redirect_uri|description), "
    "field_empty, checked, app_exists (the app this run created exists), credential_shown (parts, e.g. client_id, "
    "client_secret). where_path: the page the step happens on (null if any page). target_role/target_name: the "
    "control the step starts with (null if none). value: for fill steps, which approved value is typed. done_when: "
    "checks that are ALL true once the step is done, e.g. a saved redirect: field_holds(field_section='Redirects', "
    "value='redirect_uri') and element_absent(role=button, name='Save Changes'). Use names exactly as the sources "
    "show them; if unsure, prefer at_page and element checks. Never put checks on sign-in, passwords, codes, "
    "secrets or terms. Handoff steps may leave done_when empty."
)


def check_from(raw: dict[str, Any]) -> Check:
    field = None
    if raw.get("field_label") or raw.get("field_section"):
        field = FieldRef(label=raw.get("field_label"), section=raw.get("field_section"))
    return Check(check=raw["check"], path=raw.get("path"), role=raw.get("role"), name=raw.get("name"),
                 field=field, value=raw.get("value"), parts=raw.get("parts"))


def to_plan_step(step_id: str, description: str, kind: str, raw: dict[str, Any], notes: list[str],
                 expected_page: str | None = None) -> PlanStep:
    where, done = [], []
    if raw.get("where_path"):
        try:
            where.append(Check(check="at_page", path=raw["where_path"]))
        except ValidationError:
            notes.append(f"Step {step_id}: its page '{str(raw['where_path'])[:60]}' was not a valid path; dropped.")
    for c in raw.get("done_when") or []:
        try:
            done.append(check_from(c))
        except (ValidationError, KeyError) as exc:
            notes.append(f"Step {step_id}: a condition was invalid and dropped ({type(exc).__name__}).")
    target = None
    if raw.get("target_role") and raw.get("target_name"):
        try:
            target = Target(role=raw["target_role"], name=raw["target_name"])
        except ValidationError:
            notes.append(f"Step {step_id}: its target was invalid and dropped.")
    value = raw.get("value") if raw.get("value") in APPROVED_VALUES else None
    return PlanStep(id=step_id, description=description, kind=kind, expected_page=expected_page,  # type: ignore[arg-type]
                    where=where, target=target, value=value, done_when=done)
