"""Structured-output contracts for the two research LLM calls.

Each contract is a strict JSON schema sent to the model (all fields required,
no extra properties; nullable via ["string","null"]) and a pydantic model that
re-validates the answer in code. Length limits are enforced in code, not in
the schema (provider strict modes vary in minItems/maxItems support).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

CRED_KINDS = ["oauth_client", "api_key", "token", "sandbox_key", "other"]
STEP_KINDS = ["navigate", "fill", "click", "capture", "verify", "handoff", "check"]
BLOCKER_KINDS = ["sign_in", "account_creation", "verification_code", "two_factor", "captcha",
                 "identity_verification", "business_verification", "payment", "terms",
                 "provider_review", "paid_plan", "partner_approval", "other"]
OUTCOMES = ["succeeded", "partial", "blocked", "waiting_on_provider", "unknown"]

STR = {"type": "string"}
NSTR = {"type": ["string", "null"]}
BOOL = {"type": "boolean"}


def obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props),
            "properties": props}


def arr(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def enum(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": values}


# ------------------------------------------------------------------ triage

TRIAGE_SCHEMA = obj({
    "app_identified": BOOL,
    "identification_confidence": enum(["high", "medium", "low", "none"]),
    "ambiguous": BOOL,
    "canonical_name": NSTR,
    "provider": NSTR,
    "candidates": arr(obj({"name": STR, "provider": STR, "homepage_url": NSTR})),
    "official_domains": arr(STR),
    "urls_to_read": arr(STR),
    "follow_up_queries": arr(STR),
    "notes": STR,
})


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Candidate(_M):
    name: str
    provider: str
    homepage_url: str | None


class Triage(_M):
    app_identified: bool
    identification_confidence: Literal["high", "medium", "low", "none"]
    ambiguous: bool
    canonical_name: str | None
    provider: str | None
    candidates: list[Candidate]
    official_domains: list[str]
    urls_to_read: list[str]
    follow_up_queries: list[str]
    notes: str

    @field_validator("official_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        out = []
        for d in v:
            d = d.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
            d = d.removeprefix("www.")
            if d and "." in d and d not in out:
                out.append(d)
        return out[:8]


# --------------------------------------------------------------- synthesis

FINDINGS_SCHEMA = obj({
    "credential_options": arr(obj({"kind": enum(CRED_KINDS), "description": STR, "best_for": STR,
                                   "source_url": NSTR})),
    "chosen_credential_kind": enum([*CRED_KINDS, "unknown"]),
    "choice_reason": STR,
    "console_url": NSTR,
    "console_url_source": NSTR,
    "sign_in_domains": arr(STR),
    "setup_steps": arr(obj({"description": STR, "kind": enum(STEP_KINDS), "source_url": NSTR})),
    "needs_redirect_uri": enum(["yes", "no", "unknown"]),
    "scopes_or_permissions": arr(obj({"name": STR, "why": STR, "source_url": NSTR})),
    "likely_blockers": arr(obj({"kind": enum(BLOCKER_KINDS), "description": STR,
                                "basis": enum(["sourced", "inferred"]), "source_url": NSTR, "quote": NSTR})),
    "oauth_metadata": obj({"metadata_url": NSTR,
                           "dynamic_registration": enum(["documented_open", "documented_restricted",
                                                         "not_documented", "unknown"]),
                           "source_url": NSTR, "quote": NSTR}),
    "verification": obj({"method": STR, "endpoint": NSTR, "what_passing_proves": STR,
                         "label_if_passes": enum(["verified", "client_recognized"]),
                         "source_url": NSTR}),
    "predicted_outcome": enum(OUTCOMES),
    "prediction_reason": STR,
    "facts": arr(obj({"statement": STR, "kind": enum(["sourced", "inferred", "unknown"]),
                      "source_url": NSTR, "quote": NSTR})),
    "unknowns": arr(STR),
})


class CredOption(_M):
    kind: Literal["oauth_client", "api_key", "token", "sandbox_key", "other"]
    description: str
    best_for: str
    source_url: str | None


class SetupStep(_M):
    description: str
    kind: Literal["navigate", "fill", "click", "capture", "verify", "handoff", "check"]
    source_url: str | None


class Scope(_M):
    name: str
    why: str
    source_url: str | None


class LikelyBlocker(_M):
    kind: Literal["sign_in", "account_creation", "verification_code", "two_factor", "captcha",
                  "identity_verification", "business_verification", "payment", "terms",
                  "provider_review", "paid_plan", "partner_approval", "other"]
    description: str
    basis: Literal["sourced", "inferred"]
    source_url: str | None
    quote: str | None


class OAuthMeta(_M):
    metadata_url: str | None
    dynamic_registration: Literal["documented_open", "documented_restricted", "not_documented", "unknown"]
    source_url: str | None
    quote: str | None


class Verification(_M):
    method: str
    endpoint: str | None
    what_passing_proves: str
    label_if_passes: Literal["verified", "client_recognized"]
    source_url: str | None


class FindingFact(_M):
    statement: str
    kind: Literal["sourced", "inferred", "unknown"]
    source_url: str | None
    quote: str | None


class Findings(_M):
    credential_options: list[CredOption]
    chosen_credential_kind: Literal["oauth_client", "api_key", "token", "sandbox_key", "other", "unknown"]
    choice_reason: str
    console_url: str | None
    console_url_source: str | None
    sign_in_domains: list[str]
    setup_steps: list[SetupStep]
    needs_redirect_uri: Literal["yes", "no", "unknown"]
    scopes_or_permissions: list[Scope]
    likely_blockers: list[LikelyBlocker]
    oauth_metadata: OAuthMeta
    verification: Verification
    predicted_outcome: Literal["succeeded", "partial", "blocked", "waiting_on_provider", "unknown"]
    prediction_reason: str
    facts: list[FindingFact]
    unknowns: list[str]
