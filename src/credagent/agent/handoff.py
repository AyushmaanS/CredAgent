"""Handoffs for the agent loop (D-078): DO (the person acts in the browser) and DECIDE (the person answers in the
terminal). Ported from the old loop, whose behaviour was shaped by the owner's checkpoint feedback (D-048–D-050):

  * a terms card names the exact box and button, and says what the agent already filled;
  * after Enter the page is re-checked: "Not done yet — still needed: …", up to 3 tries, then the run is saved with
    the step waiting for the person;
  * the browser-level domain guard is lifted only while the person acts (single sign-on may need other sites);
  * time spent waiting for the person is not counted against the run's time budget.

Code decides the kind and the card; the model can only ask.
"""

from __future__ import annotations

import inspect
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from credagent.browser.snapshot import Snapshot
from credagent.handoff.cards import render_card
from credagent.policy.hard_checks import check
from credagent.secrets.masking import Masker
from credagent.state.models import Evidence, Handoff, Run, StepRecord
from credagent.state.store import RunStore

MAX_HANDOFF_TRIES = 3

DO_INSTRUCTIONS = {
    "sign_in": "Sign in (or create the account) in the CredAgent browser window. Complete any code or 2FA prompt.",
    "verification_code": "Enter the verification code / complete the second factor in the browser window.",
    "captcha": "Complete the human check (CAPTCHA) in the browser window.",
    "payment": "This page asks for payment. Decide yourself; the agent never enters payment details. "
    "If you do not want to pay, leave the page and press Enter.",
    "terms": "Read the terms. If you agree, tick the box (if any) and submit the form yourself.",
    "cookie_consent": "Choose your cookie preference in the banner.",
    "off_allow_list": "The agent stopped at a page outside the allowed domains. If this page is expected, act on it "
    "yourself; otherwise go back to the provider's console.",
    "account_creation": "Create the account yourself in the browser window.",
    "unexpected": "Check the browser window and do what the page needs, or bring it back to the console.",
    "human_field": "Fill this field yourself in the browser window.",
}

BLOCKER_KINDS = {
    "sign_in", "account_creation", "verification_code", "two_factor", "captcha", "identity_verification",
    "business_verification", "payment", "terms", "cookie_consent", "provider_review", "paid_plan",
    "partner_approval", "policy_denied", "off_allow_list", "unexpected", "service_unavailable", "budget_exhausted",
    "replan_limit", "app_not_identified", "secret_hidden", "other",
}

IMPLIED_BUTTON = re.compile(r"by (clicking|selecting|tapping|pressing) [“\"'‘]?([A-Za-z][\w &-]{0,30}?)[”\"'’]?[,.]?\s+"
                            r"you (agree|accept|consent)", re.I)


def terms_form(obs: Any, gates: list) -> str | None:
    g = next((x for x in gates if x.kind == "terms"), None)
    box = next((i for i in obs.inputs if g and i["xpath"] == g.target_xpath), None)
    return (g.form_xpath if g else None) or (box["form"] if box else None)


def terms_submit_text(obs: Any, gates: list) -> str | None:
    """The button that submits the terms form: the form's submit button, or the one named in the agreement
    wording ("By clicking Create, you agree…")."""
    form = terms_form(obs, gates)
    submit = next((b for b in obs.buttons if form and b["form"] == form and b["type"] in ("submit", "")), None)
    if submit and submit["text"]:
        return submit["text"]
    g = next((x for x in gates if x.kind == "terms"), None)
    for text in (g.evidence if g else []):
        m = IMPLIED_BUTTON.search(text)
        if m:
            return m.group(2).strip()
    return None


