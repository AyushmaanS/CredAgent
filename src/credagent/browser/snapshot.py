"""The agent's view of a page (D-078): URL, headings, numbered interactive elements, trimmed text.

Built from the plain-code observation (`observe.py`), so every secret rule applies unchanged:
  * credential-like elements are not listed, and their text is replaced by [SECRET-ELEMENT];
  * field values are never reported, only whether a field is filled;
  * every string is masked before it can reach a model or a log.

Elements get refs `e1…eN` in document order. A ref is valid only for the snapshot that issued it; the
executor refuses a ref that no longer matches the page ("stale").
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from credagent.browser.observe import OBSERVE_JS, Observation, from_raw
from credagent.secrets.masking import Masker

MAX_ELEMENTS = 200  # more than this is a page the agent should narrow by scrolling or sections
TEXT_CHARS = 3000
RENDER_CHARS = 16_000


@dataclass(frozen=True)
class Element:
    ref: str
    xpath: str
    role: str  # link | button | field | checkbox | radio | select | tab | menuitem | switch
    name: str
    tag: str = ""
    type: str = ""
    href: str = ""
    disabled: bool = False
    checked: bool = False
    filled: bool = False
    readonly: bool = False
    section: str = ""
    options: tuple[str, ...] = ()
    in_dialog: bool = False
    in_view: bool = True

    @property
    def is_field(self) -> bool:
        return self.role in ("field", "select")

    def key(self) -> str:
        return f"{self.role}|{self.name}|{self.section}"

    def line(self, origin: str = "") -> str:
        bits = [f'{self.ref} {self.role} "{self.name}"' if self.name else f"{self.ref} {self.role}"]
        if self.section and self.is_field:
            bits.append(f"in “{self.section}”")
        if self.type == "password":
            bits.append("(password)")
        if self.role in ("checkbox", "radio", "switch"):
            bits.append("[checked]" if self.checked else "[unchecked]")
        if self.is_field:
            bits.append("[filled]" if self.filled else "[empty]")
        if self.options:
            bits.append("options: " + " | ".join(self.options[:8]))
        if self.disabled:
            bits.append("[disabled]")
        if self.readonly:
            bits.append("[read-only]")
        if self.in_dialog:
            bits.append("[in dialog]")
        if self.href:
            bits.append("→ " + short_href(self.href, origin))
        return " ".join(bits)


def short_href(href: str, origin: str = "") -> str:
    p = urlparse(href)
    if not p.scheme or p.scheme not in ("http", "https"):
        return href[:60]
    same = origin and f"{p.scheme}://{p.netloc}" == origin
    path = (p.path or "/") + (f"?{p.query}" if p.query else "")
    return (path if same else f"{p.scheme}://{p.netloc}{path}")[:110]


@dataclass
class Snapshot:
    url: str  # raw; for code checks and the executor only, never logged
    url_masked: str
    title: str
    text: str
    headings: list[str]
    elements: list[Element]
    dialogs: list[str]
    iframes: list[str]
    scroll: dict[str, int]
    obs: Observation  # the full plain-code observation, for the hard checks
    truncated: int = 0  # interactive elements left out because of MAX_ELEMENTS
    refused: set[str] = field(default_factory=set)  # xpaths the safety rules refused on this page (shown flagged)
    _by_ref: dict[str, Element] = field(default_factory=dict, repr=False)

    def element(self, ref: str | None) -> Element | None:
        return self._by_ref.get((ref or "").strip().lower())

    @property
    def origin(self) -> str:
        p = urlparse(self.url)
        return f"{p.scheme}://{p.netloc}" if p.scheme else ""

    @property
    def secret_count(self) -> int:
        return len(self.obs.secret_xpaths)

    def fingerprint(self) -> str:
        """Changes when the page meaningfully changes: address, title, text size, filled fields, and the elements
        the agent can see (their roles, names and states)."""
        import hashlib

        state = "|".join(f"{e.key()}:{int(e.filled)}{int(e.checked)}{int(e.disabled)}" for e in self.elements)
        return f"{self.obs.fingerprint()}|{hashlib.md5(state.encode(), usedforsecurity=False).hexdigest()[:12]}"

    def render(self, max_chars: int = RENDER_CHARS) -> str:
        """Compact text for the model. Elements are never cut mid-way; text comes last and is trimmed."""
        origin = self.origin
        out = [f"URL: {self.url_masked}", f"Title: {self.title[:120]}"]
        if self.headings:
            out.append("Headings: " + " | ".join(self.headings[:20]))
        if self.dialogs:
            out.append("Dialogs: " + " || ".join(d[:160] for d in self.dialogs[:3]))
        if self.scroll:
            y, h, v = self.scroll.get("y", 0), self.scroll.get("height", 0), self.scroll.get("view", 0)
            if h > v + 20:
                out.append(f"Scroll: {y} of {h - v} (page is taller than the window)")
        if self.secret_count:
            out.append(f"Note: {self.secret_count} credential-like value(s) are on this page and are hidden from you.")
        more = f", +{self.truncated} more not shown" if self.truncated else ""
        out.append(f"Elements ({len(self.elements)}{more}):")
        out += [e.line(origin) + (" [refused by safety rules: do not choose it]" if e.xpath in self.refused else "")
                for e in self.elements]
        text = re.sub(r"\n{2,}", "\n", self.text).strip()[:TEXT_CHARS]
        out.append("Page text:\n" + text)
        body = "\n".join(out)
        if len(body) > max_chars:  # keep the structure; cut the text first, then the tail of the element list
            body = body[: max_chars - 40].rsplit("\n", 1)[0] + "\n[…trimmed]"
        return body


def build_snapshot(raw: dict[str, Any], masker: Masker) -> Snapshot:
    obs = from_raw(raw if isinstance(raw, dict) else {}, masker)
    els: list[Element] = []
    for i, e in enumerate(obs.elements[:MAX_ELEMENTS], 1):
        els.append(Element(
            ref=f"e{i}", xpath=e["xpath"], role=e.get("role") or "button", name=(e.get("name") or "").strip(),
            tag=e.get("tag", ""), type=e.get("type", ""), href=e.get("href", ""),
            disabled=bool(e.get("disabled")), checked=bool(e.get("checked")),
            filled=bool(e.get("value_len")), readonly=bool(e.get("readonly")), section=e.get("section") or "",
            options=tuple(e.get("options") or ()), in_dialog=bool(e.get("in_dialog")),
            in_view=bool(e.get("in_view", True)),
        ))
    snap = Snapshot(
        url=obs.url, url_masked=obs.url_masked, title=obs.title, text=obs.text, headings=list(obs.headings),
        elements=els, dialogs=[b["text"] for b in obs.banners if b.get("text")], iframes=list(obs.iframes),
        scroll=dict(obs.scroll), obs=obs, truncated=max(0, len(obs.elements) - MAX_ELEMENTS),
    )
    snap._by_ref = {e.ref: e for e in els}
    return snap


async def take_snapshot(page: Any, masker: Masker, not_secret: list[str] | None = None) -> Snapshot:
    """Observe the live page in plain code and build the numbered snapshot. `not_secret`: the run's own
    approved values (e.g. the app name), which are never treated as credentials."""
    import json

    raw = await page.evaluate(OBSERVE_JS.replace("__NOT_SECRET__", json.dumps(list(not_secret or []))))
    return build_snapshot(raw if isinstance(raw, dict) else {}, masker)


def describe_change(before: Snapshot | None, after: Snapshot) -> str:
    """What the last action did, in one line the model can use ("no change" is the important one)."""
    if before is None:
        return "first look at the page"
    parts: list[str] = []
    b_url, a_url = urlparse(before.url), urlparse(after.url)
    if (b_url.netloc, b_url.path) != (a_url.netloc, a_url.path):
        parts.append(f"navigated to {short_href(after.url_masked, before.origin)}")
    elif b_url.query != a_url.query or b_url.fragment != a_url.fragment:
        parts.append("the address changed (query or fragment)")
    if len(after.dialogs) > len(before.dialogs):
        parts.append("a dialog appeared: " + after.dialogs[-1][:80])
    elif len(after.dialogs) < len(before.dialogs):
        parts.append("a dialog closed")
    cb, ca = Counter(e.key() for e in before.elements), Counter(e.key() for e in after.elements)
    added, removed = ca - cb, cb - ca
    if added:
        names = [k.split("|")[0] + " “" + k.split("|")[1][:30] + "”" for k in list(added)[:4]]
        parts.append(f"{sum(added.values())} new element(s): " + ", ".join(names))
    if removed:
        names = [k.split("|")[0] + " “" + k.split("|")[1][:30] + "”" for k in list(removed)[:4]]
        parts.append(f"{sum(removed.values())} element(s) gone: " + ", ".join(names))
    prior = {e.xpath: e for e in before.elements}
    for e in after.elements:
        old = prior.get(e.xpath)
        if old is None or not e.name:
            continue
        if e.is_field and old.filled != e.filled:
            parts.append(f"field “{e.name[:30]}” is now {'filled' if e.filled else 'empty'}")
        elif e.role in ("checkbox", "radio", "switch") and old.checked != e.checked:
            parts.append(f"“{e.name[:30]}” is now {'checked' if e.checked else 'unchecked'}")
    if after.secret_count != before.secret_count:
        parts.append("credential-like values " + ("appeared" if after.secret_count > before.secret_count else "went"))
    return "; ".join(dict.fromkeys(parts)) or "no change"
