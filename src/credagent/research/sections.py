"""Choose which parts of a long page the model sees (instead of the first N characters).

Split at markdown headings (falling back to blank-line paragraphs), cap each section,
score sections by credential-related terms (plus the app name), always keep the
opening section, fill the budget with the highest-scoring sections, and emit them in
page order with explicit omission markers so the model knows text is missing.
Deterministic: same input, same output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TERMS = {
    # weight 3: what we are looking for
    "client secret": 3, "client id": 3, "client_id": 3, "client_secret": 3, "api key": 3,
    "access token": 3, "personal access token": 3, "generate": 2, "register": 2, "create": 2,
    "new app": 3, "oauth app": 3, "credential": 3, "secret": 2, "callback": 2, "redirect": 2,
    "scope": 2, "permission": 2, "token endpoint": 3, "authorize": 2, "authorization": 1,
    # weight 2: blockers and gates
    "terms": 2, "agree": 2, "review": 2, "verification": 2, "verify": 1, "business": 2,
    "payment": 2, "billing": 2, "plan": 1, "approval": 2, "sandbox": 2, "test mode": 2,
    "developer settings": 3, "console": 2, "dashboard": 1, "settings": 1,
}
OMITTED = "\n\n[… section omitted …]\n\n"
MAX_SECTION = 2500


@dataclass(frozen=True)
class Selection:
    text: str
    complete: bool
    chars_total: int
    chars_seen: int
    kept: int
    total: int


def split_sections(text: str) -> list[str]:
    parts = re.split(r"(?m)^(?=#{1,6}\s)", text)
    if len(parts) <= 2:  # no useful heading structure
        parts = re.split(r"\n\s*\n", text)
    sections: list[str] = []
    for p in parts:
        p = p.strip()
        while len(p) > MAX_SECTION:  # cap very long sections at a paragraph/line boundary
            cut = max(p.rfind("\n\n", 0, MAX_SECTION), p.rfind("\n", 0, MAX_SECTION))
            cut = cut if cut > MAX_SECTION // 3 else MAX_SECTION
            sections.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            sections.append(p)
    return sections


def score(section: str, extra_terms: tuple[str, ...] = ()) -> int:
    low = section.lower()
    s = sum(w * low.count(t) for t, w in TERMS.items())
    s += sum(2 * low.count(t.lower()) for t in extra_terms if t)
    return s


def select(text: str, budget: int, extra_terms: tuple[str, ...] = ()) -> Selection:
    if len(text) <= budget:
        return Selection(text, True, len(text), len(text), 1, 1)
    secs = split_sections(text)
    order = sorted(range(1, len(secs)), key=lambda i: (-score(secs[i], extra_terms), i))
    chosen = {0}
    used = len(secs[0])
    for i in order:
        cost = len(secs[i]) + len(OMITTED)
        if used + cost > budget:
            continue
        chosen.add(i)
        used += cost
    out, prev = [], -1
    for i in sorted(chosen):
        if prev != -1 and i != prev + 1:
            out.append(OMITTED.strip())
        out.append(secs[i])
        prev = i
    if prev != len(secs) - 1:
        out.append(OMITTED.strip())
    body = "\n\n".join(out)[:budget]
    return Selection(body, False, len(text), len(body), len(chosen), len(secs))
