"""Recorded terms-of-automation checks (ATTEMPT-PROTOCOL §2.3, v2).

One entry per provider, written by a person after reading the provider's terms. The finding decides
whether the console may be automated:
  prohibited     → never automated
  unclear        → automated by default (owner decision, D-059); reports say the wording was unclear
  not_prohibited → automated
A provider with no entry is never automated: its terms have not been checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class TermsCheck:
    provider: str
    finding: Literal["prohibited", "unclear", "not_prohibited"]
    checked_on: str
    sources: list[str] = field(default_factory=list)
    summary: str = ""
    record: str = ""  # where the full finding is written down

    @property
    def may_automate(self) -> bool:
        return self.finding in ("unclear", "not_prohibited")


TERMS_CHECKS: dict[str, TermsCheck] = {
    "spotify": TermsCheck(
        provider="Spotify",
        finding="unclear",
        checked_on="2026-11-16",
        sources=[
            "https://developer.spotify.com/terms",
            "https://developer.spotify.com/policy",
            "https://www.spotify.com/us/legal/end-user-agreement/",
        ],
        summary="No clause addresses automating the Developer Dashboard. The nearest (Developer Terms "
                "IV.2.4.1) bars robots/tools that retrieve, duplicate or index Spotify content. The account "
                "holder is responsible for all activity on the account (VI.1.4).",
        record="docs/DECISIONS.md D-058",
    ),
}


def lookup(*names: str | None) -> TermsCheck | None:
    """Find the check for a provider by any of its names (canonical app name, provider, run input)."""
    for n in names:
        key = (n or "").strip().lower()
        if not key:
            continue
        for k, v in TERMS_CHECKS.items():
            if key == k or key.startswith(k + " ") or k in key.split():
                return v
    return None
