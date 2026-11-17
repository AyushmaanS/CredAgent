"""Live credential verification (spec §6.10). Code only; secrets never leave this module.

A credential counts as working only if a live test passes. Labels:
  verified           the credential-specific live test passed
  client_recognized  the provider accepted the client authentication, but issued no token
  inconclusive       a test ran but did not establish validity
  invalid            the provider rejected the credential
  untested           no live test was run (the reason says why)

Built-in test (generic, needs no provider-specific code):
  OAuth client with a secret + a token endpoint observed in the provider's public OAuth metadata
  → RFC 6749 §4.4 client-credentials token request with the client ID and secret.
  An issued access token proves the pair is live; the token is registered with the Masker and dropped.
If the provider publishes no OAuth metadata, the token endpoint that research established from a
retrieved source (never an inferred one) is used, still only on the allowed domains over HTTPS.
Anything else is `untested` with the reason (e.g. API keys, or the authorization-code flow a person approves).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from credagent.policy.hard_checks import host_allowed
from credagent.secrets.masking import Masker
from credagent.secrets.store import SecretFileStore, SecretStoreError
from credagent.state.models import Run, VerificationResult, now

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def _result(label: str, test: str, observed: str, limitations: list[str] | None = None,
            tested: bool = True) -> VerificationResult:
    return VerificationResult(label=label, tested_at=now() if tested else None, test_description=test,  # type: ignore[arg-type]
                              observed_result=observed, production_limitations=limitations or [])


def _endpoint_ok(url: str, allowed: list[str]) -> bool:
    p = urlparse(url)
    secure = p.scheme == "https" or (p.scheme == "http" and (p.hostname or "") in LOOPBACK)
    return secure and host_allowed(url, allowed)


def researched_token_endpoint(run: Run) -> str | None:
    """The token endpoint research established from a retrieved source (never an inferred one)."""
    if run.plan.token_endpoint:
        return run.plan.token_endpoint
    vp = run.plan.verification_procedure  # plans written before the field existed
    if "[inferred]" in vp or "— endpoint " not in vp:
        return None
    ep = vp.split("— endpoint ", 1)[1].split()[0].rstrip(".,;)")
    return ep if ep.startswith("https://") and "token" in ep.lower() else None


_SCOPE_RE = re.compile(r"\bscope[s]?\s*[(:]?\s*['\"`]([A-Za-z0-9_.:\- ]{1,80})['\"`]", re.I)
# The form-body wording: "scope=identify" or "scope=identify+connections" / "identify%20connections" (D-088).
_SCOPE_FORM_RE = re.compile(r"\bscope=([A-Za-z0-9_.:\-+%]{1,80})", re.I)


def researched_scope(run: Run) -> str | None:
    """A least-privilege scope the sourced verification procedure names (e.g. Discord needs scope 'identify')."""
    vp = run.plan.verification_procedure
    if "[inferred]" in vp:
        return None
    m = _SCOPE_RE.search(vp)
    if m:
        return m.group(1).strip()
    m = _SCOPE_FORM_RE.search(vp)
    return m.group(1).replace("%20", " ").replace("+", " ").strip() if m else None


def verify_run(run: Run, store: SecretFileStore, masker: Masker, http: httpx.Client) -> VerificationResult:
    cred = run.credential
    if cred is None:
        return _result("untested", "none", "No credential was captured, so there is nothing to test.", tested=False)
    limits = list(run.observed_limitations)
    if cred.kind != "oauth_client":
        return _result("untested", "none",
                       f"No built-in live test for a {cred.kind.replace('_', ' ')} yet; a provider-specific test is "
                       "needed (Sprint 6). The credential is stored but not proven to work.", tested=False)
    if "client_id" not in cred.parts:
        return _result("untested", "none", "The client ID was not captured, so no test can be run.", tested=False)
    if "client_secret" not in cred.parts:
        return _result("untested", "none",
                       "Public client (no client secret): proving it works needs the authorization-code flow, "
                       "which a person approves in the browser. Not built yet (Sprint 6).", tested=False)
    meta = (run.metadata_check or {}).get("metadata") or {}
    token_ep = meta.get("token_endpoint")
    grants = meta.get("grant_types_supported")
    where = "from the provider's OAuth metadata"
    if not isinstance(token_ep, str) or not token_ep:
        token_ep, where = researched_token_endpoint(run), "from sourced research (no OAuth metadata was found)"
    test = f"OAuth client-credentials token request (RFC 6749 §4.4) at {token_ep} ({where})"
    if not token_ep:
        return _result("untested", "none",
                       "No token endpoint was observed in the provider's OAuth metadata or established by sourced "
                       "research; a provider-specific test is needed.", tested=False)
    if not _endpoint_ok(token_ep, run.plan.allowed_domains):
        return _result("untested", test, "The token endpoint is not on the allowed domains (or not HTTPS); the "
                       "secret was not sent.", tested=False)
    if isinstance(grants, list) and "client_credentials" not in grants:
        return _result("untested", "none",
                       "The provider's metadata does not list the client-credentials grant; proving this client "
                       "works needs the authorization-code flow (Sprint 6).", tested=False)
    try:
        cid = store.get(cred.parts["client_id"].store_ref)
        sec = store.get(cred.parts["client_secret"].store_ref)
    except SecretStoreError as exc:
        return _result("untested", test, f"The stored credential could not be read safely: {exc}", tested=False)
    masker.register(sec, label="client_secret")
    methods = meta.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    data = {"grant_type": "client_credentials"}
    scope = researched_scope(run)
    if scope:
        data["scope"] = scope
    kw: dict[str, Any] = {"timeout": 20}
    if "client_secret_basic" in methods:
        kw["auth"] = (cid, sec)
    else:
        data |= {"client_id": cid, "client_secret": sec}
    try:
        r = http.post(token_ep, data=data, **kw)
    except httpx.HTTPError as exc:
        return _result("untested", test, f"Could not reach the token endpoint ({type(exc).__name__}); no result.",
                       tested=False)
    finally:
        cid = sec = ""
        data.clear()
        kw.clear()
    try:
        body: dict[str, Any] = r.json() if r.content else {}
    except ValueError:
        body = {}
    token = body.get("access_token") if isinstance(body, dict) else None
    if isinstance(token, str) and len(token) >= 6:
        masker.register(token, label="access_token")  # never stored, never shown
        body.clear()
        detail = f"HTTP {r.status_code}: the provider issued an access token for this client ID and secret"
        return _result("verified", test, masker.mask_text(detail), limits)
    err = str(body.get("error") or "") if isinstance(body, dict) else ""
    status = f"HTTP {r.status_code}" + (f" ({err})" if err else "")
    if r.status_code == 401 or err == "invalid_client":
        return _result("invalid", test, f"{status}: the provider rejected the client ID/secret.", limits)
    if err == "unauthorized_client":
        return _result("client_recognized", test,
                       f"{status}: the provider authenticated the client but will not issue a token with this "
                       "grant. The credential is not proven to work for the integration.", limits)
    if r.status_code >= 500:
        return _result("inconclusive", test, f"{status}: provider error; the test did not establish validity.",
                       limits)
    return _result("inconclusive", test,
                   masker.mask_text(f"{status}: no token was issued; the test did not establish validity."), limits)
