"""RFC 7591 dynamic client registration (the browser-free shortcut).

Secrets in the response are registered with the Masker and written to the owner-only
secret store immediately; only references and masked displays leave this function.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from credagent.secrets.masking import Masker, masked_display
from credagent.secrets.store import SecretFileStore
from credagent.state.models import CredentialPart, CredentialReference

SECRET_FIELDS = ("client_secret", "registration_access_token")


@dataclass
class DcrOutcome:
    ok: bool
    observed: str
    credential: CredentialReference | None = None
    needs_initial_access_token: bool = False


def register(
    endpoint: str,
    http: httpx.Client,
    store: SecretFileStore,
    masker: Masker,
    run_id: str,
    *,
    client_name: str,
    redirect_uri: str,
) -> DcrOutcome:
    body = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "client_credentials"],
        "token_endpoint_auth_method": "client_secret_basic",
    }
    try:
        r = http.post(endpoint, json=body, timeout=20)
    except httpx.HTTPError as exc:
        return DcrOutcome(False, f"registration request failed: {type(exc).__name__}")
    if r.status_code in (401, 403):
        return DcrOutcome(
            False,
            f"HTTP {r.status_code}: registration requires authorization (an initial access token); not open",
            needs_initial_access_token=True,
        )
    if r.status_code not in (200, 201):
        return DcrOutcome(False, f"HTTP {r.status_code}: {masker.mask_text(r.text[:200])}")
    try:
        data: dict[str, Any] = r.json()
    except ValueError:
        return DcrOutcome(False, "registration response was not JSON")
    cid = data.get("client_id")
    if not isinstance(cid, str) or not cid:
        return DcrOutcome(False, "registration response had no client_id")
    parts: dict[str, CredentialPart] = {}
    for name in ("client_id", *SECRET_FIELDS):
        value = data.get(name)
        if isinstance(value, str) and value:
            if name in SECRET_FIELDS:
                masker.register(value, label=name)
            ref = store.put(run_id, name, value)
            parts[name] = CredentialPart(store_ref=ref, masked_display=masked_display(value))
    data = {}  # drop raw values
    kind = "oauth_client"
    has_secret = "client_secret" in parts
    return DcrOutcome(
        True,
        f"HTTP {r.status_code}: client registered "
        f"({'client ID + secret' if has_secret else 'client ID only (public client)'})",
        CredentialReference(kind=kind, parts=parts),
    )
