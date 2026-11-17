"""Run domain model (engineering spec §5) with code-enforced invariants.

Invariants enforced here (not by convention):
* `succeeded` requires a captured credential whose live test is `verified`
  with no production limitations (PRD §10).
* Status transitions follow TRANSITIONS; terminal outcomes are final unless the
  outcome is resumable and the transition is an explicit resume.
* At most one pending handoff at a time.
* No raw secret is stored: credentials are references plus masked displays.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RunStatus = Literal[
    "running", "succeeded", "partial", "blocked", "waiting_on_provider", "failed", "cancelled"
]
OUTCOMES: tuple[str, ...] = (
    "succeeded", "partial", "blocked", "waiting_on_provider", "failed", "cancelled"
)
CredentialVerification = Literal["verified", "client_recognized", "inconclusive", "invalid", "untested"]
CredentialKind = Literal["oauth_client", "api_key", "token", "sandbox_key", "other"]
Actor = Literal["agent", "person", "system"]
FactKind = Literal["sourced", "observed", "inferred", "unknown"]
BlockerKind = Literal[
    "sign_in", "account_creation", "verification_code", "two_factor", "captcha",
    "identity_verification", "business_verification", "payment", "terms", "cookie_consent",
    "provider_review", "paid_plan", "partner_approval", "policy_denied", "off_allow_list",
    "unexpected", "service_unavailable", "budget_exhausted", "replan_limit", "app_not_identified",
    "secret_hidden", "other",  # replan_limit is only found in runs saved before D-078
]
LEGACY_RUN_FIELDS = ("replans_used", "plan_cursor", "loop", "proofs", "bindings")
RunPhase = Literal["created", "research", "planned", "browser", "verifying", "done"]

# Which statuses may follow which. Resume re-enters "running" from resumable outcomes.
TRANSITIONS: dict[str, set[str]] = {
    "running": set(OUTCOMES),
    "blocked": {"running", "cancelled"},
    "waiting_on_provider": {"running", "cancelled"},
    "failed": {"running", "cancelled"},       # only when Run.resumable is True
    "partial": {"running", "succeeded", "failed"},  # e.g. re-verify after provider review
    "succeeded": {"partial", "failed"},     # only via `credagent verify` re-running the live test
    "cancelled": set(),
}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(3)}"


def new_run_id(app: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", app.lower()).strip("-")[:20] or "app"
    return f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{slug}-{secrets.token_hex(2)}"


class InvariantError(ValueError):
    """A state change that would break a run invariant (always a bug or a policy denial)."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Fact(Strict):
    statement: str
    kind: FactKind
    source_url: str | None = None
    quote: str | None = None  # verbatim excerpt, checked by code against the text the model saw

    @model_validator(mode="after")
    def _sourced_needs_url(self) -> Fact:
        if self.kind == "sourced" and not self.source_url:
            raise ValueError("a sourced fact needs a source_url")
        return self


class PlanStep(BaseModel):
    """A step of the research plan. Guidance for the agent, not a script (D-078). Runs saved before D-078 carry extra
    fields (conditions, targets); they are ignored when loading."""

    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    id: str
    description: str  # the step's intent, shown to the agent and to the person
    kind: Literal["navigate", "fill", "click", "capture", "verify", "handoff", "check"]
    expected_page: str | None = None


class Source(Strict):
    url: str
    title: str = ""
    via: Literal["search", "extract"]
    query: str | None = None
    # How much of this source the model actually saw:
    #   snippet  = search-result excerpt only (page never opened)
    #   full     = the whole extracted page text
    #   sections = a long page cut down to the sections most relevant to credentials
    depth: Literal["snippet", "full", "sections"] = "snippet"
    chars_total: int | None = None
    chars_seen: int | None = None
    sections_kept: int | None = None
    sections_total: int | None = None

    def depth_label(self) -> str:
        if self.depth == "snippet":
            return (f"snippet only: {self.chars_seen:,} of {self.chars_total:,} chars of the search excerpt; "
                    "page not opened") if self.chars_total else "snippet only; page not opened"
        if self.depth == "full":
            return f"read in full ({self.chars_total:,} chars)"
        return (f"read {self.chars_seen:,} of {self.chars_total:,} chars: {self.sections_kept} of "
                f"{self.sections_total} sections, chosen for relevance to credentials")


class Identification(Strict):
    canonical_name: str | None = None
    provider: str | None = None
    confidence: Literal["high", "medium", "low", "none"] = "none"
    official_domains: list[str] = Field(default_factory=list)


