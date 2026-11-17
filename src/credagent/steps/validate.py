"""Validate checkable steps (design §8). Code decides; the model's conditions are only data."""

from __future__ import annotations

from credagent.state.models import PlanStep
from credagent.steps.checks import Check

AGENT_KINDS = ("navigate", "click", "fill", "check")


def is_create_step(step: PlanStep) -> bool:
    from credagent.policy.engine import CREATE_RE

    return step.kind in ("click", "handoff", "navigate", "fill") and bool(CREATE_RE.search(step.description)) and \
        not step.description.lstrip().lower().startswith("if ")


def validate_steps(steps: list[PlanStep], allowed_domains: list[str], notes: list[str]) -> list[PlanStep]:
    """Normalise model-written steps. Returns new steps; appends human-readable notes for the report."""
    out: list[PlanStep] = []
    creates = [i for i, x in enumerate(steps) if is_create_step(x)]
    create_at = creates[-1] if creates else None  # the step that actually creates (e.g. "Submit … Create app")
    for idx, s in enumerate(steps):
        upd: dict = {}
        if s.kind in ("capture", "verify"):  # code-owned: no model-written conditions
            if s.where or s.done_when or s.target:
                notes.append(f"Step {s.id}: conditions on a code-owned {s.kind} step were removed.")
            out.append(s.model_copy(update={"where": [], "done_when": [], "target": None, "inferred": False}))
            continue
        where = [c for c in s.where if c.check == "at_page"]
        if len(where) != len(s.where):
            notes.append(f"Step {s.id}: only page checks are kept in 'where'.")
        bad_host = [c for c in where if c.host and not any(
            c.host.lower() == d or c.host.lower().endswith("." + d) for d in allowed_domains)]
        if bad_host:
            notes.append(f"Step {s.id}: a page outside the allowed domains was removed from 'where'.")
            where = [c for c in where if c not in bad_host]
        upd["where"] = where
        done = list(s.done_when)
        if idx == create_at:
            if not any(c.check == "app_exists" for c in done):
                done.append(Check(check="app_exists"))  # D-063: the create step is proven by the app existing
        if s.kind == "fill" and s.value and not any(c.check == "field_holds" for c in done):
            notes.append(f"Step {s.id}: a fill step without a field check is judged by Jev (inferred).")
        upd["done_when"] = done
        upd["inferred"] = s.kind in AGENT_KINDS and not done
        if upd["inferred"] and not s.inferred:
            notes.append(f"Step {s.id} (“{s.description[:60]}”) has no checkable condition: Jev's judgement decides "
                         "it, and the report marks it inferred.")
        out.append(s.model_copy(update=upd))
    return out


def has_checks(steps: list[PlanStep]) -> bool:
    """Proof mode needs at least one checkable browser step; otherwise the run uses legacy behaviour."""
    return any(s.done_when for s in steps if s.kind not in ("capture", "verify"))
