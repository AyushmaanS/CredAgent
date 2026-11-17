"""Fault injection for fake-provider scenarios (the `llm` field in scenarios.json).

Test harness only. Wraps whatever answers the agent's steps (the real StepLLM, or the offline ScriptedLLM) and makes
the model misbehave, so the PRD §8 rules can be exercised end to end:

  llm: flaky → every other answer is unusable; the loop records it and asks again (the run still succeeds)
  llm: down  → FastRouter is unreachable; the run checkpoints and ends `failed: service unavailable`, resumable
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from credagent.agent.llm import LLMUnavailable, StepResult


@dataclass(frozen=True)
class Faults:
    flaky: bool = False
    down: bool = False

    @property
    def any(self) -> bool:
        return self.flaky or self.down


def faults_for(spec: dict[str, Any]) -> Faults:
    return Faults(flaky=spec.get("llm") == "flaky", down=spec.get("llm") == "down")


class FaultyLLM:
    def __init__(self, inner: Any, faults: Faults) -> None:
        self.inner = inner
        self.faults = faults
        self.calls = 0

    def decide(self, ctx: Any) -> StepResult:
        self.calls += 1
        if self.faults.down:
            raise LLMUnavailable("simulated: FastRouter unreachable (scenario fault)")
        if self.faults.flaky and self.calls % 2 == 1:
            return StepResult(None, "simulated: the model's answer was unusable (scenario fault)", 0, None, None, 2)
        return self.inner.decide(ctx)
