"""One structured LLM call per step (D-078): build the masked prompt, call the model with the step schema, parse.

Retry rules (PRD §8, adapted): invalid output or a failed call is retried once; if FastRouter is unreachable twice,
`LLMUnavailable` is raised so the run can checkpoint and end `failed: service unavailable`, resumable. A prompt that
would leak a secret is never sent (`PromptLeak` propagates).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from credagent.agent.prompt import PromptContext, build_messages
from credagent.agent.step import STEP_SCHEMA, AgentStep
from credagent.reasoning.fastrouter import ModelCallError, OutputTruncated, ServiceUnavailable
from credagent.secrets.masking import Masker


class LLMUnavailable(Exception):
    """FastRouter could not be reached, twice in a row."""


@dataclass
class StepResult:
    step: AgentStep | None
    error: str | None = None  # why there is no usable step (the model's output stayed invalid)
    latency_ms: int = 0
    usage: dict[str, Any] | None = None
    model: str | None = None
    attempts: int = 1


class StepLLM:
    def __init__(self, reasoner: Any, masker: Masker, *, model: str | None = None, max_tokens: int = 700,
                 timeout_s: float = 60.0) -> None:
        self.reasoner = reasoner
        self.masker = masker
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s

    def decide(self, ctx: PromptContext) -> StepResult:
        messages = build_messages(ctx, self.masker)  # may raise PromptLeak: nothing is sent
        max_tokens = self.max_tokens
        latency, last_error = 0, ""
        for attempt in (1, 2):
            try:
                r = self.reasoner.chat(
                    messages, model=self.model, json_schema=copy.deepcopy(STEP_SCHEMA), schema_name="agent_step",
                    max_tokens=max_tokens, timeout_s=self.timeout_s)
            except ServiceUnavailable as exc:
                last_error = f"service unavailable: {str(exc)[:120]}"
                if attempt == 2:
                    raise LLMUnavailable(last_error) from None
                continue
            except OutputTruncated as exc:
                last_error, max_tokens = f"output cut off: {str(exc)[:120]}", min(max_tokens * 2, 4000)
                continue
            except ModelCallError as exc:
                last_error = str(exc)[:200]
                continue
            latency += int(r.get("latency_ms") or 0)
            try:
                step = AgentStep.model_validate(r["parsed"])
            except (ValidationError, KeyError, TypeError) as exc:
                last_error = f"invalid step: {_short(exc)}"
                messages = [*messages, {"role": "user", "content": (
                    f"Your last reply was not valid ({_short(exc)}). Reply again with ONE valid action as JSON.")}]
                continue
            return StepResult(step, None, latency, r.get("usage"), r.get("model"), attempt)
        return StepResult(None, last_error or "no usable answer", latency, None, None, 2)


def _short(exc: BaseException) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", ()))
        return f"{loc}: {first.get('msg', 'invalid')}"[:160]
    return type(exc).__name__
