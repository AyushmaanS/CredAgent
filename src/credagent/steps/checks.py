"""The closed check vocabulary for plan steps (design §5). Evaluated by plain code; no model involved.

A check is data (the LLM may only name these checks and fill their parameters); code decides what it means:

  at_page          path glob (placeholders {app_id}, {base}); optional host. Docs pages never match.
  element_present  role (button | link | field | heading | dialog | checkbox) + name, match exact | contains
  element_absent   the same, negated
  field_holds      field (label / aria label / section) holds an approved value: an in-page equality test
                   that returns only true/false. Only for code-approved, non-secret values.
  field_empty      the field has no value
  checked          the checkbox is ticked (never a terms control)
  app_exists       this run created an app, and the page shows its name or its ID in the URL
  credential_shown the run holds the named credential parts (captured by plain code)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, model_validator

CheckName = Literal["at_page", "element_present", "element_absent", "field_holds", "field_empty", "checked",
                    "app_exists", "credential_shown"]
Role = Literal["button", "link", "field", "heading", "dialog", "checkbox"]
APPROVED_VALUES = ("app_name", "homepage_url", "redirect_uri", "description")
PLACEHOLDERS = ("{app_id}", "{base}")
NEVER_COMPARE = re.compile(r"password|passcode|secret|token|api[\s_-]*key|code|otp|card|cvc|cvv|iban|ssn", re.I)


_norm = lambda t: re.sub(r"\s+", " ", (t or "")).strip().lower()  # noqa: E731


class FieldRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = None
    section: str | None = None

    @model_validator(mode="after")
    def _one(self) -> FieldRef:
        if not (self.label or self.section):
            raise ValueError("a field needs a label or a section")
        return self


class Target(BaseModel):
    """The control a step starts with (ranked first when it is on the page)."""

    model_config = ConfigDict(extra="forbid")
    role: Role
    name: str

    def matches(self, description: str) -> bool:
        d = _norm(description)
        kind = {"button": "button", "link": "link", "field": "text field", "checkbox": "checkbox"}.get(self.role, "")
        return (not kind or d.startswith(kind)) and _norm(self.name) in d


class Check(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: CheckName
    path: str | None = None
    host: str | None = None
    role: Role | None = None
    name: str | None = None
    match: Literal["exact", "contains"] = "contains"
    field: FieldRef | None = None
    value: str | None = None
    parts: list[str] | None = None

    @model_validator(mode="after")
    def _params(self) -> Check:
        c = self.check
        if c == "at_page":
            if not self.path or not self.path.startswith("/"):
                raise ValueError("at_page needs a path starting with /")
            for ph in re.findall(r"\{[^}]*\}", self.path):
                if ph not in PLACEHOLDERS:
                    raise ValueError(f"unknown placeholder {ph}")
        elif c in ("element_present", "element_absent"):
            if not (self.role and self.name):
                raise ValueError(f"{c} needs role and name")
        elif c in ("field_holds", "field_empty", "checked"):
            if self.field is None:
                raise ValueError(f"{c} needs a field")
            if c == "field_holds":
                if self.value not in APPROVED_VALUES:
                    raise ValueError("field_holds compares only with an approved value key")
                if NEVER_COMPARE.search(f"{self.field.label or ''} {self.field.section or ''}"):
                    raise ValueError("field_holds is never used on secret, password or code fields")
        elif c == "credential_shown" and not self.parts:
            raise ValueError("credential_shown needs parts")
        return self

    def describe(self) -> str:
        c = self.check
        if c == "at_page":
            return f"on page {self.path}"
        if c in ("element_present", "element_absent"):
            return f"{self.role} “{self.name}” {'shown' if c == 'element_present' else 'not shown'}"
        if c == "field_holds":
            return f"“{self.field.label or self.field.section}” holds the {self.value.replace('_', ' ')}"
        if c == "field_empty":
            return f"“{self.field.label or self.field.section}” is empty"
        if c == "checked":
            return f"“{self.field.label or self.field.section}” is ticked"
        if c == "app_exists":
            return "this run's app exists"
        return "credential shown: " + ", ".join(self.parts or [])


@dataclass
class Context:
    """What checks may use besides the page: bound placeholders, approved values, run facts."""

    values: Any  # FieldValues
    allowed_domains: list[str]
    created: bool = False
    app_name: str = ""
    credential_parts: set[str] = field(default_factory=set)
    bindings: dict[str, str] = field(default_factory=dict)  # "app_id" -> value, "base" -> origin


@dataclass
class Result:
    check: Check
    ok: bool | None  # None: cannot be judged on this page

    def line(self) -> str:
        mark = "✓" if self.ok else ("?" if self.ok is None else "✗")
        return f"[{mark}] {self.check.describe()}"


def is_docs_host(url: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return host.startswith("docs.") or host.startswith("developer-docs.") or p.path.startswith("/docs")


def path_regex(path: str, bindings: dict[str, str]) -> re.Pattern[str]:
    """Glob → regex. {app_id} matches the bound ID (or captures one); * one segment; ** anything."""
    out = ""
    i = 0
    while i < len(path):
        if path.startswith("{app_id}", i):
            out += re.escape(bindings["app_id"]) if "app_id" in bindings else r"(?P<app_id>[A-Za-z0-9_-]+)"
            i += len("{app_id}")
        elif path.startswith("{base}", i):
            i += len("{base}")
        elif path.startswith("**", i):
            out += ".*"
            i += 2
        elif path[i] == "*":
            out += "[^/]*"
            i += 1
        else:
            out += re.escape(path[i])
            i += 1
    return re.compile(f"^{out}/?$")


def match_at_page(check: Check, url: str, ctx: Context) -> tuple[bool, dict[str, str]]:
    from credagent.policy.hard_checks import host_allowed

    if not host_allowed(url, ctx.allowed_domains) or is_docs_host(url):
        return False, {}
    p = urlparse(url)
    if check.host and (p.hostname or "").lower() != check.host.lower():
        return False, {}
    m = path_regex(check.path or "/", ctx.bindings).match(p.path)
    if not m:
        return False, {}
    return True, {k: v for k, v in m.groupdict().items() if v}


def _elements(obs: Any, role: str) -> list[str]:
    if role == "button":
        return [b.get("text") or "" for b in obs.buttons]
    if role == "link":
        return [a.get("text") or "" for a in obs.links]
    if role == "heading":
        return list(getattr(obs, "headings", []) or [])
    if role == "dialog":
        return [b.get("text") or "" for b in obs.banners]
    if role == "checkbox":
        return [i.get("label") or "" for i in obs.inputs if i.get("type") == "checkbox"]
    return [f"{i.get('label') or ''} {i.get('section') or ''}" for i in obs.inputs
            if i.get("type") not in ("checkbox", "radio", "hidden", "submit", "button")]


def element_shown(check: Check, obs: Any) -> bool:
    want = _norm(check.name)
    for text in _elements(obs, check.role or "button"):
        t = _norm(text)
        if (t == want) if check.match == "exact" else (want in t):
            return True
    return False


def fields_for(ref: FieldRef, obs: Any) -> list[dict]:
    out = []
    for i in obs.inputs:
        if i.get("type") in ("hidden", "submit", "button", "image", "reset") or i.get("type") == "password":
            continue
        label = _norm(i.get("label")) + " " + _norm(i.get("name"))
        section = _norm(i.get("section"))
        if (ref.label and _norm(ref.label) in label) or (ref.section and _norm(ref.section) == section):
            out.append(i)
    return out


FIELD_EQUALS_JS = r"""
(() => {
  const xs = __XPATHS__, want = __WANT__;
  return xs.some(x => {
    const el = document.evaluate(x, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    return !!el && typeof el.value === 'string' && el.value.trim() === want;
  });
})()
"""


async def field_equals(page: Any, xpaths: list[str], want: str) -> bool:
    """In-page equality test against a code-approved, non-secret value. Returns only true/false; no field value
    leaves the page."""
    if not xpaths:
        return False
    js = FIELD_EQUALS_JS.replace("__XPATHS__", json.dumps(xpaths[:20])).replace("__WANT__", json.dumps(want))
    return bool(await page.evaluate(js))


async def evaluate(check: Check, page: Any, obs: Any, ctx: Context, *, new_bindings: dict | None = None) -> bool:
    c = check.check
    if c == "at_page":
        ok, bound = match_at_page(check, obs.url, ctx)
        if ok and new_bindings is not None:
            new_bindings.update(bound)
        return ok
    if c == "element_present":
        return element_shown(check, obs)
    if c == "element_absent":
        return not element_shown(check, obs)
    if c in ("field_holds", "field_empty", "checked"):
        boxes = fields_for(check.field, obs)  # type: ignore[arg-type]
        if c == "field_empty":
            return bool(boxes) and all(not b.get("value_len") for b in boxes)
        if c == "checked":
            return any(b.get("checked") for b in boxes)
        want = ctx.values.get(check.value)
        filled = [b["xpath"] for b in boxes if b.get("value_len") == len(want or "")]
        return bool(want) and bool(filled) and await field_equals(page, filled, want)
    if c == "app_exists":
        if not ctx.created:
            return False
        url_has_id = "app_id" in ctx.bindings and ctx.bindings["app_id"] in obs.url
        if url_has_id:
            return True
        if not ctx.app_name:
            return False
        name = ctx.app_name.lower()
        texts = [obs.text or "", *(a.get("text") or "" for a in obs.links), *(b.get("text") or "" for b in obs.buttons),
                 *(getattr(obs, "headings", []) or [])]
        return any(name in t.lower() for t in texts)
    if c == "credential_shown":
        return set(check.parts or []) <= ctx.credential_parts
    return False


async def evaluate_all(checks: list[Check], page: Any, obs: Any, ctx: Context) -> tuple[list[Result], dict]:
    """Evaluate a list of checks; returns results and any placeholder bindings learned from at_page."""
    bound: dict[str, str] = {}
    out = []
    for ch in checks:
        out.append(Result(ch, await evaluate(ch, page, obs, ctx, new_bindings=bound)))
    return out, bound
