"""The values the agent may type, and how a field label maps to one of them (D-078).

Every typed value is owned by code (`FieldValues`), shown in the plan and the consent screen, and never written by a
model: the model names a key, code supplies the value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

APPROVED_VALUES = ("app_name", "homepage_url", "redirect_uri", "description")


@dataclass(frozen=True)
class FieldValues:
    """Every value the agent may type. Owned by code, shown in the plan, never model-written."""

    app_name: str
    homepage_url: str
    redirect_uri: str
    description: str = "Created by CredAgent for integration testing."

    @classmethod
    def default(cls, redirect_uri: str) -> FieldValues:
        origin = re.match(r"^(https?://[^/]+)", redirect_uri)
        return cls(
            app_name=f"credagent-demo-{datetime.now(UTC):%Y%m%d}",
            homepage_url=origin.group(1) if origin else redirect_uri,
            redirect_uri=redirect_uri,
        )

    def get(self, key: str | None) -> str | None:
        return getattr(self, key, None) if key else None


FIELD_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("redirect_uri", re.compile(r"callback|redirect", re.I)),
    ("homepage_url", re.compile(r"homepage|home page|website|site url|app url|\burl\b", re.I)),
    ("app_name", re.compile(r"(app(lication)?|integration|connection|client|project)?\s*name|title", re.I)),
    ("description", re.compile(r"description|about|summary", re.I)),
]


def field_key_for(label: str) -> str | None:
    for key, rx in FIELD_RULES:
        if rx.search(label):
            return key
    return None
