"""Handoff cards (PRD §9): the six required fields, rendered for the terminal.

1. what is done so far (n of m)   2. what is blocking + evidence
3. exactly what to do and where   4. what the agent does afterwards
5. how to resume                   6. what not to do
"""

from __future__ import annotations

import textwrap

from credagent.secrets.masking import Masker
from credagent.state.models import Handoff, Run

WIDTH = 78
RESUME_AVAILABLE = True  # `credagent resume` exists since Sprint 5
DEFAULT_DONT = {
    "DO": ["Do not close the CredAgent browser window while this handoff is open.",
           "Do not paste any secret or code shown on screen into chat or the terminal."],
    "DECIDE": ["Do not change anything in the browser while answering."],
}


def progress(run: Run) -> str:
    """The plan is guidance for the agent, not a step counter (D-078): count what was actually done."""
    agent = sum(1 for s in run.steps if s.actor == "agent" and s.outcome == "done")
    person = sum(1 for s in run.steps if s.actor == "person" and s.outcome == "done")
    created = f"; created: {', '.join(run.created)[:90]}" if run.created else ""
    return f"{agent} actions by the agent, {person} by you{created}"


def _wrap(label: str, text: str) -> list[str]:
    # Never break inside words or at hyphens: run IDs and commands must stay copy-pasteable.
    lines = textwrap.wrap(text, WIDTH - 4 - len(label), break_on_hyphens=False, break_long_words=False) or [""]
    pad = " " * len(label)
    return [f"  {label}{lines[0]}"] + [f"  {pad}{ln}" for ln in lines[1:]]


def render_card(run: Run, handoff: Handoff, masker: Masker | None = None) -> str:
    m = masker or Masker()
    title = ("ACTION NEEDED IN THE BROWSER (DO)" if handoff.kind == "DO"
             else "DECISION NEEDED IN THE TERMINAL (DECIDE)")
    out = ["=" * WIDTH, f"  {title} · run {run.id}", "=" * WIDTH]
    out += _wrap("1. Done so far:  ", progress(run))
    out += _wrap("2. Blocking:     ", handoff.reason)
    for ev in handoff.evidence[:4]:
        where = f" ({ev.url})" if ev.url else ""
        out += _wrap("   Evidence:     ", f"[{ev.kind}] {ev.text}{where}")
    out += _wrap("3. What to do:   ", f"{handoff.person_instruction} Where: {handoff.where}.")
    if handoff.kind == "DECIDE":
        for i, opt in enumerate(handoff.options, 1):
            out += _wrap(f"   Option {i}:     ", opt)
    out += _wrap("4. Then I will:  ", handoff.expected_resume_action)
    resume = ("Press Enter here when you are done." if handoff.kind == "DO"
              else "Type the option number here.")
    later = (f"If you closed this terminal, run: credagent resume {run.id}" if RESUME_AVAILABLE else
             f"If you close this terminal, the run is saved as {run.id} (the resume command arrives in Sprint 5).")
    out += _wrap("5. To resume:    ", f"{resume} {later}")
    donts = handoff.what_not_to_do or DEFAULT_DONT[handoff.kind]
    for i, d in enumerate(donts):
        out += _wrap("6. Do not:       " if i == 0 else "                 ", d)
    out.append("=" * WIDTH)
    return m.mask_text("\n".join(out))