class Plan(Strict):
    identification: Identification = Field(default_factory=Identification)
    credential_kind: CredentialKind | Literal["unknown"] = "unknown"
    console_url: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list, max_length=40)
    predicted_outcome: Literal[
        "succeeded", "partial", "blocked", "waiting_on_provider", "failed", "unknown"
    ] = "unknown"
    expected_blockers: list[str] = Field(default_factory=list)
    verification_procedure: str = ""
    facts: list[Fact] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)  # other credential types research found
    sources: list[Source] = Field(default_factory=list)
    needs_redirect_uri: Literal["yes", "no", "unknown"] = "unknown"
    scopes: list[str] = Field(default_factory=list)
    dynamic_registration: Literal[
        "documented_open", "documented_restricted", "not_documented", "unknown"] = "unknown"
    metadata_url: str | None = None
    token_endpoint: str | None = None  # from sourced research; used by the live test if no metadata is found
    validation_notes: list[str] = Field(default_factory=list)  # what code corrected in the model's plan
    domains_inferred: list[str] = Field(default_factory=list)  # allowed domains derived from names (not the model's)


class Evidence(Strict):
    kind: Literal["observed", "inferred"]
    text: str
    url: str | None = None


class StepRecord(Strict):
    id: str = Field(default_factory=lambda: new_id("s-"))
    plan_step_id: str | None = None
    action: str
    actor: Actor
    at: str = Field(default_factory=now)
    outcome: Literal["done", "failed", "skipped", "denied", "handed_off", "in_doubt"]
    evidence: list[Evidence] = Field(default_factory=list)
    checkpoint_seq: int | None = None


class Handoff(Strict):
    id: str = Field(default_factory=lambda: new_id("h-"))
    kind: Literal["DO", "DECIDE"]
    reason: str
    blocker_kind: BlockerKind = "unexpected"
    evidence: list[Evidence] = Field(default_factory=list)
    completed_so_far: str
    person_instruction: str
    where: str
    expected_resume_action: str
    what_not_to_do: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)  # DECIDE only
    answer: str | None = None
    created_at: str = Field(default_factory=now)
    status: Literal["pending", "completed", "cancelled"] = "pending"
    resolved_at: str | None = None

    @model_validator(mode="after")
    def _decide_has_options(self) -> Handoff:
        if self.kind == "DECIDE" and len(self.options) < 2:
            raise ValueError("a DECIDE handoff needs at least two options")
        if self.kind == "DO" and self.options:
            raise ValueError("a DO handoff has no terminal options; the person acts in the browser")
        if self.answer is not None and self.answer not in self.options:
            raise ValueError("answer must be one of the options")
        return self


class Blocker(Strict):
    id: str = Field(default_factory=lambda: new_id("b-"))
    kind: BlockerKind
    description: str
    evidence: list[Evidence] = Field(default_factory=list)
    who_must_act: Literal["person", "provider", "owner", "agent"]
    next_steps: list[str] = Field(default_factory=list)
    at: str = Field(default_factory=now)


