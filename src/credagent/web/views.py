"""Run state → what the UI shows (D-089). Pure functions: no I/O, no model calls, and never a secret.

The input is what the backend already records (`Run` and its events) plus a small summary of the live controller
(or None). Every field in the output is derived from those facts; nothing is invented. Credentials appear only as
the masked displays the run already holds.
"""

from __future__ import annotations

import re
from typing import Any

from credagent.orchestrator import FAKE_PROVIDER_NAME
from credagent.state.models import Handoff, Run

CRED_LABELS = {"oauth_client": "OAuth client", "api_key": "API key", "token": "Access token",
               "sandbox_key": "Sandbox key", "other": "Credential", "unknown": "Credential"}
PART_LABELS = {"client_id": "Client ID", "client_secret": "Client secret", "api_key": "API key", "token": "Token",
               "signing_secret": "Signing secret", "registration_access_token": "Registration token"}
VERIFICATION_TEXT = {
    "verified": "Verified: the provider accepted this credential in a live test.",
    "client_recognized": "Partly verified: the provider recognised the client but issued no token.",
    "inconclusive": "Not verified: the live test ran but did not prove the credential works.",
    "invalid": "Rejected: the provider refused this credential in the live test.",
    "untested": "Not tested: no live test has been run for this credential.",
}
HANDOFF_TITLES = {
    "sign_in": "Sign in to continue", "account_creation": "Create or sign in to an account",
    "verification_code": "Enter a verification code", "two_factor": "Complete the second factor",
    "captcha": "Complete the human check", "terms": "Review and accept the provider's terms",
    "cookie_consent": "Choose a cookie preference", "payment": "A payment step needs you",
    "identity_verification": "Identity verification needs you",
    "business_verification": "Business verification needs you",
    "off_allow_list": "The agent left the provider's site", "secret_hidden": "The secret could not be captured",
    "human_field": "Fill in a field yourself", "secret_rotation": "Confirm resetting a secret",
}
NO_RESUME = ("terms_unchecked", "terms_prohibited", "config")  # resuming would only hit the same wall
_PLAIN = [
    (re.compile(r"\s*If you do not agree, press Ctrl\+C: nothing is submitted and the run is saved\."),
     " If you do not agree, choose “Save and stop”: nothing is submitted and the run is saved."),
    (re.compile(r"press Ctrl\+C:? ?"), "choose “Save and stop”: "),
    (re.compile(r",? ?(then )?(and )?press Enter( here)?( when you are done)?"), ""),
    (re.compile(r"\s*When you are done, press Enter\."), ""),
    (re.compile(r"leave the page and press Enter"), "leave the page, then choose “I've done this”"),
    (re.compile(r"\bthis terminal\b"), "this page"),
    (re.compile(r"the person reviews and submits"), "you review and submit"),
]
_FRIENDLY_EVENTS = {
    "research_started": "Researching how the app issues credentials",
    "metadata_checked": None, "browser_opened": "Opened the agent's browser window",
    "resource_created": "Registered the application at the provider",
    "credential_captured": "Captured the credential and stored it on this machine",
    "agent_done_accepted": "The credential page was reached",
    "paused": "Paused: the run is saved", "plan_ready": "The plan is ready",
}


