"""Candidate elements for Jev's element-selection decision (spec §6.4/§6.5).

Sources:
* Stagehand observe() on ordinary pages, with any credential-like elements excluded
  via ignore_locators (Sprint 0 D-013).
* Plain-code DOM enumeration on credential-bearing pages (no model sees the page) and
  as a fallback when observe() returns nothing.
Both are normalised to c0..cN (deduplicated by element, capped) with a code-built
description. Typed values are never taken from a model: they come from FieldValues.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from credagent.browser.observe import Observation
from credagent.decisions.jev import Candidate
from credagent.policy.hard_checks import CREDENTIAL_TEXT

MAX_CANDIDATES = 20


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


@dataclass(frozen=True)
class RawCandidate:
    xpath: str
    method: str  # click | fill | select | check
    description: str
    href: str | None = None
    source: str = "dom"  # dom | stagehand
    field_key: str | None = None
    filled: bool = False


def use_stagehand(obs: Observation) -> bool:
    """Never let Stagehand's model read a page that shows or talks about credentials."""
    return not obs.secret_bearing and not CREDENTIAL_TEXT.search(obs.text)


def dom_candidates(obs: Observation) -> list[RawCandidate]:
    secret = set(obs.secret_xpaths)
    out: list[RawCandidate] = []
    for i in obs.inputs:
        if i["xpath"] in secret or i["readonly"]:
            continue
        label = i["label"] or i["name"] or i["id"] or i["type"]
        if i["type"] in ("checkbox", "radio"):
            out.append(
                RawCandidate(i["xpath"], "check", f"{i['type']} '{label}'" + (" (checked)" if i["checked"] else ""))
            )
        elif i["tag"] == "select":
            out.append(
                RawCandidate(
                    i["xpath"],
                    "select",
                    f"dropdown '{label}'" + (" (chosen)" if i["value_len"] else ""),
                    filled=bool(i["value_len"]),
                )
            )
        elif i["type"] in ("submit", "button"):
            continue
        else:
            filled = i["value_len"] > 0
            out.append(
                RawCandidate(
                    i["xpath"],
                    "fill",
                    f"text field '{label}'" + (" (already filled)" if filled else ""),
                    field_key=field_key_for(label),
                    filled=filled,
                )
            )
    for b in obs.buttons:
        if b["xpath"] in secret or b["disabled"]:
            continue
        out.append(RawCandidate(b["xpath"], "click", f"button '{b['text'] or b['name'] or 'unnamed'}'"))
    for a in obs.links:
        if a["xpath"] in secret or not a["text"]:
            continue
        out.append(RawCandidate(a["xpath"], "click", f"link '{a['text']}'", href=a["href"]))
    return out


def _xpath_of(selector: str) -> str:
    return selector[len("xpath=") :] if selector.startswith("xpath=") else selector


def from_stagehand(actions: list[Any], obs: Observation) -> list[RawCandidate]:
    """Map Stagehand observe() Actions to candidates; descriptions are rebuilt from page data where possible."""
    by_xpath = (
        {i["xpath"]: i for i in obs.inputs} | {b["xpath"]: b for b in obs.buttons} | {a["xpath"]: a for a in obs.links}
    )
    links = {a["xpath"]: a["href"] for a in obs.links}
    out = []
    for a in actions:
        xp = _xpath_of(a.selector)
        if xp in set(obs.secret_xpaths):
            continue
        method = (a.method or "click").lower()
        method = {"type": "fill", "selectoptionfromdropdown": "select"}.get(method, method)
        if method not in ("click", "fill", "select", "check"):
            continue
        el = by_xpath.get(xp)
        label = (el.get("label") or el.get("text") or "") if el else ""
        desc = a.description if not label else f"{a.description} [{label}]"
        filled = bool(el and el.get("value_len"))
        out.append(
            RawCandidate(
                xp,
                method,
                desc + (" (already filled)" if method == "fill" and filled else ""),
                href=links.get(xp),
                source="stagehand",
                field_key=field_key_for(label or a.description) if method == "fill" else None,
                filled=filled,
            )
        )
    return out


def normalise(
    raw: list[RawCandidate], exclude: set[str] | None = None
) -> tuple[list[Candidate], dict[str, RawCandidate]]:
    seen: set[tuple[str, str]] = set()
    cands: list[Candidate] = []
    mapping: dict[str, RawCandidate] = {}
    for r in raw:
        key = (r.xpath, r.method)
        if key in seen or (exclude and r.xpath in exclude):
            continue
        seen.add(key)
        cid = f"c{len(cands)}"
        cands.append(Candidate(id=cid, description=r.description[:200], method=r.method))
        mapping[cid] = r
        if len(cands) >= MAX_CANDIDATES:
            break
    return cands, mapping