def terms_instruction(obs: Any, gates: list) -> tuple[str, str]:
    """Exact instruction for a terms gate, naming the box and the button, and what is still missing.
    Returns (instruction, still_missing)."""
    g = next((x for x in gates if x.kind == "terms"), None)
    box = next((i for i in obs.inputs if g and i["xpath"] == g.target_xpath), None)
    form = (g.form_xpath if g else None) or (box["form"] if box else None)
    submit = next((b for b in obs.buttons if form and b["form"] == form and b["type"] in ("submit", "")), None)
    named = terms_submit_text(obs, gates)
    btn = (f"“{submit['text']}”" if submit and submit["text"]
           else f"“{named}”" if named else "the form's submit button")
    stop = " If you do not agree, press Ctrl+C: nothing is submitted and the run is saved."
    empty = [i["label"][:60] for i in obs.inputs
             if form and i["form"] == form and i["required"] and not i["value_len"]
             and i["type"] not in ("checkbox", "radio", "submit", "button", "hidden")]
    if empty:
        fields = ", ".join(f"“{e}”" for e in empty)
        btn = f"{btn} (first fill the required field(s) the agent could not: {fields})"
    if box and not box["checked"]:
        missing = f"tick “{box['label'][:90]}” and click {btn}"
        return f"In the browser window: read the terms, tick “{box['label'][:90]}”, then click {btn}.{stop}", missing
    if box and box["checked"]:
        return (f"The box “{box['label'][:90]}” is ticked, but the form is not submitted yet. Click {btn} in the "
                f"browser window.{stop}"), f"click {btn}"
    return (f"In the browser window: read the terms linked on the page. If you agree, click {btn}: clicking it "
            f"accepts the terms.{stop}"), f"click {btn}"


def form_summary_text(summary: dict[str, list[str]]) -> str:
    parts = []
    if summary.get("filled"):
        parts.append("The agent filled: " + ", ".join(summary["filled"]) + ".")
    if summary.get("left_empty"):
        parts.append("Left empty (no approved value; fill them yourself if needed): "
                     + ", ".join(summary["left_empty"]) + ".")
    return (" " + " ".join(parts)) if parts else ""


def still_needed(now: Snapshot, before: Snapshot, kind: str, allowed: list[str]) -> str | None:
    """After the person pressed Enter: what is still missing, or None when the handoff's condition is resolved."""
    gates_now = check(now.obs, allowed)
    if kind == "terms":
        if not any(g.kind == "terms" for g in gates_now) or now.url != before.url:
            return None
        return terms_instruction(now.obs, gates_now)[1]
    if kind == "secret_hidden":
        if now.secret_count > before.secret_count or now.url != before.url:
            return None
        return "the secret is still hidden"
    if kind in {g.kind for g in gates_now if g.action in ("DO", "BLOCK")}:
        return "the page still shows the same step (" + kind.replace("_", " ") + ")"
    if kind in ("unexpected", "human_field", "off_allow_list") and now.fingerprint() == before.fingerprint():
        return "nothing has changed on the page yet"
    return None


Prepare = Callable[[Snapshot, list], Awaitable[tuple[Snapshot, list, str]]]


