"""Fault injection for fake-provider scenarios (the `jev` and `fastrouter` fields in scenarios.json).

Test harness only. Wraps whatever answers model calls (the real FastRouterClient, or the offline
RuleLLM) and makes the configured services fail, so the PRD §8 rules can be exercised end to end:

  jev: always_fail  + fastrouter: llm_up → every Jev call errors; the LLM still answers (fallbacks)
  jev: always_fail  + fastrouter: down   → Jev and the LLM are both unreachable (service unavailable)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from credagent.reasoning.fastrouter import ModelCallError, ServiceUnavailable


@dataclass(frozen=True)
class Faults:
    jev_fails: bool = False
    llm_down: bool = False

    @property
    def any(self) -> bool:
        return self.jev_fails or self.llm_down


def faults_for(spec: dict[str, Any]) -> Faults:
    down = spec.get("fastrouter") == "down"
    return Faults(jev_fails=spec.get("jev") == "always_fail" or down, llm_down=down)


class FaultyFastRouter:
    def __init__(self, inner: Any, faults: Faults) -> None:
        self.inner = inner
        self.faults = faults
        self.jev_calls = 0
        self.llm_calls = 0

    def systemone(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.jev_calls += 1
        if self.faults.llm_down:
            raise ServiceUnavailable("simulated: FastRouter unreachable (scenario fault)")
        if self.faults.jev_fails:
            raise ModelCallError("simulated: Jev call failed (scenario fault)")
        return self.inner.systemone(*args, **kwargs)

    def chat(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.llm_calls += 1
        if self.faults.llm_down:
            raise ServiceUnavailable("simulated: FastRouter unreachable (scenario fault)")
        return self.inner.chat(*args, **kwargs)