def plain(text: str) -> str:
    """Terminal wording ("press Enter", "this terminal") → wording for the page. Facts are never changed."""
    out = text or ""
    for rx, rep in _PLAIN:
        out = rx.sub(rep, out)
    out = re.sub(r"\s+([.,;:])", r"\1", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _first_sentence(text: str, limit: int = 160) -> str:
    t = plain(text)
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    return (m.group(1) if m else t)[:limit]


def _events_of(events: list[dict], *types: str) -> list[dict]:
    return [e for e in events if e["type"] in types]


def milestones(run: Run, events: list[dict], live: dict | None, state: str) -> list[dict]:
    """The real facts that mark progress. A milestone is done when the backend recorded it; the first one that is
    not done is current (or blocked / failed, by the run's state). Nothing here estimates a percentage."""
    p = run.plan
    fake = run.provider == FAKE_PROVIDER_NAME
    seqs = {t: max((e["seq"] for e in events if e["type"] == t), default=0) for t in
            ("consent_given", "resumed", "browser_opened", "resource_created", "credential_captured")}
    consented = bool(live and live.get("consented")) or (seqs["consent_given"] > seqs["resumed"]
                                                         and seqs["consent_given"] > 0)
    cred_parts = list(run.credential.parts) if run.credential else []
    v = run.verification
    rows: list[tuple[str, str, bool, str]] = [
        ("identified", "Application identified", bool(p.identification.canonical_name),
         " · ".join(x for x in (p.identification.canonical_name, p.identification.provider) if x)),
        ("portal", "Developer portal located", bool(p.console_url), p.console_url or ""),
        ("type", "Credential type chosen",
         run.phase not in ("created", "research") and p.credential_kind != "unknown",
         CRED_LABELS.get(p.credential_kind, "") if p.credential_kind != "unknown" else ""),
    ]
    if not fake:
        rows.append(("consent", "Your go-ahead", consented, "Given for this session" if consented else ""))
    rows += [
        ("browser", "Browser opened", bool(seqs["browser_opened"]), ""),
        ("registered", "Application registered", bool(run.created) or bool(seqs["resource_created"]),
         "; ".join(run.created)[:120] if run.created else ""),
        ("captured", "Credentials captured", bool(cred_parts), ", ".join(PART_LABELS.get(x, x) for x in cred_parts)),
        ("verified", "Credentials verified", bool(v and v.label == "verified"),
         v.label.replace("_", " ") if v else ""),
    ]
    out, current_found = [], False
    for mid, label, done, detail in rows:
        if done:
            status = "done"
        elif not current_found and state not in ("completed",):
            current_found = True
            status = {"attention": "blocked", "failed": "failed"}.get(state, "current")
            if state == "paused":
                status = "current"
        else:
            status = "pending"
        out.append({"id": mid, "label": label, "status": status, "detail": detail})
    if state == "completed" and run.status == "partial":  # captured, but the live test did not fully pass
        for row in out:
            if row["id"] == "verified":
                row["status"], row["detail"] = "blocked", (v.label.replace("_", " ") if v else "not tested")
    return out


def latest_activity(run: Run, events: list[dict]) -> dict | None:
    """The newest meaningful thing the backend recorded, in plain words."""
    for e in reversed(events):
        t, d = e["type"], e.get("data") or {}
        text = None
        if t == "agent_step" and d.get("reason"):
            text = str(d["reason"])[:200]
        elif t == "handoff_opened":
            text = f"Waiting for you: {HANDOFF_TITLES.get(str(d.get('blocker')), 'your input is needed')}"
        elif t == "handoff_resolved":
            text = "Thanks. The agent is checking the page and continuing"
        elif t == "verified":
            text = f"Live test result: {str(d.get('label', '')).replace('_', ' ')}"
        elif t == "metadata_checked":
            text = str(d.get("reason") or "Checked the provider's public OAuth metadata")[:200]
        elif t == "run_finished":
            text = str(d.get("reason") or "")[:200] or None
        elif t == "research_started":
            text = f"Researching how {run.app_input} issues credentials"
        elif _FRIENDLY_EVENTS.get(t):
            text = _FRIENDLY_EVENTS[t]
        if text:
            return {"text": plain(text), "at": e.get("at"), "seq": e["seq"]}
    return None


def _done_counts(run: Run) -> str:
    c = run.counts()
    text = f"{c['agent']} actions by the agent, {c['person']} by you"
    return text + (f"; created: {'; '.join(run.created)[:100]}" if run.created else "")


def _attention(run: Run, live: dict, state_hint: str) -> dict | None:
    pending = live.get("pending")
    if pending == "consent" and live.get("consent"):
        return {"type": "consent", "title": "Your go-ahead is needed", **live["consent"]}
    h: Handoff | None = run.pending_handoff
    if h is None or pending not in ("enter", "choose"):
        return None
    done_labels = [m["label"] for m in live.get("_milestones", []) if m["status"] == "done"]
    base = {
        "title": "Your attention is needed",
        "headline": HANDOFF_TITLES.get(h.blocker_kind) or _first_sentence(h.reason, 90),
        "why": plain(h.reason),
        "done_so_far": _done_counts(run),
        "done_milestones": done_labels,
        "evidence": [plain(e.text)[:200] for e in h.evidence][:3],
        "handoff_id": h.id,
        "blocker_kind": h.blocker_kind,
    }
    if h.kind == "DO":
        base |= {"type": "do", "instruction": plain(h.person_instruction),
                 "where": "the agent's Chrome window",
                 "can_focus_browser": bool(run.browser and run.browser.chrome_pid)}
    else:
        base |= {"type": "decide", "instruction": plain(h.person_instruction), "options": list(h.options)}
    return base


def _failure(run: Run, steps_done: list[str]) -> dict:
    """Recoverable / needs you / unrecoverable, from the status and `resumable` the backend records."""
    next_steps = [plain(s) for b in run.blockers for s in b.next_steps][:6]
    if run.status == "failed" and run.resumable:
        kind, title = "recoverable", "The run stopped, and it can continue"
    elif run.status == "blocked" and run.resumable:
        kind, title = "needs_you", "The run is blocked until something is resolved"
    elif run.status == "waiting_on_provider":
        kind, title = "waiting", "Waiting on the provider"
    else:
        kind, title = "unrecoverable", "The run cannot continue"
    reason = re.sub(r"^(failed|blocked|partial): ", "", plain(run.status_reason or ""))
    return {"kind": kind, "title": title, "reason": reason, "completed": steps_done,
            "next_steps": next_steps or ([] if kind == "unrecoverable"
                                         else ["Resume the run once the cause is fixed."]),
            "can_resume": bool(run.resumable and run.status in ("failed", "blocked")),
            "blockers": [{"kind": b.kind, "description": plain(b.description)} for b in run.blockers][:4]}


def _result(run: Run) -> dict:
    v = run.verification
    parts = []
    for name, part in (run.credential.parts.items() if run.credential else []):
        parts.append({"name": name, "label": PART_LABELS.get(name, name.replace("_", " ").title()),
                      "masked": part.masked_display, "secret": name != "client_id",
                      "revealable": True})
    label = v.label if v else "untested"
    return {
        "app": run.plan.identification.canonical_name or run.app_name or run.app_input,
        "provider": run.plan.identification.provider,
        "credential_type": CRED_LABELS.get(
            run.credential.kind if run.credential else run.plan.credential_kind, "Credential"),
        "verification": {"label": label, "text": VERIFICATION_TEXT.get(label, label),
                         "method": plain(v.test_description) if v else None,
                         "observed": plain(v.observed_result) if v else None,
                         "limitations": [plain(x) for x in (v.production_limitations if v else [])]},
        "parts": parts,
        "completed_at": (v.tested_at if v and v.tested_at else run.updated_at),
        "permissions": None,  # not recorded by the backend (no scopes are requested when the app is created)
        "created_items": list(run.created),
        "limitations": [plain(x) for x in run.observed_limitations][:4],
        "cleanup": "Delete the application in the provider's console when you no longer need it. "
                   "CredAgent never deletes.",
        "partial": run.status == "partial",
    }


def build_view(run: Run, events: list[dict], live: dict | None) -> dict[str, Any]:
    """The whole picture for one run."""
    alive = bool(live and live.get("alive"))
    if run.status == "succeeded":
        state = "completed"
    elif run.status == "partial":
        state = "completed"
    elif run.status != "running":
        state = "failed"
    elif alive:
        pending = live.get("pending") if live else None
        waiting = pending == "consent" or (run.pending_handoff and pending in ("enter", "choose"))
        state = "attention" if waiting else "running"
    else:
        state = "paused"
    ms = milestones(run, events, live, state)
    attention = None
    if state == "attention" and live is not None:
        attention = _attention(run, {**live, "_milestones": ms}, state)
        if attention is None:
            state = "running"
            ms = milestones(run, events, live, state)
    done_labels = [m["label"] for m in ms if m["status"] == "done"]
    headline = {
        "running": "Working on it",
        "attention": "Your attention is needed",
        "paused": "Paused",
        "completed": ("Credentials verified" if run.status == "succeeded"
                      else "Credentials captured, not fully verified"),
        "failed": "The run did not finish",
    }[state]
    error = (live or {}).get("error")
    return {
        "id": run.id,
        "app": {"input": run.app_input, "name": run.plan.identification.canonical_name or run.app_name,
                "provider": run.plan.identification.provider},
        "fake": run.provider == FAKE_PROVIDER_NAME,
        "state": state,
        "headline": headline,
        "status": run.status,
        "phase": run.phase,
        "reason": plain(run.status_reason or ""),
        "milestones": ms,
        "activity": latest_activity(run, events),
        "attention": attention,
        "result": _result(run) if state == "completed" else None,
        "failure": _failure(run, done_labels) if state == "failed" else None,
        "paused": {"can_resume": run.status == "running" and run.phase != "done"
                   and not (error and error.get("kind") in NO_RESUME),
                   "error": error, "done_so_far": done_labels} if state == "paused" else None,
        "live": {"alive": alive, "stage": (live or {}).get("stage"), "can_stop": bool(attention)},
        "created_at": run.created_at, "updated_at": run.updated_at,
        "last_seq": events[-1]["seq"] if events else 0,
        "can_verify": bool(run.credential and "client_secret" in run.credential.parts
                           and run.provider != FAKE_PROVIDER_NAME),
    }


def summary(run: Run) -> dict[str, Any]:
    """One row of the recent-runs list."""
    state = ("completed" if run.status in ("succeeded", "partial") else
             "failed" if run.status != "running" else "paused")
    return {"id": run.id, "app": run.plan.identification.canonical_name or run.app_name or run.app_input,
            "status": run.status, "state": state, "updated_at": run.updated_at,
            "fake": run.provider == FAKE_PROVIDER_NAME}


_SAFE_EVENT_KEYS = ("seq", "at", "type")


def public_event(e: dict) -> dict:
    """An event for the technical log. The store already masks and refuses secrets; this trims the payload."""
    data = e.get("data") or {}
    text = "; ".join(f"{k}={str(v)[:80]}" for k, v in list(data.items())[:6] if k != "hints")
    return {k: e.get(k) for k in _SAFE_EVENT_KEYS} | {"text": text[:300]}
