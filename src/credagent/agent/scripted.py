"""A deterministic stand-in for the LLM (tests and `--offline` fake-provider runs only, D-078).

It is NOT a model: it follows the fake console's flow with plain rules, through the same contract as the real
model (`PromptContext` in, `StepResult` out), so every action still goes through validation, policy and the executor.
Real providers never use it.
"""

from __future__ import annotations

import re

from credagent.agent.llm import StepResult
from credagent.agent.prompt import PromptContext
from credagent.agent.step import AgentStep
from credagent.browser.candidates import field_key_for
from credagent.policy.engine import HUMAN_ONLY_FIELDS

CREATE_BUTTON = re.compile(r"^(create|create app|create application|register)$", re.I)
NEW_APP = re.compile(r"new app|new application|create an app", re.I)
CONSOLE_LINK = re.compile(r"developer console|^console$", re.I)


def _step(action: str, reason: str, **kw: object) -> AgentStep:
    return AgentStep(action=action, reason=reason, expected="", **kw)  # type: ignore[arg-type]


class ScriptedLLM:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, ctx: PromptContext) -> StepResult:
        self.calls += 1
        return StepResult(self._choose(ctx), None, 0, None, "scripted-llm", 1)

    def _choose(self, ctx: PromptContext) -> AgentStep:
        snap = ctx.snapshot
        usable = [e for e in snap.elements if not e.disabled and e.xpath not in snap.refused]
        if any("A credential-like value is displayed" in n for n in ctx.notes):
            return _step("done", "the page shows the new credential")
        for e in usable:  # fill every empty field that has an approved value
            if e.role == "field" and not e.filled and not e.readonly and e.type != "password":
                key = field_key_for(e.name or e.section)
                if key in ctx.approved and not HUMAN_ONLY_FIELDS.search(e.name or ""):
                    return _step("type", f"fill {e.name or e.section} with the approved value", ref=e.ref,
                                 value_key=key)  # type: ignore[arg-type]
        if not ctx.created:
            create = next((e for e in usable if e.role == "button" and CREATE_BUTTON.match(e.name.strip())), None)
            if create is not None:
                return _step("click", "the form is filled: create the app", ref=create.ref)
            new = next((e for e in usable if e.role in ("link", "button") and NEW_APP.search(e.name)), None)
            if new is not None:
                return _step("click", "open the form to create the app", ref=new.ref)
            if "/console" not in snap.url:
                console = next((e for e in usable if e.role == "link" and CONSOLE_LINK.search(e.name)), None)
                if console is not None:
                    return _step("click", "open the developer console", ref=console.ref)
        return _step("ask_person", "I cannot tell what to do on this page", person_kind="DO",
                     person_why="The scripted stand-in does not know this page. Please bring it to a page it can "
                                "continue from.")
