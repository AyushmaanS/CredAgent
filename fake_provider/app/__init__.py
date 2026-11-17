"""Fakeprov server and scenario loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fake_provider.app.server import FakeProvider, Scenario

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios.json"


def load_scenarios() -> dict[str, dict[str, Any]]:
    """Name → {"description", "config", "llm", "expect"}."""
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["scenarios"]


def scenario(name: str) -> Scenario:
    return Scenario.from_dict({"name": name, **load_scenarios()[name]["config"]})


__all__ = ["FakeProvider", "Scenario", "load_scenarios", "scenario"]
