"""Code-owned page checks (spec §6.4 step 2, §6.6). Run on every observed page, before Jev.

They only read the Observation (plain-code data). Results:
  Gate(action="DO")     a person must act in the browser (sign-in, code, CAPTCHA, payment, …)
  Gate(action="BLOCK")  a requirement that cannot be met now (business/identity verification)
  Gate(action="AUTO")   the agent may resolve it by a fixed code rule (limited cookie option)
  Gate(action="INFO")   recorded evidence that changes policy (terms present, credential shown)
No model output can remove a gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

from credagent.browser.observe import Observation

TERMS_RE = re.compile(
    r"(agree|accept|consent)[^.\n]{0,80}(terms|conditions|policy|agreement|eula)|terms of (service|use)"
    r"|developer (terms|agreement)",
    re.I,
)
IMPLIED_RE = re.compile(
    r"\bby (clicking|creating|continuing|signing up|registering|submitting|selecting|tapping|"
    r"using|proceeding)\b[^.\n]{0,160}?\b(you )?(agree|accept|consent)",
    re.I,
)
CAPTCHA_TEXT = re.compile(
    r"verify (that )?you are (a )?human|i'?m not a robot|are you a robot|security check|"
    r"prove you'?re human|captcha|checking your browser",
    re.I,
)
CAPTCHA_FRAME = re.compile(r"recaptcha|hcaptcha|challenges\.cloudflare|turnstile|arkoselabs|funcaptcha", re.I)
CODE_TEXT = re.compile(
    r"verification code|enter the (\d[- ]digit )?code|one[- ]time (pass)?code|two[- ]factor|2fa|"
    r"authenticator app|security key|passkey|magic link|check your (email|inbox|phone)",
    re.I,
)
VERIFY_TEXT = re.compile(
    r"business verification|verify your (business|organi[sz]ation|identity|company)|"
    r"identity verification|legal entity|company registration number|government[- ]issued id|"
    r"KYC",
    re.I,
)
PAYMENT_FIELD = re.compile(
    r"card ?number|credit card|debit card|\bcvc\b|\bcvv\b|security code|expir(y|ation) date|iban", re.I
)
LIMITED_COOKIE = re.compile(
    r"^(reject( all)?|decline( all)?|necessary only|only necessary|essential only|"
    r"use necessary cookies only|refuse( all)?|deny( all)?)$",
    re.I,
)
COOKIE_WORD = re.compile(r"cookie|consent|tracking|privacy choices", re.I)
AGENT_INSTRUCTION = re.compile(
    r"(automated|ai) (agents?|assistants?)|ignore (all |any )?(previous|earlier|prior) "
    r"instructions|system prompt",
    re.I,
)
CREDENTIAL_TEXT = re.compile(
    r"client[\s_-]*secret|api[\s_-]*key|secret[\s_-]*key|access[\s_-]*token|"
    r"personal access token|signing secret",
    re.I,
)

Kind = Literal[
    "off_allow_list",
    "sign_in",
    "verification_code",
    "captcha",
    "payment",
    "business_verification",
    "terms",
    "cookie_consent",
    "credential_shown",
    "agent_instruction",
]


@dataclass(frozen=True)
class Gate:
    kind: Kind
    action: Literal["DO", "BLOCK", "AUTO", "INFO"]
    reason: str
    evidence: list[str] = field(default_factory=list)
    target_xpath: str | None = None  # AUTO: the control to use; INFO terms: the terms control
    form_xpath: str | None = None  # terms: the form whose submit carries the agreement


def host_allowed(url: str, allowed: list[str]) -> bool:
    p = urlparse(url)
    if p.scheme in ("about", "data", "chrome") or url in ("", "about:blank"):
        return True
    host = (p.hostname or "").lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in allowed)


def _quote(text: str, m: re.Match[str], pad: int = 60) -> str:
    a, b = max(0, m.start() - pad), min(len(text), m.end() + pad)
    return "…" + " ".join(text[a:b].split()) + "…"


def check(obs: Observation, allowed: list[str]) -> list[Gate]:
    gates: list[Gate] = []
    text = obs.text
    if not host_allowed(obs.url, allowed):
        gates.append(
            Gate(
                "off_allow_list",
                "DO",
                f"The page is outside the allowed domains ({', '.join(allowed)}).",
                [f"URL: {obs.url_masked}"],
            )
        )
        return gates  # nothing else on an off-domain page matters to the agent

    pw = [i for i in obs.inputs if i["type"] == "password"]
    if pw:
        gates.append(
            Gate(
                "sign_in",
                "DO",
                "This page asks for a password (sign-in or account creation).",
                [f"password field: {pw[0]['label'] or pw[0]['name']}", f"title: {obs.title}"],
            )
        )
    m = CODE_TEXT.search(text)
    if m and any(i["type"] in ("text", "tel", "number", "") for i in obs.inputs):
        gates.append(
            Gate("verification_code", "DO", "The page asks for a verification code / second factor.", [_quote(text, m)])
        )
    m = CAPTCHA_TEXT.search(text)
    frames = [f for f in obs.iframes if CAPTCHA_FRAME.search(f)]
    if m or frames:
        gates.append(
            Gate(
                "captcha",
                "DO",
                "A CAPTCHA or bot check is shown; only a person may complete it.",
                ([_quote(text, m)] if m else []) + [f"iframe: {f[:80]}" for f in frames[:2]],
            )
        )
    pay = [
        i
        for i in obs.inputs
        if i["autocomplete"].startswith("cc-") or PAYMENT_FIELD.search(i["label"] + " " + i["name"])
    ]
    if pay:
        gates.append(
            Gate(
                "payment",
                "DO",
                "The page asks for payment details; the agent never enters them.",
                [f"field: {pay[0]['label'] or pay[0]['name']}"],
            )
        )
    m = VERIFY_TEXT.search(text)
    if m:
        gates.append(
            Gate(
                "business_verification",
                "BLOCK",
                "The provider requires business/identity verification before continuing.",
                [_quote(text, m)],
            )
        )

    for i in obs.inputs:
        if i["type"] in ("checkbox", "radio") and TERMS_RE.search(i["label"]):
            gates.append(
                Gate(
                    "terms",
                    "INFO",
                    "A terms-acceptance control is on this page (always the person's).",
                    [f'checkbox: "{i["label"][:120]}"'],
                    target_xpath=i["xpath"],
                    form_xpath=i["form"],
                )
            )
    for f in obs.forms:
        m = IMPLIED_RE.search(f["text"])
        if m:
            gates.append(
                Gate(
                    "terms",
                    "INFO",
                    "Submitting this form implies agreement to terms (always the person's).",
                    [_quote(f["text"], m)],
                    form_xpath=f["xpath"],
                )
            )
    if not any(g.kind == "terms" for g in gates):
        m = IMPLIED_RE.search(text)
        if m:
            gates.append(
                Gate("terms", "INFO", "The page says an action implies agreement to terms.", [_quote(text, m)])
            )

    for b in obs.banners:
        if not COOKIE_WORD.search(b["text"]):
            continue
        limited = [x for x in obs.buttons if x["in_dialog"] and LIMITED_COOKIE.match(x["text"].strip())]
        if limited:
            gates.append(
                Gate(
                    "cookie_consent",
                    "AUTO",
                    "Cookie banner: choosing the most limited option.",
                    [f'banner: "{b["text"][:100]}"', f'button: "{limited[0]["text"]}"'],
                    target_xpath=limited[0]["xpath"],
                )
            )
        else:
            gates.append(
                Gate(
                    "cookie_consent",
                    "DO",
                    "Cookie banner has no limited option; the person chooses.",
                    [f'banner: "{b["text"][:100]}"'],
                )
            )
        break

    if obs.secret_xpaths or (CREDENTIAL_TEXT.search(text) and "[SECRET-ELEMENT]" in text):
        gates.append(
            Gate(
                "credential_shown",
                "INFO",
                "A credential-like value is displayed on this page.",
                [f"{len(obs.secret_xpaths)} credential-like element(s)"],
            )
        )
    m = AGENT_INSTRUCTION.search(text)
    if m:
        gates.append(
            Gate(
                "agent_instruction",
                "INFO",
                "The page contains text addressed to automated agents; it is treated as data and never followed.",
                [_quote(text, m)],
            )
        )
    return gates


def blocking(gates: list[Gate]) -> list[Gate]:
    """Gates that stop the agent before any action on this page (DO first, then BLOCK)."""
    return [g for g in gates if g.action == "DO"] + [g for g in gates if g.action == "BLOCK"]