class Handoffs:
    """Opens cards, waits for the person, re-checks the page. `observe` takes a fresh snapshot; `set_guard(True/False)`
    restores or lifts the browser-level domain guard."""

    def __init__(self, store: RunStore, masker: Masker, io: Any, allowed: list[str],
                 observe: Callable[[], Awaitable[Snapshot]], set_guard: Callable[[bool], Awaitable[None]]) -> None:
        self.store, self.masker, self.io, self.allowed = store, masker, io, allowed
        self.observe, self.set_guard = observe, set_guard
        self.waited = 0.0  # seconds spent waiting for the person

    def _cp(self, run: Run, event: str, data: dict | None = None) -> None:
        self.store.checkpoint(run, event, self.masker.mask(data or {}))

    def _step(self, run: Run, action: str, actor: str, outcome: str) -> None:
        run.add_step(StepRecord(action=self.masker.mask_text(action)[:200], actor=actor, outcome=outcome,  # type: ignore[arg-type]
                                checkpoint_seq=run.checkpoint_seq + 1))

    async def _wait(self, call: Callable[[], Any]) -> Any:
        t0 = time.monotonic()
        try:
            out = call()
            if inspect.isawaitable(out):
                out = await out
            return out
        finally:
            self.waited += time.monotonic() - t0

    def _open(self, run: Run, kind: Literal["DO", "DECIDE"], blocker: str, reason: str, evidence: list[str],
              snap: Snapshot, instruction: str | None, options: list[str] | None, after: str) -> Handoff:
        h = run.open_handoff(Handoff(
            kind=kind,
            blocker_kind=blocker if blocker in BLOCKER_KINDS else ("other" if kind == "DECIDE" else "unexpected"),
            reason=self.masker.mask_text(reason),
            evidence=[Evidence(kind="observed", text=self.masker.mask_text(e)[:300], url=snap.url_masked)
                      for e in evidence[:4]],
            completed_so_far="agent loop",
            person_instruction=instruction or DO_INSTRUCTIONS.get(blocker, DO_INSTRUCTIONS["unexpected"]),
            where="the CredAgent Chrome window" if kind == "DO" else "this terminal",
            expected_resume_action=after, options=options or []))
        self._cp(run, "handoff_opened", {"handoff_id": h.id, "kind": kind, "blocker": blocker})
        self.io.say(render_card(run, h, self.masker))
        return h

    async def do(self, run: Run, kind: str, reason: str, evidence: list[str], snap: Snapshot, gates: list, *,
                 instruction: str | None = None, after: str = "Re-check the page, then continue.",
                 prepare: Prepare | None = None) -> str | None:
        """The person acts in the browser, then presses Enter. Returns "done", or None (no answer, or still not
        done after MAX_HANDOFF_TRIES: the run is saved with the handoff pending)."""
        if kind == "terms" and prepare is not None:
            snap, gates, extra = await prepare(snap, gates)  # the agent fills what it may before the person acts
            if instruction is None:
                instruction = terms_instruction(snap.obs, gates)[0] + extra
        if kind == "terms" and instruction is None:
            instruction = terms_instruction(snap.obs, gates)[0]
        h = self._open(run, "DO", kind, reason, evidence, snap, instruction, None, after)
        await self.set_guard(False)
        try:
            for attempt in range(1, MAX_HANDOFF_TRIES + 1):
                if not await self._wait(lambda: self.io.wait_enter(
                        "Press Enter when you are done (Ctrl+C to stop; the run is saved)")):
                    return None
                try:
                    now = await self.observe()
                    missing = still_needed(now, snap, kind, self.allowed)
                except Exception:  # noqa: BLE001 - if the page cannot be read, let the main loop look again
                    missing = None
                if missing is None:
                    break
                self._cp(run, "handoff_not_done_yet", {"handoff_id": h.id, "attempt": attempt, "still": missing})
                if attempt == MAX_HANDOFF_TRIES:
                    self.io.say(f"Still needed: {missing}. The run is saved with this step waiting for you.")
                    return None
                self.io.say(f"Not done yet — still needed: {missing}. Do that in the browser, then press Enter.")
        finally:
            await self.set_guard(True)
        run.resolve_handoff(h.id)
        self._step(run, f"person: {h.person_instruction[:120]}", "person", "done")
        self._cp(run, "handoff_resolved", {"handoff_id": h.id})
        return "done"

    async def decide(self, run: Run, kind: str, reason: str, evidence: list[str], snap: Snapshot, options: list[str], *,
                     instruction: str, after: str) -> str | None:
        """The person answers in the terminal. Returns the chosen option, or None (no answer)."""
        h = self._open(run, "DECIDE", kind, reason, evidence, snap, instruction, options, after)
        answer = await self._wait(lambda: self.io.choose("Your decision", h.options))
        if answer is None:
            return None
        run.resolve_handoff(h.id, answer=answer)
        self._step(run, f"person decided: {answer}", "person", "done")
        self._cp(run, "handoff_resolved", {"handoff_id": h.id, "answer": answer})
        return answer
