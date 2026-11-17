"""Credential capture by plain browser code (spec §6.9). No model ever sees a value.

1. The observer (browser/observe.py) has already flagged credential-looking elements by XPath only.
2. CAPTURE_JS reads exactly those elements' values plus a short label context, in the page.
3. Code classifies each by its label (client ID / client secret / API key / token / signing secret).
   Unlabelled values are not guessed at: they are counted and left alone.
4. Each secret value is registered with the Masker *before* anything else happens to it, written to the
   owner-only store, and dropped. Only store references and masked displays leave this module.
   IDs (client/application ID) are stored too but not registered as secrets: they appear in URLs.

Shown-once secrets: capture happens on the first view, on the page as it is (no reload, no navigation).
If the page shows the secret label but the value is hidden, the result says so (`secret_hidden`), and
the caller hands the choice to regenerate to the person. The credential is then not captured.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from credagent.browser.observe import Observation
from credagent.secrets.masking import Masker, masked_display
from credagent.secrets.store import SecretFileStore
from credagent.state.models import CredentialPart, CredentialReference

CAPTURE_JS = r"""
(() => {
  const xs = __XPATHS__;
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  return xs.map(x => {
    const el = document.evaluate(x, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    if (!el) return null;
    const value = clean(el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' ? el.value : el.innerText);
    const own = [el.id, el.getAttribute('aria-label'), el.getAttribute('data-label'), el.getAttribute('name')]
      .filter(Boolean).join(' ');
    let around = el.parentElement ? clean(el.parentElement.innerText) : '';
    let lab = '';
    if (el.labels && el.labels.length) lab = Array.from(el.labels).map(l => clean(l.innerText)).join(' ');
    const prev = el.previousElementSibling ? clean(el.previousElementSibling.innerText) : '';
    // The nearest short text above among the ancestors' earlier siblings: a row's label in a neighbouring div that
    // is not linked to the field (Discord, D-087).
    let above = '';
    for (let a = el, d = 0; a && !above && d < 6; a = a.parentElement, d++) {
      for (let s = a.previousElementSibling, n = 0; s && !above && n < 3; s = s.previousElementSibling, n++) {
        const t = clean(s.innerText || '');
        if (t && t.length <= 60 && !/^(copy|copied)$/i.test(t)) above = t;
      }
    }
    // The nearest heading above (e.g. <h3>Client Secret</h3> above a row that holds the value and a Copy button).
    let section = '';
    for (let a = el, d = 0; a && !section && d < 8; a = a.parentElement, d++) {
      for (let s = a.previousElementSibling; s && !section; s = s.previousElementSibling) {
        const h = /^H[1-6]$/.test(s.tagName) ? s
          : s.querySelector && s.querySelector('h1,h2,h3,h4,h5,h6,[role=heading]');
        if (h && clean(h.innerText)) section = clean(h.innerText).slice(0, 80);
      }
    }
    // Labels are often a heading one or two levels up (e.g. <h2>Application ID</h2><div><div>123…</div></div>).
    const p1 = el.parentElement, p2 = p1 && p1.parentElement;
    const pprev = p1 && p1.previousElementSibling ? clean(p1.previousElementSibling.innerText) : '';
    const up = p2 ? clean(p2.innerText) : '';
    return { xpath: x, value, own: own.slice(0, 120), label: lab.slice(0, 120), prev: prev.slice(0, 120),
             around: around.slice(0, 240), pprev: pprev.slice(0, 120), up: up.slice(0, 240), section,
             above: above.slice(0, 80) };
  });
})()
"""

# Order matters: the more specific names first.
PART_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("client_secret", re.compile(r"client[\s_-]*secret|consumer[\s_-]*secret|app(lication)?[\s_-]*secret", re.I)),
    ("client_id", re.compile(r"client[\s_-]*id|consumer[\s_-]*key|app(lication)?[\s_-]*id", re.I)),
    ("signing_secret", re.compile(r"signing[\s_-]*secret|webhook[\s_-]*secret", re.I)),
    ("api_key", re.compile(r"api[\s_-]*key|secret[\s_-]*key", re.I)),
    ("token", re.compile(r"(access|bearer|personal access|bot|api|auth)[\s_-]*token|\btoken\b", re.I)),
]
SECRET_PARTS = {"client_secret", "signing_secret", "api_key", "token"}
HIDDEN_RE = re.compile(
    r"(client[\s_-]*secret|secret|api[\s_-]*key|token)\W{0,3}[^\n]{0,40}?([•●∙*]{4,}|\(hidden|is hidden|"
    r"won[’']t be able to see it again|only shown once)",
    re.I,
)
LIMITATION_RE = re.compile(
    r"[^.\n]{0,80}\b(testing mode|test mode|sandbox|development mode|unverified app|only test users|"
    r"until (the app|it) (passes|is approved)|submit (the app )?for review to)\b[^.\n]{0,120}",
    re.I,
)
VALUE_OK = re.compile(r"^[A-Za-z0-9_\-.~+/=]{6,512}$")


@dataclass
class CaptureResult:
    credential: CredentialReference | None
    captured: list[str] = field(default_factory=list)  # part names stored
    unlabelled: int = 0  # credential-looking values with no recognisable label (left alone)
    ambiguous: list[str] = field(default_factory=list)  # a part name seen twice with different values
    secret_hidden: bool = False  # the page shows a secret label but no value (shown-once, already viewed)
    limitations: list[str] = field(default_factory=list)  # observed production limitations (no secrets)

    @property
    def has_secret(self) -> bool:
        return any(p in SECRET_PARTS for p in self.captured)

    def observed(self) -> str:
        bits = [f"captured {', '.join(self.captured) or 'nothing'}"]
        if self.unlabelled:
            bits.append(f"{self.unlabelled} unlabelled credential-like value(s) left alone")
        if self.ambiguous:
            bits.append(f"ambiguous (seen twice, not stored): {', '.join(self.ambiguous)}")
        if self.secret_hidden:
            bits.append("the secret is hidden on this page (shown once, already viewed)")
        return "; ".join(bits)


def classify(item: dict[str, str]) -> str | None:
    """Name a captured element from its own attributes first, then its label, the text right before it,
    then the surrounding text. None = no recognisable label (never guessed)."""
    for key in ("own", "label", "prev", "around", "pprev", "above", "section", "up"):
        text = item.get(key) or ""
        for name, rx in PART_PATTERNS:
            if rx.search(text):
                return name
    return None


def credential_kind(plan_kind: str, parts: set[str]) -> str:
    if plan_kind in ("oauth_client", "api_key", "token", "sandbox_key", "other"):
        return plan_kind
    if parts & {"client_id", "client_secret"}:
        return "oauth_client"
    if "api_key" in parts:
        return "api_key"
    if "token" in parts:
        return "token"
    return "other"


async def read_flagged(page: Any, xpaths: list[str]) -> list[dict[str, str]]:
    raw = await page.evaluate(CAPTURE_JS.replace("__XPATHS__", json.dumps(xpaths[:50])))
    return [r for r in (raw or []) if isinstance(r, dict)]


def store_capture(
    items: list[dict[str, str]],
    obs: Observation,
    *,
    store: SecretFileStore,
    masker: Masker,
    run_id: str,
    plan_kind: str,
) -> CaptureResult:
    """Pure code: classify, register, store. `items` hold raw values and are cleared before returning."""
    values = [str(i.get("value") or "") for i in items]
    named: dict[str, str] = {}
    res = CaptureResult(credential=None)
    for item, value in zip(items, values, strict=True):
        if not VALUE_OK.match(value):
            continue
        # Labels may contain other values from the same row: remove every captured value first.
        for k in ("own", "label", "prev", "around", "pprev", "up", "section", "above"):
            t = str(item.get(k) or "")
            for v in values:
                if v:
                    t = t.replace(v, " ")
            item[k] = t
        name = classify(item)
        if name is None:
            res.unlabelled += 1
            continue
        if name in named and named[name] != value:
            res.ambiguous.append(name)
            continue
        named[name] = value
    for name in res.ambiguous:
        named.pop(name, None)
    # Register secrets with the Masker before anything else touches them. IDs (client/application ID) are
    # not secrets and often appear in URLs; registering them made the leak guard refuse a normal page URL
    # (Discord run 20261116-171020, D-062). Unlabelled values are not stored or written by CredAgent; the
    # observer already removed them from page text, and the high-entropy masking rule still applies.
    for name, value in named.items():
        if name in SECRET_PARTS:
            masker.register(value, label=name)
    parts: dict[str, CredentialPart] = {}
    for name, value in named.items():
        ref = store.put(run_id, name, value)
        parts[name] = CredentialPart(store_ref=ref, masked_display=masked_display(value))
        res.captured.append(name)
    named.clear()
    for item in items:
        item.clear()
    values.clear()
    res.secret_hidden = bool(HIDDEN_RE.search(obs.text)) and not res.has_secret
    res.limitations = sorted({" ".join(m.group(0).split())[:200] for m in LIMITATION_RE.finditer(obs.text)})
    if parts:
        res.credential = CredentialReference(kind=credential_kind(plan_kind, set(parts)), parts=parts)  # type: ignore[arg-type]
    return res


async def capture(
    page: Any, obs: Observation, *, store: SecretFileStore, masker: Masker, run_id: str, plan_kind: str
) -> CaptureResult:
    items = await read_flagged(page, obs.secret_xpaths)
    return store_capture(items, obs, store=store, masker=masker, run_id=run_id, plan_kind=plan_kind)


def load_into_masker(credential: CredentialReference | None, store: SecretFileStore, masker: Masker) -> int:
    """After a restart (resume/verify), teach the Masker this run's stored secrets again. Returns how many."""
    n = 0
    for name, part in (credential.parts.items() if credential else []):
        if name in SECRET_PARTS or name == "registration_access_token":
            try:
                masker.register(store.get(part.store_ref), label=name)
                n += 1
            except Exception:  # noqa: BLE001, S112 - a missing/unsafe file is reported by `credagent secret`
                continue
    return n
