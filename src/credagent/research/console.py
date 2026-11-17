"""The developer console address, when research could not find it (D-092).

A plan with no console URL cannot start: the browser has nowhere to go. Instead of failing silently, the person is
asked for the address. It is accepted only if it is a plain https address with a domain name, and its host is added
to the allowed domains (the owner's own statement of where the console is, recorded in the plan's notes).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from credagent.research.agent import on_domain
from credagent.state.models import Plan


def accept_console_url(plan: Plan, raw: object) -> tuple[Plan | None, str]:
    """(the updated plan, "") or (None, why the address was refused, in words for the person)."""
    url = str(raw or "").strip()
    if not url:
        return None, "Paste the address of the provider's developer console."
    if len(url) > 300 or re.search(r"\s", url):
        return None, "That does not look like a single web address."
    p = urlparse(url)
    if p.scheme != "https" or not p.hostname:
        return None, "Use the full address, starting with https://"
    if p.username or p.password:
        return None, "The address must not contain a user name or password."
    host = p.hostname.lower().removeprefix("www.")
    if "." not in host or re.fullmatch(r"[\d.]+", host):
        return None, "Use the console's web address (a domain name), not an IP number."
    allowed = list(plan.allowed_domains)
    if not on_domain(host, allowed):
        allowed.append(host)
    note = f"Console address given by the owner: {host}{p.path[:60]}. Its host is allowed for this run."
    return plan.model_copy(update={"console_url": url, "allowed_domains": allowed,
                                   "validation_notes": [*plan.validation_notes, note]}), ""
