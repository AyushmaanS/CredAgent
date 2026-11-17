"""Plain-code page observation (no model involved).

One JavaScript pass collects what code-owned checks and Jev need. Secret-bearing
values never leave the page:
* input values are reported only as length + a "looks like a credential" flag;
* elements whose text looks like a credential (long mixed token, or a token next to a
  "secret / API key / token" label) are reported only by XPath, and their text is
  replaced by [SECRET-ELEMENT] in the page text before it is returned.
The returned text is masked again in Python before any use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from credagent.secrets.masking import Masker

OBSERVE_JS = r"""
(() => {
  const TOKEN = /^[A-Za-z0-9_\-.~+\/=]{20,}$/;
  const SECRET_LABEL = /(client[\s_-]*secret|secret[\s_-]*key|api[\s_-]*key|access[\s_-]*token|private[\s_-]*key|\btoken\b|\bsecret\b|password)/i;
  const mixed = t => /[A-Za-z]/.test(t) && /[0-9]/.test(t);
  // Lowercase word slugs ("credagent-demo-20261117") are names, not secrets: same rule as the masker (D-076).
  const slug = t => /^[a-z0-9]{1,20}(?:[-_][a-z0-9]{1,20})+$/.test(t);
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const xp = el => { let p = ''; for (; el && el.nodeType === 1; el = el.parentNode) {
      let i = 1, s = el.previousElementSibling;
      while (s) { if (s.nodeName === el.nodeName) i++; s = s.previousElementSibling; }
      p = '/' + el.nodeName.toLowerCase() + '[' + i + ']' + p; } return p; };
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const labelOf = el => {
    let t = el.getAttribute('aria-label') || '';
    if (!t && el.labels && el.labels.length) t = Array.from(el.labels).map(l => l.innerText).join(' ');
    if (!t) { const l = el.closest('label'); if (l) t = l.innerText; }
    if (!t) t = el.getAttribute('placeholder') || el.getAttribute('title') || el.name || el.id || '';
    if (el.tagName === 'SELECT') {            // a wrapping <label> also contains every option's text
      for (const o of el.options) t = t.split(o.text).join(' ');
    }
    return clean(t).slice(0, 160);
  };
  const ctx = el => { const p = el.parentElement; return clean(p ? p.innerText : '').slice(0, 200); };
  // The nearest heading above an element (e.g. "Redirects"), for fields that have no label of their own.
  const sectionOf = el => {
    for (let a = el, d = 0; a && d < 8; a = a.parentElement, d++) {
      for (let s = a.previousElementSibling; s; s = s.previousElementSibling) {
        const h = /^H[1-6]$/.test(s.tagName) ? s : s.querySelector && s.querySelector('h1,h2,h3,h4,h5,h6,[role=heading]');
        if (h && clean(h.innerText)) return clean(h.innerText).slice(0, 80);
      }
    }
    return '';
  };

  // credential-looking elements
  const secretEls = [];
  for (const el of document.querySelectorAll('code,pre,kbd,samp,span,div,td,p,strong,b,input,textarea')) {
    if (!vis(el)) continue;
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      const v = (el.value || '').trim();
      if (el.type === 'password') continue;
      if (v.length >= 20 && TOKEN.test(v) && mixed(v) && (el.readOnly || SECRET_LABEL.test(labelOf(el) + ' ' + ctx(el))))
        secretEls.push(el);
      continue;
    }
    if (el.children.length) continue;               // leaf elements only
    const t = clean(el.innerText);
    if (t.length >= 20 && TOKEN.test(t) && mixed(t) && !slug(t)) secretEls.push(el);
    // A numeric client/application ID (e.g. a Discord snowflake) is not secret, but it is part of the
    // credential being created: report it the same way so plain code can capture it next to its label.
    else if (/^\d{15,22}$/.test(t)) {
      const p1 = el.parentElement, near = [ctx(el), el.previousElementSibling ? el.previousElementSibling.innerText : '',
        p1 && p1.previousElementSibling ? p1.previousElementSibling.innerText : '',
        p1 && p1.parentElement ? clean(p1.parentElement.innerText).slice(0, 200) : ''].join(' ');
      if (/(client|application|app)[\s_-]*id/i.test(near)) secretEls.push(el);
    }
  }
  let text = document.body ? document.body.innerText : '';
  for (const el of secretEls) { const t = clean(el.innerText); if (t) text = text.split(t).join('[SECRET-ELEMENT]'); }
  text = text.slice(0, 20000);

  const inputs = Array.from(document.querySelectorAll('input,textarea,select')).filter(el => vis(el) && el.type !== 'hidden').map(el => ({
    xpath: xp(el), tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(), name: el.name || '',
    id: el.id || '', label: labelOf(el), required: !!el.required, checked: !!el.checked, readonly: !!el.readOnly,
    autocomplete: el.getAttribute('autocomplete') || '', value_len: (el.value || '').length, section: sectionOf(el),
    value_secretlike: secretEls.includes(el),
    options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => clean(o.text).slice(0, 80)).slice(0, 20) : [],
    form: el.form ? xp(el.form) : null,
  }));
  const buttons = Array.from(document.querySelectorAll('button,input[type=submit],input[type=button],[role=button]')).filter(vis).map(el => ({
    xpath: xp(el), text: clean(el.innerText || el.value || el.getAttribute('aria-label')).slice(0, 120),
    type: (el.getAttribute('type') || '').toLowerCase(), name: el.name || '', value: (el.tagName === 'BUTTON' ? (el.value || '') : '').slice(0, 40),
    disabled: !!el.disabled, form: el.form ? xp(el.form) : null,
    in_dialog: !!el.closest('[role=dialog],[aria-modal=true],[id*=cookie],[class*=cookie],[id*=consent],[class*=consent]'),
  }));
  const links = Array.from(document.querySelectorAll('a[href]')).filter(vis).map(el => ({
    xpath: xp(el), text: clean(el.innerText).slice(0, 120), href: el.href }));
  const forms = Array.from(document.querySelectorAll('form')).map(f => ({ xpath: xp(f), text: clean(f.innerText).slice(0, 1500) }));
  const banners = Array.from(document.querySelectorAll('[role=dialog],[aria-modal=true],[id*=cookie],[class*=cookie],[id*=consent],[class*=consent]'))
    .filter(vis).map(el => ({ xpath: xp(el), text: clean(el.innerText).slice(0, 400) }));
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading]')).filter(vis)
    .map(el => clean(el.innerText).slice(0, 120)).filter(Boolean).slice(0, 60);
  return { url: location.href, title: document.title || '', text, inputs, buttons, links, forms, banners, headings,
           iframes: Array.from(document.querySelectorAll('iframe')).map(f => f.src || '').slice(0, 20),
           secret_xpaths: secretEls.map(xp).slice(0, 50) };
})()
"""


@dataclass
class Observation:
    url: str                       # raw: used only for code checks (allow-list); never logged
    title: str
    text: str                      # masked, secret elements removed in-page
    inputs: list[dict[str, Any]] = field(default_factory=list)
    buttons: list[dict[str, Any]] = field(default_factory=list)
    links: list[dict[str, Any]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    banners: list[dict[str, Any]] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    iframes: list[str] = field(default_factory=list)
    secret_xpaths: list[str] = field(default_factory=list)
    url_masked: str = ""           # safe for logs/models (query tokens may be credentials)

    @property
    def secret_bearing(self) -> bool:
        return bool(self.secret_xpaths) or "[REDACTED" in self.text

    def fingerprint(self) -> str:
        """Changes when the page meaningfully changes (used for no-progress detection)."""
        filled = ",".join(f"{i['xpath']}:{i['value_len']}:{int(i['checked'])}" for i in self.inputs)
        return f"{self.url}|{self.title}|{len(self.text)}|{filled}"

    def summary(self) -> dict[str, Any]:
        """Small, secret-free record for the event log."""
        return {"url": self.url_masked, "title": self.title[:120], "inputs": len(self.inputs),
                "buttons": len(self.buttons), "links": len(self.links),
                "secret_elements": len(self.secret_xpaths), "banners": len(self.banners)}


def from_raw(raw: dict[str, Any], masker: Masker) -> Observation:
    def m(x: Any) -> Any:
        return masker.mask(x)
    return Observation(
        url=str(raw.get("url", "")), title=m(str(raw.get("title", ""))), text=m(str(raw.get("text", ""))),
        inputs=m(raw.get("inputs") or []), buttons=m(raw.get("buttons") or []), links=m(raw.get("links") or []),
        forms=m(raw.get("forms") or []), banners=m(raw.get("banners") or []), headings=m(raw.get("headings") or []),
        iframes=[str(x) for x in raw.get("iframes") or []], secret_xpaths=list(raw.get("secret_xpaths") or []),
        url_masked=masker.mask_text(str(raw.get("url", ""))),
    )


async def observe_page(page: Any, masker: Masker) -> Observation:
    raw = await page.evaluate(OBSERVE_JS)
    return from_raw(raw if isinstance(raw, dict) else {}, masker)