class CredentialPart(Strict):
    store_ref: str = Field(pattern=r"^file:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    masked_display: str


class CredentialReference(Strict):
    """Pointer to stored secret material. Never holds a raw value."""

    kind: CredentialKind
    parts: dict[str, CredentialPart]  # e.g. {"client_id": ..., "client_secret": ...}
    captured_at: str = Field(default_factory=now)


class VerificationResult(Strict):
    label: CredentialVerification
    tested_at: str | None = None
    test_description: str
    observed_result: str
    production_limitations: list[str] = Field(default_factory=list)


class Consent(Strict):
    """ATTEMPT-PROTOCOL §2.6: what the owner agreed to for this provider in this session (no passwords)."""

    provider: str
    account: str  # the owner's own description, e.g. "my test Spotify account (Premium)"
    given_at: str = Field(default_factory=now)
    scope: str
    terms_finding: Literal["prohibited", "unclear", "not_prohibited", "unchecked"]
    terms_record: str = ""


class BrowserSession(Strict):
    chrome_pid: int | None = None
    cdp_port: int | None = None
    profile_dir: str
    last_url: str | None = None


class Run(Strict):
    id: str
    app_input: str
    app_name: str | None = None
    provider: str | None = None
    created_at: str = Field(default_factory=now)
    updated_at: str = Field(default_factory=now)
    status: RunStatus = "running"
    phase: RunPhase = "created"
    status_reason: str | None = None
    resumable: bool = True
    current_step_id: str | None = None
    plan: Plan = Field(default_factory=Plan)
    steps: list[StepRecord] = Field(default_factory=list)
    handoffs: list[Handoff] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    credential: CredentialReference | None = None
    verification: VerificationResult | None = None
    predicted_outcome: str | None = None
    actual_outcome: str | None = None
    untested: list[str] = Field(default_factory=list)
    browser: BrowserSession | None = None
    metadata_check: dict | None = None  # observed OAuth metadata / DCR eligibility (no secrets)
    observed_limitations: list[str] = Field(default_factory=list)  # seen on the credential page (no secrets)
    consent: list[Consent] = Field(default_factory=list)  # one per session in which a real provider was run
    created: list[str] = Field(default_factory=list)  # what this run created at the provider (cleanup; D-063)
    checkpoint_seq: int = 0

    @model_validator(mode="before")
    @classmethod
    def _drop_pre_d078_fields(cls, data: object) -> object:
        """Runs saved by the earlier step-machine loop stay readable: its bookkeeping fields are dropped."""
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k not in LEGACY_RUN_FIELDS}
            if isinstance(data.get("plan"), dict):
                data["plan"] = {k: v for k, v in data["plan"].items() if k != "revision"}
        return data

    @model_validator(mode="after")
    def _invariants(self) -> Run:
        if self.status == "succeeded":
            if self.credential is None:
                raise ValueError("succeeded requires a captured credential")
            v = self.verification
            if v is None or v.label != "verified":
                raise ValueError("succeeded requires a verified live test (PRD §10)")
            if v.production_limitations:
                raise ValueError("a verified credential with production limitations is partial")
        if sum(h.status == "pending" for h in self.handoffs) > 1:
            raise ValueError("at most one pending handoff")
        return self

    # ----------------------------------------------------------- queries

    @property
    def pending_handoff(self) -> Handoff | None:
        return next((h for h in self.handoffs if h.status == "pending"), None)

    @property
    def is_terminal(self) -> bool:
        return self.status != "running"

    def counts(self) -> dict[str, int]:
        return {a: sum(s.actor == a for s in self.steps) for a in ("agent", "person", "system")}

    # ---------------------------------------------------------- mutations

    def _touch(self) -> None:
        self.updated_at = now()

    def _require_running(self, what: str) -> None:
        if self.status != "running":
            raise InvariantError(f"cannot {what}: run is {self.status}")

    def add_step(self, step: StepRecord) -> StepRecord:
        self._require_running("add a step")
        self.steps.append(step)
        self.current_step_id = step.id
        self._touch()
        return step

    def open_handoff(self, handoff: Handoff) -> Handoff:
        self._require_running("open a handoff")
        if self.pending_handoff is not None:
            raise InvariantError("a handoff is already pending")
        self.handoffs.append(handoff)
        self._touch()
        return handoff

    def resolve_handoff(self, handoff_id: str, *, answer: str | None = None,
                        cancelled: bool = False) -> Handoff:
        h = next((x for x in self.handoffs if x.id == handoff_id), None)
        if h is None or h.status != "pending":
            raise InvariantError("no such pending handoff")
        if h.kind == "DECIDE" and not cancelled:
            if answer not in h.options:
                raise InvariantError("DECIDE answer must be one of the offered options")
            h.answer = answer
        h.status = "cancelled" if cancelled else "completed"
        h.resolved_at = now()
        self._touch()
        return h

    def add_blocker(self, blocker: Blocker) -> Blocker:
        self.blockers.append(blocker)
        self._touch()
        return blocker

    def transition(self, status: str, reason: str | None = None, *, resumable: bool | None = None,
                   resume: bool = False) -> None:
        allowed = TRANSITIONS[self.status]
        if status not in allowed:
            raise InvariantError(f"invalid transition {self.status} → {status}")
        if status == "running":
            if not resume:
                raise InvariantError("re-entering running is only allowed via resume")
            if self.status == "failed" and not self.resumable:
                raise InvariantError("this failed run is not resumable")
        # Validate the target state as a whole before committing (e.g. succeeded rules).
        candidate = self.model_copy(update={"status": status})
        Run.model_validate(candidate.model_dump())
        self.status = status
        self.status_reason = reason
        if resumable is not None:
            self.resumable = resumable
        if status in OUTCOMES:
            self.actual_outcome = status
        self._touch()


def decide_outcome(
    *,
    credential_captured: bool,
    verification: VerificationResult | None,
    provider_review_pending: bool = False,
    blocker: Blocker | None = None,
    error: str | None = None,
    cancelled: bool = False,
) -> tuple[str, str]:
    """Map what happened to a PRD §10 outcome. Returns (outcome, reason).

    Only a verified credential without production limitations is `succeeded`.
    """
    if cancelled:
        return "cancelled", "cancelled by the person"
    if credential_captured:
        label = verification.label if verification else "untested"
        if label == "verified":
            if verification and verification.production_limitations:
                return "partial", "verified, but limited: " + "; ".join(
                    verification.production_limitations)
            return "succeeded", "credential captured and live test passed"
        if label == "invalid":
            return "failed", "credential captured but the provider rejected it in the live test"
        if provider_review_pending:
            return "waiting_on_provider", f"credential {label}; provider review pending"
        return "partial", f"credential captured but not verified ({label})"
    if provider_review_pending:
        return "waiting_on_provider", "provider review/approval is pending"
    if blocker is not None:
        return "blocked", blocker.description
    if error is not None:
        return "failed", error
    return "failed", "run ended without a credential and without a recorded blocker"
