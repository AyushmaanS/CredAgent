"""Code-assigned risk for a proposed action (D-081). Replaces Jev's risk answer.

The policy engine decides allow / DO / DECIDE / deny; for a button click it needs a risk. The old rule assumed
"hard to undo" whenever Jev was unsure, which produced the repeated "New Application?" questions. Now code assigns
it from what the control is, with the owner's rule (2026-11-17):

  * the hard stops come first and are unchanged (delete, review, payment, verification, account security, terms,
    off-site, one app per run): `evaluate` handles them before it ever looks at risk;
  * creating a project or workspace the provider needs first is asked (the person says yes); it is not the app;
  * creating the ONE planned app is already consented (the consent screen says "Will create one app …"), so
    the first create click is not asked again; a second one is denied by the policy;
  * a button whose name carries a consequence verb asks the person; any other button goes ahead and is logged.
    This lets through a button not on the list; the hard stops are the backstop.
"""

from __future__ import annotations

import re

from credagent.policy.engine import CREATE_RE, ProposedAction

CONSEQUENCE_RE = re.compile(
    r"\b(reset|regenerate|rotate|generate (a )?new|transfer|publish|make (it )?public|go public|confirm|"
    r"disable|enable|disconnect|leave|archive|convert|migrate|merge|overwrite|replace|ban|kick|erase|wipe|"
    r"clear all)\b|\b(add|create|generate|issue)\b( a| another| new)* (client )?secrets?\b",
    re.I,
)


def assess_risk(action: ProposedAction, *, already_created: bool = False, setup: bool = False) -> str:
    """read_only | reversible | hard_to_undo | irreversible (`evaluate` turns the last two into a DECIDE)."""
    label = action.description or ""
    if action.method == "navigate":
        return "read_only"
    if action.method in ("fill", "select", "check"):
        return "reversible"
    if action.href and not label.startswith("button"):
        return "read_only"  # following a link
    if setup and CREATE_RE.search(label):
        return "hard_to_undo"  # a project or workspace the provider needs first: the person says yes (D-094)
    if CREATE_RE.search(label) and not already_created:
        return "reversible"  # the one consented create (a second one is denied before risk is read)
    if CONSEQUENCE_RE.search(label):
        return "hard_to_undo"
    return "reversible"
