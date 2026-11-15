"""Public OAuth authorization-server metadata discovery (RFC 8414 / OpenID Connect Discovery)
and dynamic-client-registration eligibility (PRD F3, spec §6.3).

Rules (code-owned):
* Only GET the standard well-known paths (plus a metadata URL the plan cites), only on the
  plan's allowed domains, only over HTTPS (HTTP allowed for loopback test sites), at most
  `max_requests` requests. Every request and result is recorded as *observed*.
* Metadata existing does not imply DCR. Eligible only if the metadata advertises a
  registration_endpoint on an allowed domain AND research documented open registration
  with a quote-verified source (plan.dynamic_registration == "documented_open").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from credagent.research.agent import host_of, on_domain
from credagent.state.models import Plan

WELL_KNOWN = ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration")
KEEP = (
    "issuer",
    "authorization_endpoint",
    "token_endpoint",
    "registration_endpoint",
    "grant_types_supported",
    "token_endpoint_auth_methods_supported",
    "scopes_supported",
)
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


@dataclass
class MetadataResult:
    checked: list[dict[str, Any]] = field(default_factory=list)
    metadata_url: str | None = None
    metadata: dict[str, Any] | None = None
    registration_endpoint: str | None = None
    dcr_eligible: bool = False
    reason: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "metadata_url": self.metadata_url,
            "metadata": self.metadata,
            "registration_endpoint": self.registration_endpoint,
            "dcr_eligible": self.dcr_eligible,
            "reason": self.reason,
        }


def _scheme_ok(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" or (p.scheme == "http" and (p.hostname or "") in LOOPBACK)


def candidate_urls(plan: Plan, base_urls: list[str] | None = None, max_n: int = 6) -> list[str]:
    allowed = plan.allowed_domains
    out: list[str] = []

    def add(u: str | None) -> None:
        if (
            u
            and u not in out
            and _scheme_ok(u)
            and (on_domain(host_of(u), allowed) or (urlparse(u).hostname or "") in LOOPBACK)
        ):
            out.append(u)

    add(plan.metadata_url)
    bases = list(base_urls or [])
    if plan.console_url:
        p = urlparse(plan.console_url)
        bases.append(f"{p.scheme}://{p.netloc}")
    bases += [f"https://{d}" for d in allowed]
    for b in bases:
        for w in WELL_KNOWN:
            add(b.rstrip("/") + w)
    return out[:max_n]


def discover(
    plan: Plan, http: httpx.Client, *, base_urls: list[str] | None = None, max_requests: int = 6
) -> MetadataResult:
    res = MetadataResult()
    allowed = plan.allowed_domains
    for url in candidate_urls(plan, base_urls, max_requests):
        try:
            r = http.get(url, timeout=10, follow_redirects=False, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            res.checked.append({"url": url, "error": type(exc).__name__})
            continue
        entry: dict[str, Any] = {"url": url, "status": r.status_code}
        res.checked.append(entry)
        if r.status_code != 200:
            continue
        try:
            data = r.json()
        except ValueError:
            entry["note"] = "not JSON"
            continue
        if not isinstance(data, dict) or not (data.get("issuer") or data.get("token_endpoint")):
            entry["note"] = "JSON but not authorization-server metadata"
            continue
        res.metadata_url = url
        res.metadata = {k: data[k] for k in KEEP if k in data}
        break

    if res.metadata is None:
        res.reason = "No public OAuth authorization-server metadata found at the checked URLs."
        return res
    reg = res.metadata.get("registration_endpoint")
    if not reg:
        res.reason = "Metadata found; it does not advertise a registration_endpoint (no dynamic registration)."
        return res
    if not (_scheme_ok(reg) and (on_domain(host_of(reg), allowed) or (urlparse(reg).hostname or "") in LOOPBACK)):
        res.reason = f"registration_endpoint {reg} is not on an allowed domain; not used."
        return res
    res.registration_endpoint = reg
    if plan.dynamic_registration != "documented_open":
        res.reason = (
            "Metadata advertises a registration_endpoint, but research did not establish (with a "
            "verified quote) that registration is open to the public; not used."
        )
        return res
    res.dcr_eligible = True
    res.reason = "registration_endpoint advertised and open registration documented by research."
    return res
